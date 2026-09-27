from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

DEFAULT_TATER_API_BASE_URL = 'http://localhost:8501/v1'
DEFAULT_TATER_BASE_MODEL = 'tater/base'
DEFAULT_TATER_HYDRA_MODEL = 'tater/hydra'
DEFAULT_TATER_CONTEXT_WINDOW = 32_768
MIN_TATER_CONTEXT_WINDOW = 4_096
MAX_TATER_CONTEXT_WINDOW = 2_000_000


def normalize_tater_api_base_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError('Tater API URL is required')

    if '://' not in value:
        value = f'http://{value}'

    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('Tater API URL must be an absolute HTTP or HTTPS URL')
    if parsed.username or parsed.password:
        raise ValueError('Tater API credentials must not be embedded in the URL')
    if parsed.query or parsed.fragment:
        raise ValueError('Tater API URL must not contain a query string or fragment')

    path = parsed.path.rstrip('/')
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def normalize_tater_model_id(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f'{label} is required')
    if any(character.isspace() for character in value):
        raise ValueError(f'{label} must not contain whitespace')
    return value


def normalize_tater_context_window(value: int | str) -> int:
    try:
        context_window = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Context window must be a whole number of tokens') from exc
    if not MIN_TATER_CONTEXT_WINDOW <= context_window <= MAX_TATER_CONTEXT_WINDOW:
        raise ValueError(
            f'Context window must be between {MIN_TATER_CONTEXT_WINDOW:,} and {MAX_TATER_CONTEXT_WINDOW:,} tokens'
        )
    return context_window


def context_compaction_threshold(context_window: int | str) -> int:
    context_window = normalize_tater_context_window(context_window)
    reserve = max(2_048, (context_window + 4) // 5)
    return context_window - reserve


def build_tater_profile_updates(
    *,
    api_base_url: str,
    api_key: str,
    base_model: str,
    hydra_model: str,
    context_window: int | str = DEFAULT_TATER_CONTEXT_WINDOW,
) -> dict:
    api_base_url = normalize_tater_api_base_url(api_base_url)
    base_model = normalize_tater_model_id(base_model, 'Base model')
    hydra_model = normalize_tater_model_id(hydra_model, 'Hydra model')
    context_window = normalize_tater_context_window(context_window)
    compact_token_threshold = context_compaction_threshold(context_window)

    if base_model == hydra_model:
        raise ValueError('Base and Hydra models must be different')

    return {
        'openai.enable': True,
        'openai.api_base_urls': [api_base_url],
        'openai.api_keys': [api_key.strip()],
        'openai.api_configs': {
            '0': {
                'enable': True,
                'provider': 'tater',
                'connection_type': 'external',
            }
        },
        'tater.base_model': base_model,
        'tater.hydra_model': hydra_model,
        'tater.context_window': context_window,
        'models.default_params': {
            'function_calling': 'legacy',
            'compact_token_threshold': compact_token_threshold,
        },
        'chat.context_compaction.enable': True,
        'chat.context_compaction.token_threshold': compact_token_threshold,
        'chat.context_compaction.token_cap': compact_token_threshold,
        'ui.default_models': base_model,
        'ui.default_pinned_models': base_model,
    }


def is_reserved_hydra_model(model: dict, hydra_model: str | None) -> bool:
    return bool(hydra_model and model.get('id') == hydra_model)
