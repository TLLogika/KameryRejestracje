"""Optional local video substitutions; real camera configuration stays in SQLite."""

import json
import math
from pathlib import Path


def load_test_sources(config_file):
    if not config_file or not Path(config_file).is_file():
        return {}
    values = json.loads(Path(config_file).read_text())
    root = (Path(__file__).resolve().parent.parent.parent / "data/test-videos").resolve()
    result = {}
    for camera_id, value in values.items():
        path = (root / value["file"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != ".mp4":
            raise ValueError("Nieprawidłowy plik testowy kamery")
        result[int(camera_id)] = {"source": str(path), "label": str(value["label"])[:80]}
        roi = value.get("analysis_roi")
        if roi is not None:
            if (
                set(roi) != {"x", "y", "w", "h"}
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in roi.values())
                or not (
                    0 <= roi["x"] < 1
                    and 0 <= roi["y"] < 1
                    and 0 < roi["w"] <= 1
                    and 0 < roi["h"] <= 1
                    and roi["x"] + roi["w"] <= 1.0001
                    and roi["y"] + roi["h"] <= 1.0001
                )
            ):
                raise ValueError("Nieprawidłowy obszar analizy nagrania")
            result[int(camera_id)]["analysis_roi"] = roi
    return result
