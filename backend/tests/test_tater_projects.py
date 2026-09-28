from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


_MODULE_NAMES = ('open_webui', 'open_webui.models', 'open_webui.models.folders')
_PREVIOUS_MODULES = {name: sys.modules.get(name) for name in _MODULE_NAMES}

models_stub = types.ModuleType('open_webui.models.folders')
models_stub.FolderForm = object
models_stub.FolderModel = object
models_stub.FolderUpdateForm = object
models_stub.Folders = object
sys.modules.setdefault('open_webui', types.ModuleType('open_webui'))
sys.modules.setdefault('open_webui.models', types.ModuleType('open_webui.models'))
sys.modules['open_webui.models.folders'] = models_stub

MODULE_PATH = Path(__file__).parents[1] / 'open_webui' / 'utils' / 'tater_projects.py'
SPEC = importlib.util.spec_from_file_location('tater_projects', MODULE_PATH)
assert SPEC and SPEC.loader
tater_projects = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tater_projects)

for module_name, previous_module in _PREVIOUS_MODULES.items():
    if previous_module is None:
        sys.modules.pop(module_name, None)
    else:
        sys.modules[module_name] = previous_module


class TaterProjectsTests(unittest.TestCase):
    def test_discovers_only_visible_direct_child_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Beta').mkdir()
            (root / 'alpha').mkdir()
            (root / '.hidden').mkdir()
            (root / 'notes.txt').write_text('not a project')
            (root / 'alpha' / 'nested').mkdir()

            projects = tater_projects.discover_project_directories(root)

            self.assertEqual([path.name for path in projects], ['alpha', 'Beta'])

    def test_project_path_must_be_one_direct_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(
                tater_projects.project_path_for_name('my-app', root),
                root.resolve() / 'my-app',
            )
            for invalid in ('', '.', '..', '../escape', 'nested/project'):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        tater_projects.project_path_for_name(invalid, root)

    def test_regular_chats_share_a_user_isolated_scratch_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            first = tater_projects.regular_chat_scratch_path('user-1', root)
            second = tater_projects.regular_chat_scratch_path('user-1', root)
            another_user = tater_projects.regular_chat_scratch_path('user-2', root)

            self.assertEqual(first, second)
            self.assertNotEqual(first, another_user)
            self.assertEqual(first.parent.name, tater_projects.TATER_SCRATCH_DIRECTORY_NAME)
            self.assertTrue(first.is_dir())
            self.assertNotIn(first.parent, tater_projects.discover_project_directories(root))

    def test_scratch_directory_name_is_reserved_from_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'reserved'):
                tater_projects.project_path_for_name(
                    tater_projects.TATER_SCRATCH_DIRECTORY_NAME,
                    Path(directory),
                )

    def test_configured_root_prefers_projects_setting_and_creates_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'projects'
            previous = os.environ.get('TATER_PROJECTS_ROOT')
            os.environ['TATER_PROJECTS_ROOT'] = str(root)
            try:
                self.assertEqual(tater_projects.configured_projects_root(), root.resolve())
                self.assertTrue(root.is_dir())
            finally:
                if previous is None:
                    os.environ.pop('TATER_PROJECTS_ROOT', None)
                else:
                    os.environ['TATER_PROJECTS_ROOT'] = previous

    def test_unlinked_directories_wait_for_explicit_project_selection(self):
        class FakeFolders:
            inserted = False

            async def get_folders_by_user_id(self, user_id, db=None):
                return []

            async def insert_new_folder(self, *args, **kwargs):
                self.inserted = True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'projects'
            root.mkdir()
            (root / 'existing-repository').mkdir()
            previous = os.environ.get('TATER_PROJECTS_ROOT')
            original_folders = tater_projects.Folders
            fake_folders = FakeFolders()
            os.environ['TATER_PROJECTS_ROOT'] = str(root)
            tater_projects.Folders = fake_folders
            try:
                projects = asyncio.run(tater_projects.sync_user_projects('user-1'))
                self.assertEqual(projects, [])
                self.assertFalse(fake_folders.inserted)
                self.assertEqual(
                    [path.name for path in tater_projects.discover_project_directories(root)],
                    ['existing-repository'],
                )
            finally:
                tater_projects.Folders = original_folders
                if previous is None:
                    os.environ.pop('TATER_PROJECTS_ROOT', None)
                else:
                    os.environ['TATER_PROJECTS_ROOT'] = previous


if __name__ == '__main__':
    unittest.main()
