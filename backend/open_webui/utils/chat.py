import logging
import sys
from typing import Any

from fastapi import Request

from open_webui.env import BYPASS_MODEL_ACCESS_CONTROL, GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel
from open_webui.routers.openai import generate_chat_completion as generate_openai_chat_completion
from open_webui.socket.main import get_event_call, get_event_emitter
from open_webui.utils.filter import get_filter_functions, process_filter_functions
from open_webui.utils.models import check_model_access, get_all_models

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


async def generate_chat_completion(
    request: Request,
    form_data: dict,
    user: Any,
    bypass_filter: bool = False,
    bypass_system_prompt: bool = False,
):
    log.debug('generate_chat_completion: %s', form_data)
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True

    request.state.bypass_filter = bypass_filter
    request.state.bypass_system_prompt = bypass_system_prompt

    if hasattr(request.state, 'metadata'):
        if 'metadata' not in form_data:
            form_data['metadata'] = request.state.metadata
        else:
            form_data['metadata'] = {
                **form_data['metadata'],
                **request.state.metadata,
            }

    model = request.app.state.MODELS.get(form_data['model'])
    if model is None:
        raise Exception('Model not found')

    if not bypass_filter and user.role == 'user':
        await check_model_access(user, model)

    return await generate_openai_chat_completion(
        request=request,
        form_data=form_data,
        user=user,
    )


chat_completion = generate_chat_completion


async def chat_completed(request: Request, form_data: dict, user: Any):
    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    data = form_data
    if not data.get('id'):
        raise Exception('Missing message id')

    model = request.app.state.MODELS.get(data['model'])
    if model is None:
        raise Exception('Model not found')

    metadata = {
        'chat_id': data['chat_id'],
        'message_id': data['id'],
        'filter_ids': data.get('filter_ids', []),
        'session_id': data['session_id'],
        'user_id': user.id,
    }

    extra_params = {
        '__event_emitter__': await get_event_emitter(metadata),
        '__event_call__': await get_event_call(metadata),
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__request__': request,
        '__model__': model,
    }

    try:
        filter_functions = await get_filter_functions(request, model, metadata.get('filter_ids', []))
        result, _ = await process_filter_functions(
            request=request,
            filter_context=None,
            filter_functions=filter_functions,
            filter_type='outlet',
            form_data=data,
            extra_params=extra_params,
        )
        return result
    except Exception as e:
        raise Exception(f'Error: {e}')
