"""UI-native tools retained by the Tater WebUI agent loop."""

import logging
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field

from open_webui.models.chats import Chats
from open_webui.utils.chat_id import is_saved_chat_id
from open_webui.utils.json_codec import JSONCodec

log = logging.getLogger(__name__)


async def ask_user(  # noqa: C901 - validation is intentionally kept in one UI boundary
    questions: list[dict],
    allow_other: bool = True,
    timeout_ms: int = 120_000,
    __event_call__: callable = None,
) -> str:
    """
    Ask the user clarifying questions before continuing.
    Use this when the next step depends on user intent, preference, or a tradeoff that cannot be inferred safely.

    :param questions: 1-3 question objects, each with id, header, question,
        and 2-3 options. Each option needs label and description.
        List the option you recommend first; the UI labels the first option Recommended.
    :param allow_other: Whether users may enter a free-form answer instead of choosing one of the options
    :param timeout_ms: How long the browser should keep the prompt open before cancelling it
    :return: JSON with status and answers keyed by question id
    """
    try:
        if not isinstance(questions, list) or not 1 <= len(questions) <= 3:
            raise ValueError('ask_user requires 1-3 questions.')

        normalized_questions = []
        seen_ids = set()
        for index, question in enumerate(questions):
            if not isinstance(question, dict):
                raise ValueError('Each question must be an object.')

            question_id = str(question.get('id') or '').strip()[:64]
            if not question_id:
                raise ValueError('Each question requires a non-empty id.')
            if question_id in seen_ids:
                raise ValueError(f'Duplicate question id: {question_id}')
            seen_ids.add(question_id)

            options = question.get('options')
            if not isinstance(options, list) or not 2 <= len(options) <= 3:
                raise ValueError('Each question requires 2-3 options.')

            normalized_options = []
            for option in options:
                if not isinstance(option, dict):
                    raise ValueError('Each option must be an object.')

                label = str(option.get('label') or '').strip()[:80]
                description = str(option.get('description') or '').strip()[:240]
                if not label or not description:
                    raise ValueError('Each option requires a label and description.')

                normalized_options.append(
                    {
                        'label': label,
                        'description': description,
                    }
                )

            question_text = str(question.get('question') or '').strip()[:500]
            if not question_text:
                raise ValueError('Each question requires question text.')

            normalized_questions.append(
                {
                    'id': question_id,
                    'header': str(question.get('header') or '').strip()[:48] or f'Question {index + 1}',
                    'question': question_text,
                    'options': normalized_options,
                    'allow_other': bool(question.get('allow_other', allow_other)),
                }
            )

        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 60_000 <= timeout_ms <= 240_000:
            timeout_ms = 120_000

        if __event_call__ is None:
            return JSONCodec.dumps(
                {
                    'status': 'error',
                    'error': 'User input requires an active browser session with WebSocket connection.',
                },
                ensure_ascii=False,
            )

        output = await __event_call__(
            {
                'type': 'request:user_input',
                'data': {
                    'questions': normalized_questions,
                    'allow_other': allow_other,
                    'timeout_ms': timeout_ms,
                },
            }
        )

        if not isinstance(output, dict):
            return JSONCodec.dumps({'status': 'error', 'error': 'Invalid user input response.'}, ensure_ascii=False)
        if output.get('error'):
            return JSONCodec.dumps({'status': 'error', 'error': output.get('error')}, ensure_ascii=False)
        if output.get('status') == 'cancelled':
            return JSONCodec.dumps({'status': 'cancelled', 'answers': {}}, ensure_ascii=False)

        return JSONCodec.dumps(
            {
                'status': 'answered',
                'answers': output.get('answers', {}),
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        log.exception('ask_user error: %s', exc)
        return JSONCodec.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False)


VALID_TASK_STATUSES = {'pending', 'in_progress', 'completed', 'cancelled'}


class TaskItem(BaseModel):
    id: str | None = Field(None, description='Unique identifier for the task. Auto-generated if omitted.')
    content: str = Field(..., description='Task description.')
    status: Literal['pending', 'in_progress', 'completed', 'cancelled'] = Field('pending', description='Task status.')


def _task_summary(all_tasks: list[dict]) -> dict:
    """Build summary counts for a task list."""
    return {
        'total': len(all_tasks),
        'pending': sum(1 for task in all_tasks if task['status'] == 'pending'),
        'in_progress': sum(1 for task in all_tasks if task['status'] == 'in_progress'),
        'completed': sum(1 for task in all_tasks if task['status'] == 'completed'),
        'cancelled': sum(1 for task in all_tasks if task['status'] == 'cancelled'),
    }


async def _emit_tasks(event_emitter, all_tasks: list[dict]):
    """Persist task state to the UI."""
    if event_emitter:
        await event_emitter(
            {
                'type': 'chat:message:tasks',
                'data': {'tasks': all_tasks},
            }
        )


async def create_tasks(
    tasks: list[TaskItem],
    __chat_id__: str = None,
    __message_id__: str = None,
    __event_emitter__: callable = None,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Create a visible task checklist for multi-step work so progress can be shown in chat.

    :param tasks: List of task items. Each item has content (required), status
        (pending|in_progress|completed|cancelled), and an optional ID.
    :return: JSON with the full task list and summary counts
    """
    if not is_saved_chat_id(__chat_id__):
        return JSONCodec.dumps({'error': 'Saved chat context not available'})

    try:
        all_tasks = []
        for index, task in enumerate(tasks):
            if hasattr(task, 'model_dump'):
                item = task.model_dump(exclude_none=True)
            elif isinstance(task, dict):
                item = task
            else:
                item = dict(task)

            content = str(item.get('content', '')).strip()
            if not content:
                continue

            item_id = str(item.get('id', '') or '').strip() or str(index + 1)
            status = str(item.get('status', 'pending')).strip().lower()
            if status not in VALID_TASK_STATUSES:
                status = 'pending'

            all_tasks.append({'id': item_id, 'content': content, 'status': status})

        await Chats.update_chat_tasks_by_id(__chat_id__, all_tasks)
        await _emit_tasks(__event_emitter__, all_tasks)

        return JSONCodec.dumps(
            {'tasks': all_tasks, 'summary': _task_summary(all_tasks)},
            ensure_ascii=False,
        )
    except Exception as exc:
        log.exception('tasks error: %s', exc)
        return JSONCodec.dumps({'error': str(exc)})


async def update_task(
    id: str,
    status: str = 'completed',
    __chat_id__: str = None,
    __message_id__: str = None,
    __event_emitter__: callable = None,
    __request__: Request = None,
    __user__: dict = None,
) -> str:
    """
    Mark a single visible task item as completed, in_progress, pending, or cancelled.

    :param id: The task ID to update
    :param status: New status: completed, in_progress, pending, or cancelled (default: completed)
    :return: JSON with the updated task list and summary counts
    """
    if not is_saved_chat_id(__chat_id__):
        return JSONCodec.dumps({'error': 'Saved chat context not available'})

    try:
        status = status.strip().lower()
        if status not in VALID_TASK_STATUSES:
            return JSONCodec.dumps(
                {'error': f'Invalid status: {status}. Must be one of: {", ".join(sorted(VALID_TASK_STATUSES))}'}
            )

        all_tasks = await Chats.get_chat_tasks_by_id(__chat_id__)
        for task in all_tasks:
            if task['id'] == id:
                task['status'] = status
                break
        else:
            return JSONCodec.dumps({'error': f'Task with id "{id}" not found'})

        await Chats.update_chat_tasks_by_id(__chat_id__, all_tasks)
        await _emit_tasks(__event_emitter__, all_tasks)

        return JSONCodec.dumps(
            {'tasks': all_tasks, 'summary': _task_summary(all_tasks)},
            ensure_ascii=False,
        )
    except Exception as exc:
        log.exception('update_task error: %s', exc)
        return JSONCodec.dumps({'error': str(exc)})
