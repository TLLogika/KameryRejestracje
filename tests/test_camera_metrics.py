import sqlite3
from collections import deque
from types import SimpleNamespace
import threading
from app.cameras import Worker
from app.store import Store


def test_old_database_migrates_without_losing_zones(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE cameras(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,source TEXT,zones TEXT)"
    )
    db.execute(
        "INSERT INTO cameras VALUES(1,?,?,?,?)",
        ("Camera", "usb", "/dev/video-test", '{"arrival":{"x":0,"y":0,"w":0.5,"h":1}}'),
    )
    db.commit()
    db.close()
    store = Store(path)
    camera = store.cameras()[0]
    assert camera["zones"]["arrival"]["w"] == 0.5
    assert camera["settings"]["rotation_seconds"] == 5
    changed = camera["settings"] | {"rotation_seconds": 7, "width": 640, "height": 480, "fps": 5}
    store.settings(1, changed)
    assert Store(path).cameras()[0]["settings"] == changed
    assert Store(path).cameras()[0]["zones"] == camera["zones"]


def test_rate_and_adaptive_minimum_exclude_paused_time():
    worker = Worker.__new__(Worker)
    worker.lock = threading.Lock()
    worker.ocr_intervals = deque([0.35] * 20)
    worker.ocr_durations = deque([0.1] * 20)
    assert worker.minimum_seconds() == 3
    worker.ocr_intervals = deque([1.1] * 20)
    assert worker.minimum_seconds() == 5
    assert Worker._rate(deque([0, 0.1, 0.2, 0.3])) == 10
    assert Worker._rate(deque([0, 100, 100.1, 100.2])) == 10


def test_paused_snapshot_keeps_resolution_but_reports_zero_live_rates():
    worker = Worker.__new__(Worker)
    worker.lock = threading.Lock()
    worker.ocr_intervals = deque([0.35] * 10)
    worker.ocr_durations = deque([0.1] * 10)
    worker.capture_times = deque([0, 0.1, 0.2])
    worker.ocr_times = deque([0, 0.5, 1])
    worker.status = "Wstrzymana — ostatnia klatka"
    worker.config = {"id": 1, "name": "Camera", "kind": "usb", "zones": {}}
    worker.detections = []
    worker.actual_resolution = {"width": 640, "height": 480}
    worker.device_fps = 15
    worker.device_format = "MJPG"
    worker.last_frame_at = None
    worker.turn_deadline = None
    worker.manager = SimpleNamespace(usb_rotation_seconds=5)
    result = worker.snapshot()
    assert "source" not in result
    assert result["metrics"]["capture_fps"] == 0
    assert result["metrics"]["last_capture_fps"] == 10
    assert result["metrics"]["ocr_fps"] == 0
    assert result["metrics"]["last_ocr_fps"] == 2
    assert result["metrics"]["resolution"] == {"width": 640, "height": 480}
