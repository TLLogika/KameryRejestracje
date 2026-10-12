import glob
import logging
import os
import threading
import time

import cv2
import numpy as np
from .recognition import Consensus, zone_at

logger = logging.getLogger(__name__)


def usb_devices():
    devices = []
    for path in sorted(glob.glob('/dev/video*')):
        # V4L2 VIDIOC_QUERYCAP: exclude metadata-only nodes without opening streams.
        try:
            import fcntl
            caps = bytearray(104)
            with open(path, 'rb', buffering=0) as f:
                fcntl.ioctl(f, 0x80685600, caps)
            flags = int.from_bytes(caps[84:88], 'little')
            if flags & 0x80000000:
                flags = int.from_bytes(caps[88:92], 'little')
            if not flags & (1 | 0x1000):
                continue
            name = caps[16:48].split(b'\0')[0].decode(errors='replace')
            stable = next((p for p in glob.glob('/dev/v4l/by-id/*') if os.path.realpath(p)==path),path)
            devices.append({'source':stable,'name':name,'device':path})
        except (OSError, ValueError):
            continue
    return devices


class Worker:
    def __init__(self, config, manager):
        self.config, self.manager = config, manager
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.frame = self.jpeg = None
        self.sequence = 0
        self.status = 'Łączenie'
        self.detections = []
        self.consensus = Consensus()
        self.thread = threading.Thread(target=self.capture,daemon=True,name=f"camera-{config['id']}")
        self.thread.start()

    def capture(self):
        while not self.stop.is_set():
            cap = None
            try:
                source = self.config['source']
                if self.config['kind']=='usb':
                    cap = cv2.VideoCapture(source,cv2.CAP_V4L2)
                    cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
                    cap.set(cv2.CAP_PROP_FPS,15)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720)
                else:
                    cap = cv2.VideoCapture(source,cv2.CAP_FFMPEG,[cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,5000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,5000])
                if not cap.isOpened():
                    raise RuntimeError('Brak połączenia')
                while not self.stop.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError('Brak obrazu')
                    ok, jpeg = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,75])
                    with self.lock:
                        self.frame = frame
                        self.jpeg = jpeg.tobytes() if ok else None
                        self.sequence += 1
                        self.status = 'Działa'
                    self.stop.wait(.07)
            except Exception:
                self.status = 'Brak obrazu — ponawiam'
                with self.lock:
                    self.frame = self.jpeg = None
                logger.warning('Kamera %s: brak połączenia',self.config['id'])
            finally:
                if cap is not None:
                    cap.release()
            self.stop.wait(3)


class Manager:
    def __init__(self, store):
        self.store = store
        self.workers = {}
        self.stop = threading.Event()
        self.ocr_status = 'Ładowanie modeli'
        self.config_lock = threading.RLock()
        self.reload()
        self.thread = threading.Thread(target=self.recognize,daemon=True,name='alpr')
        self.thread.start()

    def reload(self):
        with self.config_lock:
            self._reload()

    def _reload(self):
        configs = {c['id']:c for c in self.store.cameras()}
        for key in list(self.workers):
            if key not in configs:
                worker = self.workers.pop(key)
                worker.stop.set()
                worker.thread.join(timeout=7)
        for key,config in configs.items():
            if key in self.workers:
                if self.workers[key].config['zones'] != config['zones']:
                    self.workers[key].consensus = Consensus()
                self.workers[key].config = config
            else:
                self.workers[key] = Worker(config,self)

    def recognize(self):
        try:
            from fast_alpr import ALPR
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            alpr = ALPR(detector_model='yolo-v9-t-384-license-plate-end2end',ocr_model='cct-xs-v2-global-model',detector_providers=['CPUExecutionProvider'],ocr_providers=['CPUExecutionProvider'],detector_sess_options=options,ocr_sess_options=options)
            self.ocr_status = 'Działa'
        except Exception as exc:
            self.ocr_status = 'Błąd ładowania modeli — sprawdź log'
            logger.exception('Nie udało się załadować ALPR')
            return
        processed = {}
        while not self.stop.is_set():
            for key,worker in list(self.workers.items()):
                with worker.lock:
                    sequence = worker.sequence
                    frame = None if worker.frame is None else worker.frame.copy()
                if frame is None or processed.get(key)==sequence:
                    continue
                processed[key] = sequence
                try:
                    h,w = frame.shape[:2]
                    reads, boxes = [], []
                    for result in alpr.predict(frame):
                        if result.ocr is None:
                            continue
                        box = result.detection.bounding_box
                        x,y = (box.x1+box.x2)/2/w,(box.y1+box.y2)/2/h
                        confidence = float(np.mean(result.ocr.confidence))
                        boxes.append({'text':result.ocr.text,'confidence':confidence,'x':box.x1/w,'y':box.y1/h,'w':(box.x2-box.x1)/w,'h':(box.y2-box.y1)/h})
                        zone = zone_at(worker.config['zones'],x,y)
                        if zone:
                            reads.append((result.ocr.text,confidence,x,y,zone))
                    if worker.stop.is_set():
                        continue
                    worker.detections = boxes
                    for plate,zone,confidence in worker.consensus.frame(reads):
                        self.store.transition(plate,zone,key,confidence)
                except Exception:
                    logger.exception('Błąd rozpoznawania kamery %s',key)
            self.stop.wait(.25)

    def close(self):
        self.stop.set()
        for worker in list(self.workers.values()):
            worker.stop.set()
        for worker in list(self.workers.values()):
            worker.thread.join(timeout=7)
        self.thread.join(timeout=10)
