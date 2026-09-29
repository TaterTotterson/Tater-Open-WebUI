from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'utils' / 'tater_profile.py'
SPEC = importlib.util.spec_from_file_location('tater_profile', MODULE_PATH)
assert SPEC and SPEC.loader
tater_profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tater_profile)


class TaterProfileTests(unittest.TestCase):
    def test_normalizes_host_and_trailing_slash(self):
        self.assertEqual(
            tater_profile.normalize_tater_api_base_url('localhost:8501/v1/'),
            'http://localhost:8501/v1',
        )

    def test_normalizes_tater_hub_from_supported_connection_urls(self):
        for value in (
            'https://tater.example/',
            'https://tater.example/v1',
            'https://tater.example/api/spudlink',
            'https://tater.example/api/spudlink/v1',
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    tater_profile.normalize_tater_hub_url(value),
                    'https://tater.example',
                )
        self.assertEqual(
            tater_profile.tater_openai_api_url('https://tater.example/tater/api/spudlink'),
            'https://tater.example/tater/v1',
        )

    def test_rejects_embedded_credentials(self):
        with self.assertRaisesRegex(ValueError, 'must not be embedded'):
            tater_profile.normalize_tater_api_base_url('http://user:secret@localhost:8501/v1')

    def test_builds_single_provider_profile(self):
        updates = tater_profile.build_tater_profile_updates(
            api_base_url='https://tater.example/v1/',
            api_key=' secret ',
            base_model='tater/base',
            hydra_model='tater/hydra',
            context_window=131072,
        )

        self.assertEqual(updates['openai.api_base_urls'], ['https://tater.example/v1'])
        self.assertEqual(updates['openai.api_keys'], ['secret'])
        self.assertEqual(updates['ui.default_models'], 'tater/base')
        self.assertEqual(updates['openai.api_configs']['0']['provider'], 'tater')
        self.assertEqual(updates['models.default_params']['function_calling'], 'legacy')
        self.assertEqual(updates['tater.context_window'], 131072)
        self.assertEqual(updates['models.default_params']['compact_token_threshold'], 104857)
        self.assertTrue(updates['chat.context_compaction.enable'])
        self.assertEqual(updates['chat.context_compaction.token_cap'], 104857)

    def test_context_window_keeps_twenty_percent_for_output_and_tools(self):
        self.assertEqual(tater_profile.context_compaction_threshold(32768), 26214)
        self.assertEqual(tater_profile.context_compaction_threshold(4096), 2048)

    def test_rejects_invalid_context_window(self):
        with self.assertRaisesRegex(ValueError, 'between'):
            tater_profile.normalize_tater_context_window(2048)

    def test_requires_distinct_base_and_hydra_models(self):
        with self.assertRaisesRegex(ValueError, 'must be different'):
            tater_profile.build_tater_profile_updates(
                api_base_url='http://localhost:8501/v1',
                api_key='',
                base_model='tater/base',
                hydra_model='tater/base',
            )

    def test_identifies_reserved_hydra_model(self):
        self.assertTrue(tater_profile.is_reserved_hydra_model({'id': 'tater/hydra'}, 'tater/hydra'))
        self.assertFalse(tater_profile.is_reserved_hydra_model({'id': 'tater/base'}, 'tater/hydra'))


if __name__ == '__main__':
    unittest.main()
