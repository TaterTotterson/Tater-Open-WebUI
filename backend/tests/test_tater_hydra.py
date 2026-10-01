from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        self.assertIn('image, audio, music, or video generation', payload['messages'][0]['content'])
        self.assertIn('generation is unavailable', payload['messages'][0]['content'])

    def test_tool_prompt_routes_media_generation_to_hydra(self):
        prompt = f"{tater_hydra.TATER_HYDRA_TOOL_SPEC['description']}\n{tater_hydra.TATER_HYDRA_SYSTEM_PROMPT}"

        for media_type in ('image', 'audio', 'music', 'video'):
            self.assertIn(media_type, prompt.lower())
        self.assertIn('ComfyUI', prompt)
        self.assertIn('Do not retry the same request', prompt)

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

    def test_media_artifacts_become_visible_chat_attachments(self):
        parsed = tater_hydra.parse_tater_hydra_response(
            {
                'model': 'tater/hydra',
                'choices': [{'message': {'role': 'assistant', 'content': ''}}],
                'spud_link': {
                    'artifacts': [
                        {
                            'id': 'image-1',
                            'type': 'image',
                            'name': 'potato.png',
                            'mimetype': 'image/png',
                            'url': '/api/spudlink/v1/files/image-1?mimetype=image/png',
                        },
                        {
                            'id': 'audio-1',
                            'name': 'song.mp3',
                            'mimetype': 'audio/mpeg',
                            'url': '/api/spudlink/v1/files/audio-1?mimetype=audio/mpeg',
                        },
                        {
                            'type': 'video',
                            'name': 'clip.mp4',
                            'mimetype': 'video/mp4',
                            'url': 'https://media.example/clip.mp4',
                        },
                    ]
                },
            },
            api_base_url='http://tater.local:8501/v1',
        )

        files = tater_hydra.tater_hydra_artifact_files(parsed)

        self.assertEqual([item['type'] for item in files], ['image', 'audio', 'video'])
        self.assertEqual(
            files[0]['url'],
            '/api/v1/tater/artifacts/image-1?mimetype=image%2Fpng',
        )
        self.assertEqual(
            files[1]['url'],
            '/api/v1/tater/artifacts/audio-1?mimetype=audio%2Fmpeg',
        )
        self.assertEqual(files[2]['url'], 'https://media.example/clip.mp4')


class TaterHydraHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = {}
        self.artifact_requests = {}
        self.artifact_payloads = {
            'image-1': (b'\x89PNG\r\n\x1a\nimage', 'image/png'),
            'audio-1': (b'ID3audio', 'audio/mpeg'),
            'video-1': (b'\x00\x00\x00\x18ftypmp42video', 'video/mp4'),
            'file-1': (b'%PDF-file', 'application/pdf'),
        }

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

        async def artifact(request):
            file_id = request.match_info['file_id']
            self.artifact_requests[file_id] = {
                'authorization': request.headers.get('Authorization'),
                'user_id': request.headers.get('X-SpudLink-User-ID'),
                'user_name': request.headers.get('X-SpudLink-User'),
            }
            payload = self.artifact_payloads.get(file_id)
            if payload is None:
                return web.Response(status=404, text='Attachment not found or expired.')
            body, content_type = payload
            return web.Response(body=body, content_type=content_type)

        app = web.Application()
        app.router.add_post('/v1/chat/completions', completion)
        app.router.add_get('/api/spudlink/v1/files/{file_id}', artifact)
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

    async def test_persists_every_hydra_media_type_in_open_webui_storage(self):
        persisted = []

        async def connection():
            return self.api_base_url, 'secret-token', 'tater/hydra'

        async def upload(_request, **kwargs):
            body = kwargs['file_obj'].read()
            artifact_id = kwargs['artifact_id']
            persisted.append({**kwargs, 'body': body})
            return {
                'id': f'local-{artifact_id}',
                'type': kwargs['media_type'],
                'url': f'/api/v1/files/local-{artifact_id}/content',
                'name': kwargs['name'],
                'content_type': kwargs['mimetype'],
                'size': kwargs['size'],
            }

        result = {
            'artifacts': [
                {'id': 'image-1', 'type': 'image', 'name': '../potato.png', 'mimetype': 'image/png'},
                {'id': 'audio-1', 'type': 'audio', 'name': 'song.mp3', 'mimetype': 'audio/mpeg'},
                {'id': 'video-1', 'type': 'video', 'name': 'clip.mp4', 'mimetype': 'video/mp4'},
                {'id': 'file-1', 'type': 'file', 'name': 'notes.pdf', 'mimetype': 'application/pdf'},
            ]
        }
        user = SimpleNamespace(id='user-1', name='Ada', email='ada@example.test')
        metadata = {'chat_id': 'chat-1', 'message_id': 'message-1'}

        with (
            patch.object(tater_hydra, 'get_tater_hydra_connection', connection),
            patch.object(tater_hydra, '_upload_tater_hydra_artifact', upload),
        ):
            files = await tater_hydra.persist_tater_hydra_artifact_files(
                SimpleNamespace(),
                result,
                metadata,
                user,
            )

        self.assertEqual([item['type'] for item in files], ['image', 'audio', 'video', 'file'])
        self.assertEqual(
            [item['url'] for item in files],
            [
                '/api/v1/files/local-image-1/content',
                '/api/v1/files/local-audio-1/content',
                '/api/v1/files/local-video-1/content',
                '/api/v1/files/local-file-1/content',
            ],
        )
        self.assertEqual(persisted[0]['name'], 'potato.png')
        self.assertEqual([item['body'] for item in persisted], [value[0] for value in self.artifact_payloads.values()])
        self.assertEqual(persisted[0]['metadata'], metadata)
        for request_headers in self.artifact_requests.values():
            self.assertEqual(request_headers['authorization'], 'Bearer secret-token')
            self.assertEqual(request_headers['user_id'], 'user-1')
            self.assertEqual(request_headers['user_name'], 'Ada')

    async def test_failed_persistence_keeps_the_protected_proxy_fallback(self):
        async def connection():
            return self.api_base_url, 'secret-token', 'tater/hydra'

        result = {
            'artifacts': [
                {
                    'id': 'missing',
                    'type': 'image',
                    'name': 'missing.png',
                    'mimetype': 'image/png',
                    'url': f'{self.api_base_url.removesuffix("/v1")}/api/spudlink/v1/files/missing',
                }
            ]
        }

        with patch.object(tater_hydra, 'get_tater_hydra_connection', connection):
            files = await tater_hydra.persist_tater_hydra_artifact_files(
                SimpleNamespace(),
                result,
                {},
                SimpleNamespace(id='user-1', name='Ada', email='ada@example.test'),
            )

        self.assertEqual(
            files,
            [
                {
                    'type': 'image',
                    'url': '/api/v1/tater/artifacts/missing?mimetype=image%2Fpng',
                    'name': 'missing.png',
                    'content_type': 'image/png',
                }
            ],
        )


if __name__ == '__main__':
    unittest.main()
