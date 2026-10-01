from __future__ import annotations

import json
import logging
import mimetypes
import os
import tempfile
from typing import Any
from urllib.parse import quote, urlencode, urljoin

log = logging.getLogger(__name__)

TATER_HYDRA_TOOL_NAME = 'tater_hydra'
DEFAULT_TATER_HYDRA_TIMEOUT_SECONDS = 600
MAX_TATER_HYDRA_TIMEOUT_SECONDS = 3600
MAX_TATER_HYDRA_RESPONSE_BYTES = 4_000_000
TATER_HYDRA_ARTIFACT_SPOOL_BYTES = 8 * 1024 * 1024
DEFAULT_TATER_HYDRA_ARTIFACT_MAX_MB = 1024

TATER_HYDRA_TOOL_SPEC = {
    'name': TATER_HYDRA_TOOL_NAME,
    'description': (
        'Delegate one self-contained task to the connected Tater Hydra runtime. Use this only for Tater-provided '
        'capabilities such as Verbas, Cores, Portals, smart-home or other connected devices, Tater automations, and '
        'generation of images, audio, music, and video. Media generation may be provided by a configured '
        'Tater Verba such as ComfyUI. Do not use this tool for ordinary conversation, reasoning, terminal commands, '
        'files, Git, builds, or tests. Hydra does not see the surrounding chat, so include the target, requested '
        'action, prompt, format, and other relevant details. If Tater reports that no matching Verba or provider is '
        'configured, report that result honestly and do not claim that media was generated.'
    ),
    'parameters': {
        'type': 'object',
        'properties': {
            'request': {
                'type': 'string',
                'description': 'A complete standalone instruction for Tater Hydra to execute.',
                'minLength': 1,
            }
        },
        'required': ['request'],
        'additionalProperties': False,
    },
}

TATER_HYDRA_SYSTEM_PROMPT = """Tater capability routing:

- Use `tater_hydra` only when the request needs a capability owned by the connected Tater system: Verbas, Cores,
  Portals, connected devices, Tater automations, or media generation.
- Requests to generate an image, animation, audio clip, music, speech media, or video belong to Hydra. Tater
  may fulfill them through a configured Verba or provider such as ComfyUI. Include the complete creative prompt and
  any requested style, dimensions, aspect ratio, duration, or format in the delegation.
- Do not delegate ordinary answers or local computer work. Use `terminal` for commands, files, Git, builds, tests,
  package management, and processes.
- Hydra does not receive this conversation automatically. Make every delegated request self-contained and include the
  exact target, action, and constraints it needs.
- Generated media can be returned as Hydra artifacts. Treat those artifacts as the requested output and tell the user
  they are attached; do not call Hydra again just because its textual response is brief or empty.
- If Hydra reports that generation is unavailable because a matching Verba or provider is missing, disabled, or not
  configured, report that limitation directly. Do not retry the same request, fabricate an artifact, or silently fall
  back to a terminal-made substitute unless the user explicitly asks for another approach.
- Treat Hydra's result as a tool result. Continue the task after it returns and clearly report the actual outcome.
"""


def hydra_timeout_seconds(value: str | int | float | None = None) -> float:
    raw = value if value is not None else os.getenv('TATER_HYDRA_TIMEOUT_SECONDS', '')
    try:
        timeout = float(raw or DEFAULT_TATER_HYDRA_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = float(DEFAULT_TATER_HYDRA_TIMEOUT_SECONDS)
    return max(1.0, min(timeout, float(MAX_TATER_HYDRA_TIMEOUT_SECONDS)))


def build_tater_hydra_payload(
    request_text: str,
    *,
    hydra_model: str,
    user_id: str,
    user_name: str,
    session_id: str | None,
) -> dict[str, Any]:
    request_text = str(request_text or '').strip()
    if not request_text:
        raise ValueError('A non-empty Hydra request is required')

    return {
        'model': hydra_model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'This is a delegated Tater capability request from Tater Open WebUI. Execute the requested Tater action '
                    'using your available Tater tools, then return a concise, factual result. For image, audio, music, '
                    'or video generation, return every generated item as a Spud Link artifact. If no capable Verba or '
                    'provider is configured, clearly say that generation is unavailable. Do not claim success unless '
                    'the action actually completed, and never invent an artifact.'
                ),
            },
            {'role': 'user', 'content': request_text},
        ],
        'stream': False,
        'user': user_id,
        'user_name': user_name,
        'metadata': {
            'source': 'tater-open-webui',
            'user_id': user_id,
            'user_name': user_name,
            **({'chat_id': session_id} if session_id else {}),
        },
    }


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ''
    parts = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get('type') in {'text', 'output_text'}:
            parts.append(str(item.get('text') or ''))
    return ''.join(parts).strip()


def parse_tater_hydra_response(payload: Any, *, api_base_url: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError('Tater Hydra returned a non-object response')

    choices = payload.get('choices')
    message = (
        choices[0].get('message') if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    )
    content = _content_text(message.get('content') if isinstance(message, dict) else '')

    spud_link = payload.get('spud_link') if isinstance(payload.get('spud_link'), dict) else {}
    raw_artifacts = spud_link.get('artifacts') if isinstance(spud_link.get('artifacts'), list) else []
    artifacts = []
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            continue
        artifact = dict(raw_artifact)
        if isinstance(artifact.get('url'), str) and artifact['url'].startswith('/'):
            artifact['url'] = urljoin(f'{api_base_url.rstrip("/")}/', artifact['url'])
        artifacts.append(artifact)

    if not content and not artifacts:
        raise RuntimeError('Tater Hydra returned an empty result')

    return {
        'status': 'completed',
        'model': str(payload.get('model') or 'tater/hydra'),
        'response': content,
        **({'artifacts': artifacts} if artifacts else {}),
        **({'usage': payload['usage']} if isinstance(payload.get('usage'), dict) else {}),
    }


def tater_hydra_artifact_files(result: Any) -> list[dict[str, Any]]:
    """Convert Hydra artifacts into chat attachments without exposing the Tater link token."""

    if not isinstance(result, dict) or not isinstance(result.get('artifacts'), list):
        return []

    files: list[dict[str, Any]] = []
    for artifact in result['artifacts']:
        if not isinstance(artifact, dict):
            continue

        mimetype = str(artifact.get('mimetype') or artifact.get('mime_type') or '').strip().lower()
        media_type = str(artifact.get('type') or '').strip().lower()
        if media_type not in {'image', 'audio', 'video', 'file'}:
            if mimetype.startswith('image/'):
                media_type = 'image'
            elif mimetype.startswith('audio/'):
                media_type = 'audio'
            elif mimetype.startswith('video/'):
                media_type = 'video'
            else:
                media_type = 'file'

        url = str(artifact.get('url') or artifact.get('dataUrl') or artifact.get('previewUrl') or '').strip()
        file_id = str(artifact.get('id') or artifact.get('file_id') or '').strip()
        if file_id and '/api/spudlink/v1/files/' in url:
            query = urlencode({'mimetype': mimetype or 'application/octet-stream'})
            url = f'/api/v1/tater/artifacts/{quote(file_id, safe="")}?{query}'
        if not url:
            continue

        file_item: dict[str, Any] = {
            'type': media_type,
            'url': url,
            'name': str(artifact.get('name') or artifact.get('filename') or 'Generated media').strip()
            or 'Generated media',
        }
        if mimetype:
            file_item['content_type'] = mimetype
        if artifact.get('size') is not None:
            file_item['size'] = artifact.get('size')
        files.append(file_item)
    return files


def _artifact_max_bytes() -> int:
    raw = os.getenv('TATER_HYDRA_ARTIFACT_MAX_MB', str(DEFAULT_TATER_HYDRA_ARTIFACT_MAX_MB))
    try:
        megabytes = int(raw)
    except (TypeError, ValueError):
        megabytes = DEFAULT_TATER_HYDRA_ARTIFACT_MAX_MB
    return max(1, min(megabytes, 4096)) * 1024 * 1024


def _artifact_name(artifact: dict[str, Any], *, index: int, mimetype: str) -> str:
    raw_name = str(artifact.get('name') or artifact.get('filename') or '').strip()
    name = os.path.basename(raw_name.replace('\\', '/')).strip()
    if not name:
        extension = mimetypes.guess_extension(mimetype or '') or ''
        name = f'tater-hydra-artifact-{index}{extension}'
    return name[:255]


async def _upload_tater_hydra_artifact(
    request: Any,
    *,
    file_obj: Any,
    name: str,
    mimetype: str,
    media_type: str,
    size: int,
    metadata: dict[str, Any],
    user: Any,
    artifact_id: str,
) -> dict[str, Any]:
    from fastapi import UploadFile
    from open_webui.routers.files import upload_file_handler

    upload = UploadFile(
        file=file_obj,
        filename=name,
        headers={'content-type': mimetype},
    )
    file_metadata = {
        key: metadata.get(key)
        for key in ('chat_id', 'message_id', 'session_id')
        if metadata.get(key)
    }
    file_metadata.update(
        {
            'source': TATER_HYDRA_TOOL_NAME,
            'tater_artifact_id': artifact_id,
            'tater_artifact_type': media_type,
        }
    )
    stored = await upload_file_handler(
        request,
        file=upload,
        metadata=file_metadata,
        process=False,
        user=user,
    )
    stored_id = str(stored.get('id') if isinstance(stored, dict) else getattr(stored, 'id', '')).strip()
    if not stored_id:
        raise RuntimeError('Open WebUI did not return a stored file id')
    return {
        'id': stored_id,
        'type': media_type,
        'url': str(request.app.url_path_for('get_file_content_by_id', id=stored_id)),
        'name': name,
        'content_type': mimetype,
        'size': size,
    }


async def persist_tater_hydra_artifact_files(
    request: Any,
    result: Any,
    metadata: dict[str, Any] | None,
    user: Any,
) -> list[dict[str, Any]]:
    """Copy Hydra artifacts into Open WebUI storage before attaching them to chat."""

    if not isinstance(result, dict) or not isinstance(result.get('artifacts'), list):
        return []

    artifacts = [item for item in result['artifacts'] if isinstance(item, dict)]
    if not artifacts:
        return []

    try:
        api_base_url, api_key, _hydra_model = await get_tater_hydra_connection()
    except Exception as exc:
        log.warning('Could not load the Tater link for Hydra artifact persistence: %s', exc)
        return tater_hydra_artifact_files(result)

    import aiohttp

    user_id = str(getattr(user, 'id', '') or '').strip()
    user_name = str(getattr(user, 'name', '') or getattr(user, 'email', '') or '').strip()
    headers = {
        'Accept-Encoding': 'identity',
        'X-SpudLink-Client': 'tater-open-webui',
        'X-SpudLink-Device': 'Tater Open WebUI',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    if user_id:
        headers['X-SpudLink-User-ID'] = user_id[:128]
    if user_name:
        headers['X-SpudLink-User'] = user_name[:80]

    max_bytes = _artifact_max_bytes()
    timeout = aiohttp.ClientTimeout(total=MAX_TATER_HYDRA_TIMEOUT_SECONDS, connect=30)
    files: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True, auto_decompress=False) as session:
        for index, artifact in enumerate(artifacts, start=1):
            fallback = tater_hydra_artifact_files({'artifacts': [artifact]})
            fallback_file = fallback[0] if fallback else None
            file_id = str(artifact.get('id') or artifact.get('file_id') or '').strip()
            if not file_id:
                if fallback_file:
                    files.append(fallback_file)
                continue

            mimetype = str(
                artifact.get('mimetype') or artifact.get('mime_type') or artifact.get('content_type') or ''
            ).strip().lower()
            media_type = str(artifact.get('type') or '').strip().lower()
            if media_type not in {'image', 'audio', 'video', 'file'}:
                if mimetype.startswith('image/'):
                    media_type = 'image'
                elif mimetype.startswith('audio/'):
                    media_type = 'audio'
                elif mimetype.startswith('video/'):
                    media_type = 'video'
                else:
                    media_type = 'file'
            name = _artifact_name(artifact, index=index, mimetype=mimetype)
            query = urlencode({'mimetype': mimetype or 'application/octet-stream'})
            artifact_url = urljoin(
                f'{api_base_url.rstrip("/")}/',
                f'/api/spudlink/v1/files/{quote(file_id, safe="")}?{query}',
            )

            try:
                request_headers = {**headers, 'Accept': mimetype or 'application/octet-stream'}
                async with session.get(artifact_url, headers=request_headers) as response:
                    if response.status >= 400:
                        detail = (await response.text())[:500]
                        raise RuntimeError(f'Tater returned HTTP {response.status}: {detail or "artifact unavailable"}')
                    if response.content_length is not None and response.content_length > max_bytes:
                        raise RuntimeError(
                            f'artifact is larger than the configured {max_bytes // (1024 * 1024)} MB limit'
                        )
                    response_mimetype = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
                    if not mimetype or mimetype == 'application/octet-stream':
                        mimetype = response_mimetype or 'application/octet-stream'
                    if media_type == 'file':
                        if mimetype.startswith('image/'):
                            media_type = 'image'
                        elif mimetype.startswith('audio/'):
                            media_type = 'audio'
                        elif mimetype.startswith('video/'):
                            media_type = 'video'

                    with tempfile.SpooledTemporaryFile(max_size=TATER_HYDRA_ARTIFACT_SPOOL_BYTES, mode='w+b') as file_obj:
                        size = 0
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            size += len(chunk)
                            if size > max_bytes:
                                raise RuntimeError(
                                    f'artifact is larger than the configured {max_bytes // (1024 * 1024)} MB limit'
                                )
                            file_obj.write(chunk)
                        if size <= 0:
                            raise RuntimeError('Tater returned an empty artifact')
                        file_obj.seek(0)
                        files.append(
                            await _upload_tater_hydra_artifact(
                                request,
                                file_obj=file_obj,
                                name=name,
                                mimetype=mimetype or 'application/octet-stream',
                                media_type=media_type,
                                size=size,
                                metadata=metadata or {},
                                user=user,
                                artifact_id=file_id,
                            )
                        )
            except Exception as exc:
                log.warning('Could not persist Tater Hydra artifact %s (%s): %s', file_id, name, exc)
                if fallback_file:
                    files.append(fallback_file)

    return files


def _error_detail(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get('detail') or payload.get('error') or payload.get('message')
        if isinstance(detail, dict):
            detail = detail.get('message') or json.dumps(detail, ensure_ascii=False)
        if detail:
            return str(detail)[:1000]
    return fallback.strip()[:1000]


async def request_tater_hydra(
    *,
    api_base_url: str,
    api_key: str,
    hydra_model: str,
    user_id: str,
    user_name: str,
    session_id: str | None,
    request_text: str,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    import aiohttp

    payload = build_tater_hydra_payload(
        request_text,
        hydra_model=hydra_model,
        user_id=user_id,
        user_name=user_name,
        session_id=session_id,
    )
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-SpudLink-Client': 'tater-open-webui',
        'X-SpudLink-Device': 'Tater Open WebUI',
        'X-SpudLink-User-ID': user_id,
        'X-SpudLink-User': user_name,
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    if session_id:
        headers['X-Tater-Session'] = session_id

    timeout_value = hydra_timeout_seconds(timeout_seconds)
    timeout = aiohttp.ClientTimeout(total=timeout_value, connect=min(30, timeout_value))
    endpoint = f'{api_base_url.rstrip("/")}/chat/completions'
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(endpoint, headers=headers, json=payload) as response:
                if response.content_length and response.content_length > MAX_TATER_HYDRA_RESPONSE_BYTES:
                    raise RuntimeError('Tater Hydra response exceeded the 4 MB limit')
                body = await response.text()
                if len(body.encode('utf-8')) > MAX_TATER_HYDRA_RESPONSE_BYTES:
                    raise RuntimeError('Tater Hydra response exceeded the 4 MB limit')
                try:
                    response_payload = json.loads(body)
                except json.JSONDecodeError:
                    response_payload = None
                if response.status >= 400:
                    detail = _error_detail(response_payload, body)
                    raise RuntimeError(f'Tater Hydra returned HTTP {response.status}: {detail or "request failed"}')
    except TimeoutError as exc:
        raise RuntimeError(f'Tater Hydra timed out after {timeout_value:g} seconds') from exc
    except aiohttp.ClientError as exc:
        raise RuntimeError(f'Could not connect to Tater Hydra: {exc}') from exc

    if response_payload is None:
        raise RuntimeError('Tater Hydra returned invalid JSON')
    return parse_tater_hydra_response(response_payload, api_base_url=api_base_url)


async def get_tater_hydra_connection() -> tuple[str, str, str]:
    from open_webui.models.config import Config
    from open_webui.utils.tater_profile import (
        DEFAULT_TATER_API_BASE_URL,
        DEFAULT_TATER_HYDRA_MODEL,
        normalize_tater_api_base_url,
    )

    values = await Config.get_many(
        'openai.api_base_urls',
        'openai.api_keys',
        'tater.hydra_model',
    )
    api_base_urls = values.get('openai.api_base_urls') or []
    api_keys = values.get('openai.api_keys') or []
    api_base_url = normalize_tater_api_base_url(api_base_urls[0] if api_base_urls else DEFAULT_TATER_API_BASE_URL)
    api_key = str(api_keys[0] if api_keys else '').strip()
    hydra_model = str(values.get('tater.hydra_model') or DEFAULT_TATER_HYDRA_MODEL).strip()
    return api_base_url, api_key, hydra_model


def get_tater_hydra_tools(
    *,
    user_id: str,
    user_name: str,
    session_id: str | None,
) -> tuple[dict[str, dict], str]:
    async def tater_hydra(request: str):
        api_base_url, api_key, hydra_model = await get_tater_hydra_connection()
        return await request_tater_hydra(
            api_base_url=api_base_url,
            api_key=api_key,
            hydra_model=hydra_model,
            user_id=user_id,
            user_name=user_name,
            session_id=session_id,
            request_text=request,
        )

    return (
        {
            TATER_HYDRA_TOOL_NAME: {
                'tool_id': f'builtin:{TATER_HYDRA_TOOL_NAME}',
                'callable': tater_hydra,
                'spec': TATER_HYDRA_TOOL_SPEC,
                'type': 'builtin',
            }
        },
        TATER_HYDRA_SYSTEM_PROMPT,
    )
