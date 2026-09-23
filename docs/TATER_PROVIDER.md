# Tater provider profile

TaterChat has one server-side OpenAI-compatible provider connection. Configure
it from **Admin settings → Tater** or with environment variables on a new data
directory.

| Setting           | Environment variable          | Default                    |
| ----------------- | ----------------------------- | -------------------------- |
| API base URL      | `TATER_API_BASE_URL`          | `http://localhost:8501/v1` |
| API key           | `TATER_API_KEY`               | empty                      |
| normal chat model | `TATER_BASE_MODEL`            | `tater/base`               |
| Tater tool model  | `TATER_HYDRA_MODEL`           | `tater/hydra`              |
| Hydra timeout     | `TATER_HYDRA_TIMEOUT_SECONDS` | `600` seconds              |
| Agent loop limit  | `TATER_AGENT_MAX_ITERATIONS`  | `32` planning rounds       |

The URL must point at the API prefix, not the Chat Completions route itself. For
example, use `http://tater-host:8501/v1`; TaterChat appends `/models` and
`/chat/completions` where needed.

Saving the profile performs these changes atomically:

- enables the single OpenAI-compatible connection;
- disables the inherited Ollama provider;
- makes the normal model the default and pinned model;
- reserves the Hydra model and removes it from the normal model picker;
- clears the cached model list so the new connection is used immediately.

The API key is stored server-side. The settings response reports only whether a
key exists, and an unchanged blank password field preserves the stored value.
The **Test connection** action calls the configured `/models` endpoint and
reports whether both configured model IDs are advertised.

In Docker, the included Compose configuration defaults to
`http://host.docker.internal:8501/v1`, allowing the container to reach Tater on
the host. Set `TATER_API_BASE_URL` to the LAN or container-network address when
Tater runs elsewhere.

This profile does not grant Tater access to the TaterChat host. Local terminal,
filesystem, process, and Git operations stay in TaterChat's own backend. The
`tater_hydra` tool uses this same saved provider connection for Tater-only
actions.

Tater's current `tater/base` endpoint returns text and does not preserve
caller-provided native OpenAI tool calls. TaterChat therefore selects the
existing structured tool-planning mode for this provider. Tater remains
unchanged, and the actual Hydra delegation still uses the normal
`POST /v1/chat/completions` endpoint.
