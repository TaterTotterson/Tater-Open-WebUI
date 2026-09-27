from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

DEFAULT_TATER_AGENT_MAX_ITERATIONS = 32
MAX_TATER_AGENT_MAX_ITERATIONS = 128
TATER_AGENT_MAX_CALLS_PER_STEP = 16
TATER_AGENT_HISTORY_MAX_CHARS = 120_000
TATER_AGENT_PLAN_RETRY_LIMIT = 2
TATER_AGENT_REPEAT_LIMIT = 3
TATER_AGENT_PROGRESS_MAX_CHARS = 600
TATER_AGENT_FINAL_ANSWER_MAX_CHARS = 40_000
TATER_AGENT_REVIEW_REASON_MAX_CHARS = 2_000
TATER_AGENT_CONTEXT_STRING_MAX_CHARS = 4_000
TATER_AGENT_CONTEXT_LIST_MAX_ITEMS = 50
TATER_AGENT_RECENT_MESSAGE_LIMIT = 12

TATER_AGENT_CONTEXT_STRING_FIELDS = (
    'objective',
    'repository_root',
    'branch',
    'cwd',
    'execution_summary',
)
TATER_AGENT_CONTEXT_LIST_FIELDS = (
    'requirements',
    'plan',
    'completed',
    'files_changed',
    'tests',
    'blockers',
)

_VOLATILE_RESULT_KEYS = {
    'created_at',
    'duration',
    'ended_at',
    'first_offset',
    'id',
    'next_offset',
    'started_at',
}


def agent_iteration_limit(value: str | int | None = None) -> int:
    raw = value if value is not None else os.getenv('TATER_AGENT_MAX_ITERATIONS', '')
    try:
        limit = int(raw or DEFAULT_TATER_AGENT_MAX_ITERATIONS)
    except (TypeError, ValueError):
        limit = DEFAULT_TATER_AGENT_MAX_ITERATIONS
    return max(1, min(limit, MAX_TATER_AGENT_MAX_ITERATIONS))


def agent_history_char_limit(context_window: int | str | None) -> int:
    try:
        tokens = int(context_window or 0)
    except (TypeError, ValueError):
        return TATER_AGENT_HISTORY_MAX_CHARS
    if tokens <= 0:
        return TATER_AGENT_HISTORY_MAX_CHARS
    return min(TATER_AGENT_HISTORY_MAX_CHARS, max(4_000, tokens * 2))


def recent_history_char_limit(context_window: int | str | None) -> int:
    try:
        tokens = int(context_window or 0)
    except (TypeError, ValueError):
        tokens = 0
    return min(48_000, max(8_000, tokens * 2 if tokens else 24_000))


def render_recent_chat_history(
    messages: list[dict[str, Any]],
    *,
    max_messages: int = TATER_AGENT_RECENT_MESSAGE_LIMIT,
    max_chars: int = 24_000,
) -> str:
    lines = []
    for message in messages[-max(1, max_messages) :]:
        content = message.get('content', '')
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        lines.append(f'{str(message.get("role") or "unknown").upper()}: """{content}"""')

    selected = []
    used = 0
    for line in reversed(lines):
        separator_size = 1 if selected else 0
        if used + separator_size + len(line) <= max_chars:
            selected.append(line)
            used += separator_size + len(line)
            continue
        if not selected:
            selected.append(line[-max_chars:])
        break
    selected.reverse()
    if len(selected) < len(lines):
        selected.insert(0, '...[older recent messages omitted]...')
    return '\n'.join(selected)[-max_chars:]


def normalize_agent_context(value: Any, previous: Any = None) -> dict[str, Any]:
    previous = previous if isinstance(previous, dict) else {}
    value = value if isinstance(value, dict) else {}
    normalized: dict[str, Any] = {}

    for field in TATER_AGENT_CONTEXT_STRING_FIELDS:
        raw = value[field] if field in value else previous.get(field, '')
        normalized[field] = str(raw or '').strip()[:TATER_AGENT_CONTEXT_STRING_MAX_CHARS]

    for field in TATER_AGENT_CONTEXT_LIST_FIELDS:
        raw = value[field] if field in value else previous.get(field, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raw = []
        normalized[field] = [
            str(item).strip()[:TATER_AGENT_CONTEXT_STRING_MAX_CHARS]
            for item in raw[:TATER_AGENT_CONTEXT_LIST_MAX_ITEMS]
            if str(item).strip()
        ]

    normalized['updated_at'] = int(time.time())
    return normalized


def render_agent_context(value: Any) -> str:
    context = normalize_agent_context(value)
    context.pop('updated_at', None)
    if not any(context.values()):
        return 'No persistent working context has been recorded yet.'
    return json.dumps(context, ensure_ascii=False, separators=(',', ':'))


def parse_tool_plan_response(
    content: str,
    max_calls: int = TATER_AGENT_MAX_CALLS_PER_STEP,
) -> dict[str, Any]:
    content = str(content or '')
    payload = None
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != '{':
            continue
        try:
            candidate, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (
            'tool_calls' in candidate
            or candidate.get('name')
            or 'progress' in candidate
            or 'final_answer' in candidate
        ):
            payload = candidate
            break
    if payload is None:
        raise ValueError('No tool-plan JSON object found')

    raw_calls = payload.get('tool_calls')
    if raw_calls is None:
        raw_calls = [payload] if payload.get('name') else []
    if not isinstance(raw_calls, list):
        raise ValueError('tool_calls must be an array')
    if len(raw_calls) > max(1, max_calls):
        raise ValueError(f'Tool plan contains too many calls ({len(raw_calls)} > {max(1, max_calls)})')

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
    progress = payload.get('progress', '')
    final_answer = payload.get('final_answer', '')
    context = payload.get('context', {})
    if not isinstance(progress, str):
        raise ValueError('progress must be a string')
    if not isinstance(final_answer, str):
        raise ValueError('final_answer must be a string')
    if not isinstance(context, dict):
        raise ValueError('context must be an object')

    progress = progress.strip()[:TATER_AGENT_PROGRESS_MAX_CHARS]
    final_answer = final_answer.strip()[:TATER_AGENT_FINAL_ANSWER_MAX_CHARS]
    if '<|tool_call' in progress.lower():
        raise ValueError('progress must not contain tool-call markup')
    if '<|tool_call' in final_answer.lower():
        raise ValueError('final_answer must not contain tool-call markup')
    if calls and final_answer:
        raise ValueError('final_answer must be empty while tool_calls are present')
    if calls and context:
        raise ValueError('context must be empty while tool_calls are present')

    return {
        'progress': progress,
        'tool_calls': calls,
        'final_answer': final_answer,
        'context': context,
    }


def parse_tool_plan(content: str, max_calls: int = TATER_AGENT_MAX_CALLS_PER_STEP) -> list[dict[str, Any]]:
    return parse_tool_plan_response(content, max_calls=max_calls)['tool_calls']


def tool_plan_retry_instruction(error: Exception | str) -> str:
    reason = str(error).strip()[:300] or 'invalid tool-plan response'
    return (
        f'Your previous response could not be used ({reason}). Retry the same planning step now. '
        'Return exactly one valid JSON object with progress, tool_calls, final_answer, and context fields. '
        'Do not include Markdown, tool-call markup, or prose outside the JSON object.'
    )


def parse_completion_review(content: str) -> dict[str, Any]:
    content = str(content or '')
    payload = None
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != '{':
            continue
        try:
            candidate, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and 'complete' in candidate:
            payload = candidate
            break
    if payload is None:
        raise ValueError('No completion-review JSON object found')

    complete = payload.get('complete')
    reason = payload.get('reason', '')
    if not isinstance(complete, bool):
        raise ValueError('complete must be a boolean')
    if not isinstance(reason, str):
        raise ValueError('reason must be a string')

    reason = reason.strip()[:TATER_AGENT_REVIEW_REASON_MAX_CHARS]
    if not complete and not reason:
        raise ValueError('An incomplete review must explain what remains')
    return {'complete': complete, 'reason': reason}


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


def _stable_result(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in {'{', '['}:
        try:
            return _stable_result(json.loads(value))
        except json.JSONDecodeError:
            pass
    if isinstance(value, dict):
        return {
            key: _stable_result(item)
            for key, item in value.items()
            if key not in _VOLATILE_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_stable_result(item) for item in value]
    return value


def tool_outcome_signature(name: str, parameters: dict[str, Any], result: Any) -> str:
    payload = json.dumps(
        {'name': name, 'parameters': parameters, 'result': _stable_result(result)},
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
