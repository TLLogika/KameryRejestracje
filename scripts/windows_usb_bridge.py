#!/usr/bin/env python3
"""Optional native Windows USB capture for the Linux Docker panel."""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit
import cv2

ROOT = Path(__file__).resolve().parent.parent


def enumerate_windows():
    from cv2_enumerate_cameras import enumerate_cameras

    return [
        info
        for info in enumerate_cameras(cv2.CAP_DSHOW)
        if info.vid is not None or "usb" in str(info.path).lower()
    ]


def device_id(info):
    return hashlib.sha256(str(info.path).encode()).hexdigest()[:16]


class Camera:
    def __init__(self, info, width, height, fps):
        self.info = info
        self.width = width
        self.height = height
        self.fps = fps
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.jpeg = None
        self.sequence = 0
        self.thread = threading.Thread(target=self.capture, daemon=True)
        self.thread.start()

    def capture(self):
        cap = cv2.VideoCapture(self.info.index, self.info.backend)
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            deadline = time.monotonic()
            while not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    with self.condition:
                        self.jpeg = jpeg.tobytes()
                        self.sequence += 1
                        self.condition.notify_all()
                deadline += 1 / self.fps
                self.stop.wait(max(0, deadline - time.monotonic()))
                deadline = max(deadline, time.monotonic() - 1 / self.fps)
        finally:
            cap.release()
            self.stop.set()
            with self.condition:
                self.condition.notify_all()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)


class Registry:
    def __init__(self, enumerate_devices=enumerate_windows, width=1280, height=720, fps=15):
        self.enumerate_devices = enumerate_devices
        self.width = width
        self.height = height
        self.fps = fps
        self.lock = threading.RLock()
        self.cameras = {}

    def devices(self):
        with self.lock:
            return [{"id": device_id(info), "name": info.name} for info in self.enumerate_devices()]

    def acquire(self, ident):
        with self.lock:
            if ident in self.cameras:
                camera, clients = self.cameras[ident]
                self.cameras[ident] = (camera, clients + 1)
                return camera
            info = next(
                (info for info in self.enumerate_devices() if device_id(info) == ident), None
            )
            if info is None:
                return None
            camera = Camera(info, self.width, self.height, self.fps)
            self.cameras[ident] = (camera, 1)
            return camera

    def release(self, ident):
        with self.lock:
            item = self.cameras.get(ident)
            if item is None:
                return
            camera, clients = item
            if clients == 1:
                camera.close()
                del self.cameras[ident]
            else:
                self.cameras[ident] = (camera, clients - 1)

    def close(self):
        with self.lock:
            for camera, clients in self.cameras.values():
                camera.close()
            self.cameras.clear()


def make_handler(registry, key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log credentials or camera paths.

        def do_GET(self):
            if not hmac.compare_digest(
                self.headers.get("Authorization", "").encode(), ("Bearer " + key).encode()
            ):
                self.send_error(401, "Authentication required")
                return
            path = urlsplit(self.path).path
            if path == "/devices":
                data = json.dumps(registry.devices()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if not path.startswith("/stream/"):
                self.send_error(404)
                return
            ident = path.removeprefix("/stream/")
            camera = registry.acquire(ident)
            if camera is None:
                self.send_error(404)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Video-Fps", str(registry.fps))
                self.end_headers()
                sequence = -1
                while not camera.stop.is_set():
                    with camera.condition:
                        camera.condition.wait_for(
                            lambda: camera.sequence != sequence or camera.stop.is_set(), timeout=5
                        )
                        jpeg = camera.jpeg
                        fresh = camera.sequence != sequence
                        sequence = camera.sequence
                    if not fresh or not jpeg:
                        continue
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpeg)).encode()
                        + b"\r\n\r\n"
                        + jpeg
                        + b"\r\n"
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                registry.release(ident)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=10001)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=15)
    args = parser.parse_args()
    if not (
        1 <= args.port <= 65535
        and 1 <= args.fps <= 60
        and 160 <= args.width <= 4096
        and 120 <= args.height <= 2160
    ):
        parser.error("Invalid port, dimensions or FPS")
    cv2.setNumThreads(1)
    key_path = ROOT / "dsecret/usb-bridge.key"
    key_path.parent.mkdir(exist_ok=True)
    if not key_path.exists():
        with key_path.open("x") as f:
            f.write(secrets.token_urlsafe(48) + "\n")
    key = key_path.read_text().strip()
    if len(key) < 32:
        raise SystemExit("Invalid bridge key")
    registry = Registry(width=args.width, height=args.height, fps=args.fps)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(registry, key))
    print(
        f"USB bridge ready on port {args.port}; cameras open only when the panel requests a stream."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        registry.close()


if __name__ == "__main__":
    main()
