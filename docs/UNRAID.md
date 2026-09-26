# Deploy TaterChat on Unraid

The GitHub workflow publishes a Linux amd64 image for ordinary Unraid servers:

```text
ghcr.io/tatertotterson/taterchat:latest
```

Version tags also publish immutable versioned images. For example, Git tag
`v0.1.0` produces `:0.1.0` and `:0.1` alongside a commit-specific `:sha-...`
tag. Prefer a version or SHA tag when you want upgrades to be deliberate.

## Registry access

The repository and its package may initially be private. In that case, create a
GitHub token with `read:packages` and authenticate from the Unraid terminal:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io --username TaterTotterson --password-stdin
docker pull ghcr.io/tatertotterson/taterchat:latest
```

Do not put a registry token into the TaterChat container. It is only used by
Docker to pull the image. Authentication is unnecessary if the package is made
public later.

## Container configuration

Generate a long random `WEBUI_SECRET_KEY` and keep the same value across
upgrades. Adjust the Tater URL and host workspace mapping for your installation:

```bash
docker run --detach \
  --name taterchat \
  --restart unless-stopped \
  --publish 3000:8080 \
  --add-host host.docker.internal:host-gateway \
  --volume /mnt/user/appdata/taterchat:/app/backend/data \
  --volume /mnt/user:/workspace \
  --env TATERCHAT_WORKSPACE=/workspace \
  --env TATER_API_BASE_URL=http://host.docker.internal:8501/v1 \
  --env TATER_API_KEY= \
  --env TATER_BASE_MODEL=tater/base \
  --env TATER_HYDRA_MODEL=tater/hydra \
  --env WEBUI_SECRET_KEY=replace-with-a-long-random-secret \
  ghcr.io/tatertotterson/taterchat:latest
```

In the Unraid Add Container form, use the same image, port, paths, variables,
and extra parameter:

```text
--add-host=host.docker.internal:host-gateway
```

If Tater runs in another container, putting both containers on the same custom
Docker network and using `http://<tater-container-name>:8501/v1` is usually more
reliable than the host alias.

The `/workspace` mapping defines what host data the local agent can access.
Mounting `/mnt/user` grants access to all user shares; map a narrower project
directory if that is preferable. The agent always has unrestricted access
inside the TaterChat container itself.

Open `http://<unraid-address>:3000` after the health status becomes healthy.
The first account created becomes the administrator.

## Updating

For `latest`, pull and recreate the container while preserving the appdata
volume:

```bash
docker pull ghcr.io/tatertotterson/taterchat:latest
docker stop taterchat
docker rm taterchat
```

Then recreate it with the same settings. Removing the container does not remove
`/mnt/user/appdata/taterchat` or the named host workspace.
