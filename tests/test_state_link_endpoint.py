from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app, to_url, CURRENT_STATE

client = TestClient(app)


def test_ng_state_link_endpoint_returns_masked():
    r = client.post('/tools/ng_state_link')
    assert r.status_code == 200
    data = r.json()
    assert 'url' in data and data['url'].startswith('http')
    assert 'masked_markdown' in data
    assert data['masked_markdown'].startswith('[Updated Neuroglancer view](')


def test_mask_fragment_only():
    # Simulate fragment-only situation
    frag = to_url(CURRENT_STATE).split('/',3)[-1]  # get the #!%7B...
    from neuroglancer_chat.backend.main import _mask_ng_urls
    masked = _mask_ng_urls(frag)
    assert 'Updated Neuroglancer view' in masked