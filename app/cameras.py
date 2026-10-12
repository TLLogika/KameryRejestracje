import glob
from collections import deque
import logging
import math
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from .recognition import Consensus, zone_at
from .video_settings import DEFAULT_SETTINGS, MIN_ROTATION_SECONDS

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


class UsbTurns:
    """FIFO gate held until VideoCapture.release finishes: at most one USB stream."""
    def __init__(self):
        self.condition = threading.Condition()
        self.waiting = deque()
        self.owner = None

    def acquire(self, camera_id, stop):
        with self.condition:
            self.waiting.append(camera_id)
            while not stop.is_set():
                if self.owner is None and self.waiting[0] == camera_id:
                    self.waiting.popleft()
                    self.owner = camera_id
                    return True
                self.condition.wait(.1)
            self.waiting.remove(camera_id)
            self.condition.notify_all()
            return False

    def release(self, camera_id):
        with self.condition:
            if self.owner == camera_id:
                self.owner = None
                self.condition.notify_all()


class Worker:
    def __init__(self, config, manager):
        self.config, self.manager = config, manager
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.frame = self.jpeg = None
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
        self.device_fps = None
        self.device_format = None
        self.turn_deadline = None
        self.status = 'Łączenie'
        self.detections = []
        self.consensus = Consensus()
        self.thread = threading.Thread(target=self.capture,daemon=True,name=f"camera-{config['id']}")
        self.thread.start()

    @staticmethod
    def _rate(times):
        if len(times)<2 or times[-1]<=times[0]:return None
        cutoff=times[-1]-5
        recent=[t for t in times if t>=cutoff]
        return round((len(recent)-1)/(recent[-1]-recent[0]),1) if len(recent)>1 else None

    def minimum_seconds(self):
        with self.lock:
            intervals=list(self.ocr_intervals)
            durations=list(self.ocr_durations)
        def p95(values):
            return sorted(values)[max(0,math.ceil(.95*len(values))-1)] if values else 0
        cycle=max(p95(intervals),p95(durations)+.25)
        return max(MIN_ROTATION_SECONDS,math.ceil(4*cycle+.5))

    def snapshot(self):
        minimum=self.minimum_seconds()
        with self.lock:
            live=self.status=='Działa'
            now=time.monotonic()
            return {key:self.config[key] for key in ('id','name','kind','zones')} | {
                'status':self.status,'detections':list(self.detections),
                'settings':DEFAULT_SETTINGS | self.config.get('settings',{}),
                'metrics':{'resolution':self.actual_resolution,'device_fps':self.device_fps,'format':self.device_format,
                    'capture_fps':self._rate(self.capture_times) if live else 0,
                    'last_capture_fps':self._rate(self.capture_times),
                    'ocr_fps':self._rate(self.ocr_times) if live else 0,
                    'last_ocr_fps':self._rate(self.ocr_times),
                    'ocr_ms':round(sum(self.ocr_durations)/len(self.ocr_durations)*1000,1) if self.ocr_durations else None,
                    'frame_age':round(now-self.last_frame_at,1) if self.last_frame_at else None,
                    'turn_remaining':round(max(0,self.turn_deadline-now),1) if self.turn_deadline and live else None,
                    'minimum_seconds':minimum,'recommended_seconds':max(5,minimum),
                    'rotation_enabled':self.manager.usb_rotation_seconds>0}}

    def capture(self):
        while not self.stop.is_set():
            cap = None
            rotating = self.config['kind']=='usb' and self.manager.usb_rotation_seconds > 0
            if rotating:
                self.status = 'Wstrzymana — ostatnia klatka' if self.jpeg else 'Czeka na turę USB'
                if not self.manager.usb_turns.acquire(self.config['id'],self.stop):
                    return
                self.status = 'Łączenie'
            with self.lock:
                settings=DEFAULT_SETTINGS | self.config.get('settings',{})
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
                source = self.config['source']
                if self.config['kind']=='usb':
                    cap = cv2.VideoCapture(source,cv2.CAP_V4L2)
                    cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*settings['format']))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,settings['width'])
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,settings['height'])
                    cap.set(cv2.CAP_PROP_FPS,settings['fps'])
                else:
                    cap = cv2.VideoCapture(source,cv2.CAP_FFMPEG,[cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,5000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,5000])
                if not cap.isOpened():
                    raise RuntimeError('Brak połączenia')
                with self.lock:
                    self.device_fps = cap.get(cv2.CAP_PROP_FPS) or None
                    code=int(cap.get(cv2.CAP_PROP_FOURCC))
                    self.device_format=''.join(chr((code>>(8*i))&255) for i in range(4)).strip('\x00') or None
                while not self.stop.is_set() and not self.reconfigure.is_set():
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError('Brak obrazu')
                    if rotating and deadline is None:
                        deadline = time.monotonic()+settings['rotation_seconds']
                    ok, jpeg = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,75])
                    with self.lock:
                        self.frame = frame
                        self.jpeg = jpeg.tobytes() if ok else None
                        self.sequence += 1
                        self.capture_times.append(time.monotonic())
                        self.last_frame_at = self.capture_times[-1]
                        self.actual_resolution = {'width':frame.shape[1],'height':frame.shape[0]}
                        self.turn_deadline = deadline
                        self.status = 'Działa'
                    self.stop.wait(.001 if self.config['kind']=='usb' else .07)
            except Exception:
                failed = True
                self.status = 'Brak obrazu — ponawiam'
                with self.lock:
                    self.frame = self.jpeg = None
                logger.warning('Kamera %s: brak połączenia',self.config['id'])
            finally:
                if cap is not None:
                    cap.release()
                with self.lock:
                    self.frame = None
                    self.capture_epoch += 1
                    self.turn_deadline = None
                    if not failed:
                        self.status = ('Wstrzymana — ostatnia klatka' if self.jpeg else 'Czeka na turę USB') if rotating else 'Łączenie'
                if rotating:
                    self.manager.usb_turns.release(self.config['id'])
            self.stop.wait(3 if failed else .05)


class Manager:
    def __init__(self, store):
        self.store = store
        self.workers = {}
        self.stop = threading.Event()
        self.usb_rotation_seconds = float(os.environ.get('USB_ROTATION_SECONDS','0'))
        if not 0 <= self.usb_rotation_seconds <= 60:
            raise ValueError('USB_ROTATION_SECONDS musi być w zakresie 0–60')
        self.usb_turns = UsbTurns()
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
                worker=self.workers[key]
                with worker.lock:
                    if worker.config.get('settings',{}) != config.get('settings',{}):
                        worker.reconfigure.set()
                    if worker.config['zones'] != config['zones'] or worker.reconfigure.is_set():
                        worker.consensus = Consensus()
                        worker.capture_epoch += 1
                    worker.config = config
            else:
                self.workers[key] = Worker(config,self)

    def recognize(self):
        try:
            from fast_alpr import ALPR
            cache = os.environ.get('ALPR_CACHE_DIR')
            if cache:
                from open_image_models.detection.core import hub as detector_hub
                from fast_plate_ocr.inference import hub as ocr_hub
                detector_hub.MODEL_CACHE_DIR = Path(cache)/'open-image-models'
                ocr_hub.MODEL_CACHE_DIR = Path(cache)/'fast-plate-ocr'
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
                    capture_epoch = worker.capture_epoch
                    frame = None if worker.frame is None else worker.frame.copy()
                if frame is None or processed.get(key)==sequence:
                    continue
                processed[key] = sequence
                try:
                    h,w = frame.shape[:2]
                    reads, boxes = [], []
                    inference_start=time.monotonic()
                    predictions=alpr.predict(frame)
                    inference_end=time.monotonic()
                    for result in predictions:
                        if result.ocr is None:
                            continue
                        box = result.detection.bounding_box
                        x,y = (box.x1+box.x2)/2/w,(box.y1+box.y2)/2/h
                        confidence = float(np.mean(result.ocr.confidence))
                        boxes.append({'text':result.ocr.text,'confidence':confidence,'x':box.x1/w,'y':box.y1/h,'w':(box.x2-box.x1)/w,'h':(box.y2-box.y1)/h})
                        zone = zone_at(worker.config['zones'],x,y)
                        if zone:
                            reads.append((result.ocr.text,confidence,x,y,zone))
                    if worker.stop.is_set() or worker.capture_epoch != capture_epoch:
                        continue
                    with worker.lock:
                        if worker.capture_epoch != capture_epoch:
                            continue
                        worker.ocr_durations.append(inference_end-inference_start)
                        if worker.last_ocr_at is not None:
                            worker.ocr_intervals.append(inference_end-worker.last_ocr_at)
                        worker.last_ocr_at=inference_end
                        worker.ocr_times.append(inference_end)
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
