from .permissions import private_mode
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from .video_settings import DEFAULT_SETTINGS


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        private_mode(Path(path).parent, 0o700)
        self.db = sqlite3.connect(path, check_same_thread=False)
        private_mode(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript(
            """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS cameras(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,source TEXT,zones TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,plate TEXT,action TEXT,camera_id INTEGER,confidence REAL,at TEXT);
        CREATE TABLE IF NOT EXISTS parking(plate TEXT PRIMARY KEY,entered_at TEXT,camera_id INTEGER);
        """
        )
        if "settings" not in {r[1] for r in self.db.execute("PRAGMA table_info(cameras)")}:
            self.db.execute("ALTER TABLE cameras ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'")
        self.db.commit()

    def cameras(self):
        with self.lock:
            return [
                dict(r)
                | {
                    "zones": json.loads(r["zones"]),
                    "settings": DEFAULT_SETTINGS | json.loads(r["settings"]),
                }
                for r in self.db.execute("SELECT * FROM cameras")
            ]

    def add_camera(self, name, kind, source):
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM cameras WHERE source=?", (source,)).fetchone():
                raise ValueError("Ta kamera jest już dodana")
            return self.db.execute(
                "INSERT INTO cameras(name,kind,source,zones) VALUES(?,?,?,?)",
                (name, kind, source, "{}"),
            ).lastrowid

    def zones(self, camera_id, zones):
        with self.lock, self.db:
            self.db.execute("UPDATE cameras SET zones=? WHERE id=?", (json.dumps(zones), camera_id))

    def settings(self, camera_id, settings):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE cameras SET settings=? WHERE id=?", (json.dumps(settings), camera_id)
            )

    def delete(self, camera_id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM cameras WHERE id=?", (camera_id,))

    def transition(self, plate, action, camera_id, confidence):
        at = datetime.now(timezone.utc).isoformat()
        with self.lock, self.db:
            exists = self.db.execute("SELECT 1 FROM parking WHERE plate=?", (plate,)).fetchone()
            if (action == "arrival" and exists) or (action == "departure" and not exists):
                return False
            if action == "arrival":
                self.db.execute("INSERT INTO parking VALUES(?,?,?)", (plate, at, camera_id))
            else:
                self.db.execute("DELETE FROM parking WHERE plate=?", (plate,))
            self.db.execute(
                "INSERT INTO events(plate,action,camera_id,confidence,at) VALUES(?,?,?,?,?)",
                (plate, action, camera_id, confidence, at),
            )
            return True

    def parking(self):
        with self.lock:
            return {
                "current": [
                    dict(r)
                    for r in self.db.execute("SELECT * FROM parking ORDER BY entered_at DESC")
                ],
                "arrival": [
                    dict(r)
                    for r in self.db.execute(
                        "SELECT * FROM events WHERE action='arrival' ORDER BY id DESC LIMIT 100"
                    )
                ],
                "departure": [
                    dict(r)
                    for r in self.db.execute(
                        "SELECT * FROM events WHERE action='departure' ORDER BY id DESC LIMIT 100"
                    )
                ],
            }

    def events(self, after):
        with self.lock:
            return [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM events WHERE id>? ORDER BY id LIMIT 1000", (after,)
                )
            ]
