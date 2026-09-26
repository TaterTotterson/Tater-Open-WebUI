# Bundled local runtime

Tater WebUI includes its terminal runtime in the FastAPI process. It does not require Open Terminal, Spudex, or a private Tater endpoint. A server-side agent planner presents shell and process tools to the normal model while all provider traffic continues through standard Chat Completions requests.

## Access model

The runtime intentionally has the same operating-system access as the Tater WebUI backend process. It can use absolute paths, move outside its starting workspace, inherit environment variables, run Git and package managers, start background processes, and open an interactive shell. Authentication is required for every HTTP and WebSocket entry point.

This is full access, not a filesystem sandbox. Run Tater WebUI only as an operating-system user whose permissions are appropriate for the files and credentials the model may reach. Do not expose it directly to the public internet.

## Working directories

Each user and chat pair gets an independent in-memory working directory. New contexts start at `TATER_WEBUI_WORKSPACE`, or the backend process working directory when that variable is unset. Changing one chat's directory does not change another chat or the backend process itself.

The working directory is reset when the backend restarts. Files and command side effects persist normally on disk.

For a native installation, set `TATER_WEBUI_WORKSPACE` to the initial project directory. Absolute paths remain available outside it.

Docker Compose mounts `TATER_WEBUI_HOST_WORKSPACE` at `/workspace`; when unset, it mounts the Tater WebUI repository itself. For example:

```dotenv
TATER_WEBUI_HOST_WORKSPACE=/Users/me/Projects
```

In Docker, "this computer" means the container filesystem plus paths explicitly mounted into it. Mount only the host directories the app should edit.

## Commands and processes

- Commands use the backend's configured login shell and inherit its environment.
- Foreground commands wait for completion; background commands return a process ID immediately.
- The model can list chat-owned processes, read retained output incrementally, wait briefly for completion, and terminate a process by ID.
- The terminal dock polls retained stdout/stderr by character offset, so command output appears incrementally without duplicating earlier chunks.
- The default timeout is 120 seconds and the maximum accepted timeout is one hour.
- Cancellation and timeout terminate the entire POSIX process group, then escalate to a forced kill if needed.
- Each chat retains at most 100 process records and up to 2,000,000 output characters per process. Tool results are capped at the latest 80,000 characters and report truncation.
- Interactive shells use a PTY and WebSocket and are currently supported on POSIX hosts.

## Terminal-first file operations

The model performs local inspection and changes through `run_command`, using ordinary shell tools such as `pwd`, `ls`, `find`, `rg`, `sed`, `cat`, Git, editors, and build tools. Filesystem convenience functions are not advertised to the model, so directory listings and file edits remain visible as real terminal commands. `display_file` remains available only to present an image, audio file, PDF, or other rendered artifact in the UI.

The file browser independently supports uploads, downloads, folders, moves, deletion, text search, ZIP archives, and file viewing. Those HTTP endpoints support the UI and are not part of the model's tool catalog.

If an `AGENTS.md` file exists in the current directory or one of its parents, its instructions are added to the local-computer system prompt, from the broadest directory to the most specific.

Shell calls declare whether they inspect, change, or verify state. After the latest change, `verify_command` runs the appropriate test, build, lint, diff, or status check; a timeout or nonzero exit code is a failed verification.

## Tool routing

Local work stays in Tater WebUI:

- terminal commands, processes, Git, builds, tests, package managers;
- file inspection and edits;
- verification of changes on the machine running the backend.

The later `tater_hydra` tool is reserved for Tater capabilities such as connected devices, Verbas, Cores, Portals, media, and automations. Local execution must not be delegated to Hydra.
