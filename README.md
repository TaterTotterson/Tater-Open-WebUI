# Tater WebUI

Tater WebUI is a standalone, terminal-first AI chat application derived from
[Open WebUI](https://github.com/open-webui/open-webui). It connects to Tater
through its standard OpenAI-compatible API and gives the normal chat model full
terminal, filesystem, process, and Git access on the machine running Tater WebUI.

## How routing works

- `tater/base` handles normal conversation and local computer work.
- Local work uses one model tool, `terminal`, with a single `command` argument.
  It waits for the command and returns output and exit status in the same call.
- Terminal commands run inside Tater WebUI; they do not go through Tater or Spudex.
- `tater_hydra` is the only other model tool. It is called only when the model needs a Tater capability, such
  as controlling a device, using a Verba, Core, Portal, media service, or
  automation.
- Hydra delegation uses the same standard `POST /v1/chat/completions`
  endpoint. There is no private Tater API.
- Image and audio UI capabilities are intentionally retained.

See [the architecture document](docs/TATER_WEBUI_ARCHITECTURE.md) for the full
boundary between Tater WebUI, Tater, Hydra, and the local runtime.

## Quick start with Docker Compose

Requirements:

- a reachable Tater OpenAI-compatible API;
- Docker with Compose;
- a host directory that Tater WebUI is allowed to access.

```bash
cp .env.example .env
```

Set these values in `.env`:

```dotenv
TATER_API_BASE_URL=http://host.docker.internal:8501/v1
TATER_API_KEY=
TATER_WEBUI_HOST_WORKSPACE=/absolute/path/to/your/projects
WEBUI_SECRET_KEY=replace-with-a-long-random-secret
```

Then start the app:

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The first account created
becomes the administrator.

The Compose setup mounts `TATER_WEBUI_HOST_WORKSPACE` at `/workspace`.
Tater WebUI can still access the rest of its container filesystem, but host files
outside mounted paths are not visible from inside Docker.

## GitHub image and Unraid

Every push to `main` builds, boots, health-checks, and publishes the public
amd64 image to `ghcr.io/tatertotterson/tater-webui`. Use `latest` for the newest
successful main build or a version tag such as `0.1.0` for a pinned release.

See [the Unraid deployment guide](docs/UNRAID.md) for volume mappings, Tater
connectivity, and a complete container command.

## Configuration

| Variable                      | Default                    | Purpose                           |
| ----------------------------- | -------------------------- | --------------------------------- |
| `TATER_API_BASE_URL`          | `http://localhost:8501/v1` | Tater API prefix                  |
| `TATER_API_KEY`               | empty                      | Server-side Tater credential      |
| `TATER_BASE_MODEL`            | `tater/base`               | Normal chat and local agent model |
| `TATER_HYDRA_MODEL`           | `tater/hydra`              | Tater-tool delegation model       |
| `TATER_HYDRA_TIMEOUT_SECONDS` | `600`                      | Hydra request timeout             |
| `TATER_AGENT_MAX_ITERATIONS`  | `32`                       | Maximum planning/tool rounds      |
| `TATER_WEBUI_WORKSPACE`       | process directory          | Initial local working directory   |

The same provider settings are available under **Admin settings → Tater**.
Details are in [the provider guide](docs/TATER_PROVIDER.md) and
[the local runtime guide](docs/LOCAL_RUNTIME.md).

## Development

Use Python 3.11 and Node.js 22.

```bash
npm ci
pip install -r backend/requirements.txt
npm run dev
```

In a second terminal:

```bash
cd backend
./dev.sh
```

The frontend runs on port 5173 and the backend on port 8080.

Run the focused backend regression suite with:

```bash
python -m unittest \
  backend.tests.test_tater_profile \
  backend.tests.test_tater_agent \
  backend.tests.test_tater_hydra \
  backend.tests.test_local_terminal_runtime \
  backend.tests.test_local_terminal_tools \
  backend.tests.test_backend_surface -v
npm run build
```

## Security

Full terminal access is intentionally unrestricted. Tater WebUI can read
credentials available to its operating-system user, edit or delete files,
install software, control processes, and make network requests. Run it as a
dedicated user with appropriate permissions and do not expose it directly to
the public internet. Use a trusted VPN or authenticated reverse proxy for
remote access.

See [the security notes](docs/SECURITY.md).

## Project status

Tater WebUI is being reduced from its Open WebUI baseline in measured,
build-tested slices. The Tater provider profile, bundled local runtime,
conditional Hydra tool, bounded inspect/edit/verify agent loop, and local
background-process controls are implemented. Browser-direct connections,
generic provider model management, model arenas, RAG, knowledge bases,
memories, web search, embeddings, rerankers, and vector databases have been
removed. The focused Tater profile is the only chat-provider setup surface;
ordinary file attachments and the image/audio experience remain available.

## Upstream and license

This project is derived from Open WebUI and retains its required notices,
copyright attribution, and license terms. See [LICENSE](LICENSE) and
[the recorded upstream baseline](docs/UPSTREAM_BASELINE.md). Open WebUI
trademarks and upstream project identity belong to their respective owners.
