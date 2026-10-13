from app.recognition import zone_at, Consensus
from app.store import Store


def rect(x, y, w=0.2, h=0.2):
    return {"x": x, "y": y, "w": w, "h": h}


def test_multiple_regions_and_same_color_overlap():
    zones = {
        "arrival": [rect(0, 0), rect(0.6, 0), rect(0.1, 0.1)],
        "departure": [rect(0, 0.6), rect(0.6, 0.6)],
    }
    assert zone_at(zones, 0.05, 0.05) == "arrival"
    assert zone_at(zones, 0.7, 0.1) == "arrival"
    assert zone_at(zones, 0.15, 0.15) == "arrival"
    assert zone_at(zones, 0.1, 0.7) == "departure"
    assert zone_at(zones, 0.7, 0.7) == "departure"
    assert zone_at(zones, 0.5, 0.5) is None
    assert zone_at({"arrival": [rect(0, 0)], "departure": [rect(0, 0)]}, 0.1, 0.1) is None
    assert zone_at({"arrival": rect(0, 0)}, 0.1, 0.1) == "arrival"


def test_multi_region_persistence_and_consensus(tmp_path):
    store = Store(tmp_path / "zones.db")
    camera = store.add_camera("Camera", "usb", "/dev/video-test")
    zones = {"arrival": [rect(0, 0), rect(0.6, 0)], "departure": [rect(0.2, 0.6), rect(0.6, 0.6)]}
    store.zones(camera, zones)
    assert Store(tmp_path / "zones.db").cameras()[0]["zones"] == zones
    consensus = Consensus()
    reads = [
        ("WA12345", 0.95, 0.1, 0.1, zone_at(zones, 0.1, 0.1)),
        ("KR98765", 0.95, 0.7, 0.7, zone_at(zones, 0.7, 0.7)),
    ]
    assert not consensus.frame(reads, 0)
    assert not consensus.frame(reads, 1)
    assert {(p, z) for p, z, c in consensus.frame(reads, 2)} == {
        ("WA12345", "arrival"),
        ("KR98765", "departure"),
    }
