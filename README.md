<p align="center">
  <img src="static/static/tater-open-webui-logo.png" alt="Tater mascot leaning on the Open WebUI logo" width="360">
</p>

# Tater Open WebUI

Tater Open WebUI is a terminal-first AI chat application derived from
[Open WebUI](https://github.com/open-webui/open-webui). It connects to Tater's
OpenAI-compatible API and gives the normal chat model unrestricted terminal
access inside the environment running Tater Open WebUI.

## What it does

- `tater/base` handles normal conversation and local computer work.
- Local work uses one model tool: `terminal({"command": "..."})`.
- `tater/hydra` is called only for Tater-owned capabilities such as connected
  devices, Verbas, Cores, Portals, media services, and automations.
- Terminal work stays local to Tater Open WebUI; it does not use Hydra or Spudex.
- The agent runs an inspect/edit/test loop and verifies completion before
  returning a final answer.
- Chat history, authentication, files, images, audio, and the terminal UI are
  retained from the Open WebUI foundation.

Both models use the standard Tater endpoint:

```text
POST {TATER_API_BASE_URL}/chat/completions
```

## Docker Compose

Requirements:

- Docker with Compose;
- a reachable Tater OpenAI-compatible API;
- a host directory that the agent is allowed to access.

```bash
cp .env.example .env
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The first account created
becomes the administrator.

The Compose setup mounts `TATER_WEBUI_HOST_WORKSPACE` at `/workspace`. Files
outside mounted paths are not visible from inside Docker.

## Published image and Unraid

Every successful push to `main` publishes a tested Linux amd64 image:

```bash
docker pull ghcr.io/tatertotterson/tater-open-webui:latest
```

See the [Unraid guide](docs/UNRAID.md) for the complete container setup.

## Configuration

Configure the provider under **Admin settings → Tater** or with environment
variables on a new data directory.

| Variable                      | Default                    | Purpose                           |
| ----------------------------- | -------------------------- | --------------------------------- |
| `TATER_API_BASE_URL`          | `http://localhost:8501/v1` | Tater API prefix                  |
| `TATER_API_KEY`               | empty                      | Server-side Tater credential      |
| `TATER_BASE_MODEL`            | `tater/base`               | Normal chat and local agent model |
| `TATER_HYDRA_MODEL`           | `tater/hydra`              | Tater capability model            |
| `TATER_CONTEXT_WINDOW`        | `32768`                    | Configured model context tokens   |
| `TATER_HYDRA_TIMEOUT_SECONDS` | `600`                      | Hydra request timeout             |
| `TATER_AGENT_MAX_ITERATIONS`  | `32`                       | Maximum planning/tool rounds      |
| `TATER_WEBUI_WORKSPACE`       | process directory          | Initial terminal directory        |

The API URL must point to the `/v1` prefix, not directly to
`/chat/completions`. Saving the Tater profile keeps the API key server-side,
sets the base model as the default, and reserves the Hydra model from ordinary
model selection. Set the context window to the maximum configured by the model
server. Tater Open WebUI compacts at 80 percent of that value, preserving the
remaining space for terminal instructions, tool results, and the response.

Hydra receives a self-contained task rather than the entire local transcript.
This avoids sending unrelated terminal output and local file contents to a
Tater capability call.

## Terminal behavior

Each user/chat pair has an independent working directory. Commands inherit the
backend process environment, may use absolute paths, and return output plus
exit status in the same tool result. The model uses ordinary shell commands for
files, Git, packages, builds, tests, and process management.

## Background tasks

When a request needs the terminal or Hydra, Tater Open WebUI moves the work into
a background task. The original chat remains available while the task runs.
Active tasks appear above Chats in the sidebar, and opening one shows its live,
read-only transcript in the normal chat layout.

The agent may show short progress updates while commands run. A completion
review prevents the task from ending while requested work is unfinished or its
answer is unsupported by actual tool results. Closing a task cancels it and its
active terminal process. When a task finishes or is cancelled, its outcome and
updated working context are returned to the chat that started it. Normal chat
also receives authoritative awareness of every currently running task. Up to
two background tasks may run for one user at a time.

## Development

Use Python 3.11 and Node.js 22.

```bash
npm ci
pip install -r backend/requirements.txt
npm run dev
```

In another terminal:

```bash
cd backend
./dev.sh
```

Run the regression suite and production build with:

```bash
python -m unittest discover -s backend/tests -p 'test_*.py'
npm run build
```

## Security

Terminal access is intentionally unrestricted for the operating-system user
running Tater Open WebUI. In Docker, that includes the container and every mounted
host path. Run it as a dedicated user, mount only intended directories, and put
remote access behind a trusted VPN or authenticated reverse proxy. See the
[security policy](docs/SECURITY.md).

## License

This project is a Tater-connected distribution of Open WebUI. It retains the
Open WebUI name and brand identity alongside Tater branding, as well as the
upstream license, historical license terms, notice, contributor agreement, and
copyright attribution. See `LICENSE`, `LICENSE_HISTORY`, `LICENSE_NOTICE`, and
`CONTRIBUTOR_LICENSE_AGREEMENT`.
