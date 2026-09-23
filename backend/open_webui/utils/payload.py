import logging
from typing import Callable, Optional

from open_webui.utils.chat_variables import render_chat_variables, render_user_variables
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.misc import (
    add_or_update_system_message,
    convert_logit_bias_input_to_json,
    deep_update,
    replace_system_message_content,
)
from open_webui.utils.task import prompt_template, prompt_variables_template

log = logging.getLogger(__name__)


async def resolve_system_prompt(
    system: Optional[str],
    metadata: Optional[dict] = None,
    user=None,
) -> str:
    if not system:
        return ''

    if metadata:
        system = render_chat_variables(
            system,
            metadata.get('chat_variables', {}),
            required=False,
        )

    system = render_user_variables(system, getattr(user, 'variables', {}) if user else {})

    # Metadata (WebUI Usage)
    if metadata:
        variables = metadata.get('variables', {})
        if variables:
            system = prompt_variables_template(system, variables)

    # Legacy (API Usage)
    system = await prompt_template(system, user)

    return system


# What goes out cannot be taken back. Let it be shaped
# well before it leaves this place.
# inplace function: form_data is modified
async def apply_system_prompt_to_body(
    system: Optional[str],
    form_data: dict,
    metadata: Optional[dict] = None,
    user=None,
    replace: bool = False,
) -> dict:
    system = await resolve_system_prompt(system, metadata, user)
    if not system:
        return form_data

    if replace:
        form_data['messages'] = replace_system_message_content(system, form_data.get('messages', []))
    else:
        form_data['messages'] = add_or_update_system_message(system, form_data.get('messages', []))

    return form_data


# inplace function: form_data is modified
def apply_model_params_to_body(params: dict, form_data: dict, mappings: dict[str, Callable]) -> dict:
    if not params:
        return form_data

    for key, value in params.items():
        if value is not None and key not in form_data:
            if key in mappings:
                cast_func = mappings[key]
                if isinstance(cast_func, Callable):
                    form_data[key] = cast_func(value)
            else:
                form_data[key] = value

    return form_data


def apply_params_to_form_data(form_data: dict, model: dict, params: dict | None = None) -> dict:
    payload_params = form_data.pop('params', {}) or {}
    params = payload_params if params is None else dict(params)
    custom_params = params.pop('custom_params', {})

    open_webui_params = {
        'stream_response': bool,
        'stream_delta_chunk_size': int,
        'function_calling': str,
        'reasoning_tags': list,
        'compact_token_threshold': int,
        'system': str,
        'note_id': str,
        'tool_approval_mode': str,
    }

    for key in list(params.keys()):
        if key in open_webui_params:
            del params[key]

    if custom_params:
        for key, value in custom_params.items():
            if isinstance(value, str):
                try:
                    custom_params[key] = JSONCodec.loads(value)
                except JSONCodec.JSONDecodeError:
                    pass

        params = deep_update(params, custom_params)

    if isinstance(params, dict):
        for key, value in params.items():
            if value is not None and key not in form_data:
                form_data[key] = value

    if 'logit_bias' in params and params['logit_bias'] is not None and 'logit_bias' not in form_data:
        try:
            logit_bias = convert_logit_bias_input_to_json(params['logit_bias'])

            if logit_bias:
                form_data['logit_bias'] = JSONCodec.loads(logit_bias)
        except Exception as e:
            log.exception(f'Error parsing logit_bias: {e}')

    return form_data


def remove_open_webui_params(params: dict) -> dict:
    """
    Removes OpenWebUI specific parameters from the provided dictionary.

    Args:
        params (dict): The dictionary containing parameters.

    Returns:
        dict: The modified dictionary with OpenWebUI parameters removed.
    """
    open_webui_params = {
        'stream_response': bool,
        'stream_delta_chunk_size': int,
        'function_calling': str,
        'reasoning_tags': list,
        'compact_token_threshold': int,
        'system': str,
        'note_id': str,
        'tool_approval_mode': str,
    }

    for key in list(params.keys()):
        if key in open_webui_params:
            del params[key]

    return params


# inplace function: form_data is modified
def apply_model_params_to_body_openai(params: dict, form_data: dict) -> dict:
    params = remove_open_webui_params(params)

    custom_params = params.pop('custom_params', {})
    if custom_params:
        # Attempt to parse custom_params if they are strings
        for key, value in custom_params.items():
            if isinstance(value, str):
                try:
                    # Attempt to parse the string as JSON
                    custom_params[key] = JSONCodec.loads(value)
                except JSONCodec.JSONDecodeError:
                    # If it fails, keep the original string
                    pass

        # If there are custom parameters, we need to apply them first
        params = deep_update(params, custom_params)

    mappings = {
        'temperature': float,
        'top_p': float,
        'min_p': float,
        'max_tokens': int,
        'frequency_penalty': float,
        'presence_penalty': float,
        'reasoning_effort': str,
        'seed': lambda x: x,
        'stop': lambda x: [bytes(s, 'utf-8').decode('unicode_escape') for s in x],
        'logit_bias': lambda x: x,
        'response_format': dict,
    }
    return apply_model_params_to_body(params, form_data, mappings)
