from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

LOCAL_TERMINAL_ID = 'local'
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_TIMEOUT_SECONDS = 3600
MAX_PROCESS_OUTPUT_CHARS = 2_000_000
MAX_TOOL_OUTPUT_CHARS = 80_000
MAX_READ_CHARS = 500_000
MAX_CONTEXT_PROCESSES = 100


def configured_workspace() -> Path:
    value = os.getenv('TATERCHAT_WORKSPACE', os.getcwd())
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise RuntimeError(f'TATERCHAT_WORKSPACE is not a directory: {path}')
    return path


def resolve_path(path: str | None, cwd: Path) -> Path:
    if not path or path == '.':
        return cwd
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve(strict=False)


def file_entry(path: Path) -> dict[str, Any]:
    details = path.stat()
    return {
        'name': path.name,
        'type': 'directory' if path.is_dir() else 'file',
        'size': details.st_size,
        'modified': int(details.st_mtime * 1000),
        'writable': os.access(path, os.W_OK),
    }


def searchable_files(root: Path, pattern: str, include_hidden: bool):
    for candidate in root.rglob('*'):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root)
        if not include_hidden and any(part.startswith('.') for part in relative.parts):
            continue
        if not fnmatch.fnmatch(candidate.name, pattern):
            continue
        try:
            raw = candidate.read_bytes()
        except (OSError, PermissionError):
            continue
        if b'\x00' in raw[:8192] or len(raw) > 2_000_000:
            continue
        yield candidate, relative, raw.decode('utf-8', 'replace')


@dataclass
class OutputChunk:
    offset: int
    data: str
    type: str = 'stdout'

    @property
    def end(self) -> int:
        return self.offset + len(self.data)


@dataclass
class ProcessRecord:
    id: str
    command: str
    cwd: str
    created_at: float
    timeout_seconds: int | None
    status: str = 'running'
    exit_code: int | None = None
    timed_out: bool = False
    chunks: list[OutputChunk] = field(default_factory=list)
    first_offset: int = 0
    next_offset: int = 0
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)
    started: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    done: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def append(self, data: str, stream: str = 'stdout') -> None:
        if not data:
            return
        self.chunks.append(OutputChunk(offset=self.next_offset, data=data, type=stream))
        self.next_offset += len(data)
        retained = self.next_offset - self.first_offset
        while self.chunks and retained > MAX_PROCESS_OUTPUT_CHARS:
            removed = self.chunks.pop(0)
            self.first_offset = removed.end
            retained = self.next_offset - self.first_offset

    def summary(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'command': self.command,
            'cwd': self.cwd,
            'status': self.status,
            'exit_code': self.exit_code,
            'created_at': self.created_at,
            'timed_out': self.timed_out,
        }

    def output_since(self, offset: int = 0, max_chars: int | None = None) -> dict[str, Any]:
        requested_offset = max(0, offset)
        effective_offset = max(requested_offset, self.first_offset)
        if max_chars is not None:
            effective_offset = max(effective_offset, self.next_offset - max(1, int(max_chars)))
        output = []
        for chunk in self.chunks:
            if chunk.end <= effective_offset:
                continue
            data = chunk.data
            if chunk.offset < effective_offset:
                data = data[effective_offset - chunk.offset :]
            output.append({'type': chunk.type, 'data': data})
        return {
            **self.summary(),
            'output': output,
            'next_offset': self.next_offset,
            'truncated': effective_offset > requested_offset,
        }

    def tool_result(self) -> dict[str, Any]:
        output = ''.join(chunk.data for chunk in self.chunks)
        truncated = self.first_offset > 0
        if len(output) > MAX_TOOL_OUTPUT_CHARS:
            output = output[-MAX_TOOL_OUTPUT_CHARS:]
            truncated = True
        return {
            **self.summary(),
            'output': output,
            'truncated': truncated,
        }


@dataclass
class RuntimeContext:
    cwd: Path
    processes: dict[str, ProcessRecord] = field(default_factory=dict)


class LocalTerminalRuntime:
    def __init__(self, workspace: Path | None = None):
        self.workspace = (workspace or configured_workspace()).resolve()
        self._contexts: dict[str, RuntimeContext] = {}

    @staticmethod
    def context_key(user_id: str, session_id: str | None) -> str:
        return f'{user_id}:{session_id or "default"}'

    def context(self, user_id: str, session_id: str | None) -> RuntimeContext:
        key = self.context_key(user_id, session_id)
        if key not in self._contexts:
            self._contexts[key] = RuntimeContext(cwd=self.workspace)
        return self._contexts[key]

    def get_cwd(self, user_id: str, session_id: str | None) -> Path:
        return self.context(user_id, session_id).cwd

    def set_cwd(self, user_id: str, session_id: str | None, path: str) -> Path:
        context = self.context(user_id, session_id)
        resolved = resolve_path(path, context.cwd)
        if not resolved.is_dir():
            raise ValueError(f'Working directory does not exist: {resolved}')
        context.cwd = resolved
        return resolved

    def resolve(self, user_id: str, session_id: str | None, path: str | None) -> Path:
        return resolve_path(path, self.get_cwd(user_id, session_id))

    def _prune_processes(self, context: RuntimeContext) -> None:
        if len(context.processes) < MAX_CONTEXT_PROCESSES:
            return
        finished = sorted(
            (record for record in context.processes.values() if record.status != 'running'),
            key=lambda record: record.created_at,
        )
        for record in finished[: max(1, len(context.processes) - MAX_CONTEXT_PROCESSES + 1)]:
            context.processes.pop(record.id, None)

    async def start_command(
        self,
        user_id: str,
        session_id: str | None,
        command: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int | None = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    ) -> ProcessRecord:
        command = command.strip()
        if not command:
            raise ValueError('Command is required')

        context = self.context(user_id, session_id)
        if cwd:
            context.cwd = self.set_cwd(user_id, session_id, cwd)

        if timeout_seconds is not None:
            timeout_seconds = max(1, min(int(timeout_seconds), MAX_COMMAND_TIMEOUT_SECONDS))

        self._prune_processes(context)
        record = ProcessRecord(
            id=uuid4().hex,
            command=command,
            cwd=str(context.cwd),
            created_at=time.time(),
            timeout_seconds=timeout_seconds,
        )
        context.processes[record.id] = record
        record.task = asyncio.create_task(self._run_process(record))
        return record

    async def _run_process(self, record: ProcessRecord) -> None:
        shell = os.getenv('SHELL') or ('/bin/sh' if os.name == 'posix' else 'cmd.exe')
        arguments = [shell, '-lc', record.command] if os.name == 'posix' else [shell, '/c', record.command]
        try:
            record.process = await asyncio.create_subprocess_exec(
                *arguments,
                cwd=record.cwd,
                env=os.environ.copy(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=os.name == 'posix',
            )
            record.started.set()

            async def drain_output() -> None:
                assert record.process and record.process.stdout
                while True:
                    chunk = await record.process.stdout.read(8192)
                    if not chunk:
                        break
                    record.append(chunk.decode('utf-8', 'replace'))

            reader = asyncio.create_task(drain_output())
            try:
                if record.timeout_seconds is None:
                    await record.process.wait()
                else:
                    await asyncio.wait_for(record.process.wait(), timeout=record.timeout_seconds)
            except TimeoutError:
                record.timed_out = True
                await self._terminate_process(record)
            finally:
                await reader

            record.exit_code = record.process.returncode
            if record.status == 'running':
                record.status = 'done'
        except asyncio.CancelledError:
            await self._terminate_process(record)
            raise
        except Exception as exc:
            record.append(f'Failed to start command: {exc}\n', 'stderr')
            record.exit_code = -1
            record.status = 'done'
        finally:
            record.started.set()
            record.done.set()

    async def _terminate_process(self, record: ProcessRecord) -> None:
        process = record.process
        if process is None and record.task and not record.task.done():
            try:
                await asyncio.wait_for(record.started.wait(), timeout=3)
            except TimeoutError:
                record.task.cancel()
            process = record.process
        if not process or process.returncode is not None:
            if record.status == 'running':
                record.status = 'killed'
            return

        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            await asyncio.wait_for(process.wait(), timeout=3)
        except (ProcessLookupError, TimeoutError):
            if process.returncode is None:
                try:
                    if os.name == 'posix':
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
        record.status = 'killed'
        record.exit_code = process.returncode

    async def run_command(
        self,
        user_id: str,
        session_id: str | None,
        command: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int | None = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        background: bool = False,
    ) -> dict[str, Any]:
        record = await self.start_command(
            user_id,
            session_id,
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
        )
        if background:
            return record.tool_result()
        await record.done.wait()
        return record.tool_result()

    def list_processes(self, user_id: str, session_id: str | None) -> list[dict[str, Any]]:
        context = self.context(user_id, session_id)
        return [record.summary() for record in sorted(context.processes.values(), key=lambda item: item.created_at)]

    def get_process(self, user_id: str, session_id: str | None, process_id: str) -> ProcessRecord:
        record = self.context(user_id, session_id).processes.get(process_id)
        if not record:
            raise KeyError(process_id)
        return record

    async def kill_process(self, user_id: str, session_id: str | None, process_id: str) -> dict[str, Any]:
        record = self.get_process(user_id, session_id, process_id)
        await self._terminate_process(record)
        record.done.set()
        return record.summary()

    def list_files(
        self,
        user_id: str,
        session_id: str | None,
        path: str | None = '.',
        *,
        recursive: bool = False,
        max_entries: int = 500,
    ) -> dict[str, Any]:
        directory = self.resolve(user_id, session_id, path)
        if not directory.is_dir():
            raise ValueError(f'Not a directory: {directory}')
        max_entries = max(1, min(int(max_entries), 5000))
        iterator = directory.rglob('*') if recursive else directory.iterdir()
        entries = []
        for item in sorted(iterator, key=lambda value: str(value).lower()):
            try:
                entry = file_entry(item)
            except (FileNotFoundError, PermissionError):
                continue
            entry['path'] = str(item)
            entry['relative_path'] = str(item.relative_to(directory))
            entries.append(entry)
            if len(entries) >= max_entries:
                break
        return {
            'path': str(directory),
            'entries': entries,
            'writable': os.access(directory, os.W_OK),
            'truncated': len(entries) >= max_entries,
        }

    def read_file(
        self,
        user_id: str,
        session_id: str | None,
        path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        resolved = self.resolve(user_id, session_id, path)
        if not resolved.is_file():
            raise FileNotFoundError(str(resolved))
        raw = resolved.read_bytes()
        if b'\x00' in raw[:8192]:
            raise ValueError(f'Binary file cannot be read as text: {resolved}')
        text = raw.decode('utf-8', 'replace')
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        start = max(1, int(start_line or 1))
        end = min(total_lines, int(end_line or total_lines))
        content = ''.join(lines[start - 1 : end])
        truncated = False
        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS]
            truncated = True
        return {
            'path': str(resolved),
            'content': content,
            'start_line': start,
            'end_line': end,
            'total_lines': total_lines,
            'truncated': truncated,
        }

    def write_file(
        self,
        user_id: str,
        session_id: str | None,
        path: str,
        content: str,
        *,
        create_parents: bool = True,
    ) -> dict[str, Any]:
        resolved = self.resolve(user_id, session_id, path)
        if create_parents:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding='utf-8')
        return {'path': str(resolved), 'bytes_written': len(content.encode('utf-8'))}

    def replace_file_content(
        self,
        user_id: str,
        session_id: str | None,
        path: str,
        old: str,
        new: str,
        *,
        replace_all: bool = False,
    ) -> dict[str, Any]:
        resolved = self.resolve(user_id, session_id, path)
        content = resolved.read_text(encoding='utf-8')
        occurrences = content.count(old)
        if occurrences == 0:
            raise ValueError('The requested text was not found in the file')
        if occurrences > 1 and not replace_all:
            raise ValueError(f'The requested text occurs {occurrences} times; set replace_all to replace every match')
        updated = content.replace(old, new) if replace_all else content.replace(old, new, 1)
        resolved.write_text(updated, encoding='utf-8')
        return {'path': str(resolved), 'replacements': occurrences if replace_all else 1}

    def search_files(
        self,
        user_id: str,
        session_id: str | None,
        query: str,
        *,
        path: str | None = '.',
        glob: str = '*',
        max_results: int = 100,
        include_hidden: bool = False,
    ) -> dict[str, Any]:
        root = self.resolve(user_id, session_id, path)
        if not root.is_dir():
            raise ValueError(f'Not a directory: {root}')
        needle = query.casefold()
        max_results = max(1, min(int(max_results), 1000))
        results = []
        for candidate, relative, text in searchable_files(root, glob, include_hidden):
            for line_number, line in enumerate(text.splitlines(), start=1):
                column = line.casefold().find(needle)
                if column == -1:
                    continue
                results.append(
                    {
                        'path': str(candidate),
                        'relative_path': str(relative),
                        'line': line_number,
                        'column': column + 1,
                        'text': line[:1000],
                    }
                )
                if len(results) >= max_results:
                    return {'results': results, 'truncated': True}
        return {'results': results, 'truncated': False}

    def delete_entry(self, user_id: str, session_id: str | None, path: str) -> dict[str, Any]:
        resolved = self.resolve(user_id, session_id, path)
        entry_type = 'directory' if resolved.is_dir() else 'file'
        if resolved.is_dir() and not resolved.is_symlink():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return {'path': str(resolved), 'type': entry_type}

    def move_entry(
        self,
        user_id: str,
        session_id: str | None,
        source: str,
        destination: str,
    ) -> dict[str, Any]:
        source_path = self.resolve(user_id, session_id, source)
        destination_path = self.resolve(user_id, session_id, destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        return {'source': str(source_path), 'destination': str(destination_path)}

    def make_directory(self, user_id: str, session_id: str | None, path: str) -> dict[str, Any]:
        resolved = self.resolve(user_id, session_id, path)
        resolved.mkdir(parents=True, exist_ok=True)
        return {'path': str(resolved)}


local_terminal_runtime = LocalTerminalRuntime()
