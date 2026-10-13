from app.recognition import Consensus, zone_at
from app.store import Store


def test_multiple_plates_separate_camera_votes():
    vote = Consensus()
    reads = [("WA12345", 0.95, 0.2, 0.2, "arrival"), ("KR98765", 0.93, 0.7, 0.7, "arrival")]
    assert vote.frame(reads, 0) == []
    assert vote.frame(reads, 1) == []
    assert {r[0] for r in vote.frame(reads, 2)} == {"WA12345", "KR98765"}
    assert Consensus().frame(reads, 2) == []


def test_disagreement_expiry_confidence():
    vote = Consensus()

    def scan(text, t, score=0.95):
        return vote.frame([(text, score, 0.3, 0.3, "arrival")], t)

    assert scan("WA12345", 0) == []
    assert scan("WA1234S", 1) == []
    assert scan("WA12345", 2) == []
    assert scan("WA12345", 3)[0][0] == "WA12345"
    assert scan("WA12345", 30) == []
    assert scan("WA12345", 31, 0.1) == []


def test_transition_deduplication_and_export(tmp_path):
    store = Store(tmp_path / "parking.db")
    assert store.transition("WA12345", "arrival", 1, 0.9)
    assert not store.transition("WA12345", "arrival", 2, 0.9)
    assert len(store.parking()["current"]) == 1
    assert store.transition("WA12345", "departure", 2, 0.9)
    assert not store.transition("WA12345", "departure", 2, 0.9)
    assert not store.parking()["current"]
    assert len(store.events(0)) == 2
    assert len(store.events(1)) == 1
    assert zone_at({"arrival": {"x": 0, "y": 0, "w": 0.4, "h": 1}}, 0.2, 0.2) == "arrival"
    assert zone_at({}, 0.2, 0.2) is None


def test_camera_persistence(tmp_path):
    path = tmp_path / "parking.db"
    store = Store(path)
    camera = store.add_camera("Wjazd", "usb", "/dev/video0")
    store.zones(camera, {"arrival": {"x": 0, "y": 0, "w": 0.3, "h": 0.4}})
    assert Store(path).cameras()[0]["zones"]["arrival"]["w"] == 0.3
