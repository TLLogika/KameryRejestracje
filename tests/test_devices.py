import errno
from pathlib import Path
from app import devices


def test_metadata_filter_stable_alias_and_physical_dedup(tmp_path, monkeypatch):
    for name in ("video0", "video1", "video2", "video10"):
        (tmp_path / name).touch()
    aliases = tmp_path / "v4l/by-id"
    aliases.mkdir(parents=True)
    (aliases / "camera-video-index0").symlink_to(tmp_path / "video0")
    results = {
        "video0": ("Camera A", "usb-bus-a"),
        "video1": None,
        "video2": ("Camera A", "usb-bus-a"),
        "video10": ("Camera B", "usb-bus-b"),
    }
    monkeypatch.setattr(devices, "query_capture", lambda p: results[p.name])
    found = devices.local_usb_devices(tmp_path)
    assert [d["name"] for d in found] == ["Camera A", "Camera B"]
    assert found[0]["source"] == str(aliases / "camera-video-index0")
    assert all(d["available"] for d in found)


def test_permission_failure_is_visible_but_not_selectable(tmp_path, monkeypatch):
    (tmp_path / "video99").touch()

    def denied(path):
        raise PermissionError(errno.EACCES, "test permission failure")

    monkeypatch.setattr(devices, "query_capture", denied)
    found = devices.local_usb_devices(tmp_path)
    assert len(found) == 1 and not found[0]["available"]
    assert "uprawnień" in found[0]["reason"]


def test_querycap_device_caps_excludes_metadata(monkeypatch):
    closed = []
    monkeypatch.setattr(devices.os, "open", lambda *args: 17)
    monkeypatch.setattr(devices.os, "close", lambda fd: closed.append(fd))

    def metadata(fd, operation, caps):
        caps[84:88] = (0x80000000 | 1).to_bytes(4, "little")
        caps[88:92] = (0x00800000).to_bytes(4, "little")

    monkeypatch.setattr(devices.fcntl, "ioctl", metadata)
    assert devices.query_capture("/dev/video-test") is None
    assert closed == [17]
