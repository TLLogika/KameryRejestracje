import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from urllib.request import urlopen
from urllib.error import HTTPError
from app.usb_bridge import BridgeCapture, bridge_devices, bridge_request
from scripts import windows_usb_bridge as bridge


def test_authenticated_bridge_enumeration_frames_and_disconnect_cleanup(tmp_path, monkeypatch):
    key = "usb-bridge-test-key-" * 3
    key_file = tmp_path / "bridge.key"
    key_file.write_text(key)
    info = SimpleNamespace(
        path="usb-test-device", name="USB camera", index=0, backend=cv2.CAP_DSHOW
    )
    releases = []

    class Capture:
        def __init__(self, *args):
            pass

        def set(self, *args):
            pass

        def read(self):
            return True, np.full((48, 64, 3), 120, dtype=np.uint8)

        def release(self):
            releases.append(True)

    monkeypatch.setattr(bridge.cv2, "VideoCapture", Capture)
    registry = bridge.Registry(lambda: [info], fps=15)
    server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.make_handler(registry, key))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("USB_BRIDGE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("USB_BRIDGE_KEY_FILE", str(key_file))
    capture = None
    try:
        with pytest.raises(HTTPError) as exc:
            urlopen(f"http://127.0.0.1:{server.server_port}/devices")
        assert exc.value.code == 401
        found = bridge_devices()
        assert len(found) == 1 and found[0]["source"].startswith("bridge:")
        request = bridge_request("/devices")
        assert (
            key not in request.full_url and request.get_header("Authorization") == "Bearer " + key
        )
        capture = BridgeCapture(found[0]["source"])
        ok, frame = capture.read()
        assert ok and frame.shape == (48, 64, 3)
        assert capture.get(cv2.CAP_PROP_FPS) == 15
        capture.release()
        capture = None
        deadline = time.monotonic() + 3
        while registry.cameras and time.monotonic() < deadline:
            time.sleep(0.05)
        assert releases and not registry.cameras
    finally:
        if capture:
            capture.release()
        server.shutdown()
        server.server_close()
        registry.close()
        thread.join(2)


def test_stable_windows_device_identity_does_not_depend_on_opencv_index():
    a = SimpleNamespace(path="usb-physical-a", index=0)
    b = SimpleNamespace(path="usb-physical-a", index=4)
    assert bridge.device_id(a) == bridge.device_id(b)
