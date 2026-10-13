"""Latest-frame acquisition and preview; no OCR or database writes."""

from collections import deque
import logging
import math
import threading
import time
import cv2
from .performance import settings_for
from .recognition import Consensus
from .usb_bridge import BridgeCapture
from .video_settings import DEFAULT_SETTINGS, MIN_ROTATION_SECONDS

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, config, manager):
        self.config, self.manager = config, manager
        self.test_video = getattr(manager, "test_sources", {}).get(config["id"])
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.frame = self.jpeg = None
        self.preview_viewers = 0
        self.preview_sequence = 0
        self.preview_times = deque(maxlen=300)
        self.preview_durations = deque(maxlen=120)
        self.last_preview_at = 0
        self.sequence = 0
        self.capture_epoch = 0
        self.reconfigure = threading.Event()
        self.capture_times = deque(maxlen=300)
        self.ocr_times = deque(maxlen=120)
        self.ocr_durations = deque(maxlen=60)
        self.ocr_intervals = deque(maxlen=60)
        self.last_ocr_at = None
        self.last_frame_at = None
        self.actual_resolution = None
        self.preview_resolution = None
        self.confirmed_reads = 0
        self.last_confirmation = None
        self.device_fps = None
        self.device_format = None
        self.turn_deadline = None
        self.status = "Łączenie"
        self.detections = []
        self.consensus = Consensus()
        self.thread = threading.Thread(
            target=self.capture, daemon=True, name=f"camera-{config['id']}"
        )
        self.thread.start()

    @staticmethod
    def _rate(times):
        if len(times) < 2 or times[-1] <= times[0]:
            return None
        cutoff = times[-1] - 5
        recent = [t for t in times if t >= cutoff]
        return round((len(recent) - 1) / (recent[-1] - recent[0]), 1) if len(recent) > 1 else None

    def minimum_seconds(self):
        with self.lock:
            intervals = list(self.ocr_intervals)
            durations = list(self.ocr_durations)

        def p95(values):
            return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)] if values else 0

        performance = settings_for(getattr(self, "manager", None))
        cycle = max(p95(intervals), p95(durations) + 0.25, 1 / performance["ocr_fps"])
        return max(MIN_ROTATION_SECONDS, math.ceil(4 * cycle + 0.5))

    def snapshot(self):
        minimum = self.minimum_seconds()
        with self.lock:
            live = self.status == "Działa"
            now = time.monotonic()
            return {key: self.config[key] for key in ("id", "name", "kind", "zones")} | {
                "status": self.status,
                "detections": list(self.detections),
                "test_mode": bool(getattr(self, "test_video", None)),
                **(
                    {
                        "name": self.config["name"] + " — TEST: " + self.test_video["label"],
                        "kind": "test",
                    }
                    if getattr(self, "test_video", None)
                    else {}
                ),
                "settings": DEFAULT_SETTINGS | self.config.get("settings", {}),
                "metrics": {
                    "detector_input_size": 256 if getattr(self, "test_video", None) else 384,
                    "analysis_roi": (
                        self.test_video.get("analysis_roi")
                        if getattr(self, "test_video", None)
                        else None
                    ),
                    "preview_resolution": getattr(self, "preview_resolution", None),
                    "confirmed_reads": getattr(self, "confirmed_reads", 0),
                    "last_confirmation": getattr(self, "last_confirmation", None),
                    "resolution": self.actual_resolution,
                    "device_fps": self.device_fps,
                    "format": self.device_format,
                    "capture_fps": self._rate(self.capture_times) if live else 0,
                    "last_capture_fps": self._rate(self.capture_times),
                    "ocr_fps": (
                        self._rate(self.ocr_times)
                        if live and settings_for(self.manager)["ocr_enabled"]
                        else 0
                    ),
                    "preview_enabled": settings_for(self.manager)["preview_enabled"],
                    "preview_fps": (
                        self._rate(getattr(self, "preview_times", []))
                        if live
                        and settings_for(self.manager)["preview_enabled"]
                        and (
                            getattr(self, "preview_viewers", 0)
                            or not settings_for(self.manager)["preview_on_demand"]
                        )
                        else 0
                    ),
                    "preview_viewers": getattr(self, "preview_viewers", 0),
                    "preview_frames": getattr(self, "preview_sequence", 0),
                    "preview_ms": (
                        round(sum(self.preview_durations) / len(self.preview_durations) * 1000, 1)
                        if getattr(self, "preview_durations", None)
                        else None
                    ),
                    "preview_fps_limit": settings_for(self.manager)["preview_fps"],
                    "ocr_fps_limit": settings_for(self.manager)["ocr_fps"],
                    "last_ocr_fps": self._rate(self.ocr_times),
                    "ocr_ms": (
                        round(sum(self.ocr_durations) / len(self.ocr_durations) * 1000, 1)
                        if self.ocr_durations
                        else None
                    ),
                    "frame_age": round(now - self.last_frame_at, 1) if self.last_frame_at else None,
                    "turn_remaining": (
                        round(max(0, self.turn_deadline - now), 1)
                        if self.turn_deadline and live
                        else None
                    ),
                    "minimum_seconds": minimum,
                    "recommended_seconds": max(5, minimum),
                    "rotation_enabled": self.config["kind"] == "usb"
                    and self.manager.usb_rotation_seconds > 0
                    and not getattr(self, "test_video", None),
                },
            }

    def capture(self):
        while not self.stop.is_set():
            cap = None
            rotating = (
                self.config["kind"] == "usb"
                and self.manager.usb_rotation_seconds > 0
                and not self.test_video
            )
            if rotating:
                self.status = "Wstrzymana — ostatnia klatka" if self.jpeg else "Czeka na turę USB"
                if not self.manager.usb_turns.acquire(self.config["id"], self.stop):
                    return
                self.status = "Łączenie"
            with self.lock:
                settings = DEFAULT_SETTINGS | self.config.get("settings", {})
                self.reconfigure.clear()
                self.capture_epoch += 1
                self.consensus = Consensus()
                self.capture_times.clear()
                self.ocr_times.clear()
                self.last_ocr_at = None
                self.turn_deadline = None
                self.detections = []
            failed = False
            deadline = None
            try:
                source = self.test_video["source"] if self.test_video else self.config["source"]
                if self.test_video:
                    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
                elif source.startswith("bridge:"):
                    cap = BridgeCapture(source)
                elif self.config["kind"] == "usb":
                    cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*settings["format"]))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings["width"])
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings["height"])
                    cap.set(cv2.CAP_PROP_FPS, settings["fps"])
                else:
                    cap = cv2.VideoCapture(
                        source,
                        cv2.CAP_FFMPEG,
                        [
                            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                            5000,
                            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                            5000,
                            cv2.CAP_PROP_N_THREADS,
                            1,
                        ],
                    )
                if not cap.isOpened():
                    raise RuntimeError("Brak połączenia")
                with self.lock:
                    self.device_fps = cap.get(cv2.CAP_PROP_FPS) or None
                    code = int(cap.get(cv2.CAP_PROP_FOURCC))
                    self.device_format = (
                        "".join(chr((code >> (8 * i)) & 255) for i in range(4)).strip("\x00")
                        or None
                    )
                video_tick = time.monotonic()
                video_interval = 1 / max(1, min(60, self.device_fps or 15))
                while not self.stop.is_set() and not self.reconfigure.is_set():
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    ok, frame = cap.read()
                    if not ok and self.test_video:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        with self.lock:
                            self.capture_epoch += 1
                            self.consensus = Consensus()
                        ok, frame = cap.read()
                        video_tick = time.monotonic()
                    if not ok:
                        raise RuntimeError("Brak obrazu")
                    if rotating and deadline is None:
                        deadline = time.monotonic() + settings["rotation_seconds"]
                    self.encode_preview(frame)
                    with self.lock:
                        self.frame = frame
                        self.sequence += 1
                        self.capture_times.append(time.monotonic())
                        self.last_frame_at = self.capture_times[-1]
                        self.actual_resolution = {"width": frame.shape[1], "height": frame.shape[0]}
                        self.turn_deadline = deadline
                        self.status = "Działa"
                    if self.test_video:
                        video_tick += video_interval
                        self.stop.wait(max(0, video_tick - time.monotonic()))
                        video_tick = max(video_tick, time.monotonic() - video_interval)
                    else:
                        self.stop.wait(0.001 if self.config["kind"] == "usb" else 0.07)
            except Exception:
                failed = True
                self.status = "Brak obrazu — ponawiam"
                with self.lock:
                    self.frame = self.jpeg = None
                logger.warning("Kamera %s: brak połączenia", self.config["id"])
            finally:
                if cap is not None:
                    cap.release()
                with self.lock:
                    self.frame = None
                    self.capture_epoch += 1
                    self.turn_deadline = None
                    if not failed:
                        self.status = (
                            ("Wstrzymana — ostatnia klatka" if self.jpeg else "Czeka na turę USB")
                            if rotating
                            else "Łączenie"
                        )
                if rotating:
                    self.manager.usb_turns.release(self.config["id"])
            self.stop.wait(3 if failed else 0.05)

    def watch_preview(self, delta):
        with self.lock:
            self.preview_viewers = max(0, self.preview_viewers + delta)
            if self.preview_viewers == 0:
                self.preview_times.clear()

    def encode_preview(self, frame):
        performance = settings_for(self.manager)
        now = time.monotonic()
        with self.lock:
            if not performance["preview_enabled"] or (
                performance["preview_on_demand"] and not self.preview_viewers
            ):
                return
            if now - self.last_preview_at < 1 / performance["preview_fps"]:
                return
        start = time.monotonic()
        preview = frame
        factor = max(1, math.ceil(frame.shape[1] / performance["preview_width"]))
        if factor > 1:
            preview = cv2.resize(
                frame,
                (frame.shape[1] // factor, frame.shape[0] // factor),
                interpolation=cv2.INTER_AREA,
            )
        ok, jpeg = cv2.imencode(
            ".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, performance["jpeg_quality"]]
        )
        finished = time.monotonic()
        with self.lock:
            if not settings_for(self.manager)["preview_enabled"]:
                return
            self.last_preview_at = now
            self.preview_durations.append(finished - start)
            self.preview_times.append(finished)
            self.jpeg = jpeg.tobytes() if ok else None
            self.preview_sequence += 1
            self.preview_resolution = {"width": preview.shape[1], "height": preview.shape[0]}
