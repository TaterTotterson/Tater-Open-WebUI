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
_INTERACTIVE_BUILD_RE = re.compile(
    r'\b(?:build|create|develop|make|write|put together|set up)\b[^\n]{0,160}'
    r'\b(?:app|application|game|website|web site|dashboard|demo|interface|ui)\b',
    re.IGNORECASE,
)
_INTERACTIVE_EXISTING_LAUNCH_RE = re.compile(
    r'\b(?:launch|serve|host|start|run|open)\b[^\n]{0,160}'
    r'\b(?:app|application|game|website|web site|dashboard|demo)\b',
    re.IGNORECASE,
)

_PROGRESS_FUTURE_PREFIX_RE = re.compile(
    r'^(?:(?:okay|ok|alright|sure)[,!.:\-\s]+)?(?:next[,.:\-\s]+)?'
    r'(?:(?:i\s+(?:will|shall|am going to)|i[\'’]ll)\s+|let me\s+)',
    re.IGNORECASE,
)
_PROGRESS_PRESENT_PREFIX_RE = re.compile(
    r'^i\s+(?:am|[\'’]m)\s+(?:now\s+)?(?=[a-z]+ing\b)', re.IGNORECASE
)
_PROGRESS_START_PREFIX_RE = re.compile(
    r'^(?:start|starting|begin|beginning)(?:\s+(?:by|with))?\s+', re.IGNORECASE
)
_PROGRESS_VERB_FORMS = {
    'analyze': 'Analyzing',
    'build': 'Building',
    'change': 'Changing',
    'check': 'Checking',
    'continue': 'Continuing',
    'edit': 'Editing',
    'explore': 'Exploring',
    'find': 'Finding',
    'inspect': 'Inspecting',
    'implement': 'Implementing',
    'locate': 'Locating',
    'look': 'Looking',
    'map': 'Mapping',
    'read': 'Reading',
    'review': 'Reviewing',
    'run': 'Running',
    'scan': 'Scanning',
    'search': 'Searching',
    'take': 'Taking',
    'test': 'Testing',
    'trace': 'Tracing',
    'update': 'Updating',
    'verify': 'Verifying',
}
_INTERACTIVE_LAUNCH_RE = re.compile(
    r'\b(?:launch|serve|host|start|run|open)\b[^\n]{0,100}'
    r'\b(?:it|app|application|game|website|web site|dashboard|demo|interface|ui)?\b',
    re.IGNORECASE,
)
_LOCAL_HTTP_PROBE_RE = re.compile(
    r'\b(?:curl|wget)\b[^\n]*(?:localhost|127\.0\.0\.1|\[::1\])|'
    r'\b(?:urlopen|requests\.get|httpx\.get)\s*\([^\n]*(?:localhost|127\.0\.0\.1|::1)',
    re.IGNORECASE,
)
_HTTP_SUCCESS_RE = re.compile(r'(?mi)^HTTP/\d(?:\.\d)?\s+[23]\d\d\b')
_LOCAL_HTTP_PORT_RE = re.compile(r'(?i)https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{1,5})\b')
_HTTP_SERVER_PORT_RE = re.compile(r'\b(?:http\.server|vite|serve|uvicorn)\b[^\n]*?\b(\d{2,5})\b')
_TERMINAL_COMMAND_ALIASES = {'curl', 'wget', 'git', 'ls', 'cat', 'rg', 'python', 'python3', 'node', 'npm'}
_PORT_REFERENCE_RE = re.compile(
    r'(?:\bport\s*(?:is|:)?\s*|(?:localhost|127\.0\.0\.1):)\d{1,5}\b',
    re.IGNORECASE,
)
_INDEPENDENT_WEATHER_COMPANION_RE = re.compile(
    r'\b(?:also|and(?:\s+also)?)\s+(?:please\s+)?'
    r'(?:(?:tell|show|give)\s+me\b|(?:check|find|get|look up)\b|what(?:\'s| is)\b)'
    r'[^.!?\n]{0,100}\b(?:weather|temperature|temp)\b',
    re.IGNORECASE,
)
_CODE_CHANGE_REQUEST_RE = re.compile(
    r'\b(?:add|build|change|create|develop|edit|fix|implement|make|modify|remove|refactor|repair|replace|'
    r'rewrite|update|write)\b[^\n]{0,180}\b(?:app|application|bug|code|component|endpoint|feature|file|'
    r'function|game|implementation|interface|library|module|package|project|repo|repository|script|service|'
    r'site|test|ui|website)\b|'
    r'\b(?:bug|code|component|endpoint|feature|file|function|implementation|module|project|repo|repository|'
    r'script|service|test|ui)\b[^\n]{0,180}\b(?:add|change|create|edit|fix|implement|modify|remove|refactor|'
    r'repair|replace|rewrite|update|write)\b',
    re.IGNORECASE,
)
_FILE_MUTATION_COMMAND_RE = re.compile(
    r'(?:^|[;&|]\s*)(?:apply_patch\b|(?:sed|perl)\b[^\n;&|]*\s-(?:i|pi)\b|'
    r'(?:cp|install|mkdir|mv|rm|touch|truncate)\b|'
    r'(?:npm|pnpm|yarn|bun)\s+(?:add|install|remove|uninstall|update)\b)|'
    r'(?:^|[^<>])>>?\s*[^&|\s]|'
    r'\b(?:open|write_text|write_bytes)\s*\([^\n]*(?:["\'](?:a|w|x)[+bt]?["\']|\.write)',
    re.IGNORECASE,
)
_GIT_REPOSITORY_COMMAND_RE = re.compile(r'\bgit\s+(?:[^\s]+\s+)*(?:rev-parse|status)\b', re.IGNORECASE)
_GIT_DIFF_COMMAND_RE = re.compile(r'\bgit\s+(?:[^\s]+\s+)*diff\b', re.IGNORECASE)
_CODE_VERIFICATION_COMMAND_RE = re.compile(
    r'\b(?:pytest|py\.test|unittest|vitest|jest|mocha|ava|playwright|cypress|rspec|rubocop|ruff|pylint|'
    r'mypy|eslint|biome|stylelint|shellcheck)\b|'
    r'\bpython(?:\d+(?:\.\d+)*)?\b[^\n;&|]*\s-m\s+(?:compileall|py_compile|pytest|unittest)\b|'
    r'\bnode\b[^\n;&|]*\s--check\b|'
    r'\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:build|check|lint|test|typecheck|validate)\b|'
    r'\b(?:cargo\s+(?:build|check|clippy|test)|go\s+test|dotnet\s+(?:build|test)|'
    r'mvn\s+(?:test|verify)|gradle\w*\s+(?:build|check|test)|make\s+(?:build|check|lint|test)|'
    r'cmake\s+--build|ctest\b|swift\s+(?:build|test))',
    re.IGNORECASE,
)
_UNQUOTED_HEREDOC_RE = re.compile(r'(?m)(<<-?)[ \t]*([A-Za-z_][A-Za-z0-9_]*)\b')
_SHELL_DIAGNOSTIC_RE = re.compile(
    r'(?mi)^(?:/[^:\n]*sh|(?:ba|z|da|a|k)?sh):\s*(?:(?:line\s+)?\d+:\s*)?.*'
    r'(?:not found|syntax error|bad substitution|unexpected|permission denied)\s*$'
)
_CODE_TEST_COMMAND_RE = re.compile(
    r'\b(?:pytest|py\.test|unittest|vitest|jest|mocha|ava|playwright|cypress|rspec)\b|'
    r'\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b|'
    r'\b(?:cargo\s+test|go\s+test|dotnet\s+test|mvn\s+test|gradle\w*\s+test|ctest\b|swift\s+test)',
    re.IGNORECASE,
)
_REGRESSION_TEST_REQUEST_RE = re.compile(
    r'\b(?:bug|defect|regression|broken|fix|repair)\b',
    re.IGNORECASE,
)
_NO_TEST_HARNESS_ANSWER_RE = re.compile(
    r'\b(?:no|without)\s+(?:existing\s+)?test(?:ing)?\s+(?:framework|harness|suite)|'
    r'\bno\s+(?:automated\s+)?tests?\b',
    re.IGNORECASE,
)
_VERIFICATION_BLOCKER_ANSWER_RE = re.compile(
    r"\b(?:blocked|could not|couldn't|failed|failing|failure|unable|unresolved error)\b",
    re.IGNORECASE,
)


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


def naturalize_progress_update(value: Any) -> str:
    """Turn future-work announcements into concise, present-tense activity updates."""

    text = re.sub(r'\s+', ' ', str(value or '').strip())
    if not text:
        return ''

    revised = _PROGRESS_FUTURE_PREFIX_RE.sub('', text, count=1)
    future_announcement = revised != text
    if not future_announcement:
        revised = _PROGRESS_PRESENT_PREFIX_RE.sub('', text, count=1)
        future_announcement = revised != text
    if not future_announcement:
        return text

    revised = _PROGRESS_START_PREFIX_RE.sub('', revised, count=1)
    revised = re.sub(r'^be\s+(?=[a-z]+ing\b)', '', revised, count=1, flags=re.IGNORECASE)
    revised = re.sub(r'^now\s+', '', revised, count=1, flags=re.IGNORECASE).strip()
    if not revised:
        return text

    first_word = re.match(r'^([A-Za-z]+)(.*)$', revised, re.DOTALL)
    if not first_word:
        return revised[:1].upper() + revised[1:]
    verb, remainder = first_word.groups()
    natural_verb = _PROGRESS_VERB_FORMS.get(verb.casefold())
    if natural_verb:
        return f'{natural_verb}{remainder}'
    return revised[:1].upper() + revised[1:]


def live_steering_acknowledgement(messages: Any) -> str:
    """Acknowledge an in-flight user message without implying that the run stopped."""

    candidates = [messages] if isinstance(messages, str) else messages or []
    values = [str(message or '').strip() for message in candidates if str(message or '').strip()]
    if len(values) != 1:
        return 'Got them—I’m incorporating those updates while the current work continues.'

    normalized = _normalized_conversation_text(values[0])
    if normalized in {'thanks', 'thank you', 'thx'}:
        return 'You’re welcome—the current work is still moving along.'
    if normalized in _CONVERSATIONAL_ONLY:
        return 'Sounds good—the current work is still moving along.'
    if '?' in values[0] or _is_task_status_query(normalized):
        return 'Good question—checking it against the work in progress now.'
    return 'Got it—adding that to the work already in progress.'


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


def requires_live_browser_delivery(request: Any) -> bool:
    """Return true when a created interactive result was explicitly requested to be launched."""

    text = re.sub(r'\s+', ' ', str(request or '')).strip()
    return bool(
        (_INTERACTIVE_BUILD_RE.search(text) and _INTERACTIVE_LAUNCH_RE.search(text))
        or (
            _INTERACTIVE_EXISTING_LAUNCH_RE.search(text)
            and re.search(r'\b(?:browser|web|port|connect|play)\b', text, re.IGNORECASE)
        )
    )


def parallel_browser_weather_plan_gap(request: Any, parallel_tasks: Any) -> str:
    """Require separate local-app and live-weather tasks for an explicitly independent request."""

    text = re.sub(r'\s+', ' ', str(request or '')).strip()
    if not requires_live_browser_delivery(text) or not _INDEPENDENT_WEATHER_COMPANION_RE.search(text):
        return ''
    tasks = parallel_tasks if isinstance(parallel_tasks, list) else []
    terminal_task_indexes = set()
    hydra_task_indexes = set()
    for index, task in enumerate(tasks):
        calls = task.get('tool_calls') if isinstance(task, dict) else []
        names = {
            str(call.get('name') or '')
            for call in calls
            if isinstance(call, dict)
        }
        if 'terminal' in names:
            terminal_task_indexes.add(index)
        if 'tater_hydra' in names:
            hydra_task_indexes.add(index)
    if any(
        terminal_index != hydra_index
        for terminal_index in terminal_task_indexes
        for hydra_index in hydra_task_indexes
    ):
        return ''
    return (
        'This request has two independent outcomes. Return parallel_tasks with a terminal task that builds, serves, '
        'and verifies the interactive app and a different tater_hydra task that retrieves the live weather.'
    )


def partition_parallel_tasks(
    parallel_tasks: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split first-step tasks into foreground terminal, background Hydra, and invalid mixed plans."""

    terminal_tasks: list[dict[str, Any]] = []
    hydra_tasks: list[dict[str, Any]] = []
    mixed_tasks: list[dict[str, Any]] = []
    for task in parallel_tasks if isinstance(parallel_tasks, list) else []:
        if not isinstance(task, dict):
            mixed_tasks.append(task)
            continue
        names = {
            str(call.get('name') or '')
            for call in task.get('tool_calls', [])
            if isinstance(call, dict)
        }
        if names == {'terminal'}:
            terminal_tasks.append(task)
        elif names == {'tater_hydra'}:
            hydra_tasks.append(task)
        else:
            mixed_tasks.append(task)
    return terminal_tasks, hydra_tasks, mixed_tasks


def tool_calls_are_hydra_only(tool_calls: Any) -> bool:
    calls = tool_calls if isinstance(tool_calls, list) else []
    return bool(calls) and all(
        isinstance(call, dict) and call.get('name') == 'tater_hydra'
        for call in calls
    )


def execution_routing_plan_gap(tool_calls: Any, parallel_tasks: Any) -> str:
    """Reject plans that would blur foreground terminal work with background Hydra work."""

    calls = tool_calls if isinstance(tool_calls, list) else []
    top_level_names = {
        str(call.get('name') or '')
        for call in calls
        if isinstance(call, dict)
    }
    if 'terminal' in top_level_names and 'tater_hydra' in top_level_names:
        return (
            'Terminal and Hydra work use different execution lanes. Return parallel_tasks with terminal work in '
            'one or more terminal-only tasks and every independent Hydra outcome in its own Hydra-only task.'
        )

    _, _, mixed_tasks = partition_parallel_tasks(parallel_tasks)
    if mixed_tasks:
        return (
            'Every parallel task must use exactly one execution lane. Keep each task terminal-only or Hydra-only, '
            'and use a separate Hydra task for every independent Hydra outcome.'
        )
    return ''


def browser_launch_completion_gap(request: Any, records: Any, final_answer: Any) -> str:
    """Describe missing launch evidence for an interactive browser deliverable."""

    if not requires_live_browser_delivery(request):
        return ''
    records = records if isinstance(records, list) else []
    background_started = False
    for record in records:
        if not isinstance(record, dict) or record.get('tool') != 'terminal':
            continue
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        result = record.get('result')
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result = {}
        result = result if isinstance(result, dict) else {}
        if parameters.get('background') is True and result.get('status') == 'running':
            background_started = True
    if not background_started:
        return (
            'The interactive app was not left running as a background server. Start its server with '
            'terminal background=true before finishing.'
        )
    if not verified_browser_launch_port(records):
        return (
            'The running app has not been verified over local HTTP. Probe its localhost URL with a successful '
            'foreground curl or wget command before finishing.'
        )
    if not _PORT_REFERENCE_RE.search(str(final_answer or '')):
        return (
            'The answer does not identify the verified listening port. Report the exact port and tell the user '
            'they can open it from the Files panel Ports section.'
        )
    return ''


def verified_browser_launch_port(records: Any) -> int | None:
    """Return the port only after a background server answers an HTTP probe."""

    records = records if isinstance(records, list) else []
    server_ports: set[int] = set()
    for record in records:
        if not isinstance(record, dict) or record.get('tool') != 'terminal':
            continue
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        result = _terminal_result(record)
        command = str(parameters.get('command') or '')
        if parameters.get('background') is not True or result.get('status') != 'running':
            continue
        match = _HTTP_SERVER_PORT_RE.search(command)
        if match:
            server_ports.add(int(match.group(1)))

    if not server_ports:
        return None
    for record in reversed(records):
        if not isinstance(record, dict) or record.get('tool') != 'terminal':
            continue
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        command = str(parameters.get('command') or '')
        match = _LOCAL_HTTP_PORT_RE.search(command)
        if not match or int(match.group(1)) not in server_ports or not _successful_local_http_probe(record):
            continue
        return int(match.group(1))
    return None


def completed_browser_launch_answer(request: Any, records: Any, proposed_calls: Any) -> str:
    """Finish a verified launch when the planner tries to rerun its server or probe."""

    if not isinstance(proposed_calls, list) or len(proposed_calls) != 1:
        return ''
    call = proposed_calls[0]
    if not isinstance(call, dict) or call.get('name') != 'terminal':
        return ''
    parameters = call.get('parameters') if isinstance(call.get('parameters'), dict) else {}
    command = str(parameters.get('command') or '')
    if not (_LOCAL_HTTP_PROBE_RE.search(command) or (parameters.get('background') and _HTTP_SERVER_PORT_RE.search(command))):
        return ''
    if not any(
        isinstance(record, dict)
        and record.get('tool') == 'terminal'
        and isinstance(record.get('parameters'), dict)
        and record['parameters'].get('command') == command
        and record['parameters'].get('background', False) == parameters.get('background', False)
        and (
            not parameters.get('cwd')
            or record['parameters'].get('cwd') == parameters.get('cwd')
        )
        for record in (records if isinstance(records, list) else [])
    ):
        return ''
    port = verified_browser_launch_port(records)
    if port is None:
        return ''
    proposed_port = _LOCAL_HTTP_PORT_RE.search(command) or _HTTP_SERVER_PORT_RE.search(command)
    if not proposed_port or int(proposed_port.group(1)) != port:
        return ''
    answer = f'The browser app is running on port {port}, and the server returned HTTP success. Open it from the Files panel’s Ports section.'
    if coding_change_completion_gap(request, records, answer):
        return ''
    return answer


def _terminal_result(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get('result')
    if isinstance(result, str) and result[:1] in {'{', '['}:
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return {}
    return result if isinstance(result, dict) else {}


def protect_terminal_file_write_command(command: Any) -> str:
    """Quote simple heredoc delimiters used by terminal file writes.

    The agent writes source files with literal heredocs. Leaving a delimiter
    unquoted lets the shell execute backticks and expand ``${...}`` inside the
    source body before it reaches the file.
    """

    command = str(command or '')
    if not command or not _FILE_MUTATION_COMMAND_RE.search(command):
        return command

    return _UNQUOTED_HEREDOC_RE.sub(
        lambda match: f"{match.group(1)}'{match.group(2)}'",
        command,
    )


def protect_terminal_tool_calls(calls: Any) -> list[dict[str, Any]]:
    """Normalize terminal writes before signatures, dispatch, and execution."""

    if not isinstance(calls, list):
        return []
    normalized = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        call = dict(call)
        parameters = call.get('parameters')
        if call.get('name') == 'terminal' and isinstance(parameters, dict) and 'command' in parameters:
            parameters = dict(parameters)
            parameters['command'] = protect_terminal_file_write_command(parameters['command'])
            call['parameters'] = parameters
        normalized.append(call)
    return normalized


def terminal_result_has_shell_error(value: Any) -> bool:
    """Detect shell diagnostics that can be hidden by a later zero exit code."""

    parsed = value
    if isinstance(parsed, str) and parsed[:1] in {'{', '['}:
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
    output = parsed.get('output') if isinstance(parsed, dict) else parsed
    return isinstance(output, str) and bool(_SHELL_DIAGNOSTIC_RE.search(output))


def _successful_terminal_record(record: dict[str, Any]) -> bool:
    result = _terminal_result(record)
    return (
        record.get('status') == 'completed'
        and result.get('exit_code') == 0
        and result.get('timed_out') is not True
        and not terminal_result_has_shell_error(result)
    )


def _successful_local_http_probe(record: dict[str, Any]) -> bool:
    parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
    command = str(parameters.get('command') or '')
    if not _LOCAL_HTTP_PROBE_RE.search(command) or not _successful_terminal_record(record):
        return False
    output = str(_terminal_result(record).get('output') or '')
    return bool(
        _HTTP_SUCCESS_RE.search(output)
        or re.search(r'\bcurl\s+[^\n]*-[A-Za-z]*f[A-Za-z]*\b', command)
        or re.search(r'\bwget\s+[^\n]*--spider\b', command)
    )


def coding_change_completion_gap(request: Any, records: Any, final_answer: Any) -> str:
    """Require diff inspection and post-edit verification before reporting coding success."""

    records = records if isinstance(records, list) else []
    terminal_records = [
        (index, record)
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get('tool') == 'terminal'
    ]
    if not terminal_records:
        return ''

    mutation_indexes = []
    for index, record in terminal_records:
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        command = str(parameters.get('command') or '')
        if _FILE_MUTATION_COMMAND_RE.search(command):
            mutation_indexes.append(index)

    coding_request = bool(_CODE_CHANGE_REQUEST_RE.search(str(request or '')))
    if not mutation_indexes and not coding_request:
        return ''
    last_mutation = max(mutation_indexes, default=-1)

    repository_confirmed = False
    diff_inspected = False
    verification_attempted = False
    verification_succeeded = False
    test_attempted = False
    test_succeeded = False
    for index, record in terminal_records:
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        command = str(parameters.get('command') or '')
        successful = _successful_terminal_record(record)
        if successful and _GIT_REPOSITORY_COMMAND_RE.search(command):
            repository_confirmed = True
        if index >= last_mutation and successful and _GIT_DIFF_COMMAND_RE.search(command):
            diff_inspected = True
        if index >= last_mutation and _CODE_VERIFICATION_COMMAND_RE.search(command):
            verification_attempted = True
            verification_succeeded = verification_succeeded or successful
        if index >= last_mutation and _CODE_TEST_COMMAND_RE.search(command):
            test_attempted = True
            test_succeeded = test_succeeded or successful

    if repository_confirmed and not diff_inspected:
        return (
            'Files were changed in a Git repository, but the final diff was not inspected after the last edit. '
            'Run git diff (and preferably git diff --check) now, review the actual changes, then continue.'
        )
    if not verification_attempted:
        return (
            'Code was changed without a post-edit verification command. Run the most relevant focused tests and '
            'a proportionate build, typecheck, lint, compile, or syntax check before finishing.'
        )
    needs_regression_test = bool(_REGRESSION_TEST_REQUEST_RE.search(str(request or '')))
    no_test_harness = bool(_NO_TEST_HARNESS_ANSWER_RE.search(str(final_answer or '')))
    if needs_regression_test and not test_attempted and not no_test_harness:
        return (
            'This is a bug fix or regression-sensitive change, but no focused test ran after the last edit. Add or '
            'update a regression test when the project has a test harness and run it before finishing. If the project '
            'has no test harness, verify that fact and explain it explicitly.'
        )
    if test_attempted and not test_succeeded and not _VERIFICATION_BLOCKER_ANSWER_RE.search(str(final_answer or '')):
        return (
            'A post-edit test command failed. Fix the failure and rerun the focused test, or clearly report the '
            'verified test failure as a blocker instead of claiming success.'
        )
    if not verification_succeeded and not _VERIFICATION_BLOCKER_ANSWER_RE.search(str(final_answer or '')):
        return (
            'The post-edit verification did not pass. Fix the failure and rerun it, or clearly report the verified '
            'failure as a blocker instead of claiming the coding work succeeded.'
        )
    return ''


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


def resolved_background_task_prompt(prompt: Any, plan: Any) -> str:
    """Use a self-contained Hydra request instead of a vague conversational follow-up."""

    fallback = str(prompt or '').strip()
    if not isinstance(plan, dict):
        return fallback
    calls = plan.get('tool_calls')
    if not isinstance(calls, list) or len(calls) != 1:
        return fallback
    call = calls[0]
    if not isinstance(call, dict) or call.get('name') != 'tater_hydra':
        return fallback
    parameters = call.get('parameters') if isinstance(call.get('parameters'), dict) else {}
    request = str(parameters.get('request') or '').strip()
    return request or fallback


def completed_hydra_delegation_answer(records: Any) -> str:
    """Return Hydra's final response when an isolated delegation completed successfully."""

    if not isinstance(records, list) or not records:
        return ''
    responses = []
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get('tool') != 'tater_hydra'
            or record.get('status') != 'completed'
        ):
            return ''
        result = record.get('result')
        if isinstance(result, str) and result[:1] in {'{', '['}:
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return ''
        if not isinstance(result, dict) or result.get('status') != 'completed':
            return ''
        response = str(result.get('response') or '').strip()
        artifacts = [item for item in result.get('artifacts', []) if isinstance(item, dict)]
        if response:
            responses.append(response)
        elif artifacts:
            media_types = sorted(
                {
                    str(item.get('type') or 'media').strip().lower() or 'media'
                    for item in artifacts
                }
            )
            label = ', '.join(media_types) if media_types else 'media'
            responses.append(
                f'Tater Hydra generated {len(artifacts)} {label} artifact'
                f'{"s" if len(artifacts) != 1 else ""}. The generated media is attached.'
            )
        else:
            return ''
    return '\n\n'.join(responses)


def terminal_command_is_obviously_read_only(command: Any) -> bool:
    """Return true only when a shell command cannot reasonably change task state."""

    command = str(command or '').strip()
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
        return True
    return bool(executable == 'git' and len(arguments) > 1 and arguments[1] in _FAST_READ_ONLY_GIT_COMMANDS)


def simple_read_only_terminal_history(records: Any) -> bool:
    """Return true for a small, successful batch of obviously read-only commands."""

    if not isinstance(records, list) or not 1 <= len(records) <= 2:
        return False
    for record in records:
        if not isinstance(record, dict) or record.get('tool') != 'terminal' or record.get('status') != 'completed':
            return False
        parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
        if not terminal_command_is_obviously_read_only(parameters.get('command')):
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


def _decode_json_like_string(value: str) -> str:
    """Decode common JSON escapes without requiring an otherwise-valid JSON string."""

    return (
        value.replace('\\n', '\n')
        .replace('\\r', '\r')
        .replace('\\t', '\t')
        .replace('\\"', '"')
        .replace('\\/', '/')
        .replace('\\\\', '\\')
    )


def _json_like_tool_plan(content: str, max_calls: int) -> dict[str, Any] | None:
    """Recover complete tool calls whose multiline command made the outer JSON invalid."""

    calls_header = re.search(r'"tool_calls"\s*:\s*\[', content)
    if not calls_header:
        return None
    calls_tail = re.search(
        r'\]\s*,\s*"parallel_tasks"\s*:\s*\[\s*\]',
        content[calls_header.end() :],
        re.DOTALL,
    )
    if not calls_tail:
        return None

    calls_content = content[calls_header.end() : calls_header.end() + calls_tail.start()]
    call_pattern = re.compile(
        r'\{\s*"name"\s*:\s*"([^"\r\n]+)"\s*,\s*"parameters"\s*:\s*\{',
        re.DOTALL,
    )
    call_matches = list(call_pattern.finditer(calls_content))
    if not call_matches:
        return None

    calls = []
    for index, call_match in enumerate(call_matches):
        segment_end = call_matches[index + 1].start() if index + 1 < len(call_matches) else len(calls_content)
        segment = calls_content[call_match.end() : segment_end]
        if not re.search(r'\}\s*(?:\}\s*)?,?\s*$', segment, re.DOTALL):
            continue

        name = call_match.group(1).strip()
        parameter_name = 'command' if name == 'terminal' else 'request' if name == 'tater_hydra' else ''
        if not parameter_name:
            continue
        value_header = re.search(rf'"{parameter_name}"\s*:\s*"', segment)
        if not value_header:
            continue
        value_tail = segment[value_header.end() :]

        delimiter_positions = []
        for following_name in ('cwd', 'background', 'timeout_seconds'):
            matches = list(
                re.finditer(
                    rf'"\s*,\s*"{following_name}"\s*:',
                    value_tail,
                    re.DOTALL,
                )
            )
            if matches:
                delimiter_positions.append(matches[-1].start())
        if delimiter_positions:
            value_end = min(delimiter_positions)
        else:
            value_end_match = re.search(
                r'"\s*\}\s*(?:\}\s*)?,?\s*$',
                value_tail,
                re.DOTALL,
            )
            if not value_end_match:
                continue
            value_end = value_end_match.start()

        raw_value = value_tail[:value_end]
        parameters: dict[str, Any] = {parameter_name: _decode_json_like_string(raw_value)}
        remaining = value_tail[value_end:]
        cwd_match = re.search(r'"cwd"\s*:\s*"([^"\r\n]*)"', remaining)
        if cwd_match:
            parameters['cwd'] = _decode_json_like_string(cwd_match.group(1))
        background_match = re.search(r'"background"\s*:\s*(true|false)', remaining, re.IGNORECASE)
        if background_match:
            parameters['background'] = background_match.group(1).casefold() == 'true'
        calls.append({'name': name, 'parameters': parameters})

    if not calls:
        return None
    if len(calls) > max(1, max_calls):
        raise ValueError(f'Tool plan contains too many calls ({len(calls)} > {max(1, max_calls)})')

    def text_field(field: str, following_field: str) -> str:
        match = re.search(
            rf'"{field}"\s*:\s*"(.*?)"\s*,\s*"{following_field}"\s*:',
            content[: calls_header.end()],
            re.DOTALL,
        )
        return _decode_json_like_string(match.group(1)).strip() if match else ''

    return {
        'progress': text_field('progress', 'tool_calls')[:TATER_AGENT_PROGRESS_MAX_CHARS],
        'task_title': text_field('task_title', 'progress')[:TATER_AGENT_TASK_TITLE_MAX_CHARS],
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
        json_like_tool_plan = _json_like_tool_plan(content, max_calls)
        if json_like_tool_plan is not None:
            return json_like_tool_plan
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
            inferred_parameters = None
            if isinstance(raw_call.get('command'), str) and (
                not name or name == 'terminal' or name in _TERMINAL_COMMAND_ALIASES
            ):
                name = 'terminal'
                inferred_parameters = {
                    key: raw_call[key]
                    for key in ('command', 'cwd', 'background', 'timeout_seconds')
                    if key in raw_call
                }
            elif not name and isinstance(raw_call.get('request'), str):
                name = 'tater_hydra'
                inferred_parameters = {'request': raw_call['request']}
            if not name:
                raise ValueError(f'Every call in {field} must have a name')
            parameters = raw_call.get('parameters', inferred_parameters or {})
            if not isinstance(parameters, dict):
                raise ValueError(f'Tool parameters for {name} must be an object')
            if name in _TERMINAL_COMMAND_ALIASES and isinstance(parameters.get('command'), str):
                name = 'terminal'
            if name == 'terminal' and not isinstance(parameters.get('command'), str):
                raise ValueError('terminal requires a command string')
            parsed_calls.append({'name': name, 'parameters': parameters})
        return parsed_calls

    raw_calls = payload.get('tool_calls')
    if raw_calls is None:
        raw_calls = [payload] if payload.get('name') else []
    calls = validated_calls(raw_calls, field='tool_calls')

    raw_parallel_tasks = payload.get('parallel_tasks', [])
    if not isinstance(raw_parallel_tasks, list):
        raise ValueError('parallel_tasks must be an array')
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
        if len(task_calls) > max(1, max_calls):
            raise ValueError(
                f'Parallel task contains too many initial calls ({len(task_calls)} > {max(1, max_calls)})'
            )
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

    if len(calls) > max(1, max_calls):
        raise ValueError(f'Tool plan contains too many calls ({len(calls)} > {max(1, max_calls)})')
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


def tool_plan_retry_instruction(
    error: Exception | str,
    previous_response: str = '',
    original_request: str = '',
) -> str:
    reason = str(error).strip()[:300] or 'invalid tool-plan response'
    previous_response = str(previous_response or '')
    original_request = _safe_activity_preview(original_request, max_chars=500)
    if 'identical' in reason.casefold() and 'call already' in reason.casefold():
        completed_call = ''
        requested_outcome = ''
        repeated_file_write = False
        try:
            rejected_plan = parse_tool_plan_response(previous_response)
            requested_outcome = _safe_activity_preview(rejected_plan.get('task_title'), max_chars=160)
            rejected_calls = rejected_plan.get('tool_calls') or []
            if rejected_calls:
                rejected = rejected_calls[0]
                rejected_name = str(rejected.get('name') or 'tool').strip()
                rejected_parameters = (
                    rejected.get('parameters')
                    if isinstance(rejected.get('parameters'), dict)
                    else {}
                )
                if rejected_name == 'terminal':
                    raw_command = str(rejected_parameters.get('command') or '')
                    repeated_file_write = bool(_FILE_MUTATION_COMMAND_RE.search(raw_command))
                    command = _safe_activity_preview(raw_command, max_chars=300)
                    cwd = _safe_activity_preview(rejected_parameters.get('cwd'), max_chars=120)
                    completed_call = f'{cwd}$ {command}' if cwd else command
                else:
                    completed_call = _safe_activity_preview(rejected_parameters, max_chars=300)
                if completed_call:
                    completed_call = f' The completed action was {rejected_name}: {completed_call}.'
        except ValueError:
            pass

        objective = requested_outcome or original_request
        objective_instruction = f' The requested outcome is: {objective}.' if objective else ''
        next_action_instruction = (
            ' This exact file write already succeeded. Earlier reads of that file are now stale. Do not write it '
            'again and do not try to repair an error from an older read. Inspect the current file with a focused '
            'read, run a syntax check or test, work on a different missing file, or finish.'
            if repeated_file_write
            else ''
        )
        return (
            f'The last plan repeated a completed call ({reason}). This does not mean the command failed; it means '
            f'the command already succeeded and its evidence is still available.{completed_call}'
            f'{objective_instruction}{next_action_instruction} '
            'Compare the requested outcome with what that completed action actually accomplished, identify the still '
            'missing result, and select the next action that closes that gap. Repeating the same read while its input '
            'is unchanged would only return the same evidence. Return exactly one valid JSON object that either '
            'contains a terminal call which concretely advances the unresolved outcome, or contains a final_answer '
            'if the outcome is already complete. For a browser-app launch, inspecting existing entry files does not '
            'launch them; if they are usable, start the HTTP server with '
            'background=true; after it starts, use the next planning step to probe localhost. Do not include Markdown '
            'or prose outside the JSON object.'
        )
    attempted_multiline_write = bool(
        re.search(
            r'(?:<<\s*[\'\"]?[A-Za-z_][A-Za-z0-9_]*|\btee\s+[^\n]+|\b(?:cat|printf)\b[^\n]*>\s*[^\s])',
            previous_response,
            re.IGNORECASE,
        )
    )
    if attempted_multiline_write:
        return (
            f'Your previous file-writing plan could not be used ({reason}). Preserve that write step; do not '
            'return to directory listing or reread files whose output is already in the execution history. Retry '
            'with exactly one terminal call for the next file. The entire response must be one valid JSON object '
            'with task_title, progress, tool_calls, parallel_tasks, final_answer, and context fields. Use one ordinary '
            'quoted heredoc command for the file and do not encode its contents as base64. Do not include '
            'Markdown, tool-call markup, or prose outside the JSON object.'
        )
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
        mutation_note = ''
        if tool == 'terminal' and status == 'completed':
            record_parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
            if _FILE_MUTATION_COMMAND_RE.search(str(record_parameters.get('command') or '')):
                mutation_note = (
                    ' note="This file mutation completed. Earlier reads of files changed by it are stale; '
                    'verify current state instead of repeating the write."'
                )
        summaries.append(
            f'{position}. iteration={iteration} tool={tool} status={status} '
            f'parameters={parameters} result={result_metadata_text}{mutation_note}'
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


def tool_call_signature(name: str, parameters: dict[str, Any], *, cwd: str = '') -> str:
    """Return a stable signature for a proposed tool call before it executes."""

    name = str(name or '').strip()
    normalized_parameters = dict(parameters) if isinstance(parameters, dict) else {}
    if name == 'terminal' and not str(normalized_parameters.get('cwd') or '').strip() and cwd:
        normalized_parameters['cwd'] = cwd
    payload = json.dumps(
        {'name': name, 'parameters': normalized_parameters},
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _terminal_file_read_targets(command: Any, cwd: str = '') -> tuple[str, ...]:
    """Return concrete files read by simple commands whose result can be safely reused."""

    command = str(command or '').strip()
    if not terminal_command_is_obviously_read_only(command):
        return ()
    try:
        arguments = shlex.split(command)
    except ValueError:
        return ()
    if not arguments or arguments[0].rsplit('/', 1)[-1] != 'cat':
        return ()

    targets = []
    for argument in arguments[1:]:
        if argument == '--':
            continue
        if argument.startswith('-') or argument == '/dev/stdin':
            continue
        target = argument if os.path.isabs(argument) else os.path.join(cwd or '.', argument)
        targets.append(os.path.normpath(target))
    return tuple(targets)


def _terminal_action_may_change_targets(record: dict[str, Any], targets: tuple[str, ...]) -> bool:
    """Return true when a later terminal action plausibly changed one of the read files."""

    if not targets or str(record.get('tool') or '') != 'terminal':
        return False
    parameters = record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
    command = str(parameters.get('command') or '').strip()
    if not command or terminal_command_is_obviously_read_only(command):
        return False

    command_cwd = str(parameters.get('cwd') or '').strip()
    for target in targets:
        relative_target = ''
        if command_cwd:
            try:
                relative_target = os.path.relpath(target, command_cwd)
            except ValueError:
                relative_target = ''
        candidates = {target, os.path.basename(target)}
        if relative_target and relative_target != '.':
            candidates.add(relative_target)
        if any(candidate and candidate in command for candidate in candidates):
            return True

    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if len(arguments) < 2 or arguments[0].rsplit('/', 1)[-1] != 'git':
        return False
    return arguments[1] in {
        'checkout',
        'merge',
        'pull',
        'rebase',
        'reset',
        'restore',
    }


def repeated_tool_call_plan_gap(tool_calls: Any, records: Any) -> str:
    """Reject repeated calls whose relevant inputs have not changed."""

    if not isinstance(tool_calls, list) or not tool_calls or not isinstance(records, list):
        return ''

    execution_records = []
    for record in records:
        if not isinstance(record, dict):
            continue
        tool = str(record.get('tool') or '').strip()
        if (
            not tool
            or tool.startswith('agent_')
            or tool in {'foreground_task_scope', 'user_steering'}
            or not isinstance(record.get('parameters'), dict)
        ):
            continue
        execution_records.append(record)
    if not execution_records:
        return ''

    def terminal_result_cwd(record: dict[str, Any]) -> str:
        result = record.get('result')
        if isinstance(result, str) and result[:1] in {'{', '['}:
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return ''
        return str(result.get('cwd') or '').strip() if isinstance(result, dict) else ''

    active_terminal_cwd = ''
    for record in reversed(execution_records):
        if record.get('tool') == 'terminal':
            active_terminal_cwd = terminal_result_cwd(record)
            if active_terminal_cwd:
                break

    latest_iteration = execution_records[-1].get('iteration')
    proposed_signatures: set[str] = set()
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get('name') or '').strip()
        parameters = call.get('parameters') if isinstance(call.get('parameters'), dict) else {}
        signature = tool_call_signature(name, parameters, cwd=active_terminal_cwd)
        if signature in proposed_signatures:
            return (
                f'The plan contains the identical {name or "tool"} call more than once. Keep one copy and use '
                'a different focused call for any additional evidence.'
            )
        proposed_signatures.add(signature)

        previous = None
        for record_index in range(len(execution_records) - 1, -1, -1):
            record = execution_records[record_index]
            record_signature = tool_call_signature(
                str(record.get('tool') or ''),
                record.get('parameters') or {},
                cwd=terminal_result_cwd(record),
            )
            if record_signature != signature:
                continue
            calls_since = execution_records[record_index + 1 :]
            record_parameters = (
                record.get('parameters') if isinstance(record.get('parameters'), dict) else {}
            )
            if name == 'terminal' and record_parameters.get('background') is True:
                prior_result = _terminal_result(record)
                if prior_result.get('status') == 'running' and not any(
                    str((item.get('parameters') or {}).get('command') or '').strip().startswith(('kill ', 'pkill '))
                    for item in calls_since
                ):
                    return (
                        'The identical background terminal command is already running. Do not launch a second '
                        'server. Probe its localhost port, or finish if a successful HTTP probe is already in history.'
                    )
            if name == 'terminal' and _successful_local_http_probe(record):
                if not any(
                    (item.get('parameters') or {}).get('background') is True
                    or _FILE_MUTATION_COMMAND_RE.search(
                        str((item.get('parameters') or {}).get('command') or '')
                    )
                    for item in calls_since
                ):
                    return (
                        'The identical local HTTP probe already returned success. Do not probe it again. '
                        'Report the verified port and finish.'
                    )
            record_cwd = str(record_parameters.get('cwd') or terminal_result_cwd(record)).strip()
            read_targets = (
                _terminal_file_read_targets(record_parameters.get('command'), record_cwd)
                if name == 'terminal'
                else ()
            )
            target_unchanged_since = bool(
                read_targets
                and not any(
                    _terminal_action_may_change_targets(item, read_targets)
                    for item in calls_since
                )
            )
            unchanged_since = bool(
                name == 'terminal'
                and all(
                    str(item.get('tool') or '') == 'terminal'
                    and terminal_command_is_obviously_read_only(
                        (item.get('parameters') or {}).get('command')
                    )
                    for item in calls_since
                )
            )
            if (
                record.get('iteration') == latest_iteration
                or unchanged_since
                or target_unchanged_since
            ):
                previous = record
            break
        if not previous:
            continue
        previous_status = str(previous.get('status') or '').strip().casefold()
        if previous_status == 'completed':
            return (
                f'The identical {name or "tool"} call already completed and no intervening action changed its '
                'inputs. Its result is in the history. Do not repeat it. A successful command only proves that it '
                'ran; if its output did not answer the task, choose a different command, path, search, or line range. '
                'Otherwise continue from that evidence or finish.'
            )
        return (
            f'The identical {name or "tool"} call already failed and no intervening action corrected its inputs. '
            'Retrying it unchanged cannot correct the failure. Inspect the recorded error and change the command or '
            'parameters, use another approach, or report the concrete blocker.'
        )
    return ''
