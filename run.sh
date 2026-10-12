#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
panel_bind_address="${HOST:-}"
if [[ -z "$panel_bind_address" ]]; then
    panel_bind_address="$(ip -4 -o addr show tailscale0 2>/dev/null | awk '{split($4, address, "/"); print address[1]; exit}' || true)"
    panel_bind_address="${panel_bind_address:-127.0.0.1}"
fi
exec .venv/bin/uvicorn app.main:app --host "$panel_bind_address" --port "${PORT:-10000}"
