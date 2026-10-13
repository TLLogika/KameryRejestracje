import asyncio
from collections import deque
from types import SimpleNamespace
import threading
import time
import cv2
import numpy as np
from fastapi.testclient import TestClient
from app.performance import DEFAULT_PERFORMANCE
from app.capture import Worker
from app.ocr import run_recognition, recognize
from app.cameras import Manager
from app.store import Store


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_preview_is_shared_rate_limited_and_idle_without_viewers(monkeypatch):
    calls = []
    real_encode = cv2.imencode

    def encode(*args):
        calls.append(time.monotonic())
        return real_encode(*args)

    monkeypatch.setattr(cv2, "imencode", encode)
    worker = Worker.__new__(Worker)
    worker.manager = SimpleNamespace(performance=DEFAULT_PERFORMANCE.copy())
    worker.lock = threading.Lock()
    worker.preview_viewers = 0
    worker.preview_sequence = 0
    worker.preview_times = deque()
    worker.preview_durations = deque()
    worker.last_preview_at = 0
    worker.jpeg = None
    frame = np.zeros((900, 1600, 3), dtype=np.uint8)
    for _ in range(10):
        worker.encode_preview(frame)
    assert calls == [] and worker.jpeg is None
    worker.watch_preview(1)
    worker.watch_preview(1)
    deadline = time.monotonic() + 0.65
    while time.monotonic() < deadline:
        worker.encode_preview(frame)
        time.sleep(0.01)
    assert 2 <= len(calls) <= 4
    assert all(b - a >= 0.19 for a, b in zip(calls, calls[1:]))
    decoded = cv2.imdecode(np.frombuffer(worker.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[1] <= 640
    assert worker.preview_sequence == len(calls)
    worker.watch_preview(-1)
    worker.watch_preview(-1)
    before = len(calls)
    time.sleep(0.21)
    worker.encode_preview(frame)
    assert len(calls) == before and worker.preview_viewers == 0
    worker.manager.performance = DEFAULT_PERFORMANCE | {"preview_enabled": False}
    worker.watch_preview(1)
    worker.encode_preview(frame)
    assert len(calls) == before


def make_ocr_worker():
    return SimpleNamespace(
        lock=threading.Lock(),
        sequence=1,
        capture_epoch=0,
        frame=np.zeros((24, 32, 3), dtype=np.uint8),
        test_video=None,
        config={"zones": {}},
        stop=threading.Event(),
        ocr_durations=deque(),
        ocr_intervals=deque(),
        last_ocr_at=None,
        ocr_times=deque(),
        detections=[],
        consensus=SimpleNamespace(frame=lambda reads: []),
    )


def test_ocr_rate_pause_resume_and_thread_reload(monkeypatch):
    worker = make_ocr_worker()
    calls = []
    loads = []

    class Alpr:
        def predict(self, frame):
            calls.append(time.monotonic())
            worker.sequence += 1
            return []

    def load(threads):
        loads.append(threads)
        return Alpr(), Alpr()

    monkeypatch.setattr("app.ocr.load_models", load)
    manager = SimpleNamespace(
        stop=threading.Event(), performance=DEFAULT_PERFORMANCE.copy(), workers={1: worker}
    )
    thread = threading.Thread(target=recognize, args=(manager,))
    thread.start()
    try:
        wait_for(lambda: len(calls) >= 3)
        assert all(b - a >= 0.49 for a, b in zip(calls, calls[1:]))
        manager.performance = DEFAULT_PERFORMANCE | {"ocr_enabled": False}
        wait_for(lambda: manager.ocr_status.startswith("Wstrzymany"))
        before = len(calls)
        time.sleep(0.25)
        assert len(calls) == before
        manager.performance = DEFAULT_PERFORMANCE | {"ocr_threads": 2}
        wait_for(lambda: loads == [1, 2] and len(calls) > before)
    finally:
        manager.stop.set()
        thread.join(3)
    assert not thread.is_alive()


def test_performance_api_validates_and_preserves_settings(tmp_path, monkeypatch):
    from app import main

    manager = Manager.__new__(Manager)
    manager.store = Store(tmp_path / "parking.db")
    manager.workers = {}
    manager.config_lock = threading.RLock()
    manager.performance = DEFAULT_PERFORMANCE.copy()
    monkeypatch.setattr(main.app.state, "manager", manager, raising=False)
    monkeypatch.setattr(main, "sessions", {"perf-session": time.time() + 100})
    client = TestClient(main.app)
    assert client.get("/api/performance").status_code == 401
    client.cookies.set("session", "perf-session")
    headers = {"X-CSRF-Token": "perf-session"}
    assert client.put("/api/performance", json=DEFAULT_PERFORMANCE).status_code == 403
    for field, value in [
        ("preview_fps", 0),
        ("preview_width", 100),
        ("jpeg_quality", 100),
        ("ocr_fps", 0),
        ("ocr_threads", 9),
    ]:
        assert (
            client.put(
                "/api/performance", headers=headers, json=DEFAULT_PERFORMANCE | {field: value}
            ).status_code
            == 422
        )
    values = DEFAULT_PERFORMANCE | {"preview_fps": 3, "ocr_enabled": False}
    assert client.put("/api/performance", headers=headers, json=values).json() == values
    assert client.get("/api/performance").json() == values
    assert Store(tmp_path / "parking.db").preference("performance") == values


def test_stream_detach_and_worker_replacement_release_preview_demand(monkeypatch):
    from app import main

    class Preview:
        def __init__(self):
            self.lock = threading.Lock()
            self.jpeg = b"jpeg"
            self.preview_sequence = 1
            self.viewers = 0

        def watch_preview(self, delta):
            self.viewers += delta

    first, second = Preview(), Preview()
    manager = SimpleNamespace(workers={1: first})
    monkeypatch.setattr(main.app.state, "manager", manager, raising=False)
    monkeypatch.setattr(main, "sessions", {"preview-test": time.time() + 100})

    async def disconnected():
        return False

    async def scenario():
        response = await main.stream(
            1, SimpleNamespace(is_disconnected=disconnected), "preview-test"
        )
        assert b"jpeg" in await anext(response.body_iterator)
        assert first.viewers == 1
        manager.workers[1] = second
        assert b"jpeg" in await anext(response.body_iterator)
        assert first.viewers == 0 and second.viewers == 1
        await response.body_iterator.aclose()
        assert second.viewers == 0

    asyncio.run(scenario())


def test_paused_ocr_does_not_write_confirmations_and_preview_changes_keep_votes(tmp_path):
    from app.recognition import Consensus

    manager = Manager.__new__(Manager)
    manager.store = Store(tmp_path / "parking.db")
    manager.test_store = Store(tmp_path / "test.db")
    manager.performance = DEFAULT_PERFORMANCE.copy()
    manager.config_lock = threading.RLock()
    worker = make_ocr_worker()
    worker.config["id"] = 1
    worker.confirmed_reads = 0
    worker.consensus = Consensus()
    worker.jpeg = b"preview"
    manager.workers = {1: worker}
    votes = worker.consensus
    epoch = worker.capture_epoch
    manager.set_performance(DEFAULT_PERFORMANCE | {"jpeg_quality": 40})
    assert worker.consensus is votes and worker.capture_epoch == epoch
    manager.set_performance(DEFAULT_PERFORMANCE | {"ocr_enabled": False})
    assert manager.record_confirmation(worker, "TEST123", "arrival", 0.99) is False
    assert worker.confirmed_reads == 0 and manager.store.events(0) == []
