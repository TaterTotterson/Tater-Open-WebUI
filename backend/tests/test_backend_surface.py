from __future__ import annotations

import ast
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).parents[1] / 'open_webui'
MAIN_PATH = BACKEND_ROOT / 'main.py'
BUILTINS_PATH = BACKEND_ROOT / 'tools' / 'builtin.py'
TOOLS_PATH = BACKEND_ROOT / 'utils' / 'tools.py'
MIDDLEWARE_PATH = BACKEND_ROOT / 'utils' / 'middleware.py'
CONFIG_PATH = BACKEND_ROOT / 'config.py'


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
            '/api/v1/pipelines',
            "prefix='/ollama'",
        )

        for prefix in removed_prefixes:
            self.assertNotIn(prefix, source)

    def test_isolated_router_modules_are_deleted(self):
        removed_modules = ('analytics', 'calendar', 'evaluations', 'functions', 'notes', 'ollama', 'pipelines')

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

    def test_chat_middleware_tool_imports_exist(self):
        tools_tree = ast.parse(TOOLS_PATH.read_text(encoding='utf-8'))
        tool_definitions = {
            node.name for node in tools_tree.body if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        }
        middleware_tree = ast.parse(MIDDLEWARE_PATH.read_text(encoding='utf-8'))
        imported_names = {
            name.name
            for node in middleware_tree.body
            if isinstance(node, ast.ImportFrom) and node.module == 'open_webui.utils.tools'
            for name in node.names
        }

        self.assertLessEqual(imported_names, tool_definitions)

    def test_media_routers_remain_available(self):
        source = MAIN_PATH.read_text(encoding='utf-8')

        self.assertIn("prefix='/api/v1/audio'", source)
        self.assertIn("prefix='/api/v1/images'", source)
        self.assertTrue((BACKEND_ROOT / 'routers' / 'audio.py').exists())
        self.assertTrue((BACKEND_ROOT / 'routers' / 'images.py').exists())

    def test_general_ollama_provider_is_removed_but_rag_option_remains(self):
        config_source = CONFIG_PATH.read_text(encoding='utf-8')

        self.assertNotIn("'ollama.enable'", config_source)
        self.assertNotIn("'ollama.base_urls'", config_source)
        self.assertNotIn("'ollama.api_configs'", config_source)
        self.assertIn("'rag.ollama.base_url'", config_source)


if __name__ == '__main__':
    unittest.main()
