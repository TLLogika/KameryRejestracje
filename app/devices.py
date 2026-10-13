"""Enumerate capture devices without starting video streams."""

import errno
import os
from pathlib import Path
import re

try:
    import fcntl
except ImportError:
    fcntl = None


def query_capture(path):
    caps = bytearray(104)
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, 0x80685600, caps)
    finally:
        os.close(fd)
    flags = int.from_bytes(caps[84:88], "little")
    if flags & 0x80000000:
        flags = int.from_bytes(caps[88:92], "little")
    if not flags & (1 | 0x1000):
        return None
    return (
        caps[16:48].split(b"\0")[0].decode(errors="replace"),
        caps[48:80].split(b"\0")[0].decode(errors="replace"),
    )


def local_usb_devices(dev=Path("/dev")):
    if fcntl is None:
        return []
    aliases = {}
    for path in sorted(
        (dev / "v4l/by-id").glob("*"), key=lambda p: ("video-index0" not in p.name, p.name)
    ):
        aliases.setdefault(os.path.realpath(path), str(path))
    devices = []
    seen = set()
    nodes = sorted(
        dev.glob("video*"),
        key=lambda p: (
            int(re.search(r"\d+$", p.name).group()) if re.search(r"\d+$", p.name) else 9999
        ),
    )
    for node in nodes:
        try:
            result = query_capture(node)
            if result is None:
                continue
            name, bus = result
            identity = (bus, name) if bus else (str(node), name)
            if identity in seen:
                continue
            seen.add(identity)
            devices.append(
                {
                    "source": aliases.get(os.path.realpath(node), str(node)),
                    "name": name,
                    "device": str(node),
                    "available": True,
                }
            )
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                index = Path("/sys/class/video4linux") / node.name / "index"
                if index.is_file() and index.read_text().strip() != "0":
                    continue
                devices.append(
                    {
                        "source": str(node),
                        "name": node.name,
                        "device": str(node),
                        "available": False,
                        "reason": "Brak uprawnień do urządzenia wideo",
                    }
                )
    return devices


def usb_devices():
    from .usb_bridge import bridge_devices

    return local_usb_devices() + bridge_devices()
