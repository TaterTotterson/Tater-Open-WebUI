from __future__ import annotations

import asyncio
import copy
import logging
import time
import traceback
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from starlette.datastructures import Headers

from open_webui.internal.db import get_async_db_context
from open_webui.models.chat_messages import ChatMessages
from open_webui.models.chats import Chat, ChatForm, ChatModel, Chats
from open_webui.models.users import UserModel
from open_webui.tasks import create_task, list_tasks
from open_webui.utils.auth import create_token
from open_webui.utils.misc import get_last_user_message
from open_webui.utils.tater_agent import (
    TATER_AGENT_CONTEXT_LIST_MAX_ITEMS,
    TATER_AGENT_MAX_PARALLEL_TASKS,
    background_task_result_answer,
    merge_task_context,
    normalize_agent_context,
    normalize_task_title,
)
from open_webui.utils.tater_run_ledger import record_tater_run_event

TATER_TASK_TYPE = 'tater_task'
TATER_TASK_ACTIVE_STATUSES = {'queued', 'running', 'cancelling'}
TATER_TASK_MAX_CONCURRENT_PER_USER = TATER_AGENT_MAX_PARALLEL_TASKS
TATER_TASK_RESULT_MAX_CHARS = 40_000
TATER_TASK_PROMPT_MAX_CHARS = 12_000
TATER_TASK_HISTORY_LIMIT_MAX = 200
TATER_TASK_HISTORY_PREVIEW_MAX_CHARS = 600
TATER_TASK_LIVE_EVENT_LIMIT = 12
TATER_TASK_LIVE_EVENT_MAX_CHARS = 600
TATER_TASK_RESULT_SUMMARY_MAX_CHARS = 4_000

log = logging.getLogger(__name__)


def _build_internal_request(
    source: Request,
    user_id: str,
    task_id: str,
    parent_chat_id: str,
    initial_plan: dict[str, Any],
) -> Request:
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.0'},
        'method': 'POST',
        'path': '/api/v1/tater/tasks/internal',
        'query_string': b'',
        'headers': Headers({}).raw,
        'client': ('127.0.0.1', 0),
        'server': ('127.0.0.1', 80),
        'scheme': 'http',
        'app': source.app,
    }
    request = Request(scope)
    token = create_token(data={'id': user_id, 'typ': 'tater-task'}, expires_delta=timedelta(hours=24))
    request.state.token = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
    request.state.enable_api_keys = False
    request.state.internal = True
    request.state.tater_task_id = task_id
    request.state.tater_parent_chat_id = parent_chat_id
    request.state.tater_initial_plan = copy.deepcopy(initial_plan)
    return request


def _runtime_task_ids(values: list[Any]) -> set[str]:
    return {
        value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)
        for value in values
    }


def tater_task_summary(chat: ChatModel) -> dict[str, Any]:
    meta = chat.meta or {}
    return {
        'id': chat.id,
        'title': chat.title,
        'status': str(meta.get('status') or 'unknown'),
        'activity': str(meta.get('activity') or ''),
        'progress_events': list(meta.get('progress_events') or []),
        'result_summary': str(meta.get('result_summary') or ''),
        'capabilities': list(meta.get('capabilities') or []),
        'parent_chat_id': meta.get('parent_chat_id'),
        'created_at': chat.created_at,
        'updated_at': chat.updated_at,
        'started_at': meta.get('started_at'),
        'finished_at': meta.get('finished_at'),
    }


def _task_chat_messages(chat: ChatModel) -> list[dict[str, Any]]:
    history = (chat.chat or {}).get('history') or {}
    messages = history.get('messages') or {}
    if not isinstance(messages, dict):
        return []
    return sorted(
        [message for message in messages.values() if isinstance(message, dict)],
        key=lambda message: int(message.get('timestamp') or 0),
    )


def _task_prompt(chat: ChatModel) -> str:
    for message in _task_chat_messages(chat):
        if message.get('role') == 'user':
            return _message_text(message)[:TATER_TASK_PROMPT_MAX_CHARS]
    return ''


def _task_output(chat: ChatModel) -> str:
    context = (chat.chat or {}).get('taterAgentContext') or {}
    if isinstance(context, dict):
        summary = str(context.get('execution_summary') or '').strip()
        if summary:
            return summary[:TATER_TASK_RESULT_MAX_CHARS]

    for message in reversed(_task_chat_messages(chat)):
        if message.get('role') != 'assistant':
            continue
        content = _message_text(message)
        if content:
            return content[:TATER_TASK_RESULT_MAX_CHARS]
        error = message.get('error')
        if error:
            error_text = error.get('content', str(error)) if isinstance(error, dict) else str(error)
            if error_text.strip():
                return error_text.strip()[:TATER_TASK_RESULT_MAX_CHARS]
    return str((chat.meta or {}).get('activity') or '').strip()[:TATER_TASK_RESULT_MAX_CHARS]


def tater_task_detail(chat: ChatModel) -> dict[str, Any]:
    return {
        **tater_task_summary(chat),
        'prompt': _task_prompt(chat),
        'output': _task_output(chat),
    }


async def get_user_tater_task_history(
    user_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), TATER_TASK_HISTORY_LIMIT_MAX))
    offset = max(0, int(offset))
    chats = await get_user_tater_task_chats(user_id)
    completed_tasks = [
        chat
        for chat in chats
        if str((chat.meta or {}).get('status') or '') not in TATER_TASK_ACTIVE_STATUSES
    ]
    completed = completed_tasks[offset : offset + limit]

    parent_ids = {
        str((chat.meta or {}).get('parent_chat_id'))
        for chat in completed
        if (chat.meta or {}).get('parent_chat_id')
    }
    parent_titles: dict[str, str] = {}
    if parent_ids:
        async with get_async_db_context() as db:
            result = await db.execute(
                select(Chat.id, Chat.title).where(Chat.user_id == user_id, Chat.id.in_(parent_ids))
            )
            parent_titles = {str(chat_id): str(title or 'Untitled chat') for chat_id, title in result.all()}

    history = []
    for chat in completed:
        detail = tater_task_detail(chat)
        summary = tater_task_summary(chat)
        parent_chat_id = str(summary.get('parent_chat_id') or '')
        history.append(
            {
                **summary,
                'parent_chat_title': parent_titles.get(parent_chat_id),
                'prompt_preview': detail['prompt'][:TATER_TASK_HISTORY_PREVIEW_MAX_CHARS],
                'output_preview': detail['output'][:TATER_TASK_HISTORY_PREVIEW_MAX_CHARS],
            }
        )
    return history


async def get_user_tater_task_chats(user_id: str) -> list[ChatModel]:
    async with get_async_db_context() as db:
        result = await db.execute(
            select(Chat)
            .where(Chat.user_id == user_id, Chat.meta['internal'].as_boolean().is_(True))
            .order_by(Chat.created_at.desc())
        )
        chats = [ChatModel.model_validate(chat) for chat in result.scalars().all()]
    return [chat for chat in chats if (chat.meta or {}).get('type') == TATER_TASK_TYPE]


async def get_user_tater_task(task_id: str, user_id: str) -> ChatModel | None:
    chat = await Chats.get_chat_by_id_and_user_id(task_id, user_id)
    if not chat or (chat.meta or {}).get('type') != TATER_TASK_TYPE:
        return None
    return chat


async def update_tater_task(
    task_id: str,
    updates: dict[str, Any],
    *,
    user_id: str | None = None,
    touch: bool = True,
) -> ChatModel | None:
    async with get_async_db_context() as db:
        statement = select(Chat).where(Chat.id == task_id)
        if user_id:
            statement = statement.where(Chat.user_id == user_id)
        if db.bind.dialect.name == 'postgresql':
            statement = statement.with_for_update()
        result = await db.execute(statement)
        chat = result.scalar_one_or_none()
        if not chat or (chat.meta or {}).get('type') != TATER_TASK_TYPE:
            return None

        chat.meta = {**(chat.meta or {}), **updates}
        flag_modified(chat, 'meta')
        if touch:
            chat.updated_at = int(time.time())
        await db.commit()
        return ChatModel.model_validate(chat)


def _clean_live_event_message(value: Any) -> str:
    message = ' '.join(str(value or '').split()).strip()
    if len(message) > TATER_TASK_LIVE_EVENT_MAX_CHARS:
        return f'{message[: TATER_TASK_LIVE_EVENT_MAX_CHARS - 1].rstrip()}…'
    return message


async def record_tater_task_progress(
    task_id: str,
    message: str,
    *,
    kind: str,
    user_id: str | None = None,
) -> ChatModel | None:
    """Persist a small, safe live handoff that the originating chat can inspect."""

    message = _clean_live_event_message(message)
    if not message:
        return None

    async with get_async_db_context() as db:
        statement = select(Chat).where(Chat.id == task_id)
        if user_id:
            statement = statement.where(Chat.user_id == user_id)
        if db.bind.dialect.name == 'postgresql':
            statement = statement.with_for_update()
        result = await db.execute(statement)
        chat = result.scalar_one_or_none()
        if not chat or (chat.meta or {}).get('type') != TATER_TASK_TYPE:
            return None

        meta = dict(chat.meta or {})
        events = [event for event in (meta.get('progress_events') or []) if isinstance(event, dict)]
        event = {'at': int(time.time()), 'kind': str(kind or 'progress')[:40], 'message': message}
        if events and events[-1].get('kind') == event['kind'] and events[-1].get('message') == message:
            events[-1] = event
        else:
            events.append(event)
        meta['progress_events'] = events[-TATER_TASK_LIVE_EVENT_LIMIT:]
        meta['activity'] = message[:240]
        chat.meta = meta
        chat.updated_at = int(time.time())
        flag_modified(chat, 'meta')
        await db.commit()
        return ChatModel.model_validate(chat)


async def emit_tater_task_event(user_id: str, task_id: str, status: str) -> None:
    from open_webui.socket.main import sio

    await sio.emit(
        'events',
        {
            'chat_id': task_id,
            'message_id': '',
            'data': {'type': 'tater:tasks', 'data': {'task_id': task_id, 'status': status}},
        },
        room=f'user:{user_id}',
    )


async def reconcile_user_tater_tasks(app, user_id: str) -> list[ChatModel]:
    chats = await get_user_tater_task_chats(user_id)
    active_ids = _runtime_task_ids(await list_tasks(app.state.redis))
    for chat in chats:
        if (chat.meta or {}).get('status') in TATER_TASK_ACTIVE_STATUSES and chat.id not in active_ids:
            updated = await update_tater_task(
                chat.id,
                {
                    'status': 'interrupted',
                    'activity': 'The server stopped before this task finished.',
                    'result_summary': 'The server stopped before this task finished.',
                    'finished_at': int(time.time()),
                },
                user_id=user_id,
            )
            if updated:
                chat = updated
    return await get_user_tater_task_chats(user_id)


def _working_context_lines(chat: ChatModel) -> list[str]:
    context = normalize_agent_context((chat.chat or {}).get('taterAgentContext'))
    lines = []
    location = ', '.join(
        value
        for value in (
            f'repository {context["repository_root"]}' if context.get('repository_root') else '',
            f'branch {context["branch"]}' if context.get('branch') else '',
            f'cwd {context["cwd"]}' if context.get('cwd') else '',
        )
        if value
    )
    if location:
        lines.append(f'  Working location: {location}')
    if context.get('files_changed'):
        lines.append(f'  Files changed so far: {", ".join(context["files_changed"][-5:])}')
    if context.get('blockers'):
        lines.append(f'  Current blocker: {context["blockers"][-1]}')
    return lines


def _detailed_task_lines(chat: ChatModel) -> list[str]:
    task = tater_task_summary(chat)
    lines = [f'- {task["id"]}: {task["title"]} — {task["status"]}']
    prompt = _task_prompt(chat)
    if prompt:
        lines.append(f'  Requested work: {_clean_live_event_message(prompt)[:500]}')
    if task['activity']:
        lines.append(f'  Current state: {task["activity"]}')
    lines.extend(_working_context_lines(chat))
    progress_events = [event for event in task['progress_events'] if isinstance(event, dict)][-4:]
    if progress_events:
        lines.append('  Recent progress:')
        lines.extend(
            f'    - {str(event.get("message") or "").strip()}'
            for event in progress_events
            if str(event.get('message') or '').strip()
        )
    if task['status'] not in TATER_TASK_ACTIVE_STATUSES:
        outcome = task['result_summary'] or _task_output(chat)
        if outcome:
            lines.append(f'  Outcome: {outcome[:1_500]}')
    return lines


async def tater_task_awareness(
    app,
    user_id: str,
    *,
    chat_id: str | None = None,
    exclude_task_id: str | None = None,
) -> str:
    chats = await reconcile_user_tater_tasks(app, user_id)
    chats = [chat for chat in chats if chat.id != exclude_task_id]
    if chat_id:
        related = [chat for chat in chats if str((chat.meta or {}).get('parent_chat_id') or '') == chat_id]
        related_ids = {chat.id for chat in related}
        other = [chat for chat in chats if chat.id not in related_ids]
    else:
        related = chats
        other = []

    related_running = [
        chat for chat in related if str((chat.meta or {}).get('status') or '') in TATER_TASK_ACTIVE_STATUSES
    ]
    related_recent = sorted(
        [
            chat
            for chat in related
            if str((chat.meta or {}).get('status') or '') not in TATER_TASK_ACTIVE_STATUSES
        ],
        key=lambda chat: chat.updated_at or 0,
        reverse=True,
    )[:3]
    other_running = [
        tater_task_summary(chat)
        for chat in other
        if str((chat.meta or {}).get('status') or '') in TATER_TASK_ACTIVE_STATUSES
    ]

    lines = [
        'Authoritative background work owned by this assistant:',
        'These are tasks you started and remain responsible for. Refer to them as your background tasks, not as '
        'unrelated external jobs.',
    ]
    if chat_id:
        lines.append('Tasks started from this chat:')
    if related_running:
        lines.append('Active:')
        for chat in related_running:
            lines.extend(_detailed_task_lines(chat))
    else:
        lines.append('Active: none')
    if related_recent:
        lines.append('Recently finished from this chat:')
        for chat in related_recent:
            lines.extend(_detailed_task_lines(chat))
    if other_running:
        lines.append('Other active tasks (brief cross-chat awareness):')
        lines.extend(
            f'- {task["id"]}: {task["title"]} — {task["status"]}'
            + (f' — {task["activity"]}' if task['activity'] else '')
            + (f' — originating chat {task["parent_chat_id"]}' if task['parent_chat_id'] else '')
            for task in other_running
        )
    lines.extend(
        [
            'Use this state to answer progress questions directly. Do not call terminal or Hydra merely to check task '
            'status, and do not start a new task for a status question. Explain what you are doing from the current '
            'state and recent progress above. A running task has the chat snapshot from when it started; do not imply '
            'that it has seen later chat messages. When it finishes, its verified context and result are merged into '
            'this originating chat so follow-up work can continue without rediscovery. Never say a task is pending '
            'when it is completed, failed, cancelled, or interrupted.',
        ]
    )
    return '\n'.join(lines)


def _message_text(message: dict | None) -> str:
    if not message:
        return ''
    output_text = ''.join(
        str(part.get('text') or '')
        for item in message.get('output') or []
        if isinstance(item, dict) and item.get('type') == 'message'
        for part in item.get('content') or []
        if isinstance(part, dict) and part.get('type') == 'output_text'
    ).strip()
    if output_text:
        return output_text
    content = message.get('content')
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return ''.join(
            str(item.get('text') or '')
            for item in content
            if isinstance(item, dict) and item.get('type') in {'text', 'output_text'}
        ).strip()
    return ''


async def _post_parent_result(
    *,
    user: UserModel,
    parent_chat_id: str,
    parent_message_id: str | None,
    task_chat_id: str,
    title: str,
    status: str,
    summary: str,
    error: str,
    model_id: str,
) -> None:
    task_chat = await Chats.get_chat_by_id(task_chat_id)
    task_context = ((task_chat.chat or {}).get('taterAgentContext') if task_chat else None) or {}
    outcome = (summary or error or 'The task finished without a result.').strip()
    handoff_context = normalize_agent_context(task_context)
    handoff_context['execution_summary'] = outcome[:TATER_TASK_RESULT_SUMMARY_MAX_CHARS]
    completion_note = _clean_live_event_message(
        f'Background task "{title}" ({task_chat_id}) finished with status {status}: {outcome}'
    )
    if status == 'completed':
        handoff_context['completed'] = [
            *(handoff_context.get('completed') or []),
            completion_note,
        ][-TATER_AGENT_CONTEXT_LIST_MAX_ITEMS:]
    else:
        handoff_context['blockers'] = [
            *(handoff_context.get('blockers') or []),
            completion_note,
        ][-TATER_AGENT_CONTEXT_LIST_MAX_ITEMS:]
    lines = [
        f'[BACKGROUND TASK FINISHED - {task_chat_id}]',
        f'Task: {title}',
        f'Status: {status}',
        f'Task view: /tasks/{task_chat_id}',
        '--- RESULT ---',
    ]
    if summary:
        lines.append(summary[:TATER_TASK_RESULT_MAX_CHARS])
    elif error:
        lines.append(error[:4000])
    else:
        lines.append('The task finished without a result.')
    if task_context:
        lines.extend(['', '--- FINAL WORKING CONTEXT ---', str(task_context)[:12_000]])

    result_message_id = str(uuid5(NAMESPACE_URL, f'tater-task-result:{task_chat_id}'))
    result_envelope = '\n'.join(lines)
    internal_message = {
        'id': result_message_id,
        'parentId': None,
        'childrenIds': [],
        'role': 'user',
        'content': result_envelope,
        'model': model_id,
        'meta': {
            'internal': True,
            'type': TATER_TASK_TYPE,
            'task_id': task_chat_id,
            'task_chat_id': task_chat_id,
        },
        'timestamp': int(time.time()),
    }
    assistant_message_id = str(uuid5(NAMESPACE_URL, f'tater-task-answer:{task_chat_id}'))
    assistant_message = {
        'id': assistant_message_id,
        'parentId': result_message_id,
        'childrenIds': [],
        'role': 'assistant',
        'content': background_task_result_answer(result_envelope),
        'done': True,
        'model': model_id,
        'timestamp': int(time.time()),
    }

    parent_folder_id = None
    async with get_async_db_context() as db:
        statement = select(Chat).where(Chat.id == parent_chat_id, Chat.user_id == user.id)
        if db.bind.dialect.name == 'postgresql':
            statement = statement.with_for_update()
        result = await db.execute(statement)
        parent = result.scalar_one_or_none()
        if not parent:
            raise RuntimeError('The originating chat no longer exists.')
        parent_folder_id = parent.folder_id

        parent_data = copy.deepcopy(parent.chat or {})
        parent_data['taterAgentContext'] = merge_task_context(
            parent_data.get('taterAgentContext'),
            handoff_context,
        )
        history = parent_data.setdefault('history', {})
        messages = history.setdefault('messages', {})
        existing_result = messages.get(result_message_id)
        if existing_result:
            result_parent_id = existing_result.get('parentId')
        else:
            current_id = history.get('currentId')
            current_message = messages.get(current_id) if current_id else None
            if current_message and current_message.get('role') == 'assistant':
                result_parent_id = current_id
            else:
                assistants = [message for message in messages.values() if message.get('role') == 'assistant']
                result_parent_id = (
                    max(assistants, key=lambda message: message.get('timestamp', 0)).get('id')
                    if assistants
                    else parent_message_id
                )
        internal_message['parentId'] = result_parent_id
        internal_message['childrenIds'] = [assistant_message_id]
        messages[result_message_id] = internal_message
        messages[assistant_message_id] = assistant_message
        if result_parent_id and result_parent_id in messages:
            children = messages[result_parent_id].setdefault('childrenIds', [])
            if result_message_id not in children:
                children.append(result_message_id)
        history['messages'] = messages
        history['currentId'] = assistant_message_id
        parent.chat = {**parent_data, 'history': history}
        parent.current_message_id = assistant_message_id
        parent.updated_at = int(time.time())
        flag_modified(parent, 'chat')
        await db.commit()

    await ChatMessages.upsert_message(result_message_id, parent_chat_id, user.id, internal_message)
    await ChatMessages.upsert_message(assistant_message_id, parent_chat_id, user.id, assistant_message)

    from open_webui.socket.main import sio

    await sio.emit(
        'events',
        {
            'chat_id': parent_chat_id,
            'message_id': assistant_message_id,
            'data': {'type': 'chat:reload'},
        },
        room=f'user:{user.id}',
    )
    await sio.emit(
        'events',
        {
            'chat_id': parent_chat_id,
            'message_id': assistant_message_id,
            'data': {'type': 'chat:list', 'data': {'folder_id': parent_folder_id}},
        },
        room=f'user:{user.id}',
    )


async def start_tater_task(
    request: Request,
    *,
    body: dict[str, Any],
    metadata: dict[str, Any],
    user: UserModel,
    task_prompt: str,
    initial_plan: dict[str, Any],
    capacity_reserved: bool = False,
) -> dict[str, Any]:
    parent_chat_id = metadata.get('chat_id')
    if not parent_chat_id:
        raise RuntimeError('A saved chat is required to start a background task.')
    parent_chat = await Chats.get_chat_by_id_and_user_id(parent_chat_id, user.id)
    if not parent_chat:
        raise RuntimeError('The originating chat could not be found.')

    if not capacity_reserved:
        existing = await reconcile_user_tater_tasks(request.app, user.id)
        active = [chat for chat in existing if (chat.meta or {}).get('status') in TATER_TASK_ACTIVE_STATUSES]
        if len(active) >= TATER_TASK_MAX_CONCURRENT_PER_USER:
            raise RuntimeError(
                f'At most {TATER_TASK_MAX_CONCURRENT_PER_USER} background tasks can run at once. '
                'Wait for one to finish or cancel one beneath its originating chat.'
            )

    task_id = str(uuid4())
    user_message_id = str(uuid4())
    assistant_message_id = str(uuid4())
    prompt = task_prompt.strip() or get_last_user_message(body.get('messages', [])) or 'Background task'
    title = normalize_task_title(initial_plan.get('task_title'), prompt)

    def ledger_event(event: str, **data: Any) -> None:
        record_tater_run_event(
            event,
            run_id=task_id,
            task_id=task_id,
            chat_id=str(parent_chat_id),
            user_id=str(user.id),
            data=data,
        )

    initial_tool_calls = initial_plan.get('tool_calls') or []
    capabilities = sorted(
        {
            'hydra' if call.get('name') == 'tater_hydra' else 'terminal'
            for call in initial_tool_calls
            if call.get('name') in {'terminal', 'tater_hydra'}
        }
    )
    now = int(time.time())
    user_message = {
        'id': user_message_id,
        'parentId': None,
        'childrenIds': [assistant_message_id],
        'role': 'user',
        'content': prompt,
        'timestamp': now,
        'models': [body['model']],
    }
    assistant_message = {
        'id': assistant_message_id,
        'parentId': user_message_id,
        'childrenIds': [],
        'role': 'assistant',
        'content': '',
        'done': False,
        'model': body['model'],
        'timestamp': now,
    }
    child_context = normalize_agent_context(
        {'objective': prompt},
        copy.deepcopy((parent_chat.chat or {}).get('taterAgentContext') or {}),
    )
    chat_data = {
        'id': task_id,
        'title': title,
        'models': [body['model']],
        'history': {
            'currentId': assistant_message_id,
            'messages': {user_message_id: user_message, assistant_message_id: assistant_message},
        },
        'messages': [{'role': 'user', 'content': prompt}],
        'taterAgentContext': child_context,
    }
    chat = await Chats.insert_new_chat(
        task_id,
        user.id,
        ChatForm(chat=chat_data, folder_id=parent_chat.folder_id),
        internal_meta={
            'internal': True,
            'type': TATER_TASK_TYPE,
            'status': 'running',
            'activity': 'Starting task',
            'progress_events': [{'at': now, 'kind': 'state', 'message': 'Starting task'}],
            'capabilities': capabilities,
            'parent_chat_id': parent_chat_id,
            'parent_message_id': metadata.get('assistant_message_id') or metadata.get('user_message_id'),
            'started_at': now,
        },
    )
    if not chat:
        raise RuntimeError('The background task record could not be created.')

    ledger_event(
        'task_created',
        title=title,
        prompt=prompt,
        model=body.get('model'),
        parent_chat_id=parent_chat_id,
        parent_message_id=metadata.get('assistant_message_id') or metadata.get('user_message_id'),
        capabilities=capabilities,
        initial_plan=initial_plan,
    )

    run = {
        'model_id': body['model'],
        'session_id': f'tater-task:{task_id}',
        'system_prompt': metadata.get('system_prompt'),
        'terminal_id': metadata.get('terminal_id'),
        'features': copy.deepcopy(metadata.get('features') or {}),
        'files': copy.deepcopy(metadata.get('files') or []),
        'variables': copy.deepcopy(metadata.get('variables') or {}),
    }

    async def run_background() -> dict[str, Any]:
        status = 'failed'
        summary = ''
        error = ''
        cancelled = False
        task_started_at = time.monotonic()
        ledger_event('task_execution_started', session_id=run['session_id'])
        try:
            child_request = _build_internal_request(
                request,
                user.id,
                task_id,
                parent_chat_id,
                initial_plan,
            )
            child_messages = copy.deepcopy(body.get('messages') or [])
            if child_messages and child_messages[-1].get('role') == 'user':
                child_messages[-1] = {
                    **child_messages[-1],
                    'content': f'Perform this confirmed background task now:\n\n{prompt}',
                }
            else:
                child_messages.append({'role': 'user', 'content': prompt})
            form_data = {
                'model': body['model'],
                'messages': child_messages,
                'stream': True,
                'chat_id': task_id,
                'id': assistant_message_id,
                'parent_id': None,
                'user_message': user_message,
                'session_id': run['session_id'],
                'background_tasks': {},
                'features': run['features'],
                'files': run['files'],
                'variables': run['variables'],
            }
            if run.get('terminal_id'):
                form_data['terminal_id'] = run['terminal_id']

            await request.app.state.CHAT_COMPLETION_HANDLER(child_request, form_data, user=user)
            ledger_event('task_completion_handler_finished')
            message = await Chats.get_message_by_id_and_message_id(task_id, assistant_message_id)
            completed_task_chat = await Chats.get_chat_by_id(task_id)
            completed_context = (
                ((completed_task_chat.chat or {}).get('taterAgentContext') if completed_task_chat else None) or {}
            )
            summary = str(completed_context.get('execution_summary') or '').strip() or _message_text(message)
            message_error = (message or {}).get('error')
            agent_stop_reason = str(getattr(child_request.state, 'tater_agent_stop_reason', '') or '').strip()
            if agent_stop_reason:
                error = agent_stop_reason
                status = 'failed'
            elif message_error:
                error = (
                    message_error.get('content', str(message_error))
                    if isinstance(message_error, dict)
                    else str(message_error)
                )
                status = 'failed'
            else:
                status = 'completed'
                if not summary:
                    summary = 'The task completed without a written summary.'
        except asyncio.CancelledError:
            cancelled = True
            status = 'cancelled'
            error = 'The task was cancelled.'
            ledger_event('task_cancelled', error=error)
            await asyncio.shield(
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    task_id,
                    assistant_message_id,
                    {'done': True, 'error': {'content': error}},
                    touch=False,
                )
            )
        except Exception as exc:
            error = str(exc)
            log.exception('Background task %s failed', task_id)
            ledger_event(
                'task_execution_failed',
                error=repr(exc),
                stacktrace=traceback.format_exc(),
            )
            await Chats.upsert_message_to_chat_by_id_and_message_id(
                task_id,
                assistant_message_id,
                {'done': True, 'error': {'content': error}},
                touch=False,
            )

        async def finalize() -> None:
            final_status = status
            final_error = error
            await record_tater_task_progress(
                task_id,
                'Posting the result to the originating chat',
                kind='state',
                user_id=user.id,
            )

            delivery_error = None
            for attempt in range(3):
                delivery_started_at = time.monotonic()
                ledger_event('parent_delivery_started', attempt=attempt + 1, status=status)
                try:
                    await _post_parent_result(
                        user=user,
                        parent_chat_id=parent_chat_id,
                        parent_message_id=metadata.get('assistant_message_id') or metadata.get('user_message_id'),
                        task_chat_id=task_id,
                        title=title,
                        status=status,
                        summary=summary,
                        error=error,
                        model_id=run['model_id'],
                    )
                    delivery_error = None
                    ledger_event(
                        'parent_delivery_finished',
                        attempt=attempt + 1,
                        status='completed',
                        duration_ms=round((time.monotonic() - delivery_started_at) * 1000, 2),
                    )
                    break
                except Exception as exc:
                    delivery_error = exc
                    ledger_event(
                        'parent_delivery_finished',
                        attempt=attempt + 1,
                        status='failed',
                        duration_ms=round((time.monotonic() - delivery_started_at) * 1000, 2),
                        error=repr(exc),
                    )
                    log.exception(
                        'Could not post result for background task %s (attempt %s/3)',
                        task_id,
                        attempt + 1,
                    )
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))

            if delivery_error is not None:
                final_status = 'failed'
                final_error = f'The work finished, but its result could not be posted: {delivery_error}'

            final_result = summary if final_status == 'completed' else final_error
            await record_tater_task_progress(
                task_id,
                f'Task {final_status}: {final_result or "No result was returned."}',
                kind='result',
                user_id=user.id,
            )
            await update_tater_task(
                task_id,
                {
                    'status': final_status,
                    'activity': final_result[:240],
                    'result_summary': final_result[:TATER_TASK_RESULT_SUMMARY_MAX_CHARS],
                    'finished_at': int(time.time()),
                },
                user_id=user.id,
            )
            await emit_tater_task_event(user.id, task_id, final_status)
            ledger_event(
                'task_finished',
                status=final_status,
                duration_ms=round((time.monotonic() - task_started_at) * 1000, 2),
                summary=summary,
                error=final_error,
            )

        await asyncio.shield(finalize())
        if cancelled:
            raise asyncio.CancelledError
        return {'status': status, 'summary': summary, 'error': error}

    try:
        await create_task(request.app.state.redis, run_background(), id=task_id, task_id=task_id)
    except Exception as exc:
        ledger_event(
            'task_scheduling_failed',
            error=repr(exc),
            stacktrace=traceback.format_exc(),
        )
        await update_tater_task(
            task_id,
            {
                'status': 'failed',
                'activity': 'The task could not be scheduled.',
                'result_summary': 'The task could not be scheduled.',
                'finished_at': int(time.time()),
            },
            user_id=user.id,
        )
        raise

    await emit_tater_task_event(user.id, task_id, 'running')
    ledger_event('task_scheduled')
    return tater_task_summary(chat)


async def start_parallel_tater_tasks(
    request: Request,
    *,
    body: dict[str, Any],
    metadata: dict[str, Any],
    user: UserModel,
    task_plans: list[dict[str, Any]],
) -> dict[str, Any]:
    """Start an independently scoped task batch after one shared capacity check."""

    if not task_plans:
        raise RuntimeError('No parallel tasks were provided.')
    if len(task_plans) > TATER_TASK_MAX_CONCURRENT_PER_USER:
        raise RuntimeError(
            f'At most {TATER_TASK_MAX_CONCURRENT_PER_USER} independent tasks can be started together.'
        )

    existing = await reconcile_user_tater_tasks(request.app, user.id)
    active = [chat for chat in existing if (chat.meta or {}).get('status') in TATER_TASK_ACTIVE_STATUSES]
    available = TATER_TASK_MAX_CONCURRENT_PER_USER - len(active)
    if len(task_plans) > available:
        raise RuntimeError(
            f'This request needs {len(task_plans)} task slots, but only {max(0, available)} are available. '
            'Wait for a running task to finish or cancel one beneath its originating chat.'
        )

    tasks = []
    errors = []
    for task_plan in task_plans:
        prompt = str(task_plan.get('task_prompt') or '').strip()
        initial_plan = {
            'task_title': task_plan.get('task_title') or '',
            'progress': task_plan.get('progress') or '',
            'tool_calls': copy.deepcopy(task_plan.get('tool_calls') or []),
            'parallel_tasks': [],
            'final_answer': '',
            'context': copy.deepcopy(task_plan.get('context') or {}),
        }
        try:
            tasks.append(
                await start_tater_task(
                    request,
                    body=body,
                    metadata=metadata,
                    user=user,
                    task_prompt=prompt,
                    initial_plan=initial_plan,
                    capacity_reserved=True,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    'title': normalize_task_title(task_plan.get('task_title'), prompt),
                    'error': str(exc),
                }
            )

    return {'tasks': tasks, 'errors': errors}
