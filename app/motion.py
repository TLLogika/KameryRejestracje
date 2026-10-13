"""Cheap scene-change gate inside blue regions; no plate recognition here."""

import cv2
from pydantic import BaseModel, Field


class MotionSettings(BaseModel):
    enabled: bool = False
    threshold_percent: float = Field(default=3, ge=0.1, le=100, allow_inf_nan=False)
    pixel_delta: int = Field(default=20, ge=1, le=100)
    check_fps: float = Field(default=3, ge=0.5, le=10, allow_inf_nan=False)
    active_seconds: float = Field(default=5, ge=1, le=120, allow_inf_nan=False)
    model_config = {"extra": "forbid"}


DEFAULT_MOTION = MotionSettings().model_dump()


class MotionGate:
    def __init__(self):
        self.reset()

    def reset(self):
        self.reference = None
        self.geometry = None
        self.last_check = -float("inf")
        self.active_until = 0
        self.triggered_at = 0
        self.changed_percent = 0
        self.triggers = 0
        self.effective_seconds = 0

    def allowed(self, now):
        return now < self.active_until

    def observe(self, frame, regions, settings, now, active_seconds):
        if not settings["enabled"]:
            return True
        if isinstance(regions, dict):
            regions = [regions]
        if not regions:
            self.reference = None
            self.active_until = 0
            return False
        if now - self.last_check < 1 / settings["check_fps"]:
            return self.allowed(now)
        self.last_check = now
        self.effective_seconds = active_seconds
        if self.allowed(now):
            self.active_until = max(self.active_until, self.triggered_at + active_seconds)
        height, width = frame.shape[:2]
        geometry = (
            width,
            height,
            tuple(tuple(r[k] for k in ("x", "y", "w", "h")) for r in regions),
        )
        samples = []
        for region in regions:
            x1, y1 = int(region["x"] * width), int(region["y"] * height)
            x2, y2 = min(width, int((region["x"] + region["w"]) * width)), min(
                height, int((region["y"] + region["h"]) * height)
            )
            crop = frame[y1 : max(y1 + 1, y2), x1 : max(x1 + 1, x2)]
            scale = min(1, 160 / crop.shape[1], 90 / crop.shape[0])
            small = cv2.resize(
                crop,
                (max(1, round(crop.shape[1] * scale)), max(1, round(crop.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            samples.append(cv2.GaussianBlur(gray, (3, 3), 0))
        if self.reference is None or self.geometry != geometry:
            self.reference, self.geometry = samples, geometry
            self.active_until = 0
            self.changed_percent = 0
            return False
        self.changed_percent = max(
            cv2.countNonZero(
                cv2.compare(cv2.absdiff(previous, current), settings["pixel_delta"], cv2.CMP_GE)
            )
            / current.size
            * 100
            for previous, current in zip(self.reference, samples)
        )
        if self.changed_percent >= settings["threshold_percent"]:
            self.reference = samples
            self.triggered_at = now
            self.active_until = now + active_seconds
            self.triggers += 1
        return self.allowed(now)
