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
TATER_ROUTER_PATH = BACKEND_ROOT / 'routers' / 'tater.py'
AUDIO_ROUTER_PATH = BACKEND_ROOT / 'routers' / 'audio.py'
TATER_LINK_PATH = BACKEND_ROOT / 'utils' / 'tater_link.py'
MODELS_PATH = BACKEND_ROOT / 'utils' / 'models.py'
CALL_OVERLAY_PATH = (
    Path(__file__).parents[2]
    / 'src'
    / 'lib'
    / 'components'
    / 'chat'
    / 'MessageInput'
    / 'CallOverlay.svelte'
)
CHAT_COMPONENT_PATH = Path(__file__).parents[2] / 'src' / 'lib' / 'components' / 'chat' / 'Chat.svelte'
TATER_API_PATH = Path(__file__).parents[2] / 'src' / 'lib' / 'apis' / 'tater' / 'index.ts'
RESPONSE_MESSAGE_PATH = (
    Path(__file__).parents[2]
    / 'src'
    / 'lib'
    / 'components'
    / 'chat'
    / 'Messages'
    / 'ResponseMessage.svelte'
)
SETTINGS_MODAL_PATH = (
    Path(__file__).parents[2] / 'src' / 'lib' / 'components' / 'chat' / 'SettingsModal.svelte'
)


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
        self.assertIn('repeated_tool_call_plan_gap(tool_calls, history_records)', middleware_source)
        self.assertIn('pending_browser_launch_verification_call(', middleware_source)
        self.assertIn('exit code zero means the command ran', middleware_source)
        self.assertNotIn("missing_completion_fields.append('context')", middleware_source)
        self.assertIn("{'taterAgentContext': saved_agent_context}", middleware_source)
        self.assertIn('render_recent_chat_history', middleware_source)
        self.assertIn('You are the completion gate for a computer-using agent', middleware_source)
        self.assertIn("body['_tater_agent_response']", middleware_source)
        self.assertIn('request.state.tater_agent_stop_reason', middleware_source)
        self.assertIn('missing_browser_launch_evidence', middleware_source)
        self.assertIn('creating and launching a game plus checking current weather', middleware_source)

        main_source = MAIN_PATH.read_text(encoding='utf-8')
        self.assertIn("form_data.pop('_tater_agent_response', None)", main_source)

    def test_terminal_stays_live_and_hydra_dispatches_to_visible_background_tasks(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')
        task_source = TATER_TASKS_PATH.read_text(encoding='utf-8')
        subagent_source = SUBAGENTS_PATH.read_text(encoding='utf-8')
        tater_router_source = TATER_ROUTER_PATH.read_text(encoding='utf-8')

        self.assertIn('start_tater_task', middleware_source)
        self.assertIn('start_parallel_tater_tasks', middleware_source)
        self.assertIn('parallel_background_tasks_dispatched', middleware_source)
        self.assertIn('Terminal work always runs live in the current chat', middleware_source)
        self.assertIn('tool_calls_are_hydra_only(tool_calls)', middleware_source)
        self.assertIn('partition_parallel_tasks(parallel_tasks)', middleware_source)
        self.assertIn('fixed task-count limit', middleware_source.lower())
        self.assertIn("@router.post('/steer')", tater_router_source)
        self.assertIn('from open_webui.models.chats import Chats', tater_router_source)
        self.assertIn('enqueue_live_agent_message', tater_router_source)
        self.assertIn("'type': 'tater:steer:consumed'", middleware_source)
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

    def test_live_message_transport_failures_do_not_cancel_the_active_run(self):
        if not CHAT_COMPONENT_PATH.exists():
            self.skipTest('frontend source is not bundled in the production image')

        chat_source = CHAT_COMPONENT_PATH.read_text(encoding='utf-8')
        api_source = TATER_API_PATH.read_text(encoding='utf-8')

        self.assertIn('{ status: response.status }', api_source)
        self.assertIn('steeringStatus === 409', chat_source)
        self.assertIn('The run is still continuing', chat_source)
        self.assertIn('messageInput?.setText(restoredPrompt)', chat_source)

    def test_progress_updates_are_present_tense_and_evidence_driven(self):
        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')

        self.assertIn('naturalize_progress_update(message)', middleware_source)
        self.assertIn('never announce that work is about to start', middleware_source)
        self.assertIn('mention the useful finding that drives the next action', middleware_source)

    def test_live_chat_smoothly_reveals_and_follows_streamed_content(self):
        if not CHAT_COMPONENT_PATH.exists():
            self.skipTest('frontend source is not bundled in the production image')

        chat_source = CHAT_COMPONENT_PATH.read_text(encoding='utf-8')
        response_source = RESPONSE_MESSAGE_PATH.read_text(encoding='utf-8')

        self.assertIn("type === 'chat:message:delta' || type === 'message'", chat_source)
        self.assertIn('scrollFollowUntil = performance.now() + 1600', chat_source)
        self.assertIn('requestAnimationFrame(followIncomingContent)', chat_source)
        self.assertIn('let renderedContent = message.content', response_source)
        self.assertIn('requestAnimationFrame(animateRenderedContent)', response_source)
        self.assertIn('content={renderedContent}', response_source)
        self.assertIn("prefers-reduced-motion: reduce", response_source)

    def test_settings_modal_scrolls_within_every_viewport(self):
        if not SETTINGS_MODAL_PATH.exists():
            self.skipTest('frontend source is not bundled in the production image')

        settings_source = SETTINGS_MODAL_PATH.read_text(encoding='utf-8')

        self.assertIn('h-[calc(100dvh-2rem)]', settings_source)
        self.assertIn('lg:h-[calc(100dvh-4rem)]', settings_source)
        self.assertIn('max-h-[54rem] min-h-0', settings_source)
        self.assertIn('overflow-y-auto overscroll-contain scrollbar-hover', settings_source)

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
        self.assertIn('regular_chat_prompt', middleware_source)
        self.assertIn('regular_chat_scratch_path', middleware_source)
        self.assertIn("workspace_type = 'scratch'", folder_source)
        self.assertIn('regular_chat_scratch_path', tools_source)
        self.assertIn('local_terminal_runtime.set_cwd', tools_source)
        self.assertIn('folder_id=parent_chat.folder_id', task_source)

    def test_local_terminal_can_keep_and_preview_browser_apps(self):
        terminal_tools = (BACKEND_ROOT / 'local_terminal' / 'tools.py').read_text(encoding='utf-8')
        terminal_router = (BACKEND_ROOT / 'routers' / 'local_terminal.py').read_text(encoding='utf-8')

        self.assertIn("'background': {", terminal_tools)
        self.assertIn('timeout_seconds=None if background else 600', terminal_tools)
        self.assertIn("@router.get('/local/ports')", terminal_router)
        self.assertIn("@router.api_route('/local/proxy/{port}/{path:path}'", terminal_router)

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

    def test_tater_spudlink_is_the_single_model_and_speech_connection(self):
        tater_source = TATER_ROUTER_PATH.read_text(encoding='utf-8')
        audio_source = AUDIO_ROUTER_PATH.read_text(encoding='utf-8')
        link_source = TATER_LINK_PATH.read_text(encoding='utf-8')
        models_source = MODELS_PATH.read_text(encoding='utf-8')

        self.assertIn("'role': TATER_OPEN_WEBUI_CLIENT_ROLE", tater_source)
        self.assertIn("'tater.link.connected': True", tater_source)
        self.assertIn("'audio.stt.engine': 'tater'", tater_source)
        self.assertIn("'audio.tts.engine': 'tater'", tater_source)
        self.assertIn("'tater': _tts_tater", audio_source)
        self.assertIn("== 'tater'", audio_source)
        self.assertIn('/api/spudlink/v1/stt/transcribe', audio_source)
        self.assertIn('/api/spudlink/v1/tts/speech', audio_source)
        self.assertIn("form_data.stt.ENGINE != 'tater'", audio_source)
        self.assertIn("form_data.tts.ENGINE != 'tater'", audio_source)
        self.assertIn("TATER_OPEN_WEBUI_CLIENT_ROLE = 'tater_open_webui'", link_source)
        self.assertIn("headers['X-SpudLink-User-ID']", link_source)
        self.assertIn("@router.get('/identity'", tater_source)
        self.assertIn("@router.post('/identity'", tater_source)
        self.assertIn("@router.get('/artifacts/{file_id}')", tater_source)
        self.assertIn('tater_link_headers(token, user)', tater_source)
        self.assertIn("model.get('id') == base_model", models_source)
        self.assertNotIn("@router.post('/verify'", tater_source)

        middleware_source = MIDDLEWARE_PATH.read_text(encoding='utf-8')
        task_source = TATER_TASKS_PATH.read_text(encoding='utf-8')
        self.assertIn('await persist_tater_hydra_artifact_files(', middleware_source)
        self.assertIn("'files': copy.deepcopy(files)", task_source)
        if RESPONSE_MESSAGE_PATH.exists():
            response_source = RESPONSE_MESSAGE_PATH.read_text(encoding='utf-8')
            self.assertIn("['image', 'audio', 'video', 'file']", response_source)
            self.assertIn('<video', response_source)
            self.assertIn('<audio', response_source)

    def test_tater_voice_mode_uses_linked_tater_speech(self):
        if not CALL_OVERLAY_PATH.exists():
            self.skipTest('frontend source is not bundled in the production image')

        voice_mode_source = CALL_OVERLAY_PATH.read_text(encoding='utf-8')

        self.assertIn('transcribeAudio(', voice_mode_source)
        self.assertIn('synthesizeOpenAISpeech(', voice_mode_source)

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
