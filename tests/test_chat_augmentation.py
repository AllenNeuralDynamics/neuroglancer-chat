from neuroglancer_chat.backend.main import _synthesize_tool_call_message, _mask_ng_urls


def test_synthesize_tool_call_message_includes_tools_only():
    tcs = [
        {"function": {"name": "ng_set_view"}},
        {"function": {"name": "ng_set_lut"}},
    ]
    msg = _synthesize_tool_call_message(tcs)
    assert "ng_set_view" in msg and "ng_set_lut" in msg
    # No URL should appear now (refactor Plan 9)
    assert "http" not in msg


def test_mask_function_noop_without_urls():
    text = "Some response without neuroglancer link"
    assert _mask_ng_urls(text) == text