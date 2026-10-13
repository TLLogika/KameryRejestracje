"""Persistent CPU and preview controls; limits are ceilings, not promised throughput."""

from pydantic import BaseModel, Field


class PerformanceSettings(BaseModel):
    preview_enabled: bool = True
    preview_on_demand: bool = True
    preview_fps: int = Field(default=5, ge=1, le=30)
    preview_width: int = Field(default=640, ge=320, le=1920)
    jpeg_quality: int = Field(default=55, ge=30, le=90)
    ocr_enabled: bool = True
    ocr_fps: float = Field(default=2, ge=0.5, le=15, allow_inf_nan=False)
    ocr_threads: int = Field(default=1, ge=1, le=8)

    model_config = {"extra": "forbid"}


DEFAULT_PERFORMANCE = PerformanceSettings().model_dump()


def settings_for(manager):
    return getattr(manager, "performance", DEFAULT_PERFORMANCE)


def analysis_due(settings, now, last_started):
    return settings["ocr_enabled"] and now - last_started >= 1 / settings["ocr_fps"]
