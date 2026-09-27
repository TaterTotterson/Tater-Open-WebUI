from __future__ import annotations

import asyncio
import mimetypes
import os
import signal
import struct
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse
from open_webui.local_terminal.runtime import local_terminal_runtime
from open_webui.local_terminal.tools import local_terminal_system_prompt
from open_webui.utils.auth import get_verified_user, get_verified_user_by_token
from open_webui.utils.json_codec import JSONCodec
from pydantic import BaseModel
from starlette.background import BackgroundTask

router = APIRouter()


def _session_id(request: Request) -> str | None:
    value = request.headers.get('x-session-id')
    return value if value else None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail='Process not found')
    if isinstance(exc, (ValueError, NotADirectoryError, IsADirectoryError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


class PathForm(BaseModel):
    path: str


class MoveForm(BaseModel):
    source: str
    destination: str


class ArchiveForm(BaseModel):
    paths: list[str]


class ExecuteForm(BaseModel):
    command: str
    cwd: str | None = None
    timeout_seconds: int | None = 120
    background: bool = True


@router.get('/local/api/config')
async def get_local_terminal_config(user=Depends(get_verified_user)):
    return {
        'features': {
            'terminal': os.name == 'posix',
            'system': True,
            'files': True,
            'execute': True,
        }
    }


@router.get('/local/system')
async def get_local_terminal_system(request: Request, user=Depends(get_verified_user)):
    cwd = local_terminal_runtime.get_cwd(user.id, _session_id(request))
    return {'prompt': local_terminal_system_prompt(str(cwd))}


@router.get('/local/files/cwd')
async def get_cwd(request: Request, user=Depends(get_verified_user)):
    cwd = local_terminal_runtime.get_cwd(user.id, _session_id(request))
    return {
        'cwd': str(cwd),
        'home': str(Path.home()),
        'root': {'path': '/', 'label': 'Host filesystem'},
    }


@router.post('/local/files/cwd')
async def set_cwd(request: Request, form_data: PathForm, user=Depends(get_verified_user)):
    try:
        cwd = local_terminal_runtime.set_cwd(user.id, _session_id(request), form_data.path)
        return {'cwd': str(cwd)}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/files/list')
async def list_files(
    request: Request,
    directory: str = '.',
    user=Depends(get_verified_user),
):
    try:
        return local_terminal_runtime.list_files(user.id, _session_id(request), directory)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/files/read')
async def read_file(
    request: Request,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    user=Depends(get_verified_user),
):
    try:
        return local_terminal_runtime.read_file(
            user.id,
            _session_id(request),
            path,
            start_line=start_line,
            end_line=end_line,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/files/view')
async def view_file(request: Request, path: str, preview: bool = False, user=Depends(get_verified_user)):
    try:
        resolved = local_terminal_runtime.resolve(user.id, _session_id(request), path)
        if not resolved.is_file():
            raise FileNotFoundError(str(resolved))
        media_type, _ = mimetypes.guess_type(resolved.name)
        return FileResponse(
            resolved,
            media_type=media_type or 'application/octet-stream',
            filename=None if preview else resolved.name,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/files/search')
async def search_file_names(
    request: Request,
    query: str = '',
    path: str = '.',
    limit: int = Query(20, ge=1, le=1000),
    type: str = 'any',
    show_hidden: bool = False,
    user=Depends(get_verified_user),
):
    try:
        listing = local_terminal_runtime.list_files(
            user.id,
            _session_id(request),
            path,
            recursive=True,
            max_entries=5000,
        )
        query_folded = query.casefold()
        results = []
        for entry in listing['entries']:
            relative = Path(entry['relative_path'])
            if not show_hidden and any(part.startswith('.') for part in relative.parts):
                continue
            if type in {'file', 'directory'} and entry['type'] != type:
                continue
            if query_folded and query_folded not in entry['name'].casefold():
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return {'results': results}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/files/glob')
async def glob_files(
    request: Request,
    pattern: str = '*',
    path: str = '.',
    type: str = 'any',
    max_results: int = Query(100, ge=1, le=5000),
    user=Depends(get_verified_user),
):
    try:
        root = local_terminal_runtime.resolve(user.id, _session_id(request), path)
        if not root.is_dir():
            raise ValueError(f'Not a directory: {root}')
        matches = []
        for candidate in root.rglob(pattern):
            candidate_type = 'directory' if candidate.is_dir() else 'file'
            if type in {'file', 'directory'} and candidate_type != type:
                continue
            matches.append(
                {
                    'path': str(candidate.relative_to(root)),
                    'type': candidate_type,
                    'size': candidate.stat().st_size,
                    'modified': int(candidate.stat().st_mtime * 1000),
                }
            )
            if len(matches) >= max_results:
                break
        return {'path': str(root), 'matches': matches}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/files/matches')
async def content_matches(
    request: Request,
    query: str,
    path: str = '.',
    show_hidden: bool = False,
    offset: int = Query(0, ge=0),
    user=Depends(get_verified_user),
):
    try:
        result = local_terminal_runtime.search_files(
            user.id,
            _session_id(request),
            query,
            path=path,
            max_results=500,
            include_hidden=show_hidden,
        )
        grouped: dict[str, dict] = {}
        for match in result['results']:
            item = grouped.setdefault(
                match['path'],
                {
                    'path': match['path'],
                    'relative_path': match['relative_path'],
                    'name': Path(match['path']).name,
                    'type': 'file',
                    'name_match': query.casefold() in Path(match['path']).name.casefold(),
                    'content_matches': [],
                },
            )
            item['content_matches'].append(
                {
                    'line': match['line'],
                    'column': match['column'],
                    'text': match['text'],
                }
            )
        items = list(grouped.values())
        page = items[offset : offset + 50]
        next_offset = offset + len(page) if offset + len(page) < len(items) else None
        return {'results': page, 'next_offset': next_offset}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post('/local/files/upload')
async def upload_file(
    request: Request,
    directory: str = '.',
    file: UploadFile = File(...),
    user=Depends(get_verified_user),
):
    try:
        target_directory = local_terminal_runtime.resolve(user.id, _session_id(request), directory)
        if not target_directory.is_dir():
            raise ValueError(f'Not a directory: {target_directory}')
        filename = Path(file.filename or 'upload').name
        target = target_directory / filename
        with target.open('wb') as destination:
            while chunk := await file.read(1024 * 1024):
                destination.write(chunk)
        return {'path': str(target), 'size': target.stat().st_size}
    except Exception as exc:
        raise _http_error(exc) from exc
    finally:
        await file.close()


@router.post('/local/files/mkdir')
async def make_directory(request: Request, form_data: PathForm, user=Depends(get_verified_user)):
    try:
        return local_terminal_runtime.make_directory(user.id, _session_id(request), form_data.path)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete('/local/files/delete')
async def delete_entry(request: Request, path: str, user=Depends(get_verified_user)):
    try:
        return local_terminal_runtime.delete_entry(user.id, _session_id(request), path)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post('/local/files/move')
async def move_entry(request: Request, form_data: MoveForm, user=Depends(get_verified_user)):
    try:
        return local_terminal_runtime.move_entry(
            user.id,
            _session_id(request),
            form_data.source,
            form_data.destination,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


def _remove_temp_file(path: str) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


@router.post('/local/files/archive')
async def archive_files(request: Request, form_data: ArchiveForm, user=Depends(get_verified_user)):
    if not form_data.paths:
        raise HTTPException(status_code=400, detail='At least one path is required')
    try:
        paths = [local_terminal_runtime.resolve(user.id, _session_id(request), path) for path in form_data.paths]
        for path in paths:
            if not path.exists():
                raise FileNotFoundError(str(path))

        temporary = tempfile.NamedTemporaryFile(prefix='tater-open-webui-', suffix='.zip', delete=False)
        temporary.close()

        def create_archive() -> None:
            with zipfile.ZipFile(temporary.name, 'w', zipfile.ZIP_DEFLATED) as archive:
                for source in paths:
                    if source.is_dir():
                        for item in source.rglob('*'):
                            if item.is_file():
                                archive.write(item, arcname=str(Path(source.name) / item.relative_to(source)))
                    else:
                        archive.write(source, arcname=source.name)

        await asyncio.to_thread(create_archive)
        return FileResponse(
            temporary.name,
            media_type='application/zip',
            filename='tater-open-webui-files.zip',
            background=BackgroundTask(_remove_temp_file, temporary.name),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/execute')
async def list_processes(request: Request, user=Depends(get_verified_user)):
    return local_terminal_runtime.list_processes(user.id, _session_id(request))


@router.post('/local/execute')
async def execute(request: Request, form_data: ExecuteForm, user=Depends(get_verified_user)):
    try:
        return await local_terminal_runtime.run_command(
            user.id,
            _session_id(request),
            form_data.command,
            cwd=form_data.cwd,
            timeout_seconds=form_data.timeout_seconds,
            background=form_data.background,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get('/local/execute/{process_id}/status')
async def process_status(
    request: Request,
    process_id: str,
    wait: float = Query(0, ge=0, le=30),
    offset: int = Query(0, ge=0),
    tail: int = Query(1000, ge=1, le=100000),
    user=Depends(get_verified_user),
):
    try:
        record = local_terminal_runtime.get_process(user.id, _session_id(request), process_id)
        if wait and record.status == 'running':
            try:
                await asyncio.wait_for(record.done.wait(), timeout=wait)
            except TimeoutError:
                pass
        return record.output_since(offset)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete('/local/execute/{process_id}')
async def kill_process(request: Request, process_id: str, user=Depends(get_verified_user)):
    try:
        return await local_terminal_runtime.kill_process(user.id, _session_id(request), process_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@dataclass
class InteractiveTerminalSession:
    id: str
    user_id: str
    chat_id: str | None
    created_at: float
    process: asyncio.subprocess.Process | None = None
    master_fd: int | None = None


interactive_sessions: dict[str, InteractiveTerminalSession] = {}


@router.post('/local/api/terminals')
async def create_terminal_session(request: Request, user=Depends(get_verified_user)):
    if os.name != 'posix':
        raise HTTPException(status_code=501, detail='Interactive terminals currently require a POSIX host')
    session = InteractiveTerminalSession(
        id=uuid4().hex,
        user_id=user.id,
        chat_id=_session_id(request),
        created_at=time.time(),
    )
    interactive_sessions[session.id] = session
    return {'id': session.id}


async def _close_interactive_session(session: InteractiveTerminalSession) -> None:
    if session.master_fd is not None:
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        session.master_fd = None
    process = session.process
    if process and process.returncode is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            await asyncio.wait_for(process.wait(), timeout=2)
        except (ProcessLookupError, TimeoutError):
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                except ProcessLookupError:
                    pass


@router.delete('/local/api/terminals/{session_id}')
async def delete_terminal_session(session_id: str, user=Depends(get_verified_user)):
    session = interactive_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Terminal session not found')
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail='Access denied')
    interactive_sessions.pop(session_id, None)
    await _close_interactive_session(session)
    return {'id': session_id, 'closed': True}


def _resize_pty(master_fd: int, cols: int, rows: int) -> None:
    import fcntl
    import termios

    size = struct.pack('HHHH', max(1, rows), max(1, cols), 0, 0)
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, size)


async def _authenticate_terminal_socket(ws: WebSocket, session: InteractiveTerminalSession) -> bool:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        payload = JSONCodec.loads(raw)
        if payload.get('type') != 'auth':
            raise ValueError('Expected auth message')
        user = await get_verified_user_by_token(payload.get('token', ''), getattr(ws.app.state, 'redis', None))
        if user is None or user.id != session.user_id:
            await ws.close(code=4001, reason='Invalid token')
            return False
    except Exception:
        await ws.close(code=4001, reason='Authentication failed')
        return False
    return True


async def _start_interactive_shell(session: InteractiveTerminalSession) -> int:
    import pty

    master_fd, slave_fd = pty.openpty()
    session.master_fd = master_fd
    shell = os.getenv('SHELL') or '/bin/sh'
    cwd = local_terminal_runtime.get_cwd(session.user_id, session.chat_id)
    environment = os.environ.copy()
    environment.setdefault('TERM', 'xterm-256color')

    try:
        session.process = await asyncio.create_subprocess_exec(
            shell,
            '-l',
            cwd=str(cwd),
            env=environment,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
        )
    except Exception:
        os.close(master_fd)
        session.master_fd = None
        raise
    finally:
        os.close(slave_fd)
    return master_fd


async def _terminal_to_client(ws: WebSocket, master_fd: int) -> None:
    while True:
        try:
            data = await asyncio.to_thread(os.read, master_fd, 8192)
        except OSError:
            return
        if not data:
            return
        await ws.send_bytes(data)


async def _client_to_terminal(ws: WebSocket, master_fd: int) -> None:
    while True:
        message = await ws.receive()
        if message['type'] == 'websocket.disconnect':
            return
        if message.get('bytes'):
            await asyncio.to_thread(os.write, master_fd, message['bytes'])
            continue
        text = message.get('text')
        if not text:
            continue
        try:
            event = JSONCodec.loads(text)
        except Exception:
            await asyncio.to_thread(os.write, master_fd, text.encode())
            continue
        if event.get('type') == 'resize':
            _resize_pty(master_fd, int(event.get('cols', 80)), int(event.get('rows', 24)))
        elif event.get('type') != 'ping':
            await asyncio.to_thread(os.write, master_fd, text.encode())


@router.websocket('/local/api/terminals/{session_id}')
async def interactive_terminal(ws: WebSocket, session_id: str):
    await ws.accept()
    session = interactive_sessions.get(session_id)
    if not session:
        await ws.close(code=4004, reason='Terminal session not found')
        return

    if not await _authenticate_terminal_socket(ws, session):
        return

    tasks: list[asyncio.Task] = []
    try:
        master_fd = await _start_interactive_shell(session)
        tasks = [
            asyncio.create_task(_terminal_to_client(ws, master_fd)),
            asyncio.create_task(_client_to_terminal(ws, master_fd)),
        ]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        interactive_sessions.pop(session_id, None)
        await _close_interactive_session(session)
        try:
            await ws.close()
        except Exception:
            pass
