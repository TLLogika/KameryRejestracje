"""Read-only machine API authentication; no access to camera streams/configuration."""

import hmac
import os
from pathlib import Path
import secrets
from fastapi import HTTPException, Request

ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = ROOT / "secret/integration.key"
KEY_PATH.parent.mkdir(mode=0o700, exist_ok=True)
if not KEY_PATH.exists():
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(secrets.token_urlsafe(48) + "\n")
# Existing keys may be mounted read-only, including Windows bind mounts.
# New keys are created with mode 0600; host setup manages existing permissions.
KEY = KEY_PATH.read_text().strip()
if len(KEY) < 32:
    raise RuntimeError("Klucz integracji musi mieć co najmniej 32 znaki")


def machine_auth(request: Request):
    provided = request.headers.get("Authorization", "")
    if not hmac.compare_digest(provided.encode(), ("Bearer " + KEY).encode()):
        raise HTTPException(
            401, "Nieprawidłowy klucz integracji", headers={"WWW-Authenticate": "Bearer"}
        )
