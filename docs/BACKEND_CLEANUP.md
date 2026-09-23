# Backend cleanup

The first backend stripping pass removes feature entry points that no longer
belong in TaterChat and narrows the built-in agent tool surface to the pieces
used by its terminal-first work loop.

## Removed in this slice

- API registration for analytics, automations, calendar, channels, evaluations,
  Python Functions, and notes.
- Isolated analytics, calendar, evaluation, Function, and note router modules.
- The calendar utility module and startup automation scheduler.
- Startup installation and safe-mode management for Open WebUI Python plugins.
- Public configuration, environment flags, and admin permission controls for
  the removed products.
- Open WebUI's inherited built-in tools for memory, retrieval, web search,
  image generation, code execution, chat search, notifications, skills, and
  subagents.
- The remote Python Pipelines router, admin component, frontend API client,
  event catalog entries, and chat/task inlet and outlet interception hooks.

TaterChat retains `ask_user`, `create_tasks`, and `update_task` as UI-native
coordination tools. Its unrestricted local terminal and conditional
`tater_hydra` tool remain separate runtime tools and are not affected by the
built-in-tool reduction.

Image generation/editing and audio transcription/speech are intentionally
retained as TaterChat UI capabilities. Surface tests require both routers to
remain registered.

## Compatibility boundary

Database tables and migrations are retained in this pass so existing databases
remain upgradeable. Channel and automation model code also remains temporarily
because shared chat, file, folder, and WebSocket modules still reference it.
Those references need to be separated before the dormant modules can be safely
deleted.

Legacy provider, retrieval, memory, and knowledge routers are deferred. They
cross shared model discovery and message-processing paths and should be removed
as their own measured slices.

## Verification

- Backend surface tests parse the application, assert removed route prefixes
  are absent, assert isolated files are deleted, and lock the built-in tool
  module to the three intended public tools.
- The Tater provider, Hydra routing, local terminal, and agent-profile tests run
  alongside the surface tests.
- Python compilation, frontend production build, Docker Compose validation, and
  whitespace checks are run before committing the slice.
