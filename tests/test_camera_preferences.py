import threading
import time
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.cameras import Manager
from app.optional.test_video import demo_catalog, demo_source
from app.store import Store


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_live_rotation_releases_streams_and_persists(tmp_path, monkeypatch):
    active = set()
    guard = threading.Lock()

    class Capture:
        def __init__(self, source, *args):
            self.source = source
            with guard:
                assert source not in active
                active.add(source)

        def set(self, *args):
            pass

        def get(self, prop):
            return 30 if prop == cv2.CAP_PROP_FPS else cv2.VideoWriter_fourcc(*"MJPG")

        def isOpened(self):
            return True

        def read(self):
            time.sleep(0.005)
            return True, np.zeros((24, 32, 3), dtype=np.uint8)

        def release(self):
            with guard:
                active.remove(self.source)

    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    from app.optional.usb_rotation import UsbTurns

    manager = Manager.__new__(Manager)
    manager.store = Store(tmp_path / "parking.db")
    manager.store.add_camera("A", "usb", "/dev/video-a")
    manager.store.add_camera("B", "usb", "/dev/video-b")
    manager.workers = {}
    manager.test_sources = {}
    manager.usb_rotation_seconds = 0
    manager.usb_turns = UsbTurns()
    manager.config_lock = threading.RLock()
    try:
        manager.reload()
        wait_for(lambda: len(active) == 2)
        manager.set_rotation(True)
        wait_for(lambda: len(active) == 1)
        time.sleep(0.15)
        assert len(active) == 1
        assert manager.store.preference("usb_rotation_enabled") is True
        manager.set_rotation(False)
        wait_for(lambda: len(active) == 2)
        persisted = Store(tmp_path / "parking.db")
        assert persisted.preference("usb_rotation_enabled") is False
    finally:
        for w in manager.workers.values():
            w.stop.set()
        for w in manager.workers.values():
            w.thread.join(3)
    assert not active


def test_bundled_videos_are_full_hd_60_fps_and_cannot_escape_catalog():
    assert len(demo_catalog()) == 2
    for item in demo_catalog():
        source = demo_source(item["id"])
        cap = cv2.VideoCapture(source["source"])
        try:
            assert cap.isOpened()
            assert cap.get(cv2.CAP_PROP_FPS) == 60
            assert cap.get(cv2.CAP_PROP_FRAME_WIDTH) == 1920
            assert cap.get(cv2.CAP_PROP_FRAME_HEIGHT) == 1080
            assert cap.read()[0]
        finally:
            cap.release()
    with pytest.raises(ValueError):
        demo_source("../../secret/integration.key")


def test_test_camera_and_switching_api_require_auth_and_validate_catalog(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    store = Store(tmp_path / "api.db")
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "sessions", {"test-session": time.time() + 100})
    manager = SimpleNamespace(workers={}, usb_rotation_seconds=0, reload=lambda: None)

    def switch(enabled):
        manager.usb_rotation_seconds = 5 if enabled else 0
        store.set_preference("usb_rotation_enabled", enabled)

    manager.set_rotation = switch
    main.app.state.manager = manager
    client = TestClient(main.app)
    assert client.get("/api/test-videos").status_code == 401
    assert client.get("/api/camera-switching").status_code == 401
    client.cookies.set("session", "test-session")
    headers = {"X-CSRF-Token": "test-session"}
    assert len(client.get("/api/test-videos").json()) == 2
    assert client.put("/api/camera-switching", json={"enabled": True}).status_code == 403
    assert client.put("/api/camera-switching", headers=headers, json={"enabled": True}).json() == {
        "enabled": True
    }
    assert client.get("/api/camera-switching").json() == {"enabled": True}
    for value in ("car-park", "parking-garage"):
        response = client.post(
            "/api/cameras", headers=headers, json={"name": value, "kind": "test", "source": value}
        )
        assert response.status_code == 200
    assert (
        client.post(
            "/api/cameras",
            headers=headers,
            json={"name": "Bad", "kind": "test", "source": "../../secret/integration.key"},
        ).status_code
        == 400
    )
    assert {c["kind"] for c in store.cameras()} == {"test"}
