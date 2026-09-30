from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path
from uuid import uuid4

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'utils' / 'tater_steering.py'
SPEC = importlib.util.spec_from_file_location('tater_steering', MODULE_PATH)
assert SPEC and SPEC.loader
tater_steering = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tater_steering)


class TaterSteeringTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_messages_are_scoped_to_the_active_chat_run(self):
        chat_id = f'chat-{uuid4()}'
        run_id = f'run-{uuid4()}'
        await tater_steering.register_live_agent_run(
            None, chat_id=chat_id, user_id='user-1', run_id=run_id
        )

        item = await tater_steering.enqueue_live_agent_message(
            None,
            chat_id=chat_id,
            user_id='user-1',
            message_id='message-1',
            message='Also add a regression test.',
        )
        messages = await tater_steering.drain_live_agent_messages(
            None, chat_id=chat_id, run_id=run_id
        )

        self.assertEqual(item['run_id'], run_id)
        self.assertEqual([message['message'] for message in messages], ['Also add a regression test.'])
        self.assertEqual(
            await tater_steering.drain_live_agent_messages(None, chat_id=chat_id, run_id=run_id), []
        )
        await tater_steering.clear_live_agent_run(None, chat_id=chat_id, run_id=run_id)

    async def test_rejects_messages_from_a_different_user(self):
        chat_id = f'chat-{uuid4()}'
        run_id = f'run-{uuid4()}'
        await tater_steering.register_live_agent_run(
            None, chat_id=chat_id, user_id='owner', run_id=run_id
        )

        item = await tater_steering.enqueue_live_agent_message(
            None,
            chat_id=chat_id,
            user_id='other-user',
            message_id='message-1',
            message='Change the task.',
        )

        self.assertIsNone(item)
        await tater_steering.clear_live_agent_run(None, chat_id=chat_id, run_id=run_id)

    async def test_clear_only_removes_the_matching_run(self):
        chat_id = f'chat-{uuid4()}'
        await tater_steering.register_live_agent_run(
            None, chat_id=chat_id, user_id='user-1', run_id='new-run'
        )

        await tater_steering.clear_live_agent_run(None, chat_id=chat_id, run_id='old-run')

        active = await tater_steering.get_live_agent_run(None, chat_id)
        self.assertEqual(active['run_id'], 'new-run')
        await tater_steering.clear_live_agent_run(None, chat_id=chat_id, run_id='new-run')
