# Deploy Tater Open WebUI on Unraid

The GitHub workflow publishes a Linux amd64 image for ordinary Unraid servers:

```text
ghcr.io/tatertotterson/tater-open-webui:latest
```

Version tags also publish immutable versioned images. For example, Git tag
`v0.1.0` produces `:0.1.0` and `:0.1` alongside a commit-specific `:sha-...`
tag. Prefer a version or SHA tag when you want upgrades to be deliberate.

## Registry access

The repository and container package are public. Pull the image directly from
the Unraid terminal; no registry token is required:

```bash
docker pull ghcr.io/tatertotterson/tater-open-webui:latest
```

Existing `tater-webui` installations can keep their current container name and
appdata path. Change only the repository/image field to the new image unless
you intentionally want to migrate those local names and paths.

## Container configuration

Generate a long random `WEBUI_SECRET_KEY` and keep the same value across
upgrades. Adjust the Tater URL and persistent projects mapping for your
installation:

```bash
docker run --detach \
  --name tater-open-webui \
  --restart unless-stopped \
  --publish 3000:8080 \
  --add-host host.docker.internal:host-gateway \
  --volume /mnt/user/appdata/tater-open-webui:/app/backend/data \
  --volume /mnt/user/TaterProjects:/projects \
  --env TATER_PROJECTS_ROOT=/projects \
  --env TATER_WEBUI_WORKSPACE=/projects \
  --env TATER_API_BASE_URL=http://host.docker.internal:8501/v1 \
  --env TATER_API_KEY= \
  --env TATER_BASE_MODEL=tater/base \
  --env TATER_HYDRA_MODEL=tater/hydra \
  --env TATER_CONTEXT_WINDOW=32768 \
  --env WEBUI_SECRET_KEY=replace-with-a-long-random-secret \
  ghcr.io/tatertotterson/tater-open-webui:latest
```

In the Unraid Add Container form, use the same image, port, paths, variables,
and extra parameter:

```text
--add-host=host.docker.internal:host-gateway
```

If Tater runs in another container, putting both containers on the same custom
Docker network and using `http://<tater-container-name>:8501/v1` is usually more
reliable than the host alias.

The `/projects` mapping is the persistent coding workspace. Every direct child
directory appears as a Project in the sidebar. A Project keeps its own chats
and shared working context, while the terminal can still access sibling
projects for coordinated changes. Map `/mnt/user/TaterProjects` (or another
durable Unraid share) to `/projects`; the agent also has unrestricted access
inside the Tater Open WebUI container itself.

Open `http://<unraid-address>:3000` after the health status becomes healthy.
The first account created becomes the administrator.

## Updating

For `latest`, pull and recreate the container while preserving the appdata
volume:

```bash
docker pull ghcr.io/tatertotterson/tater-open-webui:latest
docker stop tater-open-webui
docker rm tater-open-webui
```

Then recreate it with the same settings. Removing the container does not remove
`/mnt/user/appdata/tater-open-webui` or `/mnt/user/TaterProjects`.
