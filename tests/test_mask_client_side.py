"""Tests for _mask_client_side: prevents double-wrapping of Neuroglancer URLs."""

import pytest

pytest.importorskip("panel_neuroglancer", reason="panel extras not installed")

from neuroglancer_chat.panel.panel_app import _mask_client_side

_BASE = "https://neuroglancer-demo.appspot.com"


def test_raw_url_is_masked():
    """A bare Neuroglancer URL in plain text gets wrapped as a markdown link."""
    text = f"Check this link: {_BASE}#!{{'layers':[]}}"
    result = _mask_client_side(text)
    assert f"[Updated Neuroglancer view]({_BASE}" in result


def test_existing_markdown_link_not_re_wrapped():
    """A URL that is already inside a markdown link is not re-masked."""
    text = (
        "Here's your data:\n\n"
        "| id | value | View |\n"
        f"| 1 | 5.5 | [view]({_BASE}#!view1) |\n"
    )
    result = _mask_client_side(text)
    assert f"[view]({_BASE}#!view1)" in result
    assert "Updated Neuroglancer view" not in result


def test_mixed_content_masks_only_raw_url():
    """Raw URLs are masked; already-wrapped markdown links are left alone."""
    text = (
        f"Raw URL: {_BASE}#!raw\n"
        f"Already wrapped: [view]({_BASE}#!wrapped)"
    )
    result = _mask_client_side(text)
    assert f"[Updated Neuroglancer view]({_BASE}#!raw)" in result
    assert f"[view]({_BASE}#!wrapped)" in result
    assert result.count("Updated Neuroglancer view") == 1
