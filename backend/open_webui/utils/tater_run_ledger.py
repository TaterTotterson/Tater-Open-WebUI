from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_LEDGER_LOCK = threading.RLock()
_SECRET_KEY_RE = re.compile(
    r'(?i)(?:^|[-_])(?:api[-_]?key|access[-_]?token|auth[-_]?token|token|secret|client[-_]?secret|'
    r'password|passwd|credential|authorization|cookie)(?:$|[-_])'
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r'(?i)\b([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)\s*=\s*'
    r'("[^"]*"|\'[^\']*\'|[^\s;&|]+)'
)
_SENSITIVE_FLAG_RE = re.compile(
    r'(?i)(--?(?:api[-_]?key|token|secret|password|passwd|credential)(?:=|\s+))([^\s;&|]+)'
)
_SENSITIVE_JSON_RE = re.compile(
    r'(?i)((?:"|\')?(?:api[-_]?key|token|secret|password|passwd|credential|authorization|cookie)'
    r'(?:"|\')?\s*:\s*(?:"|\'))([^"\']+)'
)
_BEARER_RE = re.compile(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+')
_URL_CREDENTIAL_RE = re.compile(r'(?i)(https?://[^\s:/@]+:)[^\s/@]+(@)')


def redact_ledger_text(value: Any, *, max_chars: int = 200_000) -> str:
    text = str(value or '')
    text = _SENSITIVE_ASSIGNMENT_RE.sub(lambda match: f'{match.group(1)}=[redacted]', text)
    text = _SENSITIVE_FLAG_RE.sub(lambda match: f'{match.group(1)}[redacted]', text)
    text = _SENSITIVE_JSON_RE.sub(lambda match: f'{match.group(1)}[redacted]', text)
    text = _BEARER_RE.sub(lambda match: f'{match.group(1)}[redacted]', text)
    text = _URL_CREDENTIAL_RE.sub(lambda match: f'{match.group(1)}[redacted]{match.group(2)}', text)
    if len(text) > max_chars:
        return f'{text[:max_chars]}\n[truncated {len(text) - max_chars} characters]'
    return text


def sanitize_ledger_value(value: Any, *, max_chars: int = 200_000, depth: int = 0) -> Any:
    if depth >= 12:
        return '[maximum nesting depth reached]'
    if isinstance(value, dict):
        sanitized = {}
        for key, item in list(value.items())[:2_000]:
            key_text = str(key)
            sanitized[key_text] = (
                '[redacted]'
                if _SECRET_KEY_RE.search(key_text)
                else sanitize_ledger_value(item, max_chars=max_chars, depth=depth + 1)
            )
        if len(value) > 2_000:
            sanitized['_truncated_items'] = len(value) - 2_000
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized = [
            sanitize_ledger_value(item, max_chars=max_chars, depth=depth + 1)
            for item in items[:2_000]
        ]
        if len(items) > 2_000:
            sanitized.append(f'[truncated {len(items) - 2_000} items]')
        return sanitized
    if isinstance(value, bytes):
        return redact_ledger_text(value.decode('utf-8', 'replace'), max_chars=max_chars)
    if isinstance(value, str):
        return redact_ledger_text(value, max_chars=max_chars)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_ledger_text(value, max_chars=max_chars)


def _rotate_ledger(path: Path, max_bytes: int, backup_count: int, incoming_bytes: int) -> None:
    try:
        current_size = path.stat().st_size
    except FileNotFoundError:
        return
    if current_size + incoming_bytes <= max_bytes:
        return

    oldest = path.with_name(f'{path.name}.{backup_count}')
    oldest.unlink(missing_ok=True)
    for index in range(backup_count - 1, 0, -1):
        source = path.with_name(f'{path.name}.{index}')
        if source.exists():
            source.replace(path.with_name(f'{path.name}.{index + 1}'))
    path.replace(path.with_name(f'{path.name}.1'))


def record_tater_run_event(
    event: str,
    *,
    run_id: str,
    task_id: str | None = None,
    chat_id: str | None = None,
    user_id: str | None = None,
    data: dict[str, Any] | None = None,
    path: str | Path | None = None,
    enabled: bool | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
    max_field_chars: int | None = None,
) -> bool:
    """Append one sanitized JSON event to the persistent Tater agent ledger.

    Logging must never interrupt a user task, so failures are reported to the
    normal application logger and returned as ``False`` instead of raised.
    """

    try:
        if (
            path is None
            or enabled is None
            or max_bytes is None
            or backup_count is None
            or max_field_chars is None
        ):
            from open_webui.env import (
                ENABLE_TATER_RUN_LEDGER,
                TATER_RUN_LEDGER_BACKUP_COUNT,
                TATER_RUN_LEDGER_MAX_BYTES,
                TATER_RUN_LEDGER_MAX_FIELD_CHARS,
                TATER_RUN_LEDGER_PATH,
            )

            path = path or TATER_RUN_LEDGER_PATH
            enabled = ENABLE_TATER_RUN_LEDGER if enabled is None else enabled
            max_bytes = TATER_RUN_LEDGER_MAX_BYTES if max_bytes is None else max_bytes
            backup_count = TATER_RUN_LEDGER_BACKUP_COUNT if backup_count is None else backup_count
            max_field_chars = (
                TATER_RUN_LEDGER_MAX_FIELD_CHARS if max_field_chars is None else max_field_chars
            )
        if not enabled:
            return False

        ledger_path = Path(path)
        payload = {
            'ts': dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds'),
            'event': str(event),
            'run_id': str(run_id),
            **({'task_id': str(task_id)} if task_id else {}),
            **({'chat_id': str(chat_id)} if chat_id else {}),
            **({'user_id': str(user_id)} if user_id else {}),
            'pid': os.getpid(),
            'data': sanitize_ledger_value(data or {}, max_chars=max_field_chars),
        }
        line = json.dumps(payload, ensure_ascii=False, default=str, separators=(',', ':')) + '\n'
        encoded_size = len(line.encode('utf-8'))

        with _LEDGER_LOCK:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_ledger(ledger_path, max_bytes, backup_count, encoded_size)
            with ledger_path.open('a', encoding='utf-8') as ledger:
                ledger.write(line)
                ledger.flush()
        return True
    except Exception:
        log.exception('Could not append %s to the Tater run ledger', event)
        return False
