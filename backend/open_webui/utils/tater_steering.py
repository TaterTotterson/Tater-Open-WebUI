from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

TATER_STEERING_TTL_SECONDS = 4 * 60 * 60
REDIS_KEY_PREFIX = os.getenv('REDIS_KEY_PREFIX', 'open-webui')

_active_runs: dict[str, dict[str, Any]] = {}
_queued_messages: dict[tuple[str, str], list[dict[str, Any]]] = {}
_lock = asyncio.Lock()


def _active_key(chat_id: str) -> str:
    return f'{REDIS_KEY_PREFIX}:tater:steering:active:{chat_id}'


def _queue_key(chat_id: str, run_id: str) -> str:
    return f'{REDIS_KEY_PREFIX}:tater:steering:queue:{chat_id}:{run_id}'


def _decode(value: Any) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        decoded = json.loads(value)
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


async def register_live_agent_run(redis, *, chat_id: str, user_id: str, run_id: str) -> None:
    record = {
        'chat_id': str(chat_id),
        'user_id': str(user_id),
        'run_id': str(run_id),
        'registered_at': time.time(),
    }
    if redis:
        await redis.set(
            _active_key(chat_id),
            json.dumps(record).encode('utf-8'),
            ex=TATER_STEERING_TTL_SECONDS,
        )
        return

    async with _lock:
        _active_runs[str(chat_id)] = record


async def get_live_agent_run(redis, chat_id: str) -> dict[str, Any] | None:
    if redis:
        return _decode(await redis.get(_active_key(chat_id)))

    async with _lock:
        record = _active_runs.get(str(chat_id))
        return dict(record) if record else None


async def enqueue_live_agent_message(
    redis,
    *,
    chat_id: str,
    user_id: str,
    message_id: str,
    message: str,
) -> dict[str, Any] | None:
    active = await get_live_agent_run(redis, chat_id)
    if not active or str(active.get('user_id')) != str(user_id):
        return None

    item = {
        'id': str(message_id),
        'message': str(message).strip(),
        'created_at': time.time(),
        'run_id': str(active['run_id']),
    }
    if not item['message']:
        return None

    if redis:
        key = _queue_key(chat_id, item['run_id'])
        pipe = redis.pipeline(transaction=False)
        pipe.rpush(key, json.dumps(item).encode('utf-8'))
        pipe.expire(key, TATER_STEERING_TTL_SECONDS)
        await pipe.execute()
        return item

    async with _lock:
        _queued_messages.setdefault((str(chat_id), item['run_id']), []).append(item)
    return item


async def drain_live_agent_messages(redis, *, chat_id: str, run_id: str) -> list[dict[str, Any]]:
    if redis:
        key = _queue_key(chat_id, run_id)
        values = await redis.eval(
            "local values = redis.call('LRANGE', KEYS[1], 0, -1); "
            "redis.call('DEL', KEYS[1]); return values",
            1,
            key,
        )
        return [item for value in values or [] if (item := _decode(value))]

    async with _lock:
        return _queued_messages.pop((str(chat_id), str(run_id)), [])


async def clear_live_agent_run(redis, *, chat_id: str, run_id: str) -> None:
    if redis:
        active_key = _active_key(chat_id)
        await redis.eval(
            "local value = redis.call('GET', KEYS[1]); "
            "if not value then return 0 end; "
            "local ok, decoded = pcall(cjson.decode, value); "
            "if ok and tostring(decoded.run_id) == ARGV[1] then "
            "redis.call('DEL', KEYS[1]); return 1 end; return 0",
            1,
            active_key,
            str(run_id),
        )
        await redis.delete(_queue_key(chat_id, run_id))
        return

    async with _lock:
        active = _active_runs.get(str(chat_id))
        if active and str(active.get('run_id')) == str(run_id):
            _active_runs.pop(str(chat_id), None)
        _queued_messages.pop((str(chat_id), str(run_id)), None)
