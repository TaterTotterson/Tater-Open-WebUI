# Tater Hydra delegation

The normal TaterChat model receives one reserved tool named `tater_hydra`. The tool delegates through the same saved OpenAI-compatible provider connection used for ordinary chat:

```text
POST {TATER_API_BASE_URL}/chat/completions
model: {TATER_HYDRA_MODEL}
```

There is no private Tater endpoint and no Spudex dependency. TaterChat sends the saved bearer token server-side and includes the chat ID as `X-Tater-Session` so Tater can scope the request consistently.

## Routing contract

Use `tater_hydra` for capabilities owned by Tater:

- Verbas and Cores;
- Portals and connected devices;
- smart-home actions;
- Tater media and automations.

Do not use it for ordinary conversation or work on the computer running TaterChat. Terminal commands, files, Git, builds, tests, packages, and processes belong to the bundled local runtime.

Hydra receives only the tool's `request`, not the complete TaterChat transcript. The normal model must formulate a self-contained instruction with the exact target, action, and constraints. This keeps unrelated local file content, terminal output, and credentials out of Tater requests.

The Hydra response is returned to the normal model as a regular tool result. The normal model remains responsible for continuing a mixed local/Tater task and accurately reporting the final outcome.

## Agent loop

The normal model plans tool work one step at a time. After each local-runtime or Hydra result, it can inspect the result and choose the next action. This supports practical loops such as inspect → edit → test → fix → retest instead of making a single batch of guesses.

The loop stops when the model reports that no more tools are needed, the same call produces the same outcome three times, planning fails, or the iteration limit is reached. Tool output fed back to the planner is bounded, and it is explicitly treated as untrusted data rather than instructions.

Tool plans are limited to 16 calls per step. Runtime process IDs and timestamps are removed from repeat signatures, so rerunning the same command with the same output is recognized as a repeat. Local changes require a later successful `verify_command`; if the compatibility planner tries to finish first, it receives up to two verification reminders and then stops with an explicit incomplete-verification notice.

Background commands remain local to TaterChat. The normal model can list them, read incremental output, and terminate them without involving Hydra.

The default limit is 32 planning rounds. Set `TATER_AGENT_MAX_ITERATIONS` from 1 through 128 to change it.

## Tater configuration

The Tater OpenAI-compatible API must be enabled and its Hydra tools setting must be on. In Tater settings this is the `tater_api_hydra_tools_enabled` option. If it is off, `tater/hydra` can answer but will not receive the Tater Verba registry needed to perform actions.

Delegations default to a ten-minute timeout. Set `TATER_HYDRA_TIMEOUT_SECONDS` between 1 and 3600 seconds to change it. Cancelling the TaterChat response cancels the in-flight HTTP request.
