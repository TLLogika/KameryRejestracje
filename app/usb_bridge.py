"""Windows USB transport: secrets are sent in headers, never in stream URLs."""

import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import cv2
import numpy as np


def bridge_request(path):
    base = os.environ.get("USB_BRIDGE_URL", "").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Nieprawidłowy adres mostka USB")
    key_path = Path(
        os.environ.get(
            "USB_BRIDGE_KEY_FILE",
            str(Path(__file__).resolve().parent.parent / "dsecret/usb-bridge.key"),
        )
    )
    key = key_path.read_text().strip()
    if len(key) < 32:
        raise ValueError("Nieprawidłowy klucz mostka USB")
    return Request(base + path, headers={"Authorization": "Bearer " + key})


def bridge_devices():
    if not os.environ.get("USB_BRIDGE_URL"):
        return []
    try:
        with urlopen(bridge_request("/devices"), timeout=2) as response:
            data = json.load(response)
        return [
            {
                "source": "bridge:" + item["id"],
                "name": item["name"] + " (USB Windows)",
                "device": "Windows USB",
                "available": True,
            }
            for item in data
            if re.fullmatch(r"[a-f0-9]{16}", item["id"])
        ]
    except (OSError, ValueError, KeyError, TypeError):
        return []


class BridgeCapture:
    def __init__(self, source):
        ident = source.removeprefix("bridge:")
        if not re.fullmatch(r"[a-f0-9]{16}", ident):
            raise ValueError("Nieprawidłowe urządzenie mostka USB")
        self.response = urlopen(bridge_request("/stream/" + ident), timeout=5)
        self.fps = float(self.response.headers.get("X-Video-Fps", "15"))

    def isOpened(self):
        return not self.response.closed

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self.fps
        if prop == cv2.CAP_PROP_FOURCC:
            return cv2.VideoWriter_fourcc(*"MJPG")
        return 0

    def read(self):
        while True:
            line = self.response.readline(4096)
            if not line:
                return False, None
            if line.strip() == b"--frame":
                break
        headers = {}
        while True:
            line = self.response.readline(4096)
            if line == b"\r\n":
                break
            if not line or b":" not in line:
                return False, None
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        size = int(headers.get("content-length", "0"))
        if not 0 < size <= 20_000_000:
            return False, None
        data = self.response.read(size)
        if len(data) != size:
            return False, None
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        return frame is not None, frame

    def release(self):
        self.response.close()
