from __future__ import annotations

import hashlib
import json
import os
from typing import Any

DEFAULT_TATER_AGENT_MAX_ITERATIONS = 32
MAX_TATER_AGENT_MAX_ITERATIONS = 128
TATER_AGENT_HISTORY_MAX_CHARS = 120_000
TATER_AGENT_REPEAT_LIMIT = 3


def agent_iteration_limit(value: str | int | None = None) -> int:
    raw = value if value is not None else os.getenv('TATER_AGENT_MAX_ITERATIONS', '')
    try:
        limit = int(raw or DEFAULT_TATER_AGENT_MAX_ITERATIONS)
    except (TypeError, ValueError):
        limit = DEFAULT_TATER_AGENT_MAX_ITERATIONS
    return max(1, min(limit, MAX_TATER_AGENT_MAX_ITERATIONS))


def parse_tool_plan(content: str) -> list[dict[str, Any]]:
    content = str(content or '')
    start = content.find('{')
    end = content.rfind('}')
    if start < 0 or end < start:
        raise ValueError('No JSON object found in the tool plan')

    payload = json.loads(content[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError('Tool plan must be a JSON object')

    raw_calls = payload.get('tool_calls')
    if raw_calls is None:
        raw_calls = [payload] if payload.get('name') else []
    if not isinstance(raw_calls, list):
        raise ValueError('tool_calls must be an array')

    calls = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ValueError('Every tool call must be an object')
        name = str(raw_call.get('name') or '').strip()
        if not name:
            raise ValueError('Every tool call must have a name')
        parameters = raw_call.get('parameters', {})
        if not isinstance(parameters, dict):
            raise ValueError(f'Tool parameters for {name} must be an object')
        calls.append({'name': name, 'parameters': parameters})
    return calls


def render_tool_history(records: list[dict[str, Any]], max_chars: int = TATER_AGENT_HISTORY_MAX_CHARS) -> str:
    if not records or max_chars <= 0:
        return ''

    lines = [json.dumps(record, ensure_ascii=False, default=str, separators=(',', ':')) for record in records]
    selected = []
    used = 0
    for line in reversed(lines):
        separator_size = 1 if selected else 0
        if used + separator_size + len(line) <= max_chars:
            selected.append(line)
            used += separator_size + len(line)
            continue

        if not selected:
            marker = '...[tool result truncated]...'
            selected.append(marker + line[-max(0, max_chars - len(marker)) :])
        break

    selected.reverse()
    if len(selected) < len(lines):
        selected.insert(0, '...[older tool results omitted]...')
    return '\n'.join(selected)[-max_chars:]


def tool_outcome_signature(name: str, parameters: dict[str, Any], result: Any) -> str:
    payload = json.dumps(
        {'name': name, 'parameters': parameters, 'result': result},
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
