import sqlite3
from scripts.pull_events import initialize, apply_events
from fastapi.testclient import TestClient
from app import main
from app.integration import KEY
from app.store import Store


def test_shared_key_read_only_export(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite3")
    monkeypatch.setattr(main, "store", store)
    store.transition("WA12345", "arrival", 1, 0.95)
    client = TestClient(main.app)
    assert client.get("/api/integration/events").status_code == 401
    assert (
        client.get("/api/integration/events", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    headers = {"Authorization": "Bearer " + KEY}
    result = client.get("/api/integration/events", headers=headers)
    assert result.status_code == 200
    assert result.json()["events"][0]["plate"] == "WA12345"
    assert len(client.get("/api/integration/parking", headers=headers).json()["current"]) == 1
    assert client.get("/api/devices", headers=headers).status_code == 401


def test_receiver_atomic_cursor_idempotence_and_restart(tmp_path):
    path = tmp_path / "receiver.db"
    db = sqlite3.connect(path)
    initialize(db)
    events = [
        {
            "id": 1,
            "plate": "WA12345",
            "action": "arrival",
            "camera_id": 1,
            "confidence": 0.95,
            "at": "2026-10-12T12:00:00Z",
        }
    ]
    assert apply_events(db, "http://camera", events) == 1
    assert apply_events(db, "http://camera", events) == 0
    assert db.execute("SELECT count(*) FROM camera_parking").fetchone()[0] == 1
    db.close()
    db = sqlite3.connect(path)
    initialize(db)
    assert db.execute("SELECT last_id FROM sync_cursors").fetchone()[0] == 1
    events.append(events[0] | {"id": 2, "action": "departure"})
    assert apply_events(db, "http://camera", events) == 1
    assert db.execute("SELECT count(*) FROM camera_parking").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM camera_events").fetchone()[0] == 2
    broken = [
        events[0] | {"id": 3, "action": "arrival"},
        events[0] | {"id": 4, "action": "invalid"},
    ]
    try:
        apply_events(db, "http://camera", broken)
    except ValueError:
        pass
    assert db.execute("SELECT last_id FROM sync_cursors").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM camera_parking").fetchone()[0] == 0
