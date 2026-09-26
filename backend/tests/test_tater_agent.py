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
    def test_parses_fenced_tool_plan(self):
        calls = tater_agent.parse_tool_plan(
            '```json\n{"tool_calls":[{"name":"terminal","parameters":{"command":"pwd"}}]}\n```'
        )

        self.assertEqual(calls, [{'name': 'terminal', 'parameters': {'command': 'pwd'}}])

    def test_parses_empty_plan(self):
        self.assertEqual(tater_agent.parse_tool_plan('{"tool_calls":[]}'), [])

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

    def test_clamps_iteration_limit(self):
        self.assertEqual(tater_agent.agent_iteration_limit('0'), 1)
        self.assertEqual(tater_agent.agent_iteration_limit('999'), 128)
        self.assertEqual(tater_agent.agent_iteration_limit('invalid'), 32)

    def test_keeps_newest_history_within_budget(self):
        history = tater_agent.render_tool_history(
            [
                {'tool': 'first', 'result': 'a' * 80},
                {'tool': 'second', 'result': 'b' * 80},
            ],
            max_chars=100,
        )

        self.assertLessEqual(len(history), 100)
        self.assertIn('bbbb', history)
        self.assertNotIn('aaaa', history)

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


if __name__ == '__main__':
    unittest.main()
