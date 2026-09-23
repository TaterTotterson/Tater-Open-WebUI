# TaterChat architecture

## Product boundary

TaterChat is a standalone computer-agent application derived from Open WebUI. It does not run inside the Tater repository and does not use Spudex for local execution.

TaterChat owns:

- the browser chat interface;
- chat history, branching, authentication, and local settings;
- the agent/tool loop;
- unrestricted terminal, filesystem, process, and Git access on the machine where TaterChat runs;
- streaming local tool activity and command output;
- connection to Tater's OpenAI-compatible API.

Tater owns:

- the configured language-model runtime exposed through the OpenAI-compatible API;
- the `tater/base` model for ordinary completion and caller-provided tool use;
- the `tater/hydra` model for Tater-specific Verbas, Cores, Portals, devices, media, and automations.

TaterChat must not execute local terminal work through Tater or Spudex. Tater must not execute TaterChat's local terminal calls.

## Model and tool routing

The normal conversation uses `tater/base` (or another non-Hydra model selected by the user). TaterChat provides its local terminal and filesystem tools in the ordinary OpenAI tool-calling request.

TaterChat also provides a client-side `tater_hydra` delegation tool. When the primary model selects that tool, TaterChat makes another ordinary request to the same `POST /v1/chat/completions` endpoint with `model: "tater/hydra"`. No private Tater endpoint or server-injected tool is required.

```text
User
  -> TaterChat agent loop
       -> ordinary response: tater/base
       -> local computer task: TaterChat terminal/filesystem tools
       -> Tater capability: POST /v1/chat/completions with model=tater/hydra
```

Examples:

- Explain code: answer with the normal model.
- Inspect a repository, edit files, run tests, or commit: use TaterChat's local tools.
- Turn on lights or control a Tater-connected device: delegate to `tater/hydra`.
- Fix a project and announce completion through Tater: use local tools first, then delegate only the announcement to `tater/hydra`.

## Keep from Open WebUI

- Svelte chat interface and responsive shell.
- Markdown, code blocks, file/artifact rendering, and tool-call displays.
- Chat persistence, history, branching, and cancellation.
- Authentication and a small user/settings surface.
- OpenAI-compatible connection and streaming code.
- The server-side tool loop and tool-result message handling.
- SQLite as the initial local database.
- Terminal dock, xterm components, command-output UI, and related WebSocket patterns.

Primary preservation paths include:

- `src/lib/components/chat/Chat.svelte`
- `src/lib/components/common/ToolCallDisplay.svelte`
- `src/lib/components/chat/TerminalDock.svelte`
- `src/lib/components/chat/XTerminal.svelte`
- `backend/open_webui/utils/chat.py`
- `backend/open_webui/routers/openai.py`
- `backend/open_webui/utils/tools.py`
- `backend/open_webui/routers/chats.py`
- `backend/open_webui/routers/auths.py`

## Replace

Open WebUI currently expects a separately configured terminal server. TaterChat will replace that dependency with a bundled local runtime in its own FastAPI backend while retaining the useful terminal UI and tool-loop integration.

The local runtime must provide:

- a persistent working directory per chat;
- foreground and background processes;
- stdout/stderr streaming;
- process cancellation and timeouts;
- interactive PTY sessions;
- direct file reads, writes, patches, directory listing, and text search;
- Git-aware status and verification;
- bounded output with truncation metadata;
- clear command/tool records in chat history;
- full host environment access when Full Access is enabled.

## Remove or defer

These features are outside the initial TaterChat product and should be removed only after the retained paths have tests:

- additional chat-provider connection and model-management paths;
- RAG, knowledge bases, embeddings, rerankers, and vector databases;
- channels, notes, calendar, and Open WebUI automations;
- model arenas, evaluations, analytics, and telemetry;
- SCIM, LDAP, enterprise groups, and cloud storage integrations;
- pipelines, arbitrary Python Functions, community imports, and marketplace surfaces;
- multi-provider administration beyond the Tater OpenAI-compatible connection;
- external terminal-server configuration after the bundled runtime replaces it.

Some code in these areas may remain temporarily when shared imports make immediate removal risky. Routes and navigation should disappear before dependency deletion.

Image generation/editing, speech, transcription, and their media UI are part
of the retained TaterChat experience. Their provider configuration can be
narrowed later without removing the user-facing media capabilities.

## Agent loop requirements

The loop continues until the task is complete, blocked on required user input, cancelled, or reaches a configured safety limit.

1. Send conversation state, the concise system prompt, and available tool schemas to the normal model.
2. If the model returns text without tool calls, finish the turn.
3. Execute local terminal/file tools on the TaterChat host.
4. Execute `tater_hydra` by calling the standard Tater Chat Completions endpoint with `model: "tater/hydra"`.
5. Append every tool result using standard OpenAI tool messages and continue the model call.
6. Stream command status, output, and assistant text to the browser throughout the loop.
7. Require verification appropriate to the change before the agent claims completion.
8. Detect repeated identical failures and stop with a concrete explanation instead of looping.

The prompt should teach routing, not enumerate the whole Tater tool catalog. Hydra owns its own tool knowledge.

## Prompt contract

The normal agent prompt will emphasize:

- Answer ordinary questions directly.
- Use local tools for terminal, filesystem, processes, Git, builds, tests, package management, and inspection of the TaterChat host.
- Use `tater_hydra` only for capabilities provided by the connected Tater system.
- Inspect before editing and preserve unrelated user changes.
- Continue after tool results; a successful command is not automatically a completed task.
- Diagnose failures, adjust, and retry when safe.
- Verify edits and report the actual result.
- Ask before destructive or materially ambiguous actions.

## Delivery sequence

1. Preserve a reproducible upstream baseline and record inherited failures.
2. Add a Tater-only provider profile and configuration flow. See
   [`TATER_PROVIDER.md`](TATER_PROVIDER.md).
3. Implement the bundled local terminal runtime behind the existing terminal/tool UI. See
   [`LOCAL_RUNTIME.md`](LOCAL_RUNTIME.md).
4. Add the `tater_hydra` delegation tool using the normal Chat Completions endpoint. See
   [`TATER_HYDRA.md`](TATER_HYDRA.md).
5. Install the focused system prompt and robust multi-tool loop.
6. Hide unneeded routes and navigation, then remove their backend routers and dependencies in measured slices. The first frontend and backend-surface slices are complete; remote Python Pipelines and the general Ollama provider have been removed. Image and audio stay as UI features. Retrieval retains its separate optional Ollama embedding client until that subsystem is handled independently.
7. Rebrand permitted surfaces, package the standalone app, and add security/audit documentation.

## Security boundary

Full Access is intentionally unrestricted host execution. It can read credentials, modify or delete files, install software, control processes, and contact external services. TaterChat must require authentication, keep secrets server-side, log tool execution, and default to local/LAN binding. Remote exposure should be placed behind a trusted VPN or authenticated reverse proxy.
