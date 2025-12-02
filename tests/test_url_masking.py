from neuroglancer_chat.backend.main import _mask_ng_urls


def test_mask_single_url():
    raw = "Here is a link: https://neuroglancer-demo.appspot.com/#!%7B%22a%22%3A1"  # truncated but starts with %7B
    masked = _mask_ng_urls(raw)
    assert "Updated Neuroglancer view" in masked
    assert "neuroglancer-demo" in masked  # hyperlink form retains URL inside markdown
    assert raw not in masked or masked.count(raw) < masked.count("Updated Neuroglancer view")


def test_mask_multiple_urls():
    u1 = "https://neuroglancer-demo.appspot.com/#!%7B%22x%22%3A1"
    u2 = "https://neuroglancer-demo.appspot.com/#!%7B%22y%22%3A2"
    raw = f"Links: {u1} and also {u2} again {u1}"
    masked = _mask_ng_urls(raw)
    # First label appears once, second gets (2)
    assert masked.count("Updated Neuroglancer view") >= 1
    assert "Updated Neuroglancer view (2)" in masked
    # Ensure each URL is now wrapped in markdown link form
    assert f"]({u1})" in masked
    assert f"]({u2})" in masked


def test_mask_http_and_simple_url():
    http_url = "http://my.neuroglancer.local/view"  # no fragment, still should mask
    raw = f"Open {http_url} now"
    masked = _mask_ng_urls(raw)
    assert "Updated Neuroglancer view" in masked
    assert f"]({http_url})" in masked