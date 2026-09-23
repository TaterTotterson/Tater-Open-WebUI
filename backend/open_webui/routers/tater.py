from __future__ import annotations

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from open_webui.models.config import Config
from open_webui.routers.openai import clear_openai_model_cache
from open_webui.utils.auth import get_admin_user
from open_webui.utils.tater_profile import (
    DEFAULT_TATER_API_BASE_URL,
    DEFAULT_TATER_BASE_MODEL,
    DEFAULT_TATER_HYDRA_MODEL,
    build_tater_profile_updates,
    normalize_tater_api_base_url,
    normalize_tater_model_id,
)


router = APIRouter()


class TaterProfileForm(BaseModel):
    api_base_url: str
    api_key: str | None = None
    base_model: str = DEFAULT_TATER_BASE_MODEL
    hydra_model: str = DEFAULT_TATER_HYDRA_MODEL


class TaterProfileResponse(BaseModel):
    api_base_url: str
    api_key_configured: bool
    base_model: str
    hydra_model: str


class TaterProfileVerification(BaseModel):
    connected: bool
    base_model_available: bool
    hydra_model_available: bool
    models: list[str]


async def get_tater_profile() -> tuple[str, str, str, str]:
    values = await Config.get_many(
        'openai.api_base_urls',
        'openai.api_keys',
        'tater.base_model',
        'tater.hydra_model',
    )
    api_base_urls = values.get('openai.api_base_urls') or []
    api_keys = values.get('openai.api_keys') or []
    return (
        api_base_urls[0] if api_base_urls else DEFAULT_TATER_API_BASE_URL,
        api_keys[0] if api_keys else '',
        values.get('tater.base_model') or DEFAULT_TATER_BASE_MODEL,
        values.get('tater.hydra_model') or DEFAULT_TATER_HYDRA_MODEL,
    )


def profile_response(api_base_url: str, api_key: str, base_model: str, hydra_model: str):
    return TaterProfileResponse(
        api_base_url=api_base_url,
        api_key_configured=bool(api_key),
        base_model=base_model,
        hydra_model=hydra_model,
    )


def validate_profile_form(form_data: TaterProfileForm) -> tuple[str, str, str]:
    try:
        api_base_url = normalize_tater_api_base_url(form_data.api_base_url)
        base_model = normalize_tater_model_id(form_data.base_model, 'Base model')
        hydra_model = normalize_tater_model_id(form_data.hydra_model, 'Hydra model')
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if base_model == hydra_model:
        raise HTTPException(status_code=400, detail='Base and Hydra models must be different')
    return api_base_url, base_model, hydra_model


@router.get('/config', response_model=TaterProfileResponse)
async def get_config(user=Depends(get_admin_user)):
    return profile_response(*(await get_tater_profile()))


@router.post('/config', response_model=TaterProfileResponse)
async def update_config(
    request: Request,
    form_data: TaterProfileForm,
    user=Depends(get_admin_user),
):
    api_base_url, base_model, hydra_model = validate_profile_form(form_data)
    _, saved_api_key, _, _ = await get_tater_profile()
    api_key = saved_api_key if form_data.api_key is None else form_data.api_key

    try:
        updates = build_tater_profile_updates(
            api_base_url=api_base_url,
            api_key=api_key,
            base_model=base_model,
            hydra_model=hydra_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await Config.upsert(updates)
    await clear_openai_model_cache(request)
    return profile_response(api_base_url, api_key.strip(), base_model, hydra_model)


@router.post('/verify', response_model=TaterProfileVerification)
async def verify_config(form_data: TaterProfileForm, user=Depends(get_admin_user)):
    api_base_url, base_model, hydra_model = validate_profile_form(form_data)
    _, saved_api_key, _, _ = await get_tater_profile()
    api_key = saved_api_key if form_data.api_key is None else form_data.api_key.strip()
    headers = {'Accept': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(f'{api_base_url}/models', headers=headers) as response:
                if response.status >= 400:
                    detail = await response.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f'Tater API returned HTTP {response.status}: {detail[:500]}',
                    )
                payload = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Could not connect to Tater API: {exc}') from exc

    raw_models = payload.get('data', []) if isinstance(payload, dict) else []
    model_ids = sorted(
        {
            str(model.get('id'))
            for model in raw_models
            if isinstance(model, dict) and model.get('id')
        }
    )
    return TaterProfileVerification(
        connected=True,
        base_model_available=base_model in model_ids,
        hydra_model_available=hydra_model in model_ids,
        models=model_ids,
    )
