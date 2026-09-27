# syntax=docker/dockerfile:1

ARG BUILD_HASH=dev-build
ARG UID=0
ARG GID=0

FROM --platform=$BUILDPLATFORM node:22-alpine3.20 AS frontend

ARG BUILD_HASH
ARG UID
ARG GID

ENV NODE_OPTIONS="--max-old-space-size=4096"
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --force
COPY . .
ENV APP_BUILD_HASH=${BUILD_HASH}
RUN npm run build

# Prepare backend permissions before copying it into the runtime image.
RUN chown -R $UID:$GID /app/backend && \
    chgrp -R 0 /app/backend/open_webui/static && \
    chmod -R g=u /app/backend/open_webui/static

FROM python:3.11-slim-bookworm

ARG BUILD_HASH
ARG UID
ARG GID

ENV PYTHONUNBUFFERED=1 \
    ENV=prod \
    PORT=8080 \
    OPENAI_API_BASE_URL="" \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false \
    WHISPER_MODEL=base \
    WHISPER_MODEL_DIR=/app/backend/data/cache/whisper/models \
    HF_HOME=/app/backend/data/cache/huggingface \
    UV_LINK_MODE=copy \
    HOME=/root \
    WEBUI_BUILD_VERSION=${BUILD_HASH} \
    DOCKER=true

WORKDIR /app/backend

RUN if [ "$UID" -ne 0 ]; then \
        if [ "$GID" -ne 0 ]; then addgroup --gid "$GID" app; fi; \
        adduser --uid "$UID" --gid "$GID" --home "$HOME" --disabled-password --no-create-home app; \
    fi && \
    chown -R "$UID:$GID" /app "$HOME"

# Git and build tools are intentionally present because the local agent has a
# real terminal. Pandoc and ffmpeg support the retained file and media UI.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl ffmpeg gcc git jq \
        libmariadb-dev libsm6 libxext6 pandoc && \
    rm -rf /var/lib/apt/lists/*

COPY --chown=$UID:$GID backend/requirements.txt ./requirements.txt

RUN --mount=from=ghcr.io/astral-sh/uv:0.12.10,source=/uv,target=/bin/uv \
    pip3 install 'torch<=2.9.1' torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cpu --no-cache-dir && \
    uv pip install --system -r requirements.txt --no-cache-dir && \
    python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8', download_root=os.environ['WHISPER_MODEL_DIR'])" && \
    mkdir -p /app/backend/data && \
    chown -R "$UID:$GID" /app/backend/data && \
    if [ -d /app/backend/data/cache ]; then chmod -R a+rX /app/backend/data/cache; fi

COPY --chown=$UID:$GID --from=frontend /app/build /app/build
COPY --chown=$UID:$GID --from=frontend /app/CHANGELOG.md /app/CHANGELOG.md
COPY --chown=$UID:$GID --from=frontend /app/package.json /app/package.json
COPY --from=frontend /app/backend .

EXPOSE 8080

HEALTHCHECK CMD curl --silent --fail http://localhost:${PORT:-8080}/health \
    | jq -ne 'input.status == true' || exit 1

USER $UID:$GID
CMD ["bash", "start.sh"]
