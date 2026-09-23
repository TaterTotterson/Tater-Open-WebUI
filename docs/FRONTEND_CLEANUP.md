# Frontend cleanup

The first stripping pass removes Open WebUI surfaces that do not belong in the
TaterChat product while preserving the chat, authentication, history, local
terminal, file navigation, and Tater configuration paths.

## Removed in this slice

- Workspace model, prompt, knowledge, skill, and toolkit routes.
- Playground and its completion and image-generation routes.
- Notes, channels, calendar, and automation routes and their standalone UI trees.
- Analytics, evaluations, and Python Function administration routes and UI trees.
- Their navigation, search actions, attachment menus, model-edit links, and admin switches.
- The Pyodide worker, browser sandbox, file navigator, preparation script, and npm dependency.
- Special Markdown rendering and navigation for removed notes and channels.
- Ollama connection, model-management, pull/download, model metadata, version,
  and provider-specific advanced-parameter UI.
- The now-unreachable generic provider administration and personal connection
  component trees; the focused Tater settings page is the provider setup UI.
- Browser-direct connections and completion RPC handling.
- Generic provider model discovery, download queues, load/eject controls, and
  their client APIs.
- Arena configuration, random-model response metadata, and arena-specific
  rating UI.
- The final orphaned workspace model screen, editor, and editor-only selector
  components. The shared knowledge picker and audio voice input remain.

The corresponding feature defaults are off. Plugins also default off so a new
TaterChat install does not expose the inherited extension surface accidentally.

## Verification

The upstream build transformed 6,366 modules and exhausted Node's default heap.
After this slice, the production build transforms 6,076 modules and completes
with the default Node 22 heap.

Image and audio components remain part of the active product and are not
included in provider cleanup.

## Follow-up

The first backend cleanup slice is now documented in
`docs/BACKEND_CLEANUP.md`. Shared database models and migrations remain until
their chat, file, folder, and WebSocket dependencies can be separated safely.
