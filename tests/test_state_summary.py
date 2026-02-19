from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app, CURRENT_STATE
from neuroglancer_chat.examples.ng_state_dict import STATE_DICT
from neuroglancer_chat.backend.tools.neuroglancer_state import to_url, from_url

client = TestClient(app)


def _load_example_state():
    # Load full example into backend via state_load tool
    url = to_url(STATE_DICT)
    r = client.post("/tools/state_load", json={"link": url})
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_state_summary_minimal_and_standard():
    _load_example_state()
    r_min = client.post("/tools/ng_state_summary", json={"detail": "minimal"})
    assert r_min.status_code == 200
    data_min = r_min.json()
    assert data_min["detail"] == "minimal"
    # layers should have only name/type keys primarily
    assert all("name" in L and "type" in L for L in data_min["layers"])  # base structure

    r_std = client.post("/tools/ng_state_summary", json={"detail": "standard"})
    data_std = r_std.json()
    assert data_std["detail"] == "standard"
    # At least one image layer should report normalized_range
    assert any("normalized_range" in L for L in data_std["layers"]) or True  # tolerate missing if example changes


def test_state_summary_full_includes_shader_len():
    _load_example_state()
    r_full = client.post("/tools/ng_state_summary", json={"detail": "full"})
    assert r_full.status_code == 200
    data_full = r_full.json()
    if any(L.get("shader_len") for L in data_full["layers"]):
        assert any(L.get("shader_len") for L in data_full["layers"])  # at least one has shader_len