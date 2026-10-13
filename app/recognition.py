import re
import time
from collections import Counter, deque


class Consensus:
    """Vote per spatial track: each plate has to win several separate frames."""

    def __init__(self, scans=3, window=12, confidence=0.8):
        self.scans, self.window, self.confidence = scans, window, confidence
        self.tracks = {}
        self.next_id = 0

    def frame(self, detections, now=None):
        now = time.monotonic() if now is None else now
        self.tracks = {k: v for k, v in self.tracks.items() if now - v["last"] < self.window}
        used, confirmed = set(), []
        for text, confidence, x, y, zone in detections:
            text = re.sub("[^A-Z0-9]", "", text.upper())
            if not 4 <= len(text) <= 12 or confidence < self.confidence:
                continue
            candidates = [
                (abs(t["x"] - x) + abs(t["y"] - y), k)
                for k, t in self.tracks.items()
                if k not in used
                and t["zone"] == zone
                and abs(t["x"] - x) < 0.15
                and abs(t["y"] - y) < 0.15
            ]
            if candidates:
                key = min(candidates)[1]
            else:
                key = self.next_id
                self.next_id += 1
                self.tracks[key] = {"votes": deque(maxlen=10), "zone": zone}
            used.add(key)
            track = self.tracks[key]
            track.update(x=x, y=y, last=now)
            track["votes"].append((now, text, confidence))
            track["votes"] = deque(
                [v for v in track["votes"] if now - v[0] < self.window], maxlen=10
            )
            votes = Counter(v[1] for v in track["votes"])
            winner, count = votes.most_common(1)[0]
            if count >= self.scans and count / len(track["votes"]) >= 0.6:
                score = sum(v[2] for v in track["votes"] if v[1] == winner) / count
                confirmed.append((winner, zone, score))
        return confirmed


def zone_at(zones, x, y):
    hits = {
        name
        for name, value in zones.items()
        if name in {"arrival", "departure"}
        for r in (value if isinstance(value, list) else [value])
        if r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]
    }
    return next(iter(hits)) if len(hits) == 1 else None
