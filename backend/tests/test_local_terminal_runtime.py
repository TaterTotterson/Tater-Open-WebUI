from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'local_terminal' / 'runtime.py'
SPEC = importlib.util.spec_from_file_location('local_terminal_runtime', MODULE_PATH)
assert SPEC and SPEC.loader
runtime_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime_module
SPEC.loader.exec_module(runtime_module)


class LocalTerminalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name)
        self.runtime = runtime_module.LocalTerminalRuntime(self.workspace)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_keeps_working_directories_separate_by_chat(self):
        first = self.workspace / 'first'
        second = self.workspace / 'second'
        first.mkdir()
        second.mkdir()

        self.runtime.set_cwd('user', 'chat-1', str(first))
        self.runtime.set_cwd('user', 'chat-2', str(second))

        self.assertEqual(self.runtime.get_cwd('user', 'chat-1'), first.resolve())
        self.assertEqual(self.runtime.get_cwd('user', 'chat-2'), second.resolve())

    async def test_runs_command_and_captures_output(self):
        result = await self.runtime.run_command(
            'user',
            'chat',
            "printf 'hello from terminal'",
        )

        self.assertEqual(result['status'], 'done')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['output'], 'hello from terminal')

    async def test_background_process_is_visible_and_can_be_cancelled(self):
        result = await self.runtime.run_command(
            'user',
            'chat',
            'sleep 30',
            background=True,
            timeout_seconds=60,
        )

        self.assertEqual(result['status'], 'running')
        process_id = result['id']
        self.assertEqual(self.runtime.list_processes('user', 'chat')[0]['id'], process_id)

        killed = await self.runtime.kill_process('user', 'chat', process_id)
        self.assertEqual(killed['status'], 'killed')

    async def test_background_output_can_be_read_incrementally(self):
        result = await self.runtime.run_command(
            'user',
            'chat',
            "printf first; sleep 0.1; printf second",
            background=True,
            timeout_seconds=10,
        )
        record = self.runtime.get_process('user', 'chat', result['id'])
        await record.done.wait()

        initial = record.output_since(0)
        follow_up = record.output_since(len('first'))

        self.assertEqual(''.join(chunk['data'] for chunk in initial['output']), 'firstsecond')
        self.assertEqual(''.join(chunk['data'] for chunk in follow_up['output']), 'second')
        self.assertEqual(follow_up['next_offset'], len('firstsecond'))

        bounded = record.output_since(0, max_chars=len('second'))
        self.assertEqual(''.join(chunk['data'] for chunk in bounded['output']), 'second')
        self.assertTrue(bounded['truncated'])

    async def test_times_out_foreground_process(self):
        result = await self.runtime.run_command(
            'user',
            'chat',
            'sleep 10',
            timeout_seconds=1,
        )

        self.assertTrue(result['timed_out'])
        self.assertEqual(result['status'], 'killed')

    def test_lists_listening_tcp_ports(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            port = server.getsockname()[1]

            ports = self.runtime.list_listening_ports(include_current_process=True)

        self.assertIn(port, {item['port'] for item in ports})

    async def test_cancelling_foreground_wait_terminates_process(self):
        command = asyncio.create_task(
            self.runtime.run_command(
                'user',
                'cancel-chat',
                'sleep 30',
                timeout_seconds=60,
            )
        )
        await asyncio.sleep(0.1)
        command.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await command

        processes = self.runtime.list_processes('user', 'cancel-chat')
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0]['status'], 'killed')

    def test_file_read_write_replace_list_and_search(self):
        written = self.runtime.write_file(
            'user',
            'chat',
            'src/example.txt',
            'alpha\nbeta\n',
        )
        self.assertTrue(Path(written['path']).is_file())

        read = self.runtime.read_file('user', 'chat', 'src/example.txt', start_line=2, end_line=2)
        self.assertEqual(read['content'], 'beta\n')

        replaced = self.runtime.replace_file_content(
            'user',
            'chat',
            'src/example.txt',
            'beta',
            'gamma',
        )
        self.assertEqual(replaced['replacements'], 1)

        listing = self.runtime.list_files('user', 'chat', 'src')
        self.assertEqual([entry['name'] for entry in listing['entries']], ['example.txt'])

        matches = self.runtime.search_files('user', 'chat', 'gamma', path='src')
        self.assertEqual(matches['results'][0]['line'], 2)
        self.assertEqual(matches['results'][0]['relative_path'], 'example.txt')


if __name__ == '__main__':
    unittest.main()
