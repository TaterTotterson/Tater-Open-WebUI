from __future__ import annotations

import unittest

from open_webui.local_terminal.tools import get_local_terminal_tools


class LocalTerminalToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_toolset_is_one_synchronous_terminal(self):
        tools, prompt = get_local_terminal_tools('user', 'chat')

        self.assertEqual(set(tools), {'terminal'})
        self.assertEqual(set(tools['terminal']['spec']['parameters']['properties']), {'command'})
        self.assertIn('Use terminal for every local action', prompt)
        self.assertIn('returns its output and exit status automatically', prompt)

        result = await tools['terminal']['callable']("printf 'terminal-result'")
        self.assertEqual(result['output'], 'terminal-result')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['status'], 'done')


if __name__ == '__main__':
    unittest.main()
