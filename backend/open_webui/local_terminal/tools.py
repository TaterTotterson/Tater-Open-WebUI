from __future__ import annotations

from pathlib import Path
from typing import Any

from open_webui.local_terminal.runtime import LOCAL_TERMINAL_ID, local_terminal_runtime


def _tool_spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        'name': name,
        'description': description,
        'parameters': {
            'type': 'object',
            'properties': properties,
            'required': required,
            'additionalProperties': False,
        },
    }


LOCAL_TERMINAL_TOOL_SPECS = {
    'run_command': _tool_spec(
        'run_command',
        (
            'Run a shell command with unrestricted access on the TaterChat host. '
            'Use this for repository inspection, builds, tests, package management, Git, and processes. '
            'Commands run in the chat working directory unless cwd is provided. Output is bounded and '
            'long-running commands can be started in the background.'
        ),
        {
            'command': {'type': 'string', 'description': 'The shell command to execute.'},
            'cwd': {
                'type': 'string',
                'description': 'Optional absolute or current-working-directory-relative directory.',
            },
            'timeout_seconds': {
                'type': 'integer',
                'minimum': 1,
                'maximum': 3600,
                'default': 120,
                'description': 'Maximum runtime for a foreground or background command.',
            },
            'background': {
                'type': 'boolean',
                'default': False,
                'description': 'Return immediately while the process continues and streams to the terminal dock.',
            },
        },
        ['command'],
    ),
    'read_file': _tool_spec(
        'read_file',
        'Read a UTF-8 text file, optionally limiting the result to an inclusive line range.',
        {
            'path': {'type': 'string', 'description': 'Absolute path or path relative to the chat working directory.'},
            'start_line': {'type': 'integer', 'minimum': 1},
            'end_line': {'type': 'integer', 'minimum': 1},
        },
        ['path'],
    ),
    'write_file': _tool_spec(
        'write_file',
        'Create or fully overwrite a UTF-8 text file. Prefer replace_file_content for focused edits.',
        {
            'path': {'type': 'string', 'description': 'Absolute path or path relative to the chat working directory.'},
            'content': {'type': 'string', 'description': 'Complete file content to write.'},
            'create_parents': {'type': 'boolean', 'default': True},
        },
        ['path', 'content'],
    ),
    'replace_file_content': _tool_spec(
        'replace_file_content',
        (
            'Replace exact text in a UTF-8 file. The edit fails when the text is absent or occurs more than once '
            'unless replace_all is true, which prevents accidental broad edits.'
        ),
        {
            'path': {'type': 'string', 'description': 'Absolute path or path relative to the chat working directory.'},
            'old': {'type': 'string', 'description': 'Exact existing text.'},
            'new': {'type': 'string', 'description': 'Replacement text.'},
            'replace_all': {'type': 'boolean', 'default': False},
        },
        ['path', 'old', 'new'],
    ),
    'list_files': _tool_spec(
        'list_files',
        'List files and directories with absolute and relative paths.',
        {
            'path': {'type': 'string', 'default': '.'},
            'recursive': {'type': 'boolean', 'default': False},
            'max_entries': {'type': 'integer', 'minimum': 1, 'maximum': 5000, 'default': 500},
        },
        [],
    ),
    'search_files': _tool_spec(
        'search_files',
        'Search text files recursively and return matching paths, lines, columns, and excerpts.',
        {
            'query': {'type': 'string', 'description': 'Literal case-insensitive text to find.'},
            'path': {'type': 'string', 'default': '.'},
            'glob': {'type': 'string', 'default': '*', 'description': 'Filename glob such as *.py.'},
            'max_results': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 100},
            'include_hidden': {'type': 'boolean', 'default': False},
        },
        ['query'],
    ),
    'set_working_directory': _tool_spec(
        'set_working_directory',
        'Set the persistent working directory for this chat and subsequent local tools.',
        {'path': {'type': 'string', 'description': 'An existing directory.'}},
        ['path'],
    ),
    'display_file': _tool_spec(
        'display_file',
        'Open an existing host file in the TaterChat file viewer.',
        {
            'path': {'type': 'string', 'description': 'Absolute path or path relative to the chat working directory.'},
            'page': {'type': 'integer', 'minimum': 1, 'description': 'Optional PDF page to show.'},
            'inline': {'type': 'boolean', 'default': False},
        },
        ['path'],
    ),
}


def _agents_instructions(cwd: str) -> str:
    directory = Path(cwd)
    candidates = [directory, *directory.parents]
    sections = []
    total_bytes = 0
    for parent in reversed(candidates):
        instructions = parent / 'AGENTS.md'
        if not instructions.is_file():
            continue
        try:
            content = instructions.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        encoded_size = len(content.encode('utf-8'))
        if total_bytes + encoded_size > 64 * 1024:
            break
        total_bytes += encoded_size
        sections.append(f'## Instructions from {instructions}\n\n{content.strip()}')
    return '\n\n'.join(sections)


def local_terminal_system_prompt(cwd: str) -> str:
    prompt = f"""You have unrestricted local computer tools on the TaterChat host.

Current working directory: {cwd}

- Use the local tools for terminal commands, filesystem work, processes, Git, builds, tests, and inspection.
- Inspect relevant files before editing and preserve unrelated user changes.
- Prefer focused file edits. Verify changes with the appropriate tests or checks before claiming completion.
- Continue after each tool result until the requested outcome is complete or genuinely blocked.
- Use background commands only when a process must remain running; inspect their status or output as needed.
- Treat destructive or materially ambiguous operations cautiously and explain blockers concretely.
"""
    agents_instructions = _agents_instructions(cwd)
    if agents_instructions:
        prompt += f'\nFollow these workspace instructions:\n\n{agents_instructions}\n'
    return prompt


def get_local_terminal_tools(user_id: str, session_id: str | None) -> tuple[dict[str, dict], str]:
    runtime = local_terminal_runtime

    async def run_command(
        command: str,
        cwd: str | None = None,
        timeout_seconds: int = 120,
        background: bool = False,
    ):
        return await runtime.run_command(
            user_id,
            session_id,
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            background=background,
        )

    async def read_file(path: str, start_line: int | None = None, end_line: int | None = None):
        return runtime.read_file(
            user_id,
            session_id,
            path,
            start_line=start_line,
            end_line=end_line,
        )

    async def write_file(path: str, content: str, create_parents: bool = True):
        return runtime.write_file(
            user_id,
            session_id,
            path,
            content,
            create_parents=create_parents,
        )

    async def replace_file_content(
        path: str,
        old: str,
        new: str,
        replace_all: bool = False,
    ):
        return runtime.replace_file_content(
            user_id,
            session_id,
            path,
            old,
            new,
            replace_all=replace_all,
        )

    async def list_files(path: str = '.', recursive: bool = False, max_entries: int = 500):
        return runtime.list_files(
            user_id,
            session_id,
            path,
            recursive=recursive,
            max_entries=max_entries,
        )

    async def search_files(
        query: str,
        path: str = '.',
        glob: str = '*',
        max_results: int = 100,
        include_hidden: bool = False,
    ):
        return runtime.search_files(
            user_id,
            session_id,
            query,
            path=path,
            glob=glob,
            max_results=max_results,
            include_hidden=include_hidden,
        )

    async def set_working_directory(path: str):
        cwd = runtime.set_cwd(user_id, session_id, path)
        return {'cwd': str(cwd)}

    async def display_file(path: str, page: int | None = None, inline: bool = False):
        resolved = runtime.resolve(user_id, session_id, path)
        return {
            'path': str(resolved),
            'full_path': str(resolved),
            'name': resolved.name,
            'exists': resolved.is_file(),
            **({'page': page} if page else {}),
        }

    callables: dict[str, Any] = {
        'run_command': run_command,
        'read_file': read_file,
        'write_file': write_file,
        'replace_file_content': replace_file_content,
        'list_files': list_files,
        'search_files': search_files,
        'set_working_directory': set_working_directory,
        'display_file': display_file,
    }
    tools = {
        name: {
            'tool_id': f'terminal:{LOCAL_TERMINAL_ID}',
            'callable': callable,
            'spec': LOCAL_TERMINAL_TOOL_SPECS[name],
            'type': 'terminal',
        }
        for name, callable in callables.items()
    }
    cwd = str(runtime.get_cwd(user_id, session_id))
    return tools, local_terminal_system_prompt(cwd)
