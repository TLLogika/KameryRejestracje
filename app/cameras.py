"""Camera lifecycle: acquisition and recognition run independently."""

import os
from pathlib import Path
import threading
import cv2
from .capture import Worker
from .devices import usb_devices
from .optional.usb_rotation import UsbTurns
from .ocr import recognize
from .recognition import Consensus
from .store import Store
from .optional.test_video import load_test_sources


class Manager:
    def __init__(self, store):
        self.store = store
        cv2.setNumThreads(1)
        self.workers = {}
        self.stop = threading.Event()
        self.usb_rotation_seconds = float(os.environ.get("USB_ROTATION_SECONDS", "0"))
        if not 0 <= self.usb_rotation_seconds <= 60:
            raise ValueError("USB_ROTATION_SECONDS musi być w zakresie 0–60")
        self.test_sources = load_test_sources(os.environ.get("TEST_CAMERA_SOURCES_FILE", ""))
        self.test_store = (
            Store(Path(__file__).resolve().parent.parent / "data/test-parking.sqlite3")
            if self.test_sources
            else None
        )
        self.usb_turns = UsbTurns()
        self.ocr_status = "Ładowanie modeli"
        self.config_lock = threading.RLock()
        self.reload()
        self.thread = threading.Thread(target=recognize, args=(self,), daemon=True, name="alpr")
        self.thread.start()

    def reload(self):
        with self.config_lock:
            self._reload()

    def _reload(self):
        configs = {c["id"]: c for c in self.store.cameras()}
        for key in list(self.workers):
            if key not in configs:
                worker = self.workers.pop(key)
                worker.stop.set()
                worker.thread.join(timeout=7)
        for key, config in configs.items():
            if key in self.workers:
                worker = self.workers[key]
                with worker.lock:
                    if worker.config.get("settings", {}) != config.get("settings", {}):
                        worker.reconfigure.set()
                    if worker.config["zones"] != config["zones"] or worker.reconfigure.is_set():
                        worker.consensus = Consensus()
                        worker.capture_epoch += 1
                    worker.config = config
            else:
                self.workers[key] = Worker(config, self)

    def record_confirmation(self, worker, plate, zone, confidence):
        with worker.lock:
            worker.confirmed_reads += 1
            worker.last_confirmation = {"plate": plate, "zone": zone, "confidence": confidence}
        destination = self.test_store if worker.test_video else self.store
        return destination.transition(plate, zone, worker.config["id"], confidence)

    def parking_store(self):
        if self.test_store and self.workers and all(w.test_video for w in self.workers.values()):
            return self.test_store
        return self.store

    def close(self):
        self.stop.set()
        for worker in list(self.workers.values()):
            worker.stop.set()
        for worker in list(self.workers.values()):
            worker.thread.join(timeout=7)
        self.thread.join(timeout=10)
