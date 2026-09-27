from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

DEFAULT_TATER_AGENT_MAX_ITERATIONS = 32
MAX_TATER_AGENT_MAX_ITERATIONS = 128
TATER_AGENT_MAX_CALLS_PER_STEP = 16
TATER_AGENT_HISTORY_MAX_CHARS = 120_000
TATER_AGENT_PLAN_RETRY_LIMIT = 2
TATER_AGENT_REPEAT_LIMIT = 3
TATER_AGENT_PROGRESS_MAX_CHARS = 600
TATER_AGENT_TASK_TITLE_MAX_CHARS = 80
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

_CONVERSATIONAL_CONFIRMATIONS = {
    'ok',
    'okay',
    'yes',
    'yep',
    'yeah',
    'sure',
    'go ahead',
    'proceed',
    'continue',
    'do it',
}
_CONVERSATIONAL_ONLY = _CONVERSATIONAL_CONFIRMATIONS | {
    'k',
    'kk',
    'thanks',
    'thank you',
    'thx',
    'got it',
    'understood',
    'sounds good',
    'perfect',
    'great',
    'cool',
    'nice',
    'awesome',
    'alright',
    'all right',
    'hello',
    'hi',
    'hey',
}
_TASK_STATUS_RE = re.compile(
    r'(?:\b(?:task|job|background work|process)\b.*\b(?:status|progress|running|finished|done|complete|result|'
    r'update|happened|cancel|stop)\b|\b(?:what happened|how is|how\'s|where is)\b.*\b(?:task|job|work)\b|'
    r'\b(?:are you still working|is it still running|is that still running|did it finish|did that finish|'
    r'is it done|is that done|any update)\b)',
    re.IGNORECASE,
)
_EXPLICIT_WORK_RE = re.compile(
    r'\b(?:run|running|search|searching|find|finding|inspect|inspecting|open|opening|read|reading|edit|editing|'
    r'change|changing|write|writing|build|building|test|testing|install|installing|clone|cloning|commit|'
    r'committing|push|pushing|pull|pulling|create|creating|delete|deleting|move|moving|copy|copying|list|'
    r'listing|show|showing|check|checking|continue|continuing|resume|resuming|proceed|proceeding)\b',
    re.IGNORECASE,
)
_PENDING_ACTION_RE = re.compile(
    r'\b(?:i\'ll|i will|i am going to|i\'m going to|i am now|i\'m now|let me|should i|shall i|'
    r'would you like me to|do you want me to|want me to|may i|ready for me to)\b',
    re.IGNORECASE,
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r'(?i)\b([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)\s*=\s*'
    r'("[^"]*"|\'[^\']*\'|[^\s;&|]+)'
)
_SENSITIVE_FLAG_RE = re.compile(
    r'(?i)(--?(?:api[-_]?key|token|secret|password|passwd|credential)(?:=|\s+))([^\s;&|]+)'
)
_BEARER_RE = re.compile(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+')


def _plain_message_text(message: dict[str, Any]) -> str:
    content = message.get('content', '')
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return ''.join(
            str(item.get('text') or '')
            for item in content
            if isinstance(item, dict) and item.get('type') in {'text', 'input_text', 'output_text'}
        ).strip()
    return str(content or '').strip()


def _normalized_conversation_text(value: str) -> str:
    value = re.sub(r'\s+', ' ', str(value or '').replace('’', "'").strip().casefold())
    return value.strip(' .,!?:;…👍🙏')


def _is_task_status_query(value: str) -> bool:
    return bool(_TASK_STATUS_RE.search(value))


def task_dispatch_request(messages: list[dict[str, Any]]) -> str | None:
    """Return concrete work to dispatch, or None for a chat-only turn.

    A short confirmation may approve work the assistant just proposed, but it
    inherits the earlier user request instead of becoming a task named "Ok".
    """

    user_indexes = [index for index, message in enumerate(messages) if message.get('role') == 'user']
    if not user_indexes:
        return None

    current_index = user_indexes[-1]
    current = _plain_message_text(messages[current_index])
    normalized = _normalized_conversation_text(current)
    if not normalized or _is_task_status_query(normalized):
        return None
    if normalized not in _CONVERSATIONAL_ONLY:
        return current
    if normalized not in _CONVERSATIONAL_CONFIRMATIONS:
        return None

    previous_assistant = ''
    for message in reversed(messages[:current_index]):
        if message.get('role') == 'assistant':
            previous_assistant = _plain_message_text(message)
            break
    previous_assistant = previous_assistant.replace('’', "'")
    if (
        not previous_assistant
        or not _PENDING_ACTION_RE.search(previous_assistant)
        or not _EXPLICIT_WORK_RE.search(previous_assistant)
    ):
        return None

    for message in reversed(messages[:current_index]):
        if message.get('role') != 'user' or (message.get('meta') or {}).get('internal') is True:
            continue
        candidate = _plain_message_text(message)
        candidate_normalized = _normalized_conversation_text(candidate)
        if not candidate_normalized or candidate.startswith('[BACKGROUND TASK'):
            continue
        if candidate_normalized in _CONVERSATIONAL_ONLY or _is_task_status_query(candidate_normalized):
            continue
        return candidate
    return None


def _safe_activity_preview(value: Any, max_chars: int = 220) -> str:
    text = re.sub(r'\s+', ' ', str(value or '').strip())
    text = _SENSITIVE_ASSIGNMENT_RE.sub(lambda match: f'{match.group(1)}=[redacted]', text)
    text = _SENSITIVE_FLAG_RE.sub(lambda match: f'{match.group(1)}[redacted]', text)
    text = _BEARER_RE.sub(lambda match: f'{match.group(1)}[redacted]', text)
    if len(text) > max_chars:
        return f'{text[: max_chars - 1].rstrip()}…'
    return text


def tool_activity_status(
    tool_name: str,
    parameters: dict[str, Any] | None,
    *,
    done: bool,
    failed: bool = False,
) -> dict[str, str]:
    parameters = parameters if isinstance(parameters, dict) else {}
    if tool_name == 'terminal':
        description = (
            'Terminal command failed'
            if failed
            else 'Finished terminal command'
            if done
            else 'Running terminal command'
        )
        command = _safe_activity_preview(parameters.get('command'))
        cwd = _safe_activity_preview(parameters.get('cwd'), max_chars=100)
        detail = f'{cwd}$ {command}' if cwd and command else command or cwd
        return {'description': description, 'detail': detail}
    if tool_name == 'tater_hydra':
        description = 'Hydra call failed' if failed else 'Hydra call finished' if done else 'Calling Tater Hydra'
        return {
            'description': description,
            'detail': _safe_activity_preview(parameters.get('request')),
        }
    description = f'{tool_name} failed' if failed else f'Finished {tool_name}' if done else f'Using {tool_name}'
    return {'description': description, 'detail': ''}


def normalize_task_title(planned_title: Any, prompt: str) -> str:
    """Return a short action label, preferring the planner's semantic title."""

    title = re.sub(r'\s+', ' ', str(planned_title or '')).strip(' \t\r\n"\'`.,!?')
    if not title:
        title = re.sub(r'\s+', ' ', str(prompt or '')).strip(' \t\r\n"\'`.,!?')
        title = re.sub(
            r'^(?:(?:can|could|would|will) you|please|i (?:want|need) you to)\s+',
            '',
            title,
            flags=re.IGNORECASE,
        )
        question = re.match(
            r'^(?:is|are|was|were|do|does|did)\s+(?:the\s+|a\s+|an\s+)?(.+)$',
            title,
            flags=re.IGNORECASE,
        )
        if question:
            title = f'Check {question.group(1)}'

    words = title.split()
    if len(words) > 10:
        title = ' '.join(words[:10])
    title = title[:TATER_AGENT_TASK_TITLE_MAX_CHARS].rstrip(' .,:;-')
    if not title:
        return 'Background task'
    return f'{title[0].upper()}{title[1:]}'


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


def merge_task_context(parent: Any, task: Any) -> dict[str, Any]:
    parent_context = normalize_agent_context(parent)
    task_context = normalize_agent_context(task)
    merged = dict(parent_context)

    if not merged.get('objective') and task_context.get('objective'):
        merged['objective'] = task_context['objective']
    for field in ('repository_root', 'branch', 'cwd', 'execution_summary'):
        if task_context.get(field):
            merged[field] = task_context[field]
    for field in TATER_AGENT_CONTEXT_LIST_FIELDS:
        merged[field] = list(
            dict.fromkeys([*(parent_context.get(field) or []), *(task_context.get(field) or [])])
        )
    return normalize_agent_context(merged)


def merge_project_context(project: Any, chat: Any) -> dict[str, Any]:
    """Fold verified chat work into memory shared by every chat in a project."""

    project_context = normalize_agent_context(project)
    chat_context = normalize_agent_context(chat)
    merged = dict(project_context)

    for field in TATER_AGENT_CONTEXT_STRING_FIELDS:
        if chat_context.get(field):
            merged[field] = chat_context[field]
    for field in TATER_AGENT_CONTEXT_LIST_FIELDS:
        merged[field] = list(
            dict.fromkeys([*(project_context.get(field) or []), *(chat_context.get(field) or [])])
        )[-TATER_AGENT_CONTEXT_LIST_MAX_ITEMS:]
    return normalize_agent_context(merged)


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
    task_title = payload.get('task_title', '')
    final_answer = payload.get('final_answer', '')
    context = payload.get('context', {})
    if not isinstance(progress, str):
        raise ValueError('progress must be a string')
    if not isinstance(task_title, str):
        raise ValueError('task_title must be a string')
    if not isinstance(final_answer, str):
        raise ValueError('final_answer must be a string')
    if not isinstance(context, dict):
        raise ValueError('context must be an object')

    progress = progress.strip()[:TATER_AGENT_PROGRESS_MAX_CHARS]
    task_title = re.sub(r'\s+', ' ', task_title).strip(' \t\r\n"\'`')[:TATER_AGENT_TASK_TITLE_MAX_CHARS]
    final_answer = final_answer.strip()[:TATER_AGENT_FINAL_ANSWER_MAX_CHARS]
    if '<|tool_call' in progress.lower():
        raise ValueError('progress must not contain tool-call markup')
    if '<|tool_call' in task_title.lower():
        raise ValueError('task_title must not contain tool-call markup')
    if '<|tool_call' in final_answer.lower():
        raise ValueError('final_answer must not contain tool-call markup')
    if calls and final_answer:
        raise ValueError('final_answer must be empty while tool_calls are present')
    if calls and context:
        raise ValueError('context must be empty while tool_calls are present')

    return {
        'progress': progress,
        'task_title': task_title,
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
        'Return exactly one valid JSON object with task_title, progress, tool_calls, final_answer, and context fields. '
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
