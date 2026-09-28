from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from open_webui.models.folders import FolderForm, FolderModel, FolderUpdateForm, Folders


def configured_projects_root() -> Path:
    """Return the host-backed directory whose direct children are projects."""

    value = os.getenv('TATER_PROJECTS_ROOT') or os.getenv('TATER_WEBUI_WORKSPACE') or '/projects'
    root = Path(value).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise RuntimeError(f'TATER_PROJECTS_ROOT is not a directory: {root}')
    return root


def project_directory_name(name: str) -> str:
    """Validate a project name before using it as one direct path component."""

    name = str(name or '').strip()
    if not name or name in {'.', '..'}:
        raise ValueError('Project name cannot be empty')
    if '/' in name or '\\' in name or any(ord(character) < 32 for character in name):
        raise ValueError('Project name cannot contain path separators or control characters')
    return name


def project_path_for_name(name: str, root: Path | None = None) -> Path:
    root = (root or configured_projects_root()).resolve()
    path = (root / project_directory_name(name)).resolve()
    if path.parent != root:
        raise ValueError('Project must be a direct child of the projects directory')
    return path


def discover_project_directories(root: Path | None = None) -> list[Path]:
    root = (root or configured_projects_root()).resolve()
    return sorted(
        (
            path.resolve()
            for path in root.iterdir()
            if path.is_dir() and not path.is_symlink() and not path.name.startswith('.')
        ),
        key=lambda path: path.name.casefold(),
    )


def folder_project_path(folder: FolderModel | None) -> Path | None:
    if not folder or not isinstance(folder.data, dict):
        return None
    value = str(folder.data.get('project_path') or '').strip()
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    root = configured_projects_root()
    if path.parent != root:
        return None
    return path


def project_prompt(folder: FolderModel, root: Path | None = None) -> str:
    root = (root or configured_projects_root()).resolve()
    path = folder_project_path(folder)
    if path is None:
        return ''
    return (
        'Current coding project (authoritative):\n'
        f'- Project name: {folder.name}\n'
        f'- Project root: {path}\n'
        f'- Projects directory: {root}\n'
        'Start terminal work in the project root. Treat its files and Git state as authoritative. '
        f'Other projects are direct children of {root} and remain accessible for cross-project inspection or edits '
        'when the user requests them. Keep this project\'s chats and persistent working context associated with it.'
    )


def _project_data(path: Path, existing: Any = None) -> dict[str, Any]:
    return {
        **(existing if isinstance(existing, dict) else {}),
        'project_path': str(path),
        'taterAgentContext': (
            existing.get('taterAgentContext', {}) if isinstance(existing, dict) else {}
        ),
    }


async def sync_user_projects(user_id: str, *, db=None) -> list[FolderModel]:
    """Keep existing project records aligned with their filesystem directories.

    The database keeps chat membership and project settings; the filesystem is
    authoritative for project contents. Legacy logical folders are migrated to
    direct project directories so existing chats are preserved. New directories
    are linked explicitly from the Create Project dialog, which also lets a
    project be removed from Tater without deleting its files.
    """

    root = configured_projects_root()
    folders = await Folders.get_folders_by_user_id(user_id, db=db)

    claimed_paths: set[Path] = set()
    for folder in folders:
        path = folder_project_path(folder)
        if path is not None and path.is_dir():
            claimed_paths.add(path)

    # Preserve existing chats by turning every legacy logical folder into a
    # top-level filesystem project. A suffix avoids colliding with real dirs.
    for folder in folders:
        if folder_project_path(folder) is not None:
            if folder.parent_id is not None:
                await Folders.update_folder_parent_id_by_id_and_user_id(
                    folder.id, user_id, None, db=db
                )
            continue

        try:
            base_name = project_directory_name(folder.name)
        except ValueError:
            base_name = ''.join(
                '-' if character in {'/', '\\'} or ord(character) < 32 else character
                for character in str(folder.name or '')
            ).strip(' .-') or 'project'
        path = project_path_for_name(base_name, root)
        suffix = 2
        while path in claimed_paths:
            path = project_path_for_name(f'{base_name}-{suffix}', root)
            suffix += 1
        path.mkdir(parents=False, exist_ok=True)
        claimed_paths.add(path)
        await Folders.update_folder_by_id_and_user_id(
            folder.id,
            user_id,
            FolderUpdateForm(
                data=_project_data(path, folder.data),
                meta={**(folder.meta or {}), 'project': True},
            ),
            db=db,
        )
        if folder.parent_id is not None:
            await Folders.update_folder_parent_id_by_id_and_user_id(folder.id, user_id, None, db=db)

    folders = await Folders.get_folders_by_user_id(user_id, db=db)
    return [
        folder
        for folder in folders
        if (path := folder_project_path(folder)) is not None and path.is_dir()
    ]
