from __future__ import annotations

import unittest

from open_webui.local_terminal.tools import get_local_terminal_tools


class LocalTerminalToolTests(unittest.TestCase):
    def test_model_toolset_is_terminal_first(self):
        tools, prompt = get_local_terminal_tools('user', 'chat')

        self.assertEqual(
            set(tools),
            {
                'run_command',
                'verify_command',
                'list_processes',
                'read_process_output',
                'kill_process',
                'display_file',
            },
        )
        self.assertIn('Use run_command for all local inspection and changes', prompt)
        self.assertIn('ls', prompt)


if __name__ == '__main__':
    unittest.main()
