# Security policy

Tater WebUI intentionally gives its chat agent unrestricted terminal,
filesystem, process, Git, package-manager, and network access as the operating
system user running the backend. In Docker, that authority includes the full
container filesystem and every host path mounted into the container.

This access is a core feature, not a sandbox. Anyone who can use the local-agent
tools must be treated as having shell access to the Tater WebUI host and its
mounted data.

## Safe deployment

- Require authentication and keep the first administrator account secure.
- Do not expose Tater WebUI directly to the public internet. Use a trusted VPN
  or authenticated reverse proxy for remote access.
- Run the container or native process as a dedicated operating-system user.
- Mount only the host directories the agent should be able to inspect or
  modify. Mounting `/mnt/user` on Unraid grants access to every user share.
- Keep `WEBUI_SECRET_KEY` stable, random, and private.
- Keep `TATER_API_KEY` server-side and out of chat messages, source control,
  screenshots, and client-side configuration.
- Treat terminal output and files as potentially sensitive before delegating a
  separate request to `tater/hydra`.

## Reporting a vulnerability

Report suspected vulnerabilities privately through
[GitHub Security Advisories](https://github.com/TaterTotterson/Tater-WebUI/security/advisories/new).
Include the affected commit or image tag, deployment configuration, impact,
reproduction steps, and a minimal proof of concept. Do not include live API
keys, credentials, or unrelated user data.

Ordinary bugs and deployment questions can use the public
[issue tracker](https://github.com/TaterTotterson/Tater-WebUI/issues).

## Supported version

Only the current `main` branch and the newest published container image are
supported. Open WebUI vulnerabilities that also affect the retained Tater WebUI
surface should be reported to both projects when appropriate.

## Intended behavior

A correctly authorized user instructing the agent to read, modify, execute, or
delete host-accessible data is expected behavior. A security issue is a way for
an unauthorized party to gain that authority, bypass authentication or
authorization, obtain another user's secrets, or cause unintended execution.

Tater WebUI is derived from Open WebUI and retains the upstream license and
required attribution. Upstream security reports unrelated to this fork should
be sent to the Open WebUI project.
