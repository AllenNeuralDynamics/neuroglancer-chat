from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app


client = TestClient(app)


def test_set_view_and_state_save():
    # set view
    payload = {
        "center": {"x": 1, "y": 2, "z": 3},
        "zoom": "fit",
        "orientation": "xy",
    }
    r = client.post("/tools/ng_set_view", json=payload)
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # save state
    r2 = client.post("/tools/state_save", json={})
    assert r2.status_code == 200
    data = r2.json()
    assert "sid" in data and "url" in data
    assert isinstance(data["url"], str) and data["url"].startswith("http")


def test_add_annotations_and_histogram():
    # add a point annotation
    payload = {
        "layer": "ROIs",
        "items": [
            {
                "type": "point",
                "center": {"x": 10, "y": 20, "z": 30},
                "id": "p1",
            }
        ],
    }
    r = client.post("/tools/ng_annotations_add", json=payload)
    assert r.status_code == 200
    assert r.json().get("ok") is True

    # set LUT to ensure endpoint works
    r2 = client.post(
        "/tools/ng_set_lut",
        json={"layer": "image", "vmin": 0.0, "vmax": 1.0},
    )
    assert r2.status_code == 200
    assert r2.json().get("ok") is True

    # histogram returns arrays
    r3 = client.post("/tools/data_plot_histogram", json={"layer": "image"})
    assert r3.status_code == 200
    data = r3.json()
    assert "hist" in data and "edges" in data
    assert len(data["hist"]) == 256
    assert len(data["edges"]) == 257
