from __future__ import annotations

from typing import Any

from open_webui.models.config import Config
from open_webui.utils.tater_profile import normalize_tater_hub_url

TATER_OPEN_WEBUI_CLIENT_ROLE = 'tater_open_webui'
TATER_OPEN_WEBUI_CLIENT_NAME = 'Tater Open WebUI'

async def get_tater_link_connection() -> tuple[str, str]:
    values = await Config.get_many(
        'tater.link.hub_url',
        'tater.link.connected',
        'openai.api_base_urls',
        'openai.api_keys',
    )
    api_urls = values.get('openai.api_base_urls') or []
    api_keys = values.get('openai.api_keys') or []
    raw_url = values.get('tater.link.hub_url') or (api_urls[0] if api_urls else '')
    hub_url = normalize_tater_hub_url(str(raw_url or ''))
    token = str(api_keys[0] if api_keys else '').strip()
    if not bool(values.get('tater.link.connected')) or not token:
        raise RuntimeError('Tater Open WebUI is not linked to Tater')
    return hub_url, token


def tater_link_headers(token: str, user: Any = None) -> dict[str, str]:
    headers = {
        'Authorization': f'Bearer {str(token or "").strip()}',
        'Accept': 'application/json, audio/wav',
        'X-SpudLink-Client': 'tater-open-webui',
        'X-SpudLink-Device': TATER_OPEN_WEBUI_CLIENT_NAME,
    }
    user_name = str(getattr(user, 'name', '') or getattr(user, 'email', '') or '').strip()
    if user_name:
        headers['X-SpudLink-User'] = user_name[:80]
    return headers
