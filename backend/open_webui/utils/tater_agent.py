from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
from typing import Any

DEFAULT_TATER_AGENT_MAX_ITERATIONS = 32
MAX_TATER_AGENT_MAX_ITERATIONS = 128
TATER_AGENT_MAX_CALLS_PER_STEP = 16
TATER_AGENT_MAX_PARALLEL_TASKS = 4
TATER_AGENT_PARALLEL_TASK_PROMPT_MAX_CHARS = 4_000
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
    r'\bwhat (?:are|were) you (?:doing|working on)\b|\bwhat(?:\'s| is) (?:your|the) progress\b|'
    r'\bhow(?:\'s| is) (?:it|that|the task) going\b|'
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
_CONTINUATION_ANSWER_RE = re.compile(
    r"\b(?:i(?:'ll| will| am going to|'m going to| need to| have to)\b|let me\b|"
    r"one moment\b|give me a moment\b|i(?:'ll| will) start by\b|i(?:'ll| will) now\b)",
    re.IGNORECASE,
)
_COMPLETION_ANSWER_RE = re.compile(
    r"\b(?:completed|finished|done|i (?:found|confirmed|verified|changed|updated|fixed|implemented|ran|tested)|"
    r"tests? (?:pass|passed)|here(?:'s| is) (?:the|my) (?:result|assessment|summary)|"
    r"the (?:result|answer|issue|cause) is)\b",
    re.IGNORECASE,
)
_FAST_READ_ONLY_COMMANDS = {
    'cat',
    'df',
    'du',
    'file',
    'grep',
    'head',
    'ls',
    'pwd',
    'realpath',
    'rg',
    'stat',
    'tail',
    'tree',
    'wc',
}
_FAST_READ_ONLY_GIT_COMMANDS = {'diff', 'log', 'rev-parse', 'show', 'status'}
_MODEL_TOOL_CALL_RE = re.compile(
    r'<\|tool_call>\s*call:([A-Za-z0-9_.:-]+)\s*(.*?)\s*<tool_call\|>',
    re.DOTALL,
)
_MODEL_QUOTED_PARAMETER_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_]*)\s*:\s*<\|"\|>(.*?)<\|"\|>(?=\s*[,}])',
    re.DOTALL,
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
        r'^(?:(?:ok(?:ay)?|perfect|great|cool|nice|awesome|alright|all right|thanks|thank you)[,!.;:\s]+)+',
        '',
        title,
        flags=re.IGNORECASE,
    )
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
    opinion = re.match(
        r'^(?:what do you think (?:of|about)|what(?:\'s| is) your opinion (?:of|on)|'
        r'tell me what you think (?:of|about))\s+(.+)$',
        title,
        flags=re.IGNORECASE,
    )
    if opinion:
        title = f'Review {opinion.group(1)}'

    words = title.split()
    if len(words) > 10:
        title = ' '.join(words[:10])
    title = title[:TATER_AGENT_TASK_TITLE_MAX_CHARS].rstrip(' .,:;-')
    if not title:
        return 'Background task'
    return f'{title[0].upper()}{title[1:]}'


def continuation_progress_update(answer: Any) -> str:
    """Return an unfinished answer as progress so the agent keeps working."""

    text = re.sub(r'\s+', ' ', str(answer or '')).strip()
    if not text or len(text) > 2_000:
        return ''
    normalized = text.replace('’', "'")
    if not _CONTINUATION_ANSWER_RE.search(normalized) or _COMPLETION_ANSWER_RE.search(normalized):
        return ''
    return text[:TATER_AGENT_PROGRESS_MAX_CHARS].rstrip()


def background_task_result_answer(content: Any) -> str:
    """Extract a user-facing task result from the internal completion envelope."""

    text = str(content or '').strip()
    title_match = re.search(r'^Task:\s*(.+)$', text, flags=re.MULTILINE)
    status_match = re.search(r'^Status:\s*(.+)$', text, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else 'Background task'
    status = status_match.group(1).strip().casefold() if status_match else 'completed'
    result = text.partition('--- RESULT ---')[2]
    result = result.partition('--- FINAL WORKING CONTEXT ---')[0].strip()
    if not result:
        result = 'The task finished without a result.'

    if status == 'completed':
        heading = f'**{title} completed.**'
    elif status == 'cancelled':
        heading = f'**{title} was cancelled.**'
    elif status == 'interrupted':
        heading = f'**{title} was interrupted before it finished.**'
    else:
        heading = f'**{title} did not complete successfully.**'
    return f'{heading}\n\n{result}'


def simple_read_only_terminal_history(records: Any) -> bool:
    """Return true for a small, successful batch of obviously read-only commands."""

    if not isinstance(records, list) or not 1 <= len(records) <= 2:
        return False
    for record in records:
        if not isinstance(record, dict) or record.get('tool') != 'terminal' or record.get('status') != 'completed':
            return False
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        command = str(parameters.get('command') or '').strip()
        if not command or re.search(r'[\n;&|><`]|\$\(', command):
            return False
        try:
            arguments = shlex.split(command)
        except ValueError:
            return False
        if not arguments:
            return False
        if any(argument == '--output' or argument.startswith('--output=') for argument in arguments[1:]):
            return False
        executable = arguments[0].rsplit('/', 1)[-1]
        if executable in _FAST_READ_ONLY_COMMANDS:
            continue
        if executable == 'git' and len(arguments) > 1 and arguments[1] in _FAST_READ_ONLY_GIT_COMMANDS:
            continue
        return False
    return True


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
        )[-TATER_AGENT_CONTEXT_LIST_MAX_ITEMS:]
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


def _escape_json_string_controls(content: str) -> str:
    """Escape literal control characters only while inside JSON strings."""

    output = []
    in_string = False
    escaped = False
    for character in content:
        if in_string:
            if escaped:
                output.append(character)
                escaped = False
                continue
            if character == '\\':
                output.append(character)
                escaped = True
                continue
            if character == '"':
                output.append(character)
                in_string = False
                continue
            if character == '\n':
                output.append('\\n')
                continue
            if character == '\r':
                output.append('\\r')
                continue
            if character == '\t':
                output.append('\\t')
                continue
            if ord(character) < 0x20:
                output.append(f'\\u{ord(character):04x}')
                continue
            output.append(character)
            continue

        output.append(character)
        if character == '"':
            in_string = True
    return ''.join(output)


def _model_tool_call_plan(content: str, max_calls: int) -> dict[str, Any] | None:
    calls = []
    for match in _MODEL_TOOL_CALL_RE.finditer(content):
        name = match.group(1).strip()
        raw_parameters = match.group(2).strip()
        if not raw_parameters.startswith('{') or not raw_parameters.endswith('}'):
            continue
        parameters = {}
        for parameter in _MODEL_QUOTED_PARAMETER_RE.finditer(raw_parameters):
            parameters[parameter.group(1)] = parameter.group(2)
        if not parameters:
            try:
                parameters = json.loads(raw_parameters.replace('<|"|>', '"'))
            except json.JSONDecodeError:
                continue
        if not isinstance(parameters, dict):
            continue
        calls.append({'name': name, 'parameters': parameters})
    if not calls:
        return None
    if len(calls) > max(1, max_calls):
        raise ValueError(f'Tool plan contains too many calls ({len(calls)} > {max(1, max_calls)})')
    return {
        'progress': '',
        'task_title': '',
        'tool_calls': calls,
        'parallel_tasks': [],
        'final_answer': '',
        'context': {},
    }


def _json_like_final_answer_plan(content: str) -> dict[str, Any] | None:
    """Recover a no-tools final response containing unescaped prose quotes."""

    if not re.search(r'"tool_calls"\s*:\s*\[\s*\]', content):
        return None
    answer_match = re.search(
        r'"final_answer"\s*:\s*"(.*)"\s*,\s*"context"\s*:',
        content,
        re.DOTALL,
    )
    if not answer_match:
        return None

    final_answer = answer_match.group(1)
    final_answer = (
        final_answer.replace('\\n', '\n')
        .replace('\\r', '\r')
        .replace('\\t', '\t')
        .replace('\\"', '"')
        .replace('\\/', '/')
        .replace('\\\\', '\\')
        .strip()
    )
    if not final_answer:
        return None

    context = {}
    raw_context = content[answer_match.end() :].lstrip()
    if raw_context.startswith('{'):
        try:
            parsed_context, _ = json.JSONDecoder().raw_decode(_escape_json_string_controls(raw_context))
            if isinstance(parsed_context, dict):
                context = parsed_context
        except json.JSONDecodeError:
            pass

    return {
        'progress': '',
        'task_title': '',
        'tool_calls': [],
        'parallel_tasks': [],
        'final_answer': final_answer[:TATER_AGENT_FINAL_ANSWER_MAX_CHARS],
        'context': context,
    }


def parse_tool_plan_response(
    content: str,
    max_calls: int = TATER_AGENT_MAX_CALLS_PER_STEP,
    *,
    allow_plain_final_answer: bool = False,
    allow_parallel_tasks: bool = True,
) -> dict[str, Any]:
    content = str(content or '')
    payload = None
    decoder = json.JSONDecoder()
    for candidate_content in (content, _escape_json_string_controls(content)):
        for index, character in enumerate(candidate_content):
            if character != '{':
                continue
            try:
                candidate, _ = decoder.raw_decode(candidate_content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and (
                'tool_calls' in candidate
                or 'parallel_tasks' in candidate
                or candidate.get('name')
                or 'progress' in candidate
                or 'final_answer' in candidate
            ):
                payload = candidate
                break
        if payload is not None:
            break
    if payload is None:
        model_tool_plan = _model_tool_call_plan(content, max_calls)
        if model_tool_plan is not None:
            return model_tool_plan
        json_like_answer = _json_like_final_answer_plan(content)
        if json_like_answer is not None:
            return json_like_answer
        plain_answer = content.strip()
        if (
            allow_plain_final_answer
            and plain_answer
            and not plain_answer.startswith(('{', '['))
            and '<|tool_call' not in plain_answer.lower()
        ):
            return {
                'progress': '',
                'task_title': '',
                'tool_calls': [],
                'parallel_tasks': [],
                'final_answer': plain_answer[:TATER_AGENT_FINAL_ANSWER_MAX_CHARS],
                'context': {},
            }
        raise ValueError('No tool-plan JSON object found')

    def validated_calls(raw_calls: Any, *, field: str) -> list[dict[str, Any]]:
        if not isinstance(raw_calls, list):
            raise ValueError(f'{field} must be an array')
        parsed_calls = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                raise ValueError(f'Every call in {field} must be an object')
            name = str(raw_call.get('name') or '').strip()
            if not name:
                raise ValueError(f'Every call in {field} must have a name')
            parameters = raw_call.get('parameters', {})
            if not isinstance(parameters, dict):
                raise ValueError(f'Tool parameters for {name} must be an object')
            parsed_calls.append({'name': name, 'parameters': parameters})
        return parsed_calls

    raw_calls = payload.get('tool_calls')
    if raw_calls is None:
        raw_calls = [payload] if payload.get('name') else []
    calls = validated_calls(raw_calls, field='tool_calls')

    raw_parallel_tasks = payload.get('parallel_tasks', [])
    if not isinstance(raw_parallel_tasks, list):
        raise ValueError('parallel_tasks must be an array')
    if len(raw_parallel_tasks) > TATER_AGENT_MAX_PARALLEL_TASKS:
        raise ValueError(
            'Plan contains too many parallel tasks '
            f'({len(raw_parallel_tasks)} > {TATER_AGENT_MAX_PARALLEL_TASKS})'
        )
    if raw_parallel_tasks and not allow_parallel_tasks:
        raise ValueError('parallel_tasks are only allowed on the first planning step of a normal chat')

    parallel_tasks = []
    for index, raw_task in enumerate(raw_parallel_tasks):
        if not isinstance(raw_task, dict):
            raise ValueError('Every parallel task must be an object')
        task_prompt = raw_task.get('task_prompt', '')
        if not isinstance(task_prompt, str):
            raise ValueError('Every parallel task task_prompt must be a string')
        task_prompt = task_prompt.strip()
        if not task_prompt:
            raise ValueError('Every parallel task must have a self-contained task_prompt')
        task_title = raw_task.get('task_title', '')
        task_progress = raw_task.get('progress', '')
        task_context = raw_task.get('context', {})
        if not isinstance(task_title, str):
            raise ValueError('Every parallel task task_title must be a string')
        if not isinstance(task_progress, str):
            raise ValueError('Every parallel task progress must be a string')
        if not isinstance(task_context, dict):
            raise ValueError('Every parallel task context must be an object')
        task_calls = validated_calls(
            raw_task.get('tool_calls', []),
            field=f'parallel_tasks[{index}].tool_calls',
        )
        if not task_calls:
            raise ValueError('Every parallel task must begin with at least one tool call')
        task_title = re.sub(r'\s+', ' ', task_title).strip(' \t\r\n"\'`')[
            :TATER_AGENT_TASK_TITLE_MAX_CHARS
        ]
        task_progress = task_progress.strip()[:TATER_AGENT_PROGRESS_MAX_CHARS]
        if '<|tool_call' in task_title.lower() or '<|tool_call' in task_progress.lower():
            raise ValueError('Parallel task text must not contain tool-call markup')
        parallel_tasks.append(
            {
                'task_title': task_title,
                'task_prompt': task_prompt[:TATER_AGENT_PARALLEL_TASK_PROMPT_MAX_CHARS],
                'progress': task_progress,
                'tool_calls': task_calls,
                'context': task_context,
            }
        )

    total_calls = len(calls) + sum(len(task['tool_calls']) for task in parallel_tasks)
    if total_calls > max(1, max_calls):
        raise ValueError(f'Tool plan contains too many calls ({total_calls} > {max(1, max_calls)})')
    if calls and parallel_tasks:
        raise ValueError('Use either top-level tool_calls or parallel_tasks, not both')
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
    if (calls or parallel_tasks) and final_answer:
        raise ValueError('final_answer must be empty while tool calls or parallel tasks are present')
    return {
        'progress': progress,
        'task_title': task_title,
        'tool_calls': calls,
        'parallel_tasks': parallel_tasks,
        'final_answer': final_answer,
        'context': context,
    }


def parse_tool_plan(content: str, max_calls: int = TATER_AGENT_MAX_CALLS_PER_STEP) -> list[dict[str, Any]]:
    return parse_tool_plan_response(content, max_calls=max_calls)['tool_calls']


def tool_plan_retry_instruction(error: Exception | str) -> str:
    reason = str(error).strip()[:300] or 'invalid tool-plan response'
    return (
        f'Your previous response could not be used ({reason}). Retry the same planning step now. '
        'Return exactly one valid JSON object with task_title, progress, tool_calls, parallel_tasks, final_answer, '
        'and context fields. '
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


def _bounded_history_text(value: Any, max_chars: int) -> str:
    text = str(value or '')
    if max_chars <= 0:
        return ''
    if len(text) <= max_chars:
        return text

    omitted = len(text) - max_chars
    marker = f'\n...[{omitted:,} characters omitted]...\n'
    if len(marker) >= max_chars:
        return text[:max_chars]
    remaining = max_chars - len(marker)
    head = (remaining + 1) // 2
    tail = remaining - head
    return f'{text[:head]}{marker}{text[-tail:] if tail else ""}'


def _history_result_parts(value: Any) -> tuple[dict[str, Any], str]:
    parsed = value
    if isinstance(value, str) and value[:1] in {'{', '['}:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value

    if not isinstance(parsed, dict):
        if isinstance(parsed, str):
            return {'result_chars': len(parsed)}, parsed
        rendered = json.dumps(parsed, ensure_ascii=False, default=str, separators=(',', ':'))
        return {'result_chars': len(rendered)}, rendered

    metadata: dict[str, Any] = {}
    output = parsed.get('output')
    for key, item in parsed.items():
        if key == 'output':
            continue
        if isinstance(item, str):
            metadata[key] = _bounded_history_text(item, 500)
            if len(item) > 500:
                metadata[f'{key}_chars'] = len(item)
        elif item is None or isinstance(item, (bool, int, float)):
            metadata[key] = item

    if isinstance(output, str):
        metadata['output_chars'] = len(output)
        return metadata, output

    rendered = json.dumps(parsed, ensure_ascii=False, default=str, separators=(',', ':'))
    metadata['result_chars'] = len(rendered)
    return metadata, rendered


def render_tool_history(records: list[dict[str, Any]], max_chars: int = TATER_AGENT_HISTORY_MAX_CHARS) -> str:
    """Render history without letting one large result erase earlier commands."""

    if not records or max_chars <= 0:
        return ''

    summaries: list[str] = []
    details: list[tuple[str, str]] = []
    for position, record in enumerate(records, start=1):
        result_metadata, result_detail = _history_result_parts(record.get('result'))
        parameters = json.dumps(
            record.get('parameters') if isinstance(record.get('parameters'), dict) else {},
            ensure_ascii=False,
            default=str,
            separators=(',', ':'),
        )
        parameters = _bounded_history_text(parameters, 1_200)
        result_metadata_text = json.dumps(
            result_metadata,
            ensure_ascii=False,
            default=str,
            separators=(',', ':'),
        )
        iteration = record.get('iteration', position)
        tool = str(record.get('tool') or 'unknown')
        status = str(record.get('status') or 'unknown')
        summaries.append(
            f'{position}. iteration={iteration} tool={tool} status={status} '
            f'parameters={parameters} result={result_metadata_text}'
        )
        if result_detail:
            details.append((f'--- result {position}: {tool} ---', result_detail))

    index_header = 'Tool call index (oldest to newest):'
    index = '\n'.join([index_header, *summaries])
    if len(index) >= max_chars:
        # Extremely small budgets cannot hold every command. Keep the newest
        # complete summaries and never tail-slice the inside of a JSON record.
        selected = []
        used = len(index_header)
        for line in reversed(summaries):
            if used + 1 + len(line) > max_chars:
                break
            selected.append(line)
            used += 1 + len(line)
        selected.reverse()
        if selected:
            while selected:
                omitted = len(summaries) - len(selected)
                omission = f'...[{omitted} older command summaries omitted]...\n' if omitted else ''
                rendered = f'{index_header}\n{omission}' + '\n'.join(selected)
                if len(rendered) <= max_chars:
                    return rendered
                selected.pop(0)
        return _bounded_history_text(summaries[-1], max_chars)

    if not details:
        return index

    details_header = '\n\nTool result excerpts:'
    fixed_size = (
        len(details_header)
        + 1
        + sum(len(header) + 1 for header, _ in details)
        + (2 * (len(details) - 1))
    )
    detail_budget = max_chars - len(index) - fixed_size
    if detail_budget <= 0:
        return index

    per_detail, remainder = divmod(detail_budget, len(details))
    rendered_details = []
    for detail_index, (header, detail) in enumerate(details):
        allowance = per_detail + (1 if detail_index < remainder else 0)
        rendered_details.append(f'{header}\n{_bounded_history_text(detail, allowance)}')

    rendered = f'{index}{details_header}\n' + '\n\n'.join(rendered_details)
    return rendered


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
