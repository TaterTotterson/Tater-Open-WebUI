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

The corresponding feature defaults are off. Plugins also default off so a new
TaterChat install does not expose the inherited extension surface accidentally.

## Verification

The upstream build transformed 6,366 modules and exhausted Node's default heap.
After this slice, the production build transforms 6,078 modules and completes
with the default Node 22 heap.

## Follow-up

The first backend cleanup slice is now documented in
`docs/BACKEND_CLEANUP.md`. Shared database models and migrations remain until
their chat, file, folder, and WebSocket dependencies can be separated safely.
