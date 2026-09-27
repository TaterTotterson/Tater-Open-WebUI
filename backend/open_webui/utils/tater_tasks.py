from __future__ import annotations

import asyncio
import copy
import time
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from starlette.datastructures import Headers

from open_webui.internal.db import get_async_db_context
from open_webui.models.chat_messages import ChatMessages
from open_webui.models.chats import Chat, ChatForm, ChatModel, Chats
from open_webui.models.users import UserModel
from open_webui.tasks import create_task, has_active_tasks, list_tasks
from open_webui.utils.auth import create_token
from open_webui.utils.misc import get_last_user_message
from open_webui.utils.tater_agent import merge_task_context

TATER_TASK_TYPE = 'tater_task'
TATER_TASK_ACTIVE_STATUSES = {'queued', 'running', 'cancelling'}
TATER_TASK_MAX_CONCURRENT_PER_USER = 2
TATER_TASK_RESULT_MAX_CHARS = 40_000


def _build_internal_request(source: Request, user_id: str, task_id: str) -> Request:
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
        'capabilities': list(meta.get('capabilities') or []),
        'parent_chat_id': meta.get('parent_chat_id'),
        'created_at': chat.created_at,
        'updated_at': chat.updated_at,
        'started_at': meta.get('started_at'),
        'finished_at': meta.get('finished_at'),
    }


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
                    'finished_at': int(time.time()),
                },
                user_id=user_id,
            )
            if updated:
                chat = updated
    return await get_user_tater_task_chats(user_id)


async def tater_task_awareness(app, user_id: str, *, exclude_task_id: str | None = None) -> str:
    chats = await reconcile_user_tater_tasks(app, user_id)
    running = [
        tater_task_summary(chat)
        for chat in chats
        if chat.id != exclude_task_id and (chat.meta or {}).get('status') in TATER_TASK_ACTIVE_STATUSES
    ]
    if not running:
        return ''

    lines = [
        'Authoritative background task state:',
        *[
            f'- {task["id"]}: {task["title"]} — {task["status"]}'
            + (f' — {task["activity"]}' if task['activity'] else '')
            for task in running
        ],
        'Use this state when the user asks about running work. Do not start another terminal or Hydra task merely to '
        'check a listed task. Explain that the task will report its result into this chat when it finishes.',
    ]
    return '\n'.join(lines)


def _message_text(message: dict | None) -> str:
    if not message:
        return ''
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


async def _queue_parent_result(
    source_request: Request,
    *,
    user: UserModel,
    parent_chat_id: str,
    parent_message_id: str | None,
    task_chat_id: str,
    title: str,
    status: str,
    summary: str,
    error: str,
    run: dict[str, Any],
) -> None:
    task_chat = await Chats.get_chat_by_id(task_chat_id)
    task_context = ((task_chat.chat or {}).get('taterAgentContext') if task_chat else None) or {}
    lines = [
        f'[BACKGROUND TASK FINISHED - {task_chat_id}]',
        'A background task started from this chat has finished. Report the outcome clearly to the user.',
        '',
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

    pending_message_id = str(uuid4())
    pending_message = {
        'id': pending_message_id,
        'parentId': None,
        'childrenIds': [],
        'role': 'user',
        'content': '\n'.join(lines),
        'model': run['model_id'],
        'meta': {
            'internal': True,
            'type': TATER_TASK_TYPE,
            'task_id': task_chat_id,
            'task_chat_id': task_chat_id,
        },
        'timestamp': int(time.time()),
    }

    async with get_async_db_context() as db:
        statement = select(Chat).where(Chat.id == parent_chat_id, Chat.user_id == user.id)
        if db.bind.dialect.name == 'postgresql':
            statement = statement.with_for_update()
        result = await db.execute(statement)
        parent = result.scalar_one_or_none()
        if not parent:
            return

        parent_data = copy.deepcopy(parent.chat or {})
        if task_context:
            parent_data['taterAgentContext'] = merge_task_context(
                parent_data.get('taterAgentContext'),
                task_context,
            )
        history = parent_data.setdefault('history', {})
        messages = history.setdefault('messages', {})
        done_assistants = [
            message
            for message in messages.values()
            if message.get('role') == 'assistant' and message.get('done') is not False
        ]
        result_parent_id = (
            max(done_assistants, key=lambda message: message.get('timestamp', 0)).get('id')
            if done_assistants
            else parent_message_id
        )
        pending_message['parentId'] = result_parent_id
        if await has_active_tasks(source_request.app.state.redis, parent_chat_id):
            pending_message['meta']['status'] = 'pending'
        messages[pending_message_id] = pending_message
        if result_parent_id and result_parent_id in messages:
            children = messages[result_parent_id].setdefault('childrenIds', [])
            if pending_message_id not in children:
                children.append(pending_message_id)
        history['messages'] = messages
        parent.chat = {**parent_data, 'history': history}
        parent.updated_at = int(time.time())
        flag_modified(parent, 'chat')
        await db.commit()

    await ChatMessages.upsert_message(pending_message_id, parent_chat_id, user.id, pending_message)

    if pending_message['meta'].get('status') == 'pending':
        from open_webui.socket.main import sio

        await sio.emit(
            'events',
            {
                'chat_id': parent_chat_id,
                'message_id': pending_message_id,
                'data': {'type': 'chat:reload'},
            },
            room=f'user:{user.id}',
        )
        return

    from open_webui.utils.subagents import process_pending_internal_messages

    await process_pending_internal_messages(source_request, parent_chat_id, user.id, run)


async def start_tater_task(
    request: Request,
    *,
    body: dict[str, Any],
    metadata: dict[str, Any],
    user: UserModel,
    initial_tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    parent_chat_id = metadata.get('chat_id')
    if not parent_chat_id:
        raise RuntimeError('A saved chat is required to start a background task.')
    parent_chat = await Chats.get_chat_by_id_and_user_id(parent_chat_id, user.id)
    if not parent_chat:
        raise RuntimeError('The originating chat could not be found.')

    existing = await reconcile_user_tater_tasks(request.app, user.id)
    active = [chat for chat in existing if (chat.meta or {}).get('status') in TATER_TASK_ACTIVE_STATUSES]
    if len(active) >= TATER_TASK_MAX_CONCURRENT_PER_USER:
        raise RuntimeError(
            f'At most {TATER_TASK_MAX_CONCURRENT_PER_USER} background tasks can run at once. '
            'Wait for one to finish or cancel one from the Tasks section.'
        )

    task_id = str(uuid4())
    user_message_id = str(uuid4())
    assistant_message_id = str(uuid4())
    prompt = get_last_user_message(body.get('messages', [])) or 'Background task'
    title = ' '.join(prompt.split())[:80] or 'Background task'
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
    child_context = copy.deepcopy((parent_chat.chat or {}).get('taterAgentContext') or {})
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
        ChatForm(chat=chat_data),
        internal_meta={
            'internal': True,
            'type': TATER_TASK_TYPE,
            'status': 'running',
            'activity': 'Starting task',
            'capabilities': capabilities,
            'parent_chat_id': parent_chat_id,
            'parent_message_id': metadata.get('assistant_message_id') or metadata.get('user_message_id'),
            'started_at': now,
        },
    )
    if not chat:
        raise RuntimeError('The background task record could not be created.')

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
        try:
            child_request = _build_internal_request(request, user.id, task_id)
            child_messages = copy.deepcopy(body.get('messages') or [])
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
            message = await Chats.get_message_by_id_and_message_id(task_id, assistant_message_id)
            summary = _message_text(message)
            message_error = (message or {}).get('error')
            if message_error:
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
            await Chats.upsert_message_to_chat_by_id_and_message_id(
                task_id,
                assistant_message_id,
                {'done': True, 'error': {'content': error}},
                touch=False,
            )

        async def finalize() -> None:
            await update_tater_task(
                task_id,
                {
                    'status': status,
                    'activity': summary[:240] if status == 'completed' else error[:240],
                    'finished_at': int(time.time()),
                },
                user_id=user.id,
            )
            await emit_tater_task_event(user.id, task_id, status)
            await _queue_parent_result(
                request,
                user=user,
                parent_chat_id=parent_chat_id,
                parent_message_id=metadata.get('assistant_message_id') or metadata.get('user_message_id'),
                task_chat_id=task_id,
                title=title,
                status=status,
                summary=summary,
                error=error,
                run=run,
            )

        await asyncio.shield(finalize())
        if cancelled:
            raise asyncio.CancelledError
        return {'status': status, 'summary': summary, 'error': error}

    try:
        await create_task(request.app.state.redis, run_background(), id=task_id, task_id=task_id)
    except Exception:
        await update_tater_task(
            task_id,
            {'status': 'failed', 'activity': 'The task could not be scheduled.', 'finished_at': int(time.time())},
            user_id=user.id,
        )
        raise

    await emit_tater_task_event(user.id, task_id, 'running')
    return tater_task_summary(chat)
