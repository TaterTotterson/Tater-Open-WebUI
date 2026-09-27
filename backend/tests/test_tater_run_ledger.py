from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'utils' / 'tater_run_ledger.py'
SPEC = importlib.util.spec_from_file_location('tater_run_ledger', MODULE_PATH)
assert SPEC and SPEC.loader
tater_run_ledger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tater_run_ledger)


class TaterRunLedgerTests(unittest.TestCase):
    def test_writes_structured_event_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.jsonl'
            written = tater_run_ledger.record_tater_run_event(
                'tool_finished',
                run_id='run-1',
                task_id='task-1',
                chat_id='chat-1',
                user_id='user-1',
                data={
                    'parameters': {
                        'command': 'API_KEY=super-secret curl --token another-secret https://example.test',
                        'authorization': 'Bearer hidden',
                    },
                    'result': 'Authorization: Bearer abc.def.ghi',
                    'usage': {'prompt_tokens': 123},
                },
                path=path,
                enabled=True,
                max_bytes=1_000_000,
                backup_count=2,
                max_field_chars=20_000,
            )

            self.assertTrue(written)
            event = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(event['event'], 'tool_finished')
            self.assertEqual(event['run_id'], 'run-1')
            self.assertEqual(event['task_id'], 'task-1')
            self.assertEqual(event['data']['parameters']['authorization'], '[redacted]')
            self.assertEqual(event['data']['usage']['prompt_tokens'], 123)
            serialized = json.dumps(event)
            self.assertNotIn('super-secret', serialized)
            self.assertNotIn('another-secret', serialized)
            self.assertNotIn('abc.def.ghi', serialized)

    def test_caps_large_fields_and_rotates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.jsonl'
            settings = {
                'path': path,
                'enabled': True,
                'max_bytes': 150,
                'backup_count': 2,
                'max_field_chars': 50,
            }

            tater_run_ledger.record_tater_run_event(
                'first',
                run_id='run-1',
                data={'output': 'a' * 500},
                **settings,
            )
            tater_run_ledger.record_tater_run_event(
                'second',
                run_id='run-1',
                data={'output': 'b' * 500},
                **settings,
            )

            self.assertTrue(path.exists())
            self.assertTrue(Path(f'{path}.1').exists())
            current = json.loads(path.read_text(encoding='utf-8'))
            self.assertIn('[truncated 450 characters]', current['data']['output'])


if __name__ == '__main__':
    unittest.main()
