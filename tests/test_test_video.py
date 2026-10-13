import json
import threading
import time
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.cameras import Worker
from app.optional.test_video import load_test_sources


def test_missing_override_and_path_escape(tmp_path):
    assert load_test_sources("") == {}
    assert load_test_sources(tmp_path / "missing.json") == {}
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"test")
    config = tmp_path / "test.json"
    config.write_text(json.dumps({"1": {"file": str(outside), "label": "test"}}))
    with pytest.raises(ValueError):
        load_test_sources(config)


def test_usb_substitution_loops_without_using_usb_gate(tmp_path):
    path = tmp_path / "loop.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    for value in (40, 100, 200):
        writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    writer.release()

    class ForbiddenGate:
        def acquire(self, *args):
            pytest.fail("Test video attempted USB acquisition")

    manager = SimpleNamespace(
        test_sources={1: {"source": str(path), "label": "Sample"}},
        usb_rotation_seconds=5,
        usb_turns=ForbiddenGate(),
    )
    config = {"id": 1, "name": "USB", "kind": "usb", "source": "/dev/video-test", "zones": {}}
    worker = Worker(config, manager)
    try:
        deadline = time.monotonic() + 4
        while worker.sequence < 8 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert worker.sequence >= 8
        snapshot = worker.snapshot()
        assert snapshot["test_mode"] and snapshot["kind"] == "test"
        assert snapshot["metrics"]["resolution"] == {"width": 64, "height": 48}
        assert not snapshot["metrics"]["rotation_enabled"]
        assert worker.capture_epoch >= 3
        assert worker.config == config
    finally:
        worker.stop.set()
        worker.thread.join(timeout=3)
    assert not worker.thread.is_alive()


def test_local_mapping_is_private_and_preserves_camera_id(tmp_path, monkeypatch):
    from app.optional import test_video

    monkeypatch.setattr(test_video, "__file__", str(tmp_path / "app/optional/test_video.py"))
    root = tmp_path / "data/test-videos"
    root.mkdir(parents=True)
    (root / "sample.mp4").write_bytes(b"sample")
    config = tmp_path / "mapping.json"
    config.write_text(json.dumps({"8": {"file": "sample.mp4", "label": "Sample"}}))
    result = load_test_sources(config)
    assert result == {8: {"source": str(root / "sample.mp4"), "label": "Sample"}}


def test_three_different_frames_confirm_into_test_database_only(tmp_path):
    from app.cameras import Manager
    from app.recognition import Consensus
    from app.store import Store

    manager = Manager.__new__(Manager)
    manager.store = Store(tmp_path / "production.sqlite3")
    manager.test_store = Store(tmp_path / "test.sqlite3")
    worker = SimpleNamespace(
        lock=threading.Lock(),
        confirmed_reads=0,
        last_confirmation=None,
        test_video={"label": "Test"},
        config={"id": 1},
    )
    manager.workers = {1: worker}
    vote = Consensus()
    for index in range(3):
        confirmed = vote.frame(
            [("TEST123", 0.99, 0.2 + 0.001 * index, 0.4, "arrival")], now=index * 0.4
        )
        for plate, zone, confidence in confirmed:
            manager.record_confirmation(worker, plate, zone, confidence)
        assert len(manager.test_store.events(0)) == (1 if index == 2 else 0)
    assert not manager.store.events(0)
    assert worker.confirmed_reads == 1
    assert manager.parking_store() is manager.test_store
    worker.test_video = None
    assert manager.parking_store() is manager.store


def test_road_calibration_contains_all_annotated_plates_and_ignores_metadata(tmp_path):
    from scripts.set_test_videos import road_roi

    annotation = tmp_path / "annotations.json"
    annotation.write_text(
        json.dumps(
            {
                "version": "1.0",
                "1": [[1, 0.4, 0.5, 0.4, 0.5, "FIRST"]],
                "2": [[1, 0.05, 0.2, 0.2, 0.3, "FIRST"], [2, 0.6, 0.8, 0.4, 0.9, "SECOND"]],
            }
        )
    )
    roi = road_roi(annotation)
    assert roi["x"] < 0.05 and roi["y"] < 0.2
    assert roi["x"] + roi["w"] > 0.8 and roi["y"] + roi["h"] > 0.9


def test_analysis_crop_uses_full_frame_coordinates_for_zones():
    from app.frame_geometry import crop_for_analysis
    from app.recognition import zone_at

    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    roi = {"x": 0.25, "y": 0.4, "w": 0.5, "h": 0.3}
    crop, x, y = crop_for_analysis(frame, roi)
    assert crop.shape == (30, 100, 3) and (x, y) == (50, 40)
    # A plate centre (20,10) in the crop is (70,50) in the original image.
    zones = {"arrival": [{"x": 0.3, "y": 0.45, "w": 0.1, "h": 0.1}]}
    assert zone_at(zones, (20 + x) / 200, (10 + y) / 100) == "arrival"
    assert crop_for_analysis(frame)[0] is frame
