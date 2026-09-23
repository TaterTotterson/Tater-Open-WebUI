# Bundled local runtime

TaterChat includes its terminal and filesystem runtime in the FastAPI process. It does not require Open Terminal, Spudex, or a private Tater endpoint. A server-side agent planner presents these local tools to the normal model while all provider traffic continues through standard Chat Completions requests.

## Access model

The runtime intentionally has the same operating-system access as the TaterChat backend process. It can use absolute paths, move outside its starting workspace, inherit environment variables, run Git and package managers, start background processes, and open an interactive shell. Authentication is required for every HTTP and WebSocket entry point.

This is full access, not a filesystem sandbox. Run TaterChat only as an operating-system user whose permissions are appropriate for the files and credentials the model may reach. Do not expose it directly to the public internet.

## Working directories

Each user and chat pair gets an independent in-memory working directory. New contexts start at `TATERCHAT_WORKSPACE`, or the backend process working directory when that variable is unset. Changing one chat's directory does not change another chat or the backend process itself.

The working directory is reset when the backend restarts. Files and command side effects persist normally on disk.

For a native installation, set `TATERCHAT_WORKSPACE` to the initial project directory. Absolute paths remain available outside it.

Docker Compose mounts `TATERCHAT_HOST_WORKSPACE` at `/workspace`; when unset, it mounts the TaterChat repository itself. For example:

```dotenv
TATERCHAT_HOST_WORKSPACE=/Users/me/Projects
```

In Docker, "this computer" means the container filesystem plus paths explicitly mounted into it. Mount only the host directories the app should edit.

## Commands and processes

- Commands use the backend's configured login shell and inherit its environment.
- Foreground commands wait for completion; background commands return a process ID immediately.
- The terminal dock polls retained stdout/stderr by character offset, so command output appears incrementally without duplicating earlier chunks.
- The default timeout is 120 seconds and the maximum accepted timeout is one hour.
- Cancellation and timeout terminate the entire POSIX process group, then escalate to a forced kill if needed.
- Each chat retains at most 100 process records and up to 2,000,000 output characters per process. Tool results are capped at the latest 80,000 characters and report truncation.
- Interactive shells use a PTY and WebSocket and are currently supported on POSIX hosts.

## File operations

The model can list and search directories, read bounded text ranges, write files, apply exact replacements, and ask the UI to display a file. The file browser additionally supports uploads, downloads, folders, moves, deletion, text search, and ZIP archives.

Text reads are capped at 500,000 characters. Binary files are rejected by the text reader and remain available through the file viewer/download route. Exact replacement fails if its target is missing or ambiguous unless the caller explicitly requests replacement of all matches.

If an `AGENTS.md` file exists in the current directory or one of its parents, its instructions are added to the local-computer system prompt, from the broadest directory to the most specific.

## Tool routing

Local work stays in TaterChat:

- terminal commands, processes, Git, builds, tests, package managers;
- file inspection and edits;
- verification of changes on the machine running the backend.

The later `tater_hydra` tool is reserved for Tater capabilities such as connected devices, Verbas, Cores, Portals, media, and automations. Local execution must not be delegated to Hydra.
