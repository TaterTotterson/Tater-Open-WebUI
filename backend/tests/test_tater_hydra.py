from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from aiohttp import web

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'utils' / 'tater_hydra.py'
SPEC = importlib.util.spec_from_file_location('tater_hydra', MODULE_PATH)
assert SPEC and SPEC.loader
tater_hydra = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tater_hydra)


class TaterHydraTests(unittest.TestCase):
    def test_builds_a_self_contained_standard_chat_completion(self):
        payload = tater_hydra.build_tater_hydra_payload(
            'Turn on the kitchen lights',
            hydra_model='tater/hydra',
            user_id='user-1',
            user_name='Ada',
            session_id='chat-1',
        )

        self.assertEqual(payload['model'], 'tater/hydra')
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['messages'][-1], {'role': 'user', 'content': 'Turn on the kitchen lights'})
        self.assertEqual(payload['user'], 'user-1')
        self.assertEqual(payload['user_name'], 'Ada')
        self.assertEqual(payload['metadata']['user_id'], 'user-1')
        self.assertEqual(payload['metadata']['chat_id'], 'chat-1')

    def test_rejects_an_empty_delegation(self):
        with self.assertRaisesRegex(ValueError, 'non-empty'):
            tater_hydra.build_tater_hydra_payload(
                '   ',
                hydra_model='tater/hydra',
                user_id='user-1',
                user_name='Ada',
                session_id='chat-1',
            )

    def test_parses_text_artifacts_and_usage(self):
        parsed = tater_hydra.parse_tater_hydra_response(
            {
                'model': 'tater/hydra',
                'choices': [{'message': {'role': 'assistant', 'content': 'The lights are on.'}}],
                'spud_link': {'artifacts': [{'name': 'result.txt', 'url': '/api/files/1'}]},
                'usage': {'total_tokens': 12},
            },
            api_base_url='http://tater.local:8501/v1',
        )

        self.assertEqual(parsed['response'], 'The lights are on.')
        self.assertEqual(parsed['artifacts'][0]['url'], 'http://tater.local:8501/api/files/1')
        self.assertEqual(parsed['usage']['total_tokens'], 12)


class TaterHydraHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = {}

        async def completion(request):
            self.received['authorization'] = request.headers.get('Authorization')
            self.received['session'] = request.headers.get('X-Tater-Session')
            self.received['user_id'] = request.headers.get('X-SpudLink-User-ID')
            self.received['user_name'] = request.headers.get('X-SpudLink-User')
            self.received['payload'] = await request.json()
            return web.json_response(
                {
                    'model': 'tater/hydra',
                    'choices': [{'message': {'role': 'assistant', 'content': 'Device action completed.'}}],
                }
            )

        app = web.Application()
        app.router.add_post('/v1/chat/completions', completion)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.api_base_url = f'http://127.0.0.1:{port}/v1'

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_calls_the_standard_tater_endpoint_with_server_credentials(self):
        result = await tater_hydra.request_tater_hydra(
            api_base_url=self.api_base_url,
            api_key='secret-token',
            hydra_model='tater/hydra',
            user_id='user-1',
            user_name='Ada',
            session_id='chat-1',
            request_text='Run a connected device action',
            timeout_seconds=5,
        )

        self.assertEqual(result['response'], 'Device action completed.')
        self.assertEqual(self.received['authorization'], 'Bearer secret-token')
        self.assertEqual(self.received['session'], 'chat-1')
        self.assertEqual(self.received['user_id'], 'user-1')
        self.assertEqual(self.received['user_name'], 'Ada')
        self.assertEqual(self.received['payload']['model'], 'tater/hydra')


if __name__ == '__main__':
    unittest.main()
