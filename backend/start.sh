#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR"

KEY_FILE="${WEBUI_SECRET_KEY_FILE:-.webui_secret_key}"
WEBUI_SECRET_KEY_LENGTH="${WEBUI_SECRET_KEY_LENGTH:-24}"
PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

if [[ -z "${WEBUI_SECRET_KEY:-}" && -z "${WEBUI_JWT_SECRET_KEY:-}" ]]; then
    if [[ ! -f "$KEY_FILE" ]]; then
        if ! [[ "$WEBUI_SECRET_KEY_LENGTH" =~ ^[1-9][0-9]*$ ]]; then
            echo "WEBUI_SECRET_KEY_LENGTH must be a positive integer." >&2
            exit 1
        fi

        echo "Generating ${KEY_FILE}..."
        head -c "$WEBUI_SECRET_KEY_LENGTH" /dev/random | base64 > "$KEY_FILE"
    fi

    WEBUI_SECRET_KEY=$(<"$KEY_FILE")
fi

PYTHON_CMD=$(command -v python3 || command -v python)
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

if [[ "$#" -gt 0 ]]; then
    ARGS=("$@")
else
    ARGS=(--workers "$UVICORN_WORKERS" --ws-per-message-deflate "${UVICORN_WS_PER_MESSAGE_DEFLATE:-true}")
fi

exec env WEBUI_SECRET_KEY="${WEBUI_SECRET_KEY:-}" \
    "$PYTHON_CMD" -m uvicorn open_webui.main:app \
        --host "$HOST" \
        --port "$PORT" \
        --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
        "${ARGS[@]}"
