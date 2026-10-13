"""Round-robin OCR of fresh frames and three-frame confirmation."""

import logging
import os
from pathlib import Path
import time
import numpy as np
from .recognition import zone_at
from .frame_geometry import crop_for_analysis

logger = logging.getLogger(__name__)


def recognize(manager):
    try:
        from fast_alpr import ALPR

        cache = os.environ.get("ALPR_CACHE_DIR")
        if cache:
            from open_image_models.detection.core import hub as detector_hub
            from fast_plate_ocr.inference import hub as ocr_hub

            detector_hub.MODEL_CACHE_DIR = Path(cache) / "open-image-models"
            ocr_hub.MODEL_CACHE_DIR = Path(cache) / "fast-plate-ocr"
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        alpr = ALPR(
            detector_model="yolo-v9-t-384-license-plate-end2end",
            ocr_model="cct-xs-v2-global-model",
            detector_providers=["CPUExecutionProvider"],
            ocr_providers=["CPUExecutionProvider"],
            detector_sess_options=options,
            ocr_sess_options=options,
        )
        test_alpr = (
            ALPR(
                detector_model="yolo-v9-t-256-license-plate-end2end",
                ocr=alpr.ocr,
                detector_providers=["CPUExecutionProvider"],
                detector_sess_options=options,
            )
            if manager.test_store
            else alpr
        )
        manager.ocr_status = "Działa"
    except Exception as exc:
        manager.ocr_status = "Błąd ładowania modeli — sprawdź log"
        logger.exception("Nie udało się załadować ALPR")
        return
    processed = {}
    while not manager.stop.is_set():
        for key, worker in list(manager.workers.items()):
            with worker.lock:
                sequence = worker.sequence
                capture_epoch = worker.capture_epoch
                frame = None if worker.frame is None else worker.frame.copy()
            if frame is None or processed.get(key) == sequence:
                continue
            processed[key] = sequence
            try:
                h, w = frame.shape[:2]
                reads, boxes = [], []
                inference_start = time.monotonic()
                analysis_frame, offset_x, offset_y = crop_for_analysis(
                    frame, worker.test_video.get("analysis_roi") if worker.test_video else None
                )
                predictions = (test_alpr if worker.test_video else alpr).predict(analysis_frame)
                inference_end = time.monotonic()
                for result in predictions:
                    if result.ocr is None:
                        continue
                    box = result.detection.bounding_box
                    x1 = max(0, box.x1 + offset_x)
                    y1 = max(0, box.y1 + offset_y)
                    x2 = min(w, box.x2 + offset_x)
                    y2 = min(h, box.y2 + offset_y)
                    x, y = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
                    confidence = float(np.mean(result.ocr.confidence))
                    boxes.append(
                        {
                            "text": result.ocr.text,
                            "confidence": confidence,
                            "x": x1 / w,
                            "y": y1 / h,
                            "w": (x2 - x1) / w,
                            "h": (y2 - y1) / h,
                        }
                    )
                    zone = zone_at(worker.config["zones"], x, y)
                    if zone:
                        reads.append((result.ocr.text, confidence, x, y, zone))
                if worker.stop.is_set() or worker.capture_epoch != capture_epoch:
                    continue
                with worker.lock:
                    if worker.capture_epoch != capture_epoch:
                        continue
                    worker.ocr_durations.append(inference_end - inference_start)
                    if worker.last_ocr_at is not None:
                        worker.ocr_intervals.append(inference_end - worker.last_ocr_at)
                    worker.last_ocr_at = inference_end
                    worker.ocr_times.append(inference_end)
                    worker.detections = boxes
                for plate, zone, confidence in worker.consensus.frame(reads):
                    manager.record_confirmation(worker, plate, zone, confidence)
            except Exception:
                logger.exception("Błąd rozpoznawania kamery %s", key)
        manager.stop.wait(0.005)
