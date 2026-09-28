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
OPENAI_ROUTER_PATH = BACKEND_ROOT / 'routers' / 'openai.py'
CHAT_UTILS_PATH = BACKEND_ROOT / 'utils' / 'chat.py'
DOCUMENT_PROCESSING_PATH = BACKEND_ROOT / 'utils' / 'document_processing.py'
TATER_TASKS_PATH = BACKEND_ROOT / 'utils' / 'tater_tasks.py'
TATER_RUN_LEDGER_PATH = BACKEND_ROOT / 'utils' / 'tater_run_ledger.py'
TATER_PROJECTS_PATH = BACKEND_ROOT / 'utils' / 'tater_projects.py'
SUBAGENTS_PATH = BACKEND_ROOT / 'utils' / 'subagents.py'
FOLDERS_ROUTER_PATH = BACKEND_ROOT / 'routers' / 'folders.py'


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
            '/api/v1/retrieval',
            '/api/v1/knowledge',
            '/api/v1/memories',
            '/api/embeddings',
            '/api/v1/embeddings',
            "prefix='/ollama'",
        )

        for prefix in removed_prefixes:
            self.assertNotIn(prefix, source)

    def test_isolated_router_modules_are_deleted(self):
        removed_modules = (
            'analytics',
            'calendar',
            'evaluations',
            'functions',
            'knowledge',
            'memories',
            'notes',
            'ollama',
            'pipelines',
            'retrieval',
        )

        for module in removed_modules:
            self.assertFalse((BACKEND_ROOT / 'routers' / f'{module}.py').exists())

        self.assertFalse((BACKEND_ROOT / 'utils' / 'calendar.py').exists())
        self.assertFalse((BACKEND_ROOT / 'utils' / 'embeddings.py').exists())
        self.assertFalse((BACKEND_ROOT / 'utils' / 'memory.py').exists())
        self.assertFalse((BACKEND_ROOT / 'tools' / 'knowledge_fs.py').exists())

    def test_inherited_builtin_tools_are_deleted(self):
        self.assertFalse(BUILTINS_PATH.exists())

        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')
        self.assertNotIn('get_builtin_tools', middleware_source)
        self.assertNotIn('connect_mcp_server', middleware_source)
        self.assertIn('Tater Open WebUI intentionally exposes only terminal and tater_hydra', middleware_source)

    def test_legacy_tool_results_are_handed_to_the_final_answer(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')

        self.assertIn("legacy_tool_prompts.append(system_prompt)", middleware_source)
        self.assertIn("tool_system_prompt='\\n\\n'.join(legacy_tool_prompts)", middleware_source)
        self.assertIn('The following tool calls have already finished for the current request', middleware_source)
        self.assertIn('Do not emit tool-call markup', middleware_source)

    def test_legacy_agent_can_stream_progress_and_requires_completion_answer(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')

        self.assertIn("'type': 'message'", middleware_source)
        self.assertIn('A progress update does not complete the task', middleware_source)
        self.assertIn('simple read-only question, use the minimum number of terminal calls', middleware_source)
        self.assertIn('TATER_AGENT_PLAN_RETRY_LIMIT + 1', middleware_source)
        self.assertIn('tool_plan_retry_instruction', middleware_source)
        self.assertIn('The task cannot be marked complete without final_answer', middleware_source)
        self.assertIn('The context object may be empty', middleware_source)
        self.assertIn('simple_read_only_terminal_history', middleware_source)
        self.assertNotIn("missing_completion_fields.append('context')", middleware_source)
        self.assertIn("{'taterAgentContext': saved_agent_context}", middleware_source)
        self.assertIn('render_recent_chat_history', middleware_source)
        self.assertIn('You are the completion gate for a computer-using agent', middleware_source)
        self.assertIn("body['_tater_agent_response']", middleware_source)
        self.assertIn('request.state.tater_agent_stop_reason', middleware_source)

        main_source = MAIN_PATH.read_text(encoding='utf-8')
        self.assertIn("form_data.pop('_tater_agent_response', None)", main_source)

    def test_terminal_and_hydra_work_dispatch_to_visible_background_tasks(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')
        task_source = TATER_TASKS_PATH.read_text(encoding='utf-8')
        subagent_source = SUBAGENTS_PATH.read_text(encoding='utf-8')

        self.assertIn('start_tater_task', middleware_source)
        self.assertIn('start_parallel_tater_tasks', middleware_source)
        self.assertIn('parallel_background_tasks_dispatched', middleware_source)
        self.assertIn("call.get('name') == 'tater_hydra'", task_source)
        self.assertNotIn('TATER_TASK_MAX_CONCURRENT_PER_USER', task_source)
        self.assertIn("'type': TATER_TASK_TYPE", task_source)
        self.assertIn("'done': True", task_source)
        self.assertIn("'type': 'chat:reload'", task_source)
        self.assertIn("'type': 'chat:list'", task_source)
        self.assertIn('parent.current_message_id = assistant_message_id', task_source)
        self.assertIn("if kind == 'tater_task':", subagent_source)
        self.assertIn('background_task_result_answer', subagent_source)
        self.assertIn('Posting the result to the originating chat', task_source)
        self.assertIn("completed_context.get('execution_summary')", task_source)
        self.assertIn("getattr(child_request.state, 'tater_agent_stop_reason'", task_source)
        self.assertIn('tater_task_awareness', middleware_source)
        self.assertIn('record_tater_task_progress', middleware_source)
        self.assertIn("chat_id=str(metadata.get('chat_id') or '') or None", middleware_source)
        self.assertIn("'progress_events':", task_source)
        self.assertIn('handoff_context', task_source)
        ast.parse(task_source)
        ast.parse(subagent_source)

    def test_agent_runs_have_a_persistent_structured_ledger(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')
        task_source = TATER_TASKS_PATH.read_text(encoding='utf-8')
        ledger_source = TATER_RUN_LEDGER_PATH.read_text(encoding='utf-8')

        self.assertIn("'agent_run_started'", middleware_source)
        self.assertIn("'planner_attempt_finished'", middleware_source)
        self.assertIn("'tool_finished'", middleware_source)
        self.assertIn("'completion_review_finished'", middleware_source)
        self.assertIn("'parent_delivery_finished'", task_source)
        self.assertIn("'task_finished'", task_source)
        self.assertIn('TATER_RUN_LEDGER_PATH', ledger_source)
        self.assertIn('[redacted]', ledger_source)

    def test_projects_are_filesystem_backed_and_inherited_by_tasks(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')
        tools_source = TOOLS_PATH.read_text(encoding='utf-8')
        task_source = TATER_TASKS_PATH.read_text(encoding='utf-8')
        folder_source = FOLDERS_ROUTER_PATH.read_text(encoding='utf-8')
        project_source = TATER_PROJECTS_PATH.read_text(encoding='utf-8')

        self.assertIn('sync_user_projects', folder_source)
        self.assertIn("or '/projects'", project_source)
        self.assertIn('Shared project working context', middleware_source)
        self.assertIn('local_terminal_runtime.set_cwd', tools_source)
        self.assertIn('folder_id=parent_chat.folder_id', task_source)

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

    def test_media_and_file_routers_remain_available(self):
        source = MAIN_PATH.read_text(encoding='utf-8')

        self.assertIn("prefix='/api/v1/audio'", source)
        self.assertIn("prefix='/api/v1/files'", source)
        self.assertIn("prefix='/api/v1/images'", source)
        self.assertTrue((BACKEND_ROOT / 'routers' / 'audio.py').exists())
        self.assertTrue((BACKEND_ROOT / 'routers' / 'files.py').exists())
        self.assertTrue((BACKEND_ROOT / 'routers' / 'images.py').exists())

    def test_general_ollama_and_retrieval_provider_options_are_removed(self):
        config_source = CONFIG_PATH.read_text(encoding='utf-8')

        self.assertNotIn("'ollama.enable'", config_source)
        self.assertNotIn("'ollama.base_urls'", config_source)
        self.assertNotIn("'ollama.api_configs'", config_source)
        self.assertNotIn("'rag.ollama.base_url'", config_source)
        self.assertNotIn("'rag.embedding_model'", config_source)
        self.assertNotIn("'web.search.enable'", config_source)

    def test_file_attachments_use_stored_text_without_vector_retrieval(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')

        self.assertTrue(DOCUMENT_PROCESSING_PATH.exists())
        self.assertIn("(file.data or {}).get('content', '')", middleware_source)
        self.assertNotIn('EMBEDDING_FUNCTION', middleware_source)
        self.assertNotIn('get_sources_from_items', middleware_source)

    def test_vector_and_web_search_implementations_are_deleted(self):
        retrieval_root = BACKEND_ROOT / 'retrieval'

        for directory in ('models', 'vector', 'web'):
            self.assertFalse(any((retrieval_root / directory).rglob('*.py')))

    def test_direct_provider_and_arena_runtime_are_removed(self):
        config_source = CONFIG_PATH.read_text(encoding='utf-8')
        main_source = MAIN_PATH.read_text(encoding='utf-8')
        chat_source = CHAT_UTILS_PATH.read_text(encoding='utf-8')

        for removed_key in (
            "'direct.enable'",
            "'direct.integrations.enable'",
            "'evaluation.arena.enable'",
            "'evaluation.arena.models'",
        ):
            self.assertNotIn(removed_key, config_source)

        self.assertNotIn('request.state.direct', main_source)
        self.assertNotIn('generate_direct_chat_completion', chat_source)
        self.assertNotIn("owned_by') == 'arena'", chat_source)

    def test_generic_provider_management_routes_are_removed(self):
        source = OPENAI_ROUTER_PATH.read_text(encoding='utf-8')

        for route in (
            "@router.get('/config')",
            "@router.post('/config/update')",
            "@router.post('/verify')",
            "@router.get('/models/{url_idx}')",
            "@router.get('/models/{url_idx}/catalog')",
            "@router.post('/models/{url_idx}/download')",
            "@router.post('/models/{url_idx}/load')",
            "@router.post('/models/{url_idx}/unload')",
        ):
            self.assertNotIn(route, source)


if __name__ == '__main__':
    unittest.main()
