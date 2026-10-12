#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f dsecret/docker.env || ! -f dsecret/compose.usb.json ]]; then
    python3 scripts/configure_docker.py
fi
exec docker compose --env-file dsecret/docker.env -f compose.yaml -f dsecret/compose.usb.json "$@"
