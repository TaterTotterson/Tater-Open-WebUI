from __future__ import annotations

import asyncio
import shlex
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_webui.local_terminal.runtime import LocalTerminalRuntime
from open_webui.local_terminal.tools import get_local_terminal_tools


class LocalTerminalToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_toolset_is_one_terminal_with_optional_background_mode(self):
        tools, prompt = get_local_terminal_tools('user', 'chat')

        self.assertEqual(set(tools), {'terminal'})
        self.assertEqual(
            set(tools['terminal']['spec']['parameters']['properties']),
            {'command', 'cwd', 'background'},
        )
        self.assertIn('Use terminal for every local action', prompt)
        self.assertIn('returns its output and exit status automatically', prompt)
        self.assertIn('Files panel\'s Ports section', prompt)

        result = await tools['terminal']['callable']("printf 'terminal-result'")
        self.assertEqual(result['output'], 'terminal-result')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['status'], 'done')

    async def test_optional_cwd_persists_for_later_calls(self):
        tools, _ = get_local_terminal_tools('cwd-user', 'cwd-chat')

        first = await tools['terminal']['callable']('pwd', cwd='/tmp')
        second = await tools['terminal']['callable']('pwd')

        self.assertEqual(first['cwd'], str(Path('/tmp').resolve()))
        self.assertEqual(second['cwd'], str(Path('/tmp').resolve()))

    async def test_managed_background_job_can_be_stopped_without_system_process_utilities(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LocalTerminalRuntime(Path(directory))
            with patch('open_webui.local_terminal.tools.local_terminal_runtime', runtime):
                tools, _ = get_local_terminal_tools('user', 'chat')
                terminal = tools['terminal']['callable']
                started = await terminal('sleep 30', background=True)
                process_id = started['id']
                try:
                    self.assertEqual(started['stop_command'], f'tater stop {process_id}')
                    _, prompt = get_local_terminal_tools('user', 'chat')
                    self.assertIn(process_id, prompt)

                    listed = await terminal('tater jobs')
                    self.assertEqual(listed['exit_code'], 0)
                    self.assertIn(f'{process_id}  running', listed['output'])

                    other_tools, _ = get_local_terminal_tools('other-user', 'chat')
                    denied = await other_tools['terminal']['callable'](f'tater stop {process_id}')
                    self.assertEqual(denied['exit_code'], 1)
                    self.assertEqual(runtime.get_process('user', 'chat', process_id).status, 'running')

                    stopped = await terminal(f'tater stop {process_id}')
                    self.assertEqual(stopped['exit_code'], 0)
                    self.assertIn('Status: killed', stopped['output'])
                    self.assertEqual(runtime.get_process('user', 'chat', process_id).status, 'killed')

                    again = await terminal(f'tater stop {process_id}')
                    self.assertIn('already finished', again['output'])
                    self.assertEqual(runtime.get_process('user', 'chat', process_id).status, 'killed')
                finally:
                    await runtime.kill_process('user', 'chat', process_id)

    async def test_stop_without_id_refuses_ambiguous_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = LocalTerminalRuntime(Path(directory))
            with patch('open_webui.local_terminal.tools.local_terminal_runtime', runtime):
                tools, _ = get_local_terminal_tools('user', 'chat')
                terminal = tools['terminal']['callable']
                first = await terminal('sleep 30', background=True)
                second = await terminal('sleep 30', background=True)
                try:
                    ambiguous = await terminal('tater stop')
                    self.assertEqual(ambiguous['exit_code'], 2)
                    self.assertIn('Multiple managed background processes', ambiguous['output'])
                    self.assertEqual(runtime.get_process('user', 'chat', first['id']).status, 'running')
                    self.assertEqual(runtime.get_process('user', 'chat', second['id']).status, 'running')
                finally:
                    await runtime.kill_process('user', 'chat', first['id'])
                    await runtime.kill_process('user', 'chat', second['id'])

    async def test_stopping_managed_http_server_closes_its_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            runtime = LocalTerminalRuntime(Path(directory))
            with patch('open_webui.local_terminal.tools.local_terminal_runtime', runtime):
                tools, _ = get_local_terminal_tools('user', 'chat')
                terminal = tools['terminal']['callable']
                started = await terminal(
                    f'{shlex.quote(sys.executable)} -m http.server {port} --bind 127.0.0.1',
                    background=True,
                )
                process_id = started['id']
                try:
                    connected = False
                    for _ in range(40):
                        try:
                            reader, writer = await asyncio.open_connection('127.0.0.1', port)
                            writer.close()
                            await writer.wait_closed()
                            connected = True
                            break
                        except OSError:
                            await asyncio.sleep(0.05)
                    self.assertTrue(connected, 'test HTTP server did not start')

                    stopped = await terminal('tater stop')
                    self.assertEqual(stopped['exit_code'], 0)
                    with self.assertRaises(OSError):
                        reader, writer = await asyncio.open_connection('127.0.0.1', port)
                        writer.close()
                        await writer.wait_closed()
                finally:
                    await runtime.kill_process('user', 'chat', process_id)


if __name__ == '__main__':
    unittest.main()
