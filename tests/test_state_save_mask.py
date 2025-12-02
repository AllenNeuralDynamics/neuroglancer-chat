from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app


client = TestClient(app)


def test_state_save_raw_and_masked():
    # Raw first
    r1 = client.post("/tools/state_save", json={"dummy": true}) if False else client.post("/tools/state_save", json={})
    assert r1.status_code == 200
    data1 = r1.json()
    assert "url" in data1 and data1["url"].startswith("http")
    assert "masked_markdown" not in data1

    # Masked
    r2 = client.post("/tools/state_save?mask=1", json={})
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2.get("url")
    assert data2.get("masked_markdown")
    # Masked should be a markdown hyperlink
    assert data2["masked_markdown"].startswith("[Updated Neuroglancer view]")
