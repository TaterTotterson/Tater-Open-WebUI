# Changelog

## [0.11.4] - 2026-09-27

### Added

- Tater-only OpenAI-compatible provider profile.
- Unrestricted local `terminal` tool for filesystem, process, Git, build, and
  test work.
- Conditional `tater/hydra` delegation for Tater-owned capabilities.
- Multi-step agent loop with visible progress, repeated-failure protection,
  completion review, and deterministic final responses.
- Public Docker image builds with backend tests and a live health check.

### Removed

- Generic model-provider setup and Ollama deployment paths.
- Retrieval, knowledge, memory, web-search, and vector-database products.
- Notes, channels, calendar, analytics, evaluations, and automation pages.
- Legacy Open WebUI deployment variants and contributor-maintenance files that
  are not used by Tater WebUI.
