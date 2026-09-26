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
- The general-purpose Ollama router, model discovery, chat and embedding
  dispatch, configuration keys, unload path, bundled-server Docker option, and
  startup launcher.
- Browser-direct model dispatch and its WebSocket completion bridge.
- Arena model registration, random model selection, response wrapping, and
  runtime configuration.
- Generic OpenAI-compatible connection editing, verification, per-connection
  model listing, and provider model download/load/unload/delete routes.
- Direct-model branches in chat, embeddings, actions, tasks, compaction,
  timers, and subagents.
- Retrieval, knowledge-base, memory, web-search, embedding, reranking, and
  vector-database routes and runtime code.
- Chroma, PGVector, Qdrant, Milvus, Pinecone, Weaviate, OpenSearch,
  Elasticsearch, sentence-transformers, BM25, Playwright, and web-search
  dependencies and container setup.
- Retrieval-specific frontend configuration and event definitions.

TaterChat retains `ask_user`, `create_tasks`, and `update_task` as UI-native
coordination tools. Its unrestricted local terminal and conditional
`tater_hydra` tool remain separate runtime tools and are not affected by the
built-in-tool reduction.

Image generation/editing and audio transcription/speech are intentionally
retained as TaterChat UI capabilities. Surface tests require both routers to
remain registered.

Normal file attachments remain. Documents are extracted once at upload time,
their full text is stored with the file record, and that text is attached to
the model request directly. Images, audio, video, raw download/preview, and
media generation are unchanged; no vector database or embedding model is
needed for file chat.

## Compatibility boundary

Database tables, migrations, and the legacy feedback `arena` column are
retained so existing databases remain upgradeable. Channel and automation
model code also remains temporarily
because shared chat, file, folder, and WebSocket modules still reference it.
Those references need to be separated before the dormant modules can be safely
deleted.

Knowledge and memory database models and historical migrations remain only so
existing databases stay upgradeable. They have no registered product routes.

## Verification

- Backend surface tests parse the application, assert removed route prefixes
  are absent, assert isolated files are deleted, and lock the built-in tool
  module to the three intended public tools.
- The Tater provider, Hydra routing, local terminal, and agent-profile tests run
  alongside the surface tests.
- Python compilation, frontend production build, Docker Compose validation, and
  whitespace checks are run before committing the slice.
