from __future__ import annotations

import unittest

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

        self.assertEqual(first['cwd'], '/tmp')
        self.assertEqual(second['cwd'], '/tmp')


if __name__ == '__main__':
    unittest.main()
