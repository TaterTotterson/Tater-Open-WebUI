from __future__ import annotations

import aiohttp
import time
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from open_webui.models.config import Config
from open_webui.env import INSTANCE_ID
from open_webui.routers.openai import clear_openai_model_cache
from open_webui.tasks import stop_task
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.tater_tasks import (
    TATER_TASK_ACTIVE_STATUSES,
    emit_tater_task_event,
    get_user_tater_task,
    get_user_tater_task_history,
    reconcile_user_tater_tasks,
    tater_task_detail,
    tater_task_summary,
    update_tater_task,
)
from open_webui.utils.tater_profile import (
    DEFAULT_TATER_API_BASE_URL,
    DEFAULT_TATER_BASE_MODEL,
    DEFAULT_TATER_CONTEXT_WINDOW,
    DEFAULT_TATER_HYDRA_MODEL,
    build_tater_profile_updates,
    normalize_tater_context_window,
    normalize_tater_hub_url,
    tater_openai_api_url,
)
from open_webui.utils.tater_link import (
    TATER_OPEN_WEBUI_CLIENT_NAME,
    TATER_OPEN_WEBUI_CLIENT_ROLE,
    get_tater_link_connection,
    tater_link_headers,
)
from pydantic import BaseModel, Field

router = APIRouter()


class TaterProfileForm(BaseModel):
    context_window: int = DEFAULT_TATER_CONTEXT_WINDOW


class TaterProfileResponse(BaseModel):
    api_base_url: str
    api_key_configured: bool
    base_model: str
    hydra_model: str
    context_window: int
    linked: bool = False
    hub_url: str = ''
    hub_name: str = ''
    node_id: str = ''
    connected_at: float = 0
    capabilities: dict[str, Any] = Field(default_factory=dict)
    speech: dict[str, Any] = Field(default_factory=dict)


class TaterLinkForm(BaseModel):
    hub_url: str
    pairing_code: str


class TaterProfileVerification(BaseModel):
    connected: bool
    base_model_available: bool
    hydra_model_available: bool
    models: list[str]


@router.get('/tasks')
async def list_background_tasks(request: Request, user=Depends(get_verified_user)):
    tasks = await reconcile_user_tater_tasks(request.app, user.id)
    return [
        tater_task_summary(task)
        for task in tasks
        if (task.meta or {}).get('status') in TATER_TASK_ACTIVE_STATUSES
    ]


@router.get('/tasks/history')
async def list_background_task_history(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_verified_user),
):
    await reconcile_user_tater_tasks(request.app, user.id)
    return await get_user_tater_task_history(user.id, limit=limit, offset=offset)


@router.get('/tasks/{task_id}')
async def get_background_task(task_id: str, user=Depends(get_verified_user)):
    task = await get_user_tater_task(task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return tater_task_detail(task)


@router.delete('/tasks/{task_id}')
async def cancel_background_task(request: Request, task_id: str, user=Depends(get_verified_user)):
    task = await get_user_tater_task(task_id, user.id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    if (task.meta or {}).get('status') not in TATER_TASK_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail='Task is no longer running')

    await update_tater_task(
        task_id,
        {'status': 'cancelling', 'activity': 'Cancelling task'},
        user_id=user.id,
    )
    result = await stop_task(request.app.state.redis, task_id)
    if not result.get('status'):
        await update_tater_task(
            task_id,
            {'status': 'interrupted', 'activity': result.get('message') or 'Task stopped'},
            user_id=user.id,
        )
    await emit_tater_task_event(user.id, task_id, 'cancelling')
    latest = await get_user_tater_task(task_id, user.id)
    return tater_task_summary(latest or task)


async def get_tater_profile() -> tuple[str, str, str, str, int]:
    values = await Config.get_many(
        'openai.api_base_urls',
        'openai.api_keys',
        'tater.base_model',
        'tater.hydra_model',
        'tater.context_window',
    )
    api_base_urls = values.get('openai.api_base_urls') or []
    api_keys = values.get('openai.api_keys') or []
    return (
        api_base_urls[0] if api_base_urls else DEFAULT_TATER_API_BASE_URL,
        api_keys[0] if api_keys else '',
        values.get('tater.base_model') or DEFAULT_TATER_BASE_MODEL,
        values.get('tater.hydra_model') or DEFAULT_TATER_HYDRA_MODEL,
        normalize_tater_context_window(values.get('tater.context_window') or DEFAULT_TATER_CONTEXT_WINDOW),
    )


async def get_tater_link_metadata() -> dict[str, Any]:
    values = await Config.get_many(
        'tater.link.connected',
        'tater.link.hub_url',
        'tater.link.hub_name',
        'tater.link.node_id',
        'tater.link.connected_at',
        'tater.link.capabilities',
        'tater.link.speech',
    )
    return {
        'linked': bool(values.get('tater.link.connected')),
        'hub_url': str(values.get('tater.link.hub_url') or ''),
        'hub_name': str(values.get('tater.link.hub_name') or ''),
        'node_id': str(values.get('tater.link.node_id') or ''),
        'connected_at': float(values.get('tater.link.connected_at') or 0),
        'capabilities': values.get('tater.link.capabilities')
        if isinstance(values.get('tater.link.capabilities'), dict)
        else {},
        'speech': values.get('tater.link.speech') if isinstance(values.get('tater.link.speech'), dict) else {},
    }


def profile_response(
    api_base_url: str,
    api_key: str,
    base_model: str,
    hydra_model: str,
    context_window: int,
    link: dict[str, Any] | None = None,
):
    link = link or {}
    return TaterProfileResponse(
        api_base_url=api_base_url,
        api_key_configured=bool(api_key),
        base_model=base_model,
        hydra_model=hydra_model,
        context_window=context_window,
        linked=bool(link.get('linked')),
        hub_url=str(link.get('hub_url') or ''),
        hub_name=str(link.get('hub_name') or ''),
        node_id=str(link.get('node_id') or ''),
        connected_at=float(link.get('connected_at') or 0),
        capabilities=link.get('capabilities') if isinstance(link.get('capabilities'), dict) else {},
        speech=link.get('speech') if isinstance(link.get('speech'), dict) else {},
    )


async def _tater_link_status(
    session: aiohttp.ClientSession,
    hub_url: str,
    token: str,
    user: Any,
) -> dict[str, Any]:
    headers = tater_link_headers(token, user)
    async with session.get(
        f'{hub_url}/api/spudlink/v1/tater-open-webui/status',
        headers=headers,
    ) as response:
        if response.status >= 400:
            detail = await response.text()
            raise HTTPException(
                status_code=502,
                detail=f'Tater rejected the Tater Open WebUI link: {detail[:500]}',
            )
        payload = await response.json()
    if not isinstance(payload, dict) or payload.get('ok') is not True:
        raise HTTPException(status_code=502, detail='Tater returned an invalid link status')
    return payload


def _linked_profile_updates(
    *,
    hub_url: str,
    token: str,
    status_payload: dict[str, Any],
    node_payload: dict[str, Any],
    context_window: int,
) -> dict[str, Any]:
    models = status_payload.get('models') if isinstance(status_payload.get('models'), dict) else {}
    speech = status_payload.get('speech') if isinstance(status_payload.get('speech'), dict) else {}
    capabilities = (
        status_payload.get('capabilities') if isinstance(status_payload.get('capabilities'), dict) else {}
    )
    server = status_payload.get('server') if isinstance(status_payload.get('server'), dict) else {}
    base_model = str(models.get('base') or DEFAULT_TATER_BASE_MODEL)
    hydra_model = str(models.get('hydra') or DEFAULT_TATER_HYDRA_MODEL)
    updates = build_tater_profile_updates(
        api_base_url=tater_openai_api_url(hub_url),
        api_key=token,
        base_model=base_model,
        hydra_model=hydra_model,
        context_window=context_window,
    )
    updates.update(
        {
            'tater.link.connected': True,
            'tater.link.hub_url': hub_url,
            'tater.link.hub_name': str(server.get('name') or 'Tater'),
            'tater.link.node_id': str(node_payload.get('id') or ''),
            'tater.link.connected_at': time.time(),
            'tater.link.capabilities': capabilities,
            'tater.link.speech': speech,
            'audio.stt.engine': 'tater',
            'audio.stt.model': str(speech.get('stt_backend') or 'tater'),
            'audio.tts.engine': 'tater',
            'audio.tts.model': str(speech.get('tts_model') or speech.get('tts_backend') or 'tater'),
            'audio.tts.voice': str(speech.get('tts_voice') or 'Tater'),
        }
    )
    return updates


@router.post('/link', response_model=TaterProfileResponse)
async def link_tater(
    request: Request,
    form_data: TaterLinkForm,
    user=Depends(get_admin_user),
):
    try:
        hub_url = normalize_tater_hub_url(form_data.hub_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pairing_code = str(form_data.pairing_code or '').strip()
    if not pairing_code:
        raise HTTPException(status_code=400, detail='Tater Open WebUI pairing code is required')

    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(
                f'{hub_url}/api/spudlink/pair',
                json={
                    'pairing_code': pairing_code,
                    'role': TATER_OPEN_WEBUI_CLIENT_ROLE,
                    'node_name': TATER_OPEN_WEBUI_CLIENT_NAME,
                    'metadata': {
                        'client': 'tater-open-webui',
                        'product': TATER_OPEN_WEBUI_CLIENT_NAME,
                        'installation_id': INSTANCE_ID,
                    },
                },
                headers={'Accept': 'application/json'},
            ) as response:
                if response.status >= 400:
                    detail = await response.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f'Tater rejected the pairing request: {detail[:500]}',
                    )
                pair_payload = await response.json()
            token = str(pair_payload.get('node_token') or '').strip()
            node = pair_payload.get('node') if isinstance(pair_payload.get('node'), dict) else {}
            if not token:
                raise HTTPException(status_code=502, detail='Tater did not return a link token')
            status_payload = await _tater_link_status(session, hub_url, token, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Could not link Tater Open WebUI to Tater: {exc}') from exc

    _, _, _, _, context_window = await get_tater_profile()
    await Config.upsert(
        _linked_profile_updates(
            hub_url=hub_url,
            token=token,
            status_payload=status_payload,
            node_payload=node,
            context_window=context_window,
        )
    )
    await clear_openai_model_cache(request)
    return profile_response(*(await get_tater_profile()), link=await get_tater_link_metadata())


@router.post('/link/verify', response_model=TaterProfileVerification)
async def verify_tater_link(request: Request, user=Depends(get_admin_user)):
    try:
        hub_url, token = await get_tater_link_connection()
        timeout = aiohttp.ClientTimeout(total=15)
        headers = tater_link_headers(token, user)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            status_payload = await _tater_link_status(session, hub_url, token, user)
            async with session.get(f'{tater_openai_api_url(hub_url)}/models', headers=headers) as response:
                if response.status >= 400:
                    detail = await response.text()
                    raise HTTPException(
                        status_code=502,
                        detail=f'Tater model API returned HTTP {response.status}: {detail[:500]}',
                    )
                models_payload = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f'Could not verify the Tater Open WebUI link: {exc}') from exc

    raw_models = models_payload.get('data', []) if isinstance(models_payload, dict) else []
    model_ids = sorted(
        {
            str(model.get('id'))
            for model in raw_models
            if isinstance(model, dict) and model.get('id')
        }
    )
    base_model = str((status_payload.get('models') or {}).get('base') or DEFAULT_TATER_BASE_MODEL)
    hydra_model = str((status_payload.get('models') or {}).get('hydra') or DEFAULT_TATER_HYDRA_MODEL)
    await Config.upsert(
        {
            'tater.link.capabilities': status_payload.get('capabilities') or {},
            'tater.link.speech': status_payload.get('speech') or {},
            'tater.link.hub_name': str((status_payload.get('server') or {}).get('name') or 'Tater'),
            'audio.stt.engine': 'tater',
            'audio.tts.engine': 'tater',
        }
    )
    return TaterProfileVerification(
        connected=True,
        base_model_available=base_model in model_ids,
        hydra_model_available=hydra_model in model_ids,
        models=model_ids,
    )


@router.delete('/link', response_model=TaterProfileResponse)
async def unlink_tater(request: Request, user=Depends(get_admin_user)):
    try:
        hub_url, token = await get_tater_link_connection()
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            await session.post(
                f'{hub_url}/api/spudlink/v1/forget',
                headers=tater_link_headers(token, user),
            )
    except Exception:
        pass

    await Config.upsert(
        {
            'openai.api_keys': [''],
            'tater.link.connected': False,
            'tater.link.hub_name': '',
            'tater.link.node_id': '',
            'tater.link.connected_at': 0,
            'tater.link.capabilities': {},
            'tater.link.speech': {},
            'audio.stt.engine': 'tater',
            'audio.tts.engine': 'tater',
        }
    )
    await clear_openai_model_cache(request)
    return profile_response(*(await get_tater_profile()), link=await get_tater_link_metadata())


@router.get('/config', response_model=TaterProfileResponse)
async def get_config(user=Depends(get_admin_user)):
    return profile_response(*(await get_tater_profile()), link=await get_tater_link_metadata())


@router.post('/config', response_model=TaterProfileResponse)
async def update_config(
    request: Request,
    form_data: TaterProfileForm,
    user=Depends(get_admin_user),
):
    link = await get_tater_link_metadata()
    if not link.get('linked'):
        raise HTTPException(status_code=409, detail='Link Tater Open WebUI through SpudLink first')
    try:
        context_window = normalize_tater_context_window(form_data.context_window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    api_base_url, api_key, _, _, _ = await get_tater_profile()
    base_model = DEFAULT_TATER_BASE_MODEL
    hydra_model = DEFAULT_TATER_HYDRA_MODEL

    try:
        updates = build_tater_profile_updates(
            api_base_url=api_base_url,
            api_key=api_key,
            base_model=base_model,
            hydra_model=hydra_model,
            context_window=context_window,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await Config.upsert(updates)
    await clear_openai_model_cache(request)
    return profile_response(
        api_base_url,
        api_key.strip(),
        base_model,
        hydra_model,
        context_window,
        link=link,
    )
