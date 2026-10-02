from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'utils' / 'tater_agent.py'
SPEC = importlib.util.spec_from_file_location('tater_agent', MODULE_PATH)
assert SPEC and SPEC.loader
tater_agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tater_agent)


class TaterAgentTests(unittest.TestCase):
    def test_plain_acknowledgement_without_pending_work_stays_in_chat(self):
        self.assertIsNone(
            tater_agent.task_dispatch_request(
                [
                    {'role': 'assistant', 'content': "You're welcome."},
                    {'role': 'user', 'content': 'Ok'},
                ]
            )
        )

    def test_confirmation_inherits_pending_task_request(self):
        request = tater_agent.task_dispatch_request(
            [
                {'role': 'user', 'content': 'Is the Tater clone in the home folder?'},
                {'role': 'assistant', 'content': 'I will search the home folder now.'},
                {'role': 'user', 'content': 'Ok'},
            ]
        )

        self.assertEqual(request, 'Is the Tater clone in the home folder?')

    def test_confirmation_understands_pending_action_word_forms(self):
        request = tater_agent.task_dispatch_request(
            [
                {'role': 'user', 'content': 'Is it in the home folder we cloned it somewhere?'},
                {
                    'role': 'assistant',
                    'content': 'I am now proceeding with the actual task: searching the home folder.',
                },
                {'role': 'user', 'content': 'Ok'},
            ]
        )

        self.assertEqual(request, 'Is it in the home folder we cloned it somewhere?')

    def test_task_status_question_stays_in_chat(self):
        for question in (
            'What happened to the task?',
            'What are you doing?',
            "What's your progress?",
            "How's it going?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(
                    tater_agent.task_dispatch_request(
                        [
                            {'role': 'assistant', 'content': 'The search is running in the background.'},
                            {'role': 'user', 'content': question},
                        ]
                    )
                )

    def test_explicit_work_after_status_phrase_can_dispatch(self):
        self.assertEqual(
            tater_agent.task_dispatch_request(
                [{'role': 'user', 'content': 'Find the task logs and show me the failure.'}]
            ),
            'Find the task logs and show me the failure.',
        )

    def test_terminal_activity_shows_command_and_redacts_secrets(self):
        status = tater_agent.tool_activity_status(
            'terminal',
            {
                'command': 'API_KEY=very-secret curl --token also-secret https://example.test',
                'cwd': '/workspace/app',
            },
            done=False,
        )

        self.assertEqual(status['description'], 'Running terminal command')
        self.assertIn('/workspace/app$', status['detail'])
        self.assertIn('API_KEY=[redacted]', status['detail'])
        self.assertIn('--token [redacted]', status['detail'])
        self.assertNotIn('very-secret', status['detail'])
        self.assertNotIn('also-secret', status['detail'])

    def test_hydra_activity_summarizes_request(self):
        status = tater_agent.tool_activity_status(
            'tater_hydra',
            {'request': 'Turn on the kitchen lights and set them to 40 percent.'},
            done=True,
        )

        self.assertEqual(status['description'], 'Hydra call finished')
        self.assertEqual(status['detail'], 'Turn on the kitchen lights and set them to 40 percent.')

    def test_parses_fenced_tool_plan(self):
        calls = tater_agent.parse_tool_plan(
            '```json\n{"tool_calls":[{"name":"terminal","parameters":{"command":"pwd"}}]}\n```'
        )

        self.assertEqual(calls, [{'name': 'terminal', 'parameters': {'command': 'pwd'}}])

    def test_parses_empty_plan(self):
        self.assertEqual(tater_agent.parse_tool_plan('{"tool_calls":[]}'), [])

    def test_infers_terminal_name_from_flat_command_call(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"tool_calls":[{"command":"ls -R web_version","cwd":"/projects/game"}]}'
        )

        self.assertEqual(
            plan['tool_calls'],
            [
                {
                    'name': 'terminal',
                    'parameters': {
                        'command': 'ls -R web_version',
                        'cwd': '/projects/game',
                    },
                }
            ],
        )

    def test_parses_progress_and_final_answer(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"progress":"I’ll inspect the project first.","tool_calls":[],"final_answer":"Done."}'
        )

        self.assertEqual(plan['progress'], 'I’ll inspect the project first.')
        self.assertEqual(plan['task_title'], '')
        self.assertEqual(plan['tool_calls'], [])
        self.assertEqual(plan['final_answer'], 'Done.')
        self.assertEqual(plan['context'], {})

    def test_naturalizes_repetitive_future_progress_announcements(self):
        examples = {
            'I will start by exploring the Hydra code.': 'Exploring the Hydra code.',
            'I’ll inspect the execution loop next.': 'Inspecting the execution loop next.',
            'I am analyzing the call sites.': 'Analyzing the call sites.',
            'Let me run the focused tests.': 'Running the focused tests.',
            'The loop is in hydra/__init__.py; tracing its caller now.': (
                'The loop is in hydra/__init__.py; tracing its caller now.'
            ),
        }

        for original, expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(tater_agent.naturalize_progress_update(original), expected)

    def test_live_steering_acknowledgement_keeps_the_run_active(self):
        self.assertEqual(
            tater_agent.live_steering_acknowledgement(['thanks']),
            'You’re welcome—the current work is still moving along.',
        )
        self.assertEqual(
            tater_agent.live_steering_acknowledgement(['also add a regression test']),
            'Got it—adding that to the work already in progress.',
        )

    def test_parses_concise_task_title(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"task_title":"Inspect Face ID Code","progress":"I’ll locate the implementation.",'
            '"tool_calls":[{"name":"terminal","parameters":{"command":"find . -iname \'*face*\'"}}],'
            '"final_answer":"","context":{}}'
        )

        self.assertEqual(plan['task_title'], 'Inspect Face ID Code')

    def test_parses_independent_parallel_tasks(self):
        plan = tater_agent.parse_tool_plan_response(
            json.dumps(
                {
                    'task_title': '',
                    'progress': 'I’ll handle these independent checks at the same time.',
                    'tool_calls': [],
                    'parallel_tasks': [
                        {
                            'task_title': 'List current directory',
                            'task_prompt': 'List the current directory and summarize it.',
                            'progress': 'I’ll inspect the current directory.',
                            'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'ls'}}],
                            'context': {},
                        },
                        {
                            'task_title': 'Count Tea files',
                            'task_prompt': 'Count the files in the tea folder.',
                            'progress': 'I’ll count the files in the tea folder.',
                            'tool_calls': [
                                {'name': 'terminal', 'parameters': {'command': 'find tea -type f | wc -l'}}
                            ],
                            'context': {},
                        },
                        {
                            'task_title': 'Check today weather',
                            'task_prompt': 'Check today’s weather.',
                            'progress': 'I’ll check today’s weather.',
                            'tool_calls': [
                                {'name': 'tater_hydra', 'parameters': {'request': 'Check today’s weather'}}
                            ],
                            'context': {},
                        },
                    ],
                    'final_answer': '',
                    'context': {},
                }
            )
        )

        self.assertEqual(plan['tool_calls'], [])
        self.assertEqual(len(plan['parallel_tasks']), 3)
        self.assertEqual(plan['parallel_tasks'][1]['task_title'], 'Count Tea files')

    def test_parallel_tasks_are_first_step_only(self):
        payload = {
            'tool_calls': [],
            'parallel_tasks': [
                {
                    'task_title': 'Check files',
                    'task_prompt': 'Check the files.',
                    'progress': 'I’ll check the files.',
                    'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'ls'}}],
                    'context': {},
                }
            ],
            'final_answer': '',
            'context': {},
        }

        with self.assertRaisesRegex(ValueError, 'first planning step'):
            tater_agent.parse_tool_plan_response(
                json.dumps(payload),
                allow_parallel_tasks=False,
            )

    def test_parallel_task_count_has_no_fixed_cap(self):
        payload = {
            'tool_calls': [],
            'parallel_tasks': [
                {
                    'task_title': f'Independent check {index}',
                    'task_prompt': f'Perform independent check {index}.',
                    'progress': f'I’ll perform independent check {index}.',
                    'tool_calls': [{'name': 'terminal', 'parameters': {'command': f'echo {index}'}}],
                    'context': {},
                }
                for index in range(8)
            ],
            'final_answer': '',
            'context': {},
        }

        plan = tater_agent.parse_tool_plan_response(json.dumps(payload))

        self.assertEqual(len(plan['parallel_tasks']), 8)

    def test_parallel_tasks_cannot_mix_with_top_level_calls(self):
        payload = {
            'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'pwd'}}],
            'parallel_tasks': [
                {
                    'task_title': 'Check files',
                    'task_prompt': 'Check the files.',
                    'progress': 'I’ll check the files.',
                    'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'ls'}}],
                    'context': {},
                }
            ],
            'final_answer': '',
            'context': {},
        }

        with self.assertRaisesRegex(ValueError, 'either top-level tool_calls or parallel_tasks'):
            tater_agent.parse_tool_plan_response(json.dumps(payload))

    def test_partitions_terminal_and_multiple_hydra_tasks(self):
        tasks = [
            {
                'task_title': 'Inspect code',
                'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'rg TODO .'}}],
            },
            {
                'task_title': 'Check weather',
                'tool_calls': [{'name': 'tater_hydra', 'parameters': {'request': 'Check weather'}}],
            },
            {
                'task_title': 'Set lights',
                'tool_calls': [{'name': 'tater_hydra', 'parameters': {'request': 'Set lights'}}],
            },
        ]

        terminal, hydra, mixed = tater_agent.partition_parallel_tasks(tasks)

        self.assertEqual([task['task_title'] for task in terminal], ['Inspect code'])
        self.assertEqual([task['task_title'] for task in hydra], ['Check weather', 'Set lights'])
        self.assertEqual(mixed, [])

    def test_rejects_mixed_terminal_and_hydra_execution_lane(self):
        gap = tater_agent.execution_routing_plan_gap(
            [
                {'name': 'terminal', 'parameters': {'command': 'pwd'}},
                {'name': 'tater_hydra', 'parameters': {'request': 'Check weather'}},
            ],
            [],
        )

        self.assertIn('different execution lanes', gap)

    def test_recognizes_hydra_only_calls(self):
        self.assertTrue(
            tater_agent.tool_calls_are_hydra_only(
                [
                    {'name': 'tater_hydra', 'parameters': {'request': 'Check weather'}},
                    {'name': 'tater_hydra', 'parameters': {'request': 'Check lights'}},
                ]
            )
        )
        self.assertFalse(
            tater_agent.tool_calls_are_hydra_only(
                [{'name': 'terminal', 'parameters': {'command': 'pwd'}}]
            )
        )

    def test_normalizes_planner_task_title(self):
        self.assertEqual(
            tater_agent.normalize_task_title('  inspect   Face ID implementation  ', 'ignored'),
            'Inspect Face ID implementation',
        )
        self.assertEqual(
            tater_agent.normalize_task_title('Perfect, what do you think of this project?', 'ignored'),
            'Review this project',
        )

    def test_task_title_fallback_cleans_request_language(self):
        self.assertEqual(
            tater_agent.normalize_task_title('', 'Can you inspect the login implementation?'),
            'Inspect the login implementation',
        )
        self.assertEqual(
            tater_agent.normalize_task_title('', 'Is the Tater clone in the home folder?'),
            'Check Tater clone in the home folder',
        )
        self.assertEqual(
            tater_agent.normalize_task_title('', 'Perfect, what do you think of this project?'),
            'Review this project',
        )

    def test_future_work_answer_becomes_progress(self):
        answer = (
            'To give you a meaningful opinion, I need to inspect the codebase. '
            'I’ll start by reading the README. One moment while I scan the files.'
        )

        self.assertEqual(tater_agent.continuation_progress_update(answer), answer)
        self.assertEqual(
            tater_agent.continuation_progress_update('I’ll inspect the project now.'),
            'I’ll inspect the project now.',
        )

    def test_completed_answer_is_not_treated_as_progress(self):
        answer = 'I inspected the codebase and found a clean event-driven design. Here is my assessment.'

        self.assertEqual(tater_agent.continuation_progress_update(answer), '')

    def test_background_task_result_is_rendered_directly(self):
        content = (
            '[BACKGROUND TASK FINISHED - task-123]\n'
            'Task: Review this project\n'
            'Status: completed\n'
            'Task view: /tasks/task-123\n'
            '--- RESULT ---\n'
            'The project has a clear architecture and focused scope.\n\n'
            '--- FINAL WORKING CONTEXT ---\n'
            "{'objective': 'Review the project'}"
        )

        self.assertEqual(
            tater_agent.background_task_result_answer(content),
            '**Review this project completed.**\n\n'
            'The project has a clear architecture and focused scope.',
        )

    def test_failed_background_task_result_is_explicit(self):
        content = (
            'Task: Run project tests\nStatus: failed\n--- RESULT ---\n'
            'The test runner could not find the required dependency.'
        )

        self.assertEqual(
            tater_agent.background_task_result_answer(content),
            '**Run project tests did not complete successfully.**\n\n'
            'The test runner could not find the required dependency.',
        )

    def test_single_hydra_request_becomes_self_contained_task_prompt(self):
        self.assertEqual(
            tater_agent.resolved_background_task_prompt(
                'try now i gave you access',
                {
                    'tool_calls': [
                        {
                            'name': 'tater_hydra',
                            'parameters': {'request': 'What is the current weather?'},
                        }
                    ]
                },
            ),
            'What is the current weather?',
        )

    def test_non_hydra_task_keeps_original_prompt(self):
        self.assertEqual(
            tater_agent.resolved_background_task_prompt(
                'Inspect the repository',
                {'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'git status'}}]},
            ),
            'Inspect the repository',
        )

    def test_completed_hydra_response_is_the_delegation_answer(self):
        result = json.dumps(
            {
                'status': 'completed',
                'model': 'tater/hydra',
                'response': 'It is partly cloudy and 86.7°F outside.',
                'usage': {'total_tokens': 100},
            }
        )

        self.assertEqual(
            tater_agent.completed_hydra_delegation_answer(
                [
                    {
                        'tool': 'tater_hydra',
                        'status': 'completed',
                        'parameters': {'request': 'What is the current weather?'},
                        'result': result,
                    }
                ]
            ),
            'It is partly cloudy and 86.7°F outside.',
        )

    def test_media_only_hydra_result_finishes_without_repeating_generation(self):
        result = json.dumps(
            {
                'status': 'completed',
                'model': 'tater/hydra',
                'response': '',
                'artifacts': [
                    {
                        'id': 'image-1',
                        'type': 'image',
                        'url': '/api/v1/tater/artifacts/image-1',
                    }
                ],
            }
        )

        self.assertEqual(
            tater_agent.completed_hydra_delegation_answer(
                [
                    {
                        'tool': 'tater_hydra',
                        'status': 'completed',
                        'parameters': {'request': 'Generate a funny potato image'},
                        'result': result,
                    }
                ]
            ),
            'Tater Hydra generated 1 image artifact. The generated media is attached.',
        )

    def test_failed_hydra_call_is_not_adopted_as_a_completed_answer(self):
        self.assertEqual(
            tater_agent.completed_hydra_delegation_answer(
                [
                    {
                        'tool': 'tater_hydra',
                        'status': 'failed',
                        'result': {'error': 'connection failed'},
                    }
                ]
            ),
            '',
        )

    def test_parses_persistent_context_with_final_answer(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"progress":"","tool_calls":[],"final_answer":"Done.",'
            '"context":{"objective":"Fix login","files_changed":["auth.py"]}}'
        )

        self.assertEqual(plan['context']['objective'], 'Fix login')
        self.assertEqual(plan['context']['files_changed'], ['auth.py'])

    def test_accepts_plain_final_answer_after_tool_work(self):
        plan = tater_agent.parse_tool_plan_response(
            'The directory contains README.md and src/.',
            allow_plain_final_answer=True,
        )

        self.assertEqual(plan['tool_calls'], [])
        self.assertEqual(plan['final_answer'], 'The directory contains README.md and src/.')
        self.assertEqual(plan['context'], {})

    def test_plain_final_answer_fallback_rejects_malformed_plan(self):
        with self.assertRaisesRegex(ValueError, 'No tool-plan JSON object found'):
            tater_agent.parse_tool_plan_response(
                '{"tool_calls": [',
                allow_plain_final_answer=True,
            )

    def test_accepts_context_while_tools_are_requested(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"progress":"","tool_calls":[{"name":"terminal","parameters":{"command":"pwd"}}],'
            '"final_answer":"","context":{"cwd":"/workspace"}}'
        )

        self.assertEqual(plan['tool_calls'][0]['parameters']['command'], 'pwd')
        self.assertEqual(plan['context']['cwd'], '/workspace')

    def test_parses_model_native_terminal_call_markup(self):
        plan = tater_agent.parse_tool_plan_response(
            '<|tool_call>call:terminal{command:<|"|>grep -rnE "Hydra|hydra" . | head<|"|>}<tool_call|>'
        )

        self.assertEqual(plan['tool_calls'][0]['name'], 'terminal')
        self.assertEqual(plan['tool_calls'][0]['parameters']['command'], 'grep -rnE "Hydra|hydra" . | head')

    def test_repairs_literal_newline_inside_final_answer_json(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"tool_calls":[],"final_answer":"First line\nSecond line","context":{}}'
        )

        self.assertEqual(plan['final_answer'], 'First line\nSecond line')

    def test_recovers_final_answer_with_unescaped_prose_quotes(self):
        plan = tater_agent.parse_tool_plan_response(
            '{"tool_calls":[],"final_answer":"Hydra handles "Minos" results.\nDone.",'
            '"context":{"objective":"Explain Hydra"}}'
        )

        self.assertEqual(plan['tool_calls'], [])
        self.assertEqual(plan['final_answer'], 'Hydra handles "Minos" results.\nDone.')

    def test_rejects_tool_markup_in_progress(self):
        with self.assertRaisesRegex(ValueError, 'must not contain tool-call markup'):
            tater_agent.parse_tool_plan_response(
                '{"progress":"<|tool_call>call:terminal:{}","tool_calls":[],"final_answer":""}'
            )

    def test_rejects_final_answer_while_more_tools_are_requested(self):
        with self.assertRaisesRegex(ValueError, 'must be empty'):
            tater_agent.parse_tool_plan_response(
                '{"progress":"","tool_calls":[{"name":"terminal","parameters":{"command":"pwd"}}],'
                '"final_answer":"Done."}'
            )

    def test_parses_completion_review(self):
        self.assertEqual(
            tater_agent.parse_completion_review('{"complete":false,"reason":"face_id is still uninspected"}'),
            {'complete': False, 'reason': 'face_id is still uninspected'},
        )

    def test_browser_launch_requires_live_server_http_probe_and_port(self):
        request = 'Make a funny woodchuck game and launch it so we can play it.'
        self.assertTrue(tater_agent.requires_live_browser_delivery(request))
        self.assertIn('background server', tater_agent.browser_launch_completion_gap(request, [], 'Done.'))

        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {
                    'command': 'python3 -m http.server 4173 --bind 0.0.0.0',
                    'background': True,
                },
                'result': json.dumps({'status': 'running', 'exit_code': None, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'curl -fsS http://127.0.0.1:4173/'},
                'result': json.dumps({'status': 'done', 'exit_code': 0, 'timed_out': False}),
            },
        ]

        self.assertEqual(
            tater_agent.browser_launch_completion_gap(
                request,
                records,
                'The game is running on port 4173. Open it from Files > Ports.',
            ),
            '',
        )

    def test_noninteractive_work_does_not_require_browser_launch(self):
        self.assertFalse(tater_agent.requires_live_browser_delivery('Run the tests for this app.'))
        self.assertEqual(
            tater_agent.browser_launch_completion_gap('Run the tests for this app.', [], 'Tests pass.'),
            '',
        )

    def test_coding_change_requires_final_diff_inspection(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git status --short'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': "python3 -c \"open('app.py', 'w').write('pass')\""},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'python3 -m py_compile app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
        ]

        self.assertIn(
            'final diff was not inspected',
            tater_agent.coding_change_completion_gap('Fix the bug in app.py', records, 'Fixed.'),
        )

    def test_coding_change_requires_post_edit_verification(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git status --short'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': "python3 -c \"open('app.py', 'w').write('pass')\""},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git diff --check && git diff -- app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
        ]

        self.assertIn(
            'post-edit verification command',
            tater_agent.coding_change_completion_gap('Fix the bug in app.py', records, 'Fixed.'),
        )

    def test_verified_coding_change_can_complete(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git status --short'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': "python3 -c \"open('app.py', 'w').write('pass')\""},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git diff --check && git diff -- app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'python3 -m unittest tests.test_app'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
        ]

        self.assertEqual(
            tater_agent.coding_change_completion_gap('Fix the bug in app.py', records, 'Fixed and tested.'),
            '',
        )

    def test_bug_fix_requires_a_focused_regression_test(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git status --short'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'touch app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git diff -- app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'python3 -m py_compile app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
        ]

        self.assertIn(
            'no focused test ran',
            tater_agent.coding_change_completion_gap('Fix the app bug', records, 'Fixed and compiled.'),
        )

    def test_verification_must_run_again_after_a_later_edit(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'pytest -q'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'sed -i.bak s/old/new/ app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git diff -- app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
        ]

        self.assertIn(
            'post-edit verification command',
            tater_agent.coding_change_completion_gap('Update the app code', records, 'Done.'),
        )

    def test_failed_verification_can_be_reported_as_a_blocker(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git status --short'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'touch app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git diff -- app.py'},
                'result': json.dumps({'exit_code': 0, 'timed_out': False}),
            },
            {
                'tool': 'terminal',
                'status': 'failed',
                'parameters': {'command': 'pytest -q'},
                'result': json.dumps({'exit_code': 1, 'timed_out': False}),
            },
        ]

        self.assertEqual(
            tater_agent.coding_change_completion_gap(
                'Fix the app bug',
                records,
                'Verification is blocked because pytest failed with an existing dependency error.',
            ),
            '',
        )

    def test_game_and_live_weather_require_separate_task_types(self):
        request = (
            'Make a funny woodchuck game and launch it so we can play it. '
            'Also tell me the current temperature outside.'
        )
        combined_plan = [
            {
                'tool_calls': [
                    {'name': 'terminal', 'parameters': {'command': 'pwd'}},
                    {'name': 'tater_hydra', 'parameters': {'request': 'Get the weather'}},
                ]
            }
        ]
        split_plan = [
            {'tool_calls': [{'name': 'terminal', 'parameters': {'command': 'pwd'}}]},
            {'tool_calls': [{'name': 'tater_hydra', 'parameters': {'request': 'Get the weather'}}]},
        ]

        self.assertIn(
            'two independent outcomes',
            tater_agent.parallel_browser_weather_plan_gap(request, combined_plan),
        )
        self.assertEqual(tater_agent.parallel_browser_weather_plan_gap(request, split_plan), '')

    def test_incomplete_review_requires_reason(self):
        with self.assertRaisesRegex(ValueError, 'must explain'):
            tater_agent.parse_completion_review('{"complete":false,"reason":""}')

    def test_parses_first_tool_plan_without_consuming_trailing_prose(self):
        calls = tater_agent.parse_tool_plan(
            'Plan: {"tool_calls":[{"name":"terminal","parameters":{"command":"cat a.py"}}]} '
            'then explain {not json}.'
        )

        self.assertEqual(calls[0]['name'], 'terminal')

    def test_rejects_invalid_parameters(self):
        with self.assertRaisesRegex(ValueError, 'must be an object'):
            tater_agent.parse_tool_plan('{"name":"terminal","parameters":"pwd"}')

    def test_rejects_oversized_tool_batch(self):
        payload = {'tool_calls': [{'name': 'terminal', 'parameters': {'command': str(i)}} for i in range(17)]}

        with self.assertRaisesRegex(ValueError, 'too many calls'):
            tater_agent.parse_tool_plan(json.dumps(payload))

    def test_retry_instruction_demands_plain_json(self):
        instruction = tater_agent.tool_plan_retry_instruction('No tool-plan JSON object found')

        self.assertIn('Retry the same planning step', instruction)
        self.assertIn('task_title, progress, tool_calls, parallel_tasks, final_answer', instruction)
        self.assertIn('Do not include Markdown', instruction)

    def test_retry_instruction_limits_error_length(self):
        instruction = tater_agent.tool_plan_retry_instruction('x' * 500)

        self.assertLess(len(instruction), 600)

    def test_retry_instruction_preserves_malformed_multiline_write(self):
        instruction = tater_agent.tool_plan_retry_instruction(
            'No tool-plan JSON object found',
            '{"tool_calls":[{"name":"terminal","parameters":{"command":"cat > index.html <<EOF\n'
            '<html>game</html>\nEOF"}}]}',
        )

        self.assertIn('Preserve that write step', instruction)
        self.assertIn('do not return to directory listing or reread files', instruction)
        self.assertIn('base64', instruction)
        self.assertIn('exactly one terminal call', instruction)

    def test_retry_instruction_explains_unresolved_outcome_after_repeated_read(self):
        instruction = tater_agent.tool_plan_retry_instruction(
            'The identical terminal call already completed and no intervening action changed its inputs.',
            json.dumps(
                {
                    'task_title': 'Launch Woodchuck Game',
                    'progress': 'Inspecting the web files.',
                    'tool_calls': [
                        {
                            'name': 'terminal',
                            'parameters': {
                                'command': 'cat web_version/index.html',
                                'cwd': '/projects/woodchuck_game',
                            },
                        }
                    ],
                    'parallel_tasks': [],
                    'final_answer': '',
                    'context': {},
                }
            ),
            'try again',
        )

        self.assertIn('does not mean the command failed', instruction)
        self.assertIn('The completed action was terminal', instruction)
        self.assertIn('The requested outcome is: Launch Woodchuck Game', instruction)
        self.assertIn('identify the still missing result', instruction)
        self.assertIn('start the HTTP server', instruction)

    def test_recent_history_keeps_latest_messages_within_budget(self):
        history = tater_agent.render_recent_chat_history(
            [
                {'role': 'user', 'content': 'old-' + ('a' * 80)},
                {'role': 'assistant', 'content': 'new-' + ('b' * 80)},
            ],
            max_chars=110,
        )

        self.assertIn('new-', history)
        self.assertNotIn('old-', history)

    def test_agent_context_merges_prior_fields(self):
        context = tater_agent.normalize_agent_context(
            {'branch': 'feature'},
            {'objective': 'Build it', 'branch': 'main', 'tests': ['unit tests pass']},
        )

        self.assertEqual(context['objective'], 'Build it')
        self.assertEqual(context['branch'], 'feature')
        self.assertEqual(context['tests'], ['unit tests pass'])

    def test_completed_task_context_merges_without_losing_parent_work(self):
        merged = tater_agent.merge_task_context(
            {
                'objective': 'Keep helping in the parent chat',
                'completed': ['Earlier work'],
                'tests': ['Earlier test'],
            },
            {
                'objective': 'Implement the background task',
                'repository_root': '/workspace/app',
                'branch': 'main',
                'completed': ['Background work'],
                'tests': ['pytest'],
                'execution_summary': 'Background task completed.',
            },
        )

        self.assertEqual(merged['objective'], 'Keep helping in the parent chat')
        self.assertEqual(merged['repository_root'], '/workspace/app')
        self.assertEqual(merged['completed'], ['Earlier work', 'Background work'])
        self.assertEqual(merged['tests'], ['Earlier test', 'pytest'])
        self.assertEqual(merged['execution_summary'], 'Background task completed.')

    def test_completed_task_context_keeps_the_latest_bounded_history(self):
        merged = tater_agent.merge_task_context(
            {'completed': [f'parent-{index}' for index in range(45)]},
            {'completed': [f'task-{index}' for index in range(10)]},
        )

        self.assertEqual(len(merged['completed']), tater_agent.TATER_AGENT_CONTEXT_LIST_MAX_ITEMS)
        self.assertNotIn('parent-0', merged['completed'])
        self.assertEqual(merged['completed'][-1], 'task-9')

    def test_project_context_keeps_shared_history_and_latest_working_state(self):
        merged = tater_agent.merge_project_context(
            {
                'objective': 'Earlier project work',
                'completed': ['Set up repository'],
                'tests': ['old tests'],
            },
            {
                'objective': 'Add project-aware chats',
                'repository_root': '/projects/tater-open-webui',
                'branch': 'main',
                'completed': ['Added project context'],
                'tests': ['new tests'],
            },
        )

        self.assertEqual(merged['objective'], 'Add project-aware chats')
        self.assertEqual(merged['repository_root'], '/projects/tater-open-webui')
        self.assertEqual(merged['completed'], ['Set up repository', 'Added project context'])
        self.assertEqual(merged['tests'], ['old tests', 'new tests'])

    def test_context_window_bounds_planner_history(self):
        self.assertEqual(tater_agent.agent_history_char_limit(4096), 8192)
        self.assertEqual(tater_agent.agent_history_char_limit(1000000), 120000)

    def test_fast_path_accepts_small_successful_read_only_terminal_history(self):
        records = [
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'ls -la'},
                'result': {'output': 'README.md\nsrc/\n', 'exit_code': 0},
            },
            {
                'tool': 'terminal',
                'status': 'completed',
                'parameters': {'command': 'git log -n 5 --oneline'},
                'result': {'output': 'abc123 latest change\n', 'exit_code': 0},
            },
        ]

        self.assertTrue(tater_agent.simple_read_only_terminal_history(records))

    def test_fast_path_rejects_failed_or_mutating_terminal_history(self):
        def record(command, status='completed'):
            return {
                'tool': 'terminal',
                'status': status,
                'parameters': {'command': command},
                'result': {'exit_code': 0},
            }

        self.assertFalse(tater_agent.simple_read_only_terminal_history([record('ls', 'failed')]))
        self.assertFalse(tater_agent.simple_read_only_terminal_history([record('rm -rf build')]))
        self.assertFalse(tater_agent.simple_read_only_terminal_history([record('git branch -D temp')]))
        self.assertFalse(tater_agent.simple_read_only_terminal_history([record('git diff --output=patch.txt')]))
        self.assertFalse(tater_agent.simple_read_only_terminal_history([record('ls | head')]))

    def test_clamps_iteration_limit(self):
        self.assertEqual(tater_agent.agent_iteration_limit('0'), 1)
        self.assertEqual(tater_agent.agent_iteration_limit('999'), 128)
        self.assertEqual(tater_agent.agent_iteration_limit('invalid'), 32)

    def test_keeps_newest_history_within_tiny_budget(self):
        history = tater_agent.render_tool_history(
            [
                {'tool': 'first', 'result': 'a' * 80},
                {'tool': 'second', 'result': 'b' * 80},
            ],
            max_chars=100,
        )

        self.assertLessEqual(len(history), 100)
        self.assertIn('second', history)

    def test_large_results_preserve_every_command_and_bounded_excerpts(self):
        history = tater_agent.render_tool_history(
            [
                {
                    'iteration': 1,
                    'tool': 'terminal',
                    'status': 'completed',
                    'parameters': {'command': 'cat hydra/__init__.py'},
                    'result': {
                        'output': 'FIRST-START\n' + ('a' * 20_000) + '\nFIRST-END',
                        'exit_code': 0,
                        'truncated': True,
                    },
                },
                {
                    'iteration': 2,
                    'tool': 'terminal',
                    'status': 'completed',
                    'parameters': {'command': 'rg -n "Hydra" hydra'},
                    'result': {
                        'output': 'SECOND-START\n' + ('b' * 20_000) + '\nSECOND-END',
                        'exit_code': 0,
                        'truncated': False,
                    },
                },
                {
                    'iteration': 3,
                    'tool': 'terminal',
                    'status': 'completed',
                    'parameters': {'command': "sed -n '1,160p' hydra/__init__.py"},
                    'result': {
                        'output': 'THIRD-START\n' + ('c' * 20_000) + '\nTHIRD-END',
                        'exit_code': 0,
                        'truncated': False,
                    },
                },
            ],
            max_chars=6_000,
        )

        self.assertLessEqual(len(history), 6_000)
        self.assertIn('cat hydra/__init__.py', history)
        self.assertIn('rg -n', history)
        self.assertIn("sed -n '1,160p'", history)
        self.assertIn('"output_chars":20022', history)
        self.assertIn('FIRST-START', history)
        self.assertIn('FIRST-END', history)
        self.assertIn('SECOND-START', history)
        self.assertIn('SECOND-END', history)
        self.assertIn('THIRD-START', history)
        self.assertIn('THIRD-END', history)
        self.assertIn('characters omitted', history)

    def test_outcome_signature_is_stable_across_parameter_order(self):
        first = tater_agent.tool_outcome_signature('tool', {'b': 2, 'a': 1}, {'ok': True})
        second = tater_agent.tool_outcome_signature('tool', {'a': 1, 'b': 2}, {'ok': True})

        self.assertEqual(first, second)

    def test_outcome_signature_ignores_process_identity_and_timestamps(self):
        first = tater_agent.tool_outcome_signature(
            'terminal',
            {'command': 'false'},
            {'id': 'first', 'created_at': 1, 'status': 'done', 'exit_code': 1, 'output': ''},
        )
        second = tater_agent.tool_outcome_signature(
            'terminal',
            {'command': 'false'},
            '{"id":"second","created_at":2,"status":"done","exit_code":1,"output":""}',
        )

        self.assertEqual(first, second)

    def test_repeated_successful_call_requires_a_different_next_action(self):
        records = [
            {
                'iteration': 8,
                'tool': 'terminal',
                'parameters': {'command': "sed -n '5700,6000p' hydra/__init__.py", 'cwd': '/projects/tater'},
                'status': 'completed',
                'result': {'output': 'execution loop', 'exit_code': 0},
            },
            {
                'iteration': 9,
                'tool': 'agent_protocol',
                'parameters': {},
                'status': 'failed',
                'result': 'A final answer is required.',
            },
        ]

        gap = tater_agent.repeated_tool_call_plan_gap(
            [
                {
                    'name': 'terminal',
                    'parameters': {
                        'cwd': '/projects/tater',
                        'command': "sed -n '5700,6000p' hydra/__init__.py",
                    },
                }
            ],
            records,
        )

        self.assertIn('already completed', gap)
        self.assertIn('choose a different command', gap)

    def test_repeated_failed_call_requires_corrected_parameters(self):
        gap = tater_agent.repeated_tool_call_plan_gap(
            [{'name': 'terminal', 'parameters': {'command': 'cat missing.py'}}],
            [
                {
                    'iteration': 2,
                    'tool': 'terminal',
                    'parameters': {'command': 'cat missing.py'},
                    'status': 'failed',
                    'result': {'output': 'No such file', 'exit_code': 1},
                }
            ],
        )

        self.assertIn('already failed', gap)
        self.assertIn('change the command or parameters', gap)

    def test_repeated_file_read_is_rejected_after_other_read_only_commands(self):
        records = [
            {
                'iteration': 2,
                'tool': 'terminal',
                'parameters': {'command': 'cat game.py', 'cwd': '/projects/woodchuck_game'},
                'status': 'completed',
                'result': {'output': 'terminal game', 'exit_code': 0},
            },
            {
                'iteration': 3,
                'tool': 'terminal',
                'parameters': {'command': 'ls -F', 'cwd': '/projects/woodchuck_game'},
                'status': 'completed',
                'result': {'output': 'game.py', 'exit_code': 0},
            },
        ]

        gap = tater_agent.repeated_tool_call_plan_gap(
            [
                {
                    'name': 'terminal',
                    'parameters': {'command': 'cat game.py', 'cwd': '/projects/woodchuck_game'},
                }
            ],
            records,
        )

        self.assertIn('no intervening action changed its inputs', gap)

    def test_repeated_file_read_is_rejected_after_unrelated_mutation(self):
        records = [
            {
                'iteration': 2,
                'tool': 'terminal',
                'parameters': {'command': 'cat game.py', 'cwd': '/projects/woodchuck_game'},
                'status': 'completed',
                'result': {'output': 'terminal game', 'exit_code': 0},
            },
            {
                'iteration': 3,
                'tool': 'terminal',
                'parameters': {
                    'command': 'mkdir -p web_version && touch web_version/index.html',
                    'cwd': '/projects/woodchuck_game',
                },
                'status': 'completed',
                'result': {'output': '', 'exit_code': 0},
            },
        ]

        gap = tater_agent.repeated_tool_call_plan_gap(
            [
                {
                    'name': 'terminal',
                    'parameters': {'command': 'cat game.py', 'cwd': '/projects/woodchuck_game'},
                }
            ],
            records,
        )

        self.assertIn('already completed', gap)
        self.assertIn('choose a different command', gap)

    def test_repeated_file_read_is_allowed_after_same_file_change(self):
        records = [
            {
                'iteration': 2,
                'tool': 'terminal',
                'parameters': {'command': 'cat game.py', 'cwd': '/projects/woodchuck_game'},
                'status': 'completed',
                'result': {'output': 'terminal game', 'exit_code': 0},
            },
            {
                'iteration': 3,
                'tool': 'terminal',
                'parameters': {
                    'command': "printf '%s' 'browser game' > game.py",
                    'cwd': '/projects/woodchuck_game',
                },
                'status': 'completed',
                'result': {'output': '', 'exit_code': 0},
            },
        ]

        gap = tater_agent.repeated_tool_call_plan_gap(
            [
                {
                    'name': 'terminal',
                    'parameters': {'command': 'cat game.py', 'cwd': '/projects/woodchuck_game'},
                }
            ],
            records,
        )

        self.assertEqual(gap, '')

    def test_repeated_terminal_call_matches_persisted_cwd_when_omitted(self):
        gap = tater_agent.repeated_tool_call_plan_gap(
            [{'name': 'terminal', 'parameters': {'command': 'ls -F'}}],
            [
                {
                    'iteration': 3,
                    'tool': 'terminal',
                    'parameters': {'command': 'ls -F', 'cwd': '/projects/woodchuck_game'},
                    'status': 'completed',
                    'result': {
                        'cwd': '/projects/woodchuck_game',
                        'output': 'game.py',
                        'exit_code': 0,
                    },
                }
            ],
        )

        self.assertIn('already completed', gap)

    def test_repeated_call_is_allowed_after_an_intervening_tool_step(self):
        records = [
            {
                'iteration': 2,
                'tool': 'terminal',
                'parameters': {'command': 'pytest -q'},
                'status': 'failed',
                'result': {'output': 'one failure', 'exit_code': 1},
            },
            {
                'iteration': 3,
                'tool': 'terminal',
                'parameters': {'command': "apply_patch <<'PATCH'\nPATCH"},
                'status': 'completed',
                'result': {'output': 'Done', 'exit_code': 0},
            },
        ]

        gap = tater_agent.repeated_tool_call_plan_gap(
            [{'name': 'terminal', 'parameters': {'command': 'pytest -q'}}],
            records,
        )

        self.assertEqual(gap, '')

    def test_duplicate_calls_in_one_plan_are_rejected(self):
        gap = tater_agent.repeated_tool_call_plan_gap(
            [
                {'name': 'terminal', 'parameters': {'command': 'pwd'}},
                {'name': 'terminal', 'parameters': {'command': 'pwd'}},
            ],
            [
                {
                    'iteration': 1,
                    'tool': 'terminal',
                    'parameters': {'command': 'ls'},
                    'status': 'completed',
                    'result': {'output': 'README.md', 'exit_code': 0},
                }
            ],
        )

        self.assertIn('more than once', gap)


if __name__ == '__main__':
    unittest.main()
