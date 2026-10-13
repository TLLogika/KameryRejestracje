from collections import deque
from types import SimpleNamespace
import threading
import time
import cv2
import numpy as np
from fastapi.testclient import TestClient
from app.motion import MotionGate, DEFAULT_MOTION
from app.recognition import zone_at, Consensus
from app.capture import Worker
from app.cameras import Manager
from app.ocr import run_recognition
from app.performance import DEFAULT_PERFORMANCE
from app.store import Store


def region(x=0, y=0, w=0.5, h=1):
    return {"x": x, "y": y, "w": w, "h": h}


def test_change_percentage_ignores_outside_and_noise_then_expires():
    gate = MotionGate()
    config = DEFAULT_MOTION | {
        "enabled": True,
        "threshold_percent": 10,
        "pixel_delta": 20,
        "check_fps": 10,
    }
    baseline = np.zeros((90, 160, 3), dtype=np.uint8)
    assert not gate.observe(baseline, [region()], config, 0, 3)
    outside = baseline.copy()
    outside[:, 80:] = 255
    assert not gate.observe(outside, [region()], config, 0.2, 3)
    noisy = outside.copy()
    noisy[:, :80] = 5
    assert not gate.observe(noisy, [region()], config, 0.4, 3)
    changed = outside.copy()
    changed[:20, :80] = 255
    assert gate.observe(changed, [region()], config, 0.6, 3)
    assert 20 < gate.changed_percent < 25
    assert gate.triggers == 1
    assert gate.observe(changed, [region()], config, 1, 3)
    assert not gate.observe(changed, [region()], config, 4, 3)
    assert gate.changed_percent == 0 and gate.triggers == 1


def test_slow_accumulated_change_multiple_regions_and_rearming():
    gate = MotionGate()
    config = DEFAULT_MOTION | {"enabled": True, "check_fps": 10}
    baseline = np.zeros((90, 160, 3), dtype=np.uint8)
    areas = [region(0, 0, 0.1, 1), region(0.5, 0, 0.5, 1)]
    assert not gate.observe(baseline, areas, config, 0, 5)
    for step in (1, 2, 3):
        frame = baseline.copy()
        frame[:, 80:] = step * 5
        assert not gate.observe(frame, areas, config, step * 0.2, 5)
    frame = baseline.copy()
    frame[:, 80:] = 25
    assert gate.observe(frame, areas, config, 1, 5)
    assert gate.changed_percent == 100
    assert not gate.observe(frame, areas, config, 7, 5)
    assert gate.observe(baseline, areas, config, 8, 5)
    assert gate.triggers == 2
    assert not gate.observe(baseline, [region(0.2, 0, 0.2, 1)], config, 9, 5)


def test_blue_overlap_never_changes_parking_classification():
    blue = region(0, 0, 1, 1)
    assert zone_at({"motion": [blue]}, 0.5, 0.5) is None
    assert zone_at({"motion": [blue], "arrival": [region()]}, 0.2, 0.5) == "arrival"


def test_motion_api_persistence_validation_and_removal(tmp_path, monkeypatch):
    from app import main

    store = Store(tmp_path / "parking.db")
    camera = store.add_camera("Test", "test", "car-park")
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "sessions", {"motion-session": time.time() + 100})
    manager = SimpleNamespace(workers={})

    def reload():
        manager.workers = {c["id"]: SimpleNamespace(config=c) for c in store.cameras()}

    manager.reload = reload
    reload()
    monkeypatch.setattr(main.app.state, "manager", manager, raising=False)
    client = TestClient(main.app)
    assert client.put(f"/api/cameras/{camera}/motion", json={"enabled": True}).status_code == 401
    client.cookies.set("session", "motion-session")
    headers = {"X-CSRF-Token": "motion-session"}
    assert client.put(f"/api/cameras/{camera}/motion", json={"enabled": True}).status_code == 403
    assert (
        client.put(
            f"/api/cameras/{camera}/motion", headers=headers, json={"enabled": True}
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"/api/cameras/{camera}/zones",
            headers=headers,
            json={"arrival": [region()], "motion": [region(0, 0, 1, 1)]},
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/cameras/{camera}/motion",
            headers=headers,
            json={"enabled": True, "threshold_percent": 7},
        ).status_code
        == 200
    )
    saved = Store(tmp_path / "parking.db").cameras()[0]
    assert saved["motion"]["enabled"] and saved["motion"]["threshold_percent"] == 7
    assert (
        client.put(
            f"/api/cameras/{camera}/motion", headers=headers, json={"threshold_percent": 101}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/cameras/{camera}/motion", headers=headers, json={"enabled": False}
        ).json()["threshold_percent"]
        == 7
    )
    # Old clients updating only parking regions preserve the blue area.
    assert (
        client.put(
            f"/api/cameras/{camera}/zones", headers=headers, json={"arrival": [region()]}
        ).status_code
        == 200
    )
    assert store.cameras()[0]["zones"]["motion"]
    assert (
        client.put(
            f"/api/cameras/{camera}/motion", headers=headers, json={"enabled": True}
        ).status_code
        == 200
    )
    removed = client.put(
        f"/api/cameras/{camera}/zones", headers=headers, json={"arrival": [region()], "motion": []}
    )
    assert removed.json()["motion_disabled"] and not store.cameras()[0]["motion"]["enabled"]


def test_idle_motion_skips_model_calls_and_records_three_frames_after_trigger(tmp_path):
    manager = Manager.__new__(Manager)
    manager.store = Store(tmp_path / "parking.db")
    manager.test_store = Store(tmp_path / "test.db")
    manager.stop = threading.Event()
    manager.performance = DEFAULT_PERFORMANCE | {"ocr_fps": 10}
    worker = Worker.__new__(Worker)
    worker.config = {
        "id": 1,
        "kind": "usb",
        "zones": {"arrival": [region(0, 0, 1, 1)], "motion": [region(0, 0, 1, 1)]},
        "motion": DEFAULT_MOTION | {"enabled": True, "check_fps": 10},
    }
    worker.manager = manager
    worker.lock = threading.Lock()
    worker.sequence = 1
    worker.capture_epoch = 0
    worker.frame = np.zeros((90, 160, 3), dtype=np.uint8)
    worker.test_video = None
    worker.stop = threading.Event()
    worker.ocr_durations = deque()
    worker.ocr_intervals = deque()
    worker.ocr_times = deque()
    worker.last_ocr_at = None
    worker.motion_gate = MotionGate()
    worker.motion_allowed = False
    worker.consensus = Consensus()
    worker.confirmed_reads = 0
    worker.detections = []
    manager.workers = {1: worker}
    calls = []
    prediction = SimpleNamespace(
        ocr=SimpleNamespace(text="TEST123", confidence=[0.99]),
        detection=SimpleNamespace(bounding_box=SimpleNamespace(x1=20, y1=20, x2=60, y2=40)),
    )

    class Alpr:
        def predict(self, frame):
            calls.append(time.monotonic())
            worker.sequence += 1
            return [prediction]

    worker.observe_motion(worker.frame)
    thread = threading.Thread(target=run_recognition, args=(manager, Alpr(), Alpr(), 1))
    thread.start()
    try:
        time.sleep(0.2)
        assert calls == [] and manager.store.events(0) == []
        worker.frame = np.full((90, 160, 3), 255, dtype=np.uint8)
        worker.observe_motion(worker.frame)
        deadline = time.monotonic() + 3
        while not manager.store.events(0) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(manager.store.events(0)) == 1 and len(calls) >= 3
        worker.motion_gate.active_until = 0
        before = len(calls)
        time.sleep(0.2)
        assert len(calls) == before
    finally:
        manager.stop.set()
        thread.join(3)
    assert not thread.is_alive()


def test_active_window_adapts_without_extending_static_scene_forever():
    gate = MotionGate()
    config = DEFAULT_MOTION | {"enabled": True, "check_fps": 10}
    baseline = np.zeros((30, 40, 3), dtype=np.uint8)
    changed = np.full_like(baseline, 255)
    assert not gate.observe(baseline, [region(0, 0, 1, 1)], config, 0, 5)
    assert gate.observe(changed, [region(0, 0, 1, 1)], config, 1, 5)
    assert gate.observe(changed, [region(0, 0, 1, 1)], config, 4, 15)
    assert gate.active_until == 16
    assert gate.observe(changed, [region(0, 0, 1, 1)], config, 15, 15)
    assert not gate.observe(changed, [region(0, 0, 1, 1)], config, 17, 15)
    assert gate.triggers == 1
