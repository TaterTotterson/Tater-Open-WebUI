from __future__ import annotations

import ast
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).parents[1] / 'open_webui'
MAIN_PATH = BACKEND_ROOT / 'main.py'
BUILTINS_PATH = BACKEND_ROOT / 'tools' / 'builtin.py'


class BackendSurfaceTests(unittest.TestCase):
    def test_removed_feature_routers_are_not_registered(self):
        source = MAIN_PATH.read_text(encoding='utf-8')
        removed_prefixes = (
            '/api/v1/analytics',
            '/api/v1/automations',
            '/api/v1/calendars',
            '/api/v1/channels',
            '/api/v1/evaluations',
            '/api/v1/functions',
            '/api/v1/notes',
        )

        for prefix in removed_prefixes:
            self.assertNotIn(prefix, source)

    def test_isolated_router_modules_are_deleted(self):
        removed_modules = ('analytics', 'calendar', 'evaluations', 'functions', 'notes')

        for module in removed_modules:
            self.assertFalse((BACKEND_ROOT / 'routers' / f'{module}.py').exists())

        self.assertFalse((BACKEND_ROOT / 'utils' / 'calendar.py').exists())

    def test_builtin_tool_surface_is_agent_core_only(self):
        tree = ast.parse(BUILTINS_PATH.read_text(encoding='utf-8'))
        async_functions = {node.name for node in tree.body if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))}

        self.assertEqual(
            async_functions,
            {'ask_user', '_task_summary', '_emit_tasks', 'create_tasks', 'update_task'},
        )

    def test_main_still_parses_after_router_pruning(self):
        ast.parse(MAIN_PATH.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
