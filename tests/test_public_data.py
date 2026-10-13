"""Public sources must not contain deployment addresses or private artifacts."""

import ipaddress
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
IPV4 = re.compile(r"(?<![\w.=])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])")
DOCUMENTATION_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
)
PRIVATE_ARTIFACTS = {"secret", "dsecret", "data", ".venv"}
PRIVATE_KEY = re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED)?\s*PRIVATE KEY-----")
TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b"
)
LOCAL_ACCOUNT = re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+/")
DEVICE_SERIAL = re.compile(r"\bAN20[0-9]{10,}\b")


def test_public_files_do_not_expose_deployment_data():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    for name in filter(None, result.stdout.decode().split("\0")):
        path = Path(name)
        assert path.parts[0] not in PRIVATE_ARTIFACTS, f"Prywatny plik w repozytorium: {name}"
        assert not re.search(
            r"\.(?:sqlite3?|log)(?:[.-]|$)", name
        ), f"Dane operacyjne w repozytorium: {name}"
        if name in {"app/demo/car-park.mp4", "app/demo/parking-garage.mp4"}:
            content_bytes = (ROOT / path).read_bytes()
            assert content_bytes[4:8] == b"ftyp" and len(content_bytes) < 50_000_000
            continue
        content = (ROOT / path).read_text()
        for candidate in IPV4.findall(content):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            allowed = (
                address.is_loopback
                or address.is_unspecified
                or any(address in network for network in DOCUMENTATION_NETWORKS)
            )
            assert allowed, f"Adres wdrożenia w publicznym pliku: {name}"
        for pattern in (PRIVATE_KEY, TOKEN, LOCAL_ACCOUNT, DEVICE_SERIAL):
            assert not pattern.search(content), f"Dane prywatne w publicznym pliku: {name}"
