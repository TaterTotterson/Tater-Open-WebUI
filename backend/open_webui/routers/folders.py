import logging
import mimetypes
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from open_webui.config import UPLOAD_DIR
from open_webui.constants import ERROR_MESSAGES
from open_webui.events import EVENTS, publish_event
from open_webui.internal.db import get_async_session
from open_webui.models.chat_messages import ChatMessages
from open_webui.models.config import Config
from open_webui.models.chats import Chats
from open_webui.models.folders import (
    FolderForm,
    FolderModel,
    FolderNameIdResponse,
    Folders,
    FolderUpdateForm,
)
from open_webui.models.access_grants import AccessGrants
from open_webui.models.automations import Automations
from open_webui.models.groups import Groups
from open_webui.models.users import Users
from open_webui.utils.access_control import has_permission
from open_webui.utils.access_control import (
    filter_allowed_access_grants,
)
from open_webui.utils.access_control.files import can_read_all_folder_files, get_accessible_folder_files
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.tater_projects import (
    configured_projects_root,
    discover_project_directories,
    folder_project_path,
    project_directory_name,
    project_path_for_name,
    sync_user_projects,
)
from open_webui.tasks import has_active_tasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


router = APIRouter()


from open_webui.utils.access_control.folders import has_folder_access as _has_folder_access


async def get_folder_unread_counts(user_id: str, db: AsyncSession | None = None) -> dict[str, int]:
    folders = await Folders.get_folders_by_user_id(user_id, db=db)
    parent_by_id = {folder.id: folder.parent_id for folder in folders}
    unread_counts = dict.fromkeys(parent_by_id.keys(), 0)
    direct_unread_counts = await Chats.count_unread_by_folder_ids(user_id, list(parent_by_id.keys()), db=db)

    for unread_folder_id, unread_count in direct_unread_counts.items():
        current_id = unread_folder_id
        seen = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            if current_id in unread_counts:
                unread_counts[current_id] += unread_count
            current_id = parent_by_id.get(current_id)

    return unread_counts


async def check_folders_permission(request: Request, user, db=None):
    """Verify the folders feature is enabled and the user has permission."""
    config = await Config.get_many('folders.enable', 'user.permissions')
    if config.get('folders.enable') is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )
    if user.role != 'admin' and not await has_permission(
        user.id,
        'features.folders',
        config.get('user.permissions'),
        db=db,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )


############################
# Project Filesystem Context
############################


@router.get('/project/context')
async def get_project_context(
    request: Request,
    chat_id: Optional[str] = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Return the directory the Files panel should show for a chat."""

    await check_folders_permission(request, user, db=db)
    root = configured_projects_root()
    project_path = root
    project_id = None
    project_name = None

    if chat_id:
        chat = await Chats.get_chat_by_id_for_user(chat_id, user, db=db)
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        if chat.folder_id:
            folder = await Folders.get_folder_by_id(chat.folder_id, db=db)
            path = folder_project_path(folder)
            if path is not None and path.is_dir():
                project_path = path
                project_id = folder.id
                project_name = folder.name

    return {
        'projects_root': str(root),
        'path': str(project_path),
        'project_id': project_id,
        'project_name': project_name,
    }


@router.get('/projects/available')
async def get_available_project_directories(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """List direct project directories that are not linked to this user's projects."""

    await check_folders_permission(request, user, db=db)
    folders = await sync_user_projects(user.id, db=db)
    claimed_paths = {
        path
        for folder in folders
        if (path := folder_project_path(folder)) is not None
    }
    return [
        {'name': path.name, 'path': str(path)}
        for path in discover_project_directories(configured_projects_root())
        if path not in claimed_paths
    ]


############################
# Get Folders
############################


@router.get('/', response_model=list[FolderNameIdResponse])
async def get_folders(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)

    folders = await sync_user_projects(user.id, db=db)
    parent_by_id = {folder.id: folder.parent_id for folder in folders}

    def is_in_parent_cycle(folder_id):
        seen_ids = {folder_id}
        current_id = parent_by_id.get(folder_id)
        while current_id and current_id not in seen_ids:
            seen_ids.add(current_id)
            current_id = parent_by_id.get(current_id)
        return current_id == folder_id

    user_group_ids = None
    if user.role != 'admin' and any(folder.data and 'files' in folder.data for folder in folders):
        user_group_ids = {group.id for group in await Groups.get_groups_by_member_id(user.id, db=db)}

    # Verify folder data integrity
    folder_list = []
    for folder in folders:
        # A missing or looping parent hides the folder from the tree, so put it back at the root
        if folder.parent_id and (folder.parent_id not in parent_by_id or is_in_parent_cycle(folder.id)):
            parent_by_id[folder.id] = None
            folder = await Folders.update_folder_parent_id_by_id_and_user_id(folder.id, user.id, None, db=db)

        if folder.data and 'files' in folder.data:
            accessible_files = await get_accessible_folder_files(
                folder.data['files'], user, db=db, user_group_ids=user_group_ids
            )
            if len(accessible_files) != len(folder.data.get('files', [])):
                folder.data['files'] = accessible_files
                await Folders.update_folder_by_id_and_user_id(
                    folder.id, user.id, FolderUpdateForm(data=folder.data), db=db
                )

        folder_list.append(folder)

    unread_counts = await get_folder_unread_counts(user.id, db=db)

    return [
        FolderNameIdResponse(**folder.model_dump(), unread_count=unread_counts.get(folder.id, 0))
        for folder in folder_list
    ]


############################
# Create Folder
############################


@router.post('/')
async def create_folder(
    request: Request,
    form_data: FolderForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    if form_data.parent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT('Projects cannot be nested'),
        )

    form_data_values = dict(form_data.data or {})
    existing_project_name = str(form_data_values.pop('existing_project_name', '') or '').strip()
    linking_existing = bool(existing_project_name)

    try:
        project_name = project_directory_name(
            existing_project_name if linking_existing else form_data.name
        )
        path = project_path_for_name(project_name, configured_projects_root())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.DEFAULT(str(exc))
        ) from exc
    existing = await Folders.get_folder_by_parent_id_and_user_id_and_name(
        None, user.id, project_name, db=db
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT('Project already exists'),
        )
    linked_projects = await sync_user_projects(user.id, db=db)
    if any(folder_project_path(folder) == path for folder in linked_projects):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT('Project directory is already linked'),
        )
    if linking_existing and (not path.is_dir() or path.is_symlink()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT('Selected project directory is not available'),
        )
    if not linking_existing and path.exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT('Project directory already exists'),
        )

    if (
        form_data.data
        and 'files' in form_data.data
        and not await can_read_all_folder_files(form_data.data['files'], user, db=db)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    try:
        if not linking_existing:
            path.mkdir(parents=False)
        project_form = FolderForm(
            name=project_name,
            parent_id=None,
            meta={**(form_data.meta or {}), 'project': True},
            data={
                **form_data_values,
                'project_path': str(path),
                'taterAgentContext': {},
            },
        )
        folder = await Folders.insert_new_folder(user.id, project_form, None, db=db)
        if not folder:
            if not linking_existing:
                path.rmdir()
            raise RuntimeError('Project record could not be created')
        await publish_event(
            request,
            EVENTS.FOLDER_CREATED,
            actor=user,
            subject_id=folder.id,
            data={'name': folder.name, 'parent_id': folder.parent_id, 'owner_id': folder.user_id},
        )
        return folder
    except Exception as e:
        log.exception(e)
        log.error('Error creating project')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT('Error creating project'),
        )


############################
# Get Shared Folders
############################


@router.get('/shared')
async def get_shared_folders(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get all folders shared with the current user (not owned by them)."""
    await check_folders_permission(request, user, db=db)
    groups = await Groups.get_groups_by_member_id(user.id, db=db)
    group_ids = {g.id for g in groups}

    folder_perms = await Folders.get_shared_folder_ids_for_user(user.id, group_ids, db=db)

    folders = await Folders.get_folders_by_ids(list(folder_perms.keys()), db=db)
    shared_folders = [folder for folder in folders if folder.user_id != user.id]

    owners = await Users.get_users_by_user_ids([folder.user_id for folder in shared_folders], db=db)
    owner_names = {owner.id: owner.name for owner in owners}

    results = [
        {
            **folder.model_dump(),
            'owner_name': owner_names.get(folder.user_id, 'Unknown'),
            'permission': folder_perms[folder.id],
        }
        for folder in shared_folders
    ]

    # Also include child folders of shared folders (inheritance)
    seen_ids = {folder.id for folder in shared_folders}
    for folder in shared_folders:
        children = await Folders.get_children_folders_by_id_and_user_id(folder.id, folder.user_id, db=db)
        for child in children or []:
            if child.id not in seen_ids:
                seen_ids.add(child.id)
                results.append(
                    {
                        **child.model_dump(),
                        'owner_name': owner_names.get(child.user_id, 'Unknown'),
                        'permission': folder_perms[folder.id],
                    }
                )

    return results


############################
# Get Folders By Id
############################


class FolderResponse(FolderModel):
    access_grants: list[dict] = []
    write_access: bool = False


@router.get('/{id}', response_model=FolderResponse)
async def get_folder_by_id(
    request: Request, id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id_and_user_id(id, user.id, db=db)
    if folder:
        grants = await AccessGrants.get_grants_by_resource('folder', id, db=db)
        return FolderResponse(
            **folder.model_dump(),
            access_grants=[g.model_dump() for g in grants],
            write_access=True,
        )

    # Check shared access
    folder = await Folders.get_folder_by_id(id, db=db)
    if folder and (user.role == 'admin' or await _has_folder_access(user.id, folder, 'read', db)):
        grants = await AccessGrants.get_grants_by_resource('folder', id, db=db)
        return FolderResponse(
            **folder.model_dump(),
            access_grants=[g.model_dump() for g in grants],
            write_access=user.role == 'admin' or await _has_folder_access(user.id, folder, 'write', db),
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ERROR_MESSAGES.NOT_FOUND,
    )


############################
# Update Folder Name By Id
############################


@router.post('/{id}/update')
async def update_folder_name_by_id(
    request: Request,
    id: str,
    form_data: FolderUpdateForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id_and_user_id(id, user.id, db=db)
    if not folder:
        # Check shared write access
        folder = await Folders.get_folder_by_id(id, db=db)
        if not folder or (user.role != 'admin' and not await _has_folder_access(user.id, folder, 'write', db)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )

    if folder:
        original_project_path = folder_project_path(folder)
        renamed_project_path = original_project_path
        normalized_project_name = None
        if form_data.name is not None:
            try:
                normalized_project_name = project_directory_name(form_data.name)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT(str(exc)),
                ) from exc
            # Check if project with same name exists
            existing_folder = await Folders.get_folder_by_parent_id_and_user_id_and_name(
                None, folder.user_id, normalized_project_name, db=db
            )
            if existing_folder and existing_folder.id != id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT('Project already exists'),
                )

            if folder.user_id == user.id and original_project_path is not None:
                try:
                    renamed_project_path = project_path_for_name(
                        normalized_project_name, configured_projects_root()
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=ERROR_MESSAGES.DEFAULT(str(exc)),
                    ) from exc
                if renamed_project_path != original_project_path:
                    if renamed_project_path.exists():
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=ERROR_MESSAGES.DEFAULT('Project directory already exists'),
                        )
                    if not original_project_path.is_dir():
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=ERROR_MESSAGES.DEFAULT('Project directory is missing'),
                        )

        if form_data.data and 'files' in form_data.data:
            owner = user if folder.user_id == user.id else await Users.get_user_by_id(folder.user_id, db=db)
            if not owner:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_MESSAGES.NOT_FOUND,
                )
            if not await can_read_all_folder_files(form_data.data['files'], owner, db=db):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
                )

        project_record_updated = False
        try:
            if (
                original_project_path is not None
                and renamed_project_path is not None
                and renamed_project_path != original_project_path
            ):
                original_project_path.rename(renamed_project_path)
            safe_data = dict(form_data.data or {})
            safe_data.pop('project_path', None)
            safe_data.pop('taterAgentContext', None)
            if renamed_project_path is not None:
                safe_data['project_path'] = str(renamed_project_path)
                safe_data['taterAgentContext'] = (folder.data or {}).get(
                    'taterAgentContext', {}
                )
            safe_payload = form_data.model_dump(exclude={'data'}, exclude_unset=True)
            if normalized_project_name is not None:
                safe_payload['name'] = normalized_project_name
            safe_form = FolderUpdateForm(
                **safe_payload,
                **({'data': safe_data} if safe_data or renamed_project_path is not None else {}),
            )
            folder = await Folders.update_folder_by_id_and_user_id(id, folder.user_id, safe_form, db=db)
            if not folder:
                raise RuntimeError('Project record could not be updated')
            project_record_updated = True
            await publish_event(
                request,
                EVENTS.FOLDER_UPDATED,
                actor=user,
                subject_id=id,
                data={'name': folder.name},
            )
            return folder
        except Exception as e:
            if (
                original_project_path is not None
                and renamed_project_path is not None
                and renamed_project_path != original_project_path
                and renamed_project_path.is_dir()
                and not original_project_path.exists()
                and not project_record_updated
            ):
                renamed_project_path.rename(original_project_path)
            log.exception(e)
            log.error(f'Error updating project: {id}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT('Error updating project'),
            )


############################
# Update Folder Parent Id By Id
############################


class FolderParentIdForm(BaseModel):
    parent_id: Optional[str] = None


@router.post('/{id}/update/parent')
async def update_folder_parent_id_by_id(
    request: Request,
    id: str,
    form_data: FolderParentIdForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id_and_user_id(id, user.id, db=db)
    if folder:
        if form_data.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT('Projects cannot be nested'),
            )

        try:
            folder = await Folders.update_folder_parent_id_by_id_and_user_id(id, user.id, form_data.parent_id, db=db)
            await publish_event(
                request,
                EVENTS.FOLDER_PARENT_UPDATED,
                actor=user,
                subject_id=id,
                data={'parent_id': form_data.parent_id},
            )
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f'Error updating folder: {id}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT('Error updating folder'),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Is Expanded By Id
############################


class FolderIsExpandedForm(BaseModel):
    is_expanded: bool


@router.post('/{id}/update/expanded')
async def update_folder_is_expanded_by_id(
    request: Request,
    id: str,
    form_data: FolderIsExpandedForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id_and_user_id(id, user.id, db=db)
    if not folder:
        folder = await Folders.get_folder_by_id(id, db=db)
        if folder and (user.role == 'admin' or await _has_folder_access(user.id, folder, 'read', db)):
            return folder

    if folder:
        try:
            folder = await Folders.update_folder_is_expanded_by_id_and_user_id(
                id, user.id, form_data.is_expanded, db=db
            )
            return folder
        except Exception as e:
            log.exception(e)
            log.error(f'Error updating folder: {id}')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.DEFAULT('Error updating folder'),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


############################
# Update Folder Access By Id
############################


class FolderAccessGrantsForm(BaseModel):
    access_grants: list[dict]


@router.post('/{id}/access/update')
async def update_folder_access_by_id(
    request: Request,
    id: str,
    form_data: FolderAccessGrantsForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id(id, db=db)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Only owner, admin, or write-granted user can update access
    if user.role != 'admin' and user.id != folder.user_id:
        if not await _has_folder_access(user.id, folder, 'write', db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    form_data.access_grants = await filter_allowed_access_grants(
        await Config.get('user.permissions'),
        user.id,
        user.role,
        form_data.access_grants,
        None,
        db=db,
    )

    await AccessGrants.set_access_grants('folder', id, form_data.access_grants, db=db)

    grants = await AccessGrants.get_grants_by_resource('folder', id, db=db)
    await publish_event(
        request,
        EVENTS.FOLDER_ACCESS_UPDATED,
        actor=user,
        subject_id=id,
        data={'grant_count': len(grants)},
    )
    return {
        **folder.model_dump(),
        'access_grants': [g.model_dump() for g in grants],
    }


############################
# Get Shared Folder Chats
############################


@router.get('/{id}/shared/chats')
async def get_shared_folder_chats(
    request: Request,
    id: str,
    page: int | None = Query(None, ge=1),
    sort_by: str = Query('unread_updated_at'),
    sort_dir: str = Query('desc'),
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get chats within a shared folder. Returns readonly flag based on permission."""
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id(id, db=db)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    is_owner = user.id == folder.user_id
    is_admin = user.role == 'admin'
    has_write = is_owner or is_admin or await _has_folder_access(user.id, folder, 'write', db)
    has_read = has_write or await _has_folder_access(user.id, folder, 'read', db)

    if not has_read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    limit = 10
    skip = (page - 1) * limit if page is not None else 0
    chats = await Chats.get_all_chats_by_folder_id(
        id,
        skip=skip,
        limit=limit if page is not None else 60,
        sort_by=sort_by,
        sort_dir=sort_dir,
        unread_for_user_id=user.id,
        db=db,
    )
    total = await Chats.count_all_chats_by_folder_id(id, db=db) if page is not None else len(chats)

    # Resolve owner names for display (avatar URLs are constructed client-side)
    owner_cache: dict[str, str] = {}
    for chat in chats:
        uid = chat['user_id']
        if uid not in owner_cache:
            u = await Users.get_user_by_id(uid, db=db)
            owner_cache[uid] = u.name if u else 'Unknown'
        chat['owner_name'] = owner_cache[uid]
        chat['active'] = False
        if chat['user_id'] != user.id:
            chat['last_read_at'] = chat['updated_at']
        if await has_active_tasks(request.app.state.redis, chat['id']):
            chat['active'] = await ChatMessages.has_unfinished_assistant_by_chat_id(chat['id'], db=db)

    response = {
        'chats': [{**chat, 'readonly': chat['user_id'] != user.id} for chat in chats],
        'folder_permission': 'write' if has_write else 'read',
    }
    if page is not None:
        response.update({'total': total, 'has_more': skip + limit < total})
    return response


@router.post('/{id}/read')
async def mark_folder_chats_read_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id(id, db=db)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    is_owner = user.id == folder.user_id
    is_admin = user.role == 'admin'
    if not (is_owner or is_admin or await _has_folder_access(user.id, folder, 'read', db)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    folder_ids = (
        await Folders.get_folder_ids_by_id_and_user_id_in_subtree(id, folder.user_id, db=db)
        if is_owner or is_admin
        else [id]
    )
    updated_count = await Chats.mark_chats_read_by_folder_ids(user.id, folder_ids, db=db)

    return {
        'folder_id': id,
        'folder_ids': folder_ids,
        'updated_count': updated_count,
        'folder_unread_counts': await get_folder_unread_counts(user.id, db=db),
    }


############################
# Delete Folder By Id
############################


@router.delete('/{id}')
async def delete_folder_by_id(
    request: Request,
    id: str,
    delete_contents: Optional[bool] = True,
    delete_project_directory: Optional[bool] = False,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_folders_permission(request, user, db=db)
    folder = await Folders.get_folder_by_id_and_user_id(id, user.id, db=db)

    if not folder:
        # Deletion cascades into the owner's data, so only the owner or an admin may delete
        folder = await Folders.get_folder_by_id(id, db=db)
        if not folder:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_MESSAGES.NOT_FOUND,
            )
        if user.role != 'admin':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    folder_owner_id = folder.user_id
    project_path = folder_project_path(folder)

    folder_ids = await Folders.get_folder_ids_by_id_and_user_id_in_subtree(id, folder_owner_id, db=db)
    if delete_contents and await Chats.count_chats_by_folder_ids_and_user_id(folder_ids, folder_owner_id, db=db):
        chat_delete_permission = await has_permission(
            user.id, 'chat.delete', await Config.get('user.permissions'), db=db
        )
        if user.role != 'admin' and not chat_delete_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
            )

    folders = []
    folders.append(folder)
    while folders:
        folder = folders.pop()
        if folder:
            try:
                folder_ids = await Folders.delete_folder_by_id_and_user_id(folder.id, folder_owner_id, db=db)

                for folder_id in folder_ids:
                    if delete_contents:
                        await Chats.delete_chats_by_user_id_and_folder_id(folder_owner_id, folder_id, db=db)

                    await Chats.move_chats_by_folder_id(folder_id, None, db=db)

                    # Clean up access grants for this folder
                    await AccessGrants.revoke_all_access('folder', folder_id, db=db)

                await Automations.clear_folder_ids(folder_owner_id, folder_ids, db=db)

                await publish_event(
                    request,
                    EVENTS.FOLDER_DELETED,
                    actor=user,
                    subject_id=id,
                    data={
                        'folder_ids': folder_ids,
                        'delete_contents': delete_contents,
                        'delete_project_directory': delete_project_directory,
                    },
                )
                if delete_project_directory and project_path is not None and project_path.exists():
                    if project_path.is_symlink() or project_path.parent != configured_projects_root():
                        raise ValueError('Project directory is outside the configured projects root')
                    shutil.rmtree(project_path)
                return True
            except Exception as e:
                log.exception(e)
                log.error(f'Error deleting folder: {id}')
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.DEFAULT('Error deleting folder'),
                )
            finally:
                # Get all subfolders
                subfolders = await Folders.get_folders_by_parent_id_and_user_id(folder.id, folder_owner_id, db=db)
                folders.extend(subfolders)

    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
