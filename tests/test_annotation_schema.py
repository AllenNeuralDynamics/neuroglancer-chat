"""Tests for annotation layer schema, adding points, and color customization."""

import json
from urllib.parse import unquote

from fastapi.testclient import TestClient

from neuroglancer_chat.backend.main import app, CURRENT_STATE, _execute_tool_by_name
from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESET_STATE = {
    "dimensions": {
        "x": [1e-9, "m"],
        "y": [1e-9, "m"],
        "z": [1e-9, "m"],
    },
    "position": [0, 0, 0],
    "layers": [],
}


def _reset():
    """Reset global state before each test."""
    import copy

    CURRENT_STATE.data = copy.deepcopy(_RESET_STATE)


# ---------------------------------------------------------------------------
# Schema validation (NeuroglancerState directly)
# ---------------------------------------------------------------------------


def test_annotation_layer_has_required_fields():
    """An annotation layer created via NeuroglancerState contains the fields
    Neuroglancer expects: type, source.url, tool, tab, annotationColor."""
    state = NeuroglancerState()
    state.add_layer("AnnTest", "annotation", annotationColor="#7300ff")
    state.add_annotations(
        "AnnTest",
        [
            {
                "point": [4998.87, 6216.5, 1175.07],
                "type": "point",
                "id": "bb79d5acc705a03fad2cc116a192df2c8a41e249",
            }
        ],
    )
    layer = next(l for l in state.data["layers"] if l["name"] == "AnnTest")

    assert layer["type"] == "annotation"
    assert "url" in layer["source"]
    assert layer["source"]["url"] == "local://annotations"
    assert "tool" in layer
    assert "tab" in layer
    assert layer["annotationColor"] == "#7300ff"
    assert isinstance(layer["annotations"], list)
    assert len(layer["annotations"]) == 1


def test_annotation_item_has_type_and_point_fields():
    """Annotation items must include 'point', 'type', and 'id' fields."""
    state = NeuroglancerState()
    state.add_layer("TestAnn", "annotation")
    state.add_annotations(
        "TestAnn",
        [{"point": [100, 200, 300], "type": "point", "id": "test-id-123"}],
    )
    layer = next(l for l in state.data["layers"] if l["name"] == "TestAnn")
    ann = layer["annotations"][0]

    assert "point" in ann
    assert ann["type"] == "point"
    assert ann["id"] == "test-id-123"


# ---------------------------------------------------------------------------
# Adding points via endpoint
# ---------------------------------------------------------------------------


def test_annotation_add_and_serialization():
    """ng_annotations_add stores points and they survive URL serialization."""
    _reset()

    client.post(
        "/tools/ng_add_layer",
        json={"name": "TestPoints", "layer_type": "annotation"},
    )

    items = [
        {
            "type": "point",
            "center": {"x": 5461.6, "y": 6213.5, "z": 1086.1},
            "id": "0b385a5d689f82fd33d31fca5e61b483c9f87f9d",
        },
        {
            "type": "point",
            "center": {"x": 5414.8, "y": 6213.5, "z": 1083.7},
            "id": "3811881a2683c1242f8fced03f3df0bbd1b057fc",
        },
    ]
    r = client.post(
        "/tools/ng_annotations_add",
        json={"layer": "TestPoints", "items": items},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True

    layer = next(
        l for l in CURRENT_STATE.data["layers"] if l["name"] == "TestPoints"
    )
    assert len(layer["annotations"]) == 2

    # Verify round-trip through URL serialization
    url = CURRENT_STATE.to_url()
    fragment = url.split("#!")[1]
    state_dict = json.loads(unquote(fragment))
    saved_layer = next(
        l for l in state_dict["layers"] if l["name"] == "TestPoints"
    )
    assert len(saved_layer["annotations"]) == 2


def test_annotation_add_creates_layer_if_missing():
    """ng_annotations_add succeeds even when the layer doesn't exist yet."""
    _reset()

    r = client.post(
        "/tools/ng_annotations_add",
        json={
            "layer": "AutoCreated",
            "items": [
                {"type": "point", "center": {"x": 1, "y": 2, "z": 3}}
            ],
        },
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Annotation colors
# ---------------------------------------------------------------------------


def test_annotation_layer_custom_color():
    """ng_add_layer stores the annotation_color on the layer."""
    _reset()

    client.post(
        "/tools/ng_add_layer",
        json={
            "name": "GreenAnnotations",
            "layer_type": "annotation",
            "annotation_color": "#00ff00",
        },
    )
    layer = next(
        l for l in CURRENT_STATE.data["layers"] if l["name"] == "GreenAnnotations"
    )
    assert layer["annotationColor"] == "#00ff00"


def test_annotation_layer_default_color():
    """ng_add_layer applies the default color when annotation_color is omitted."""
    _reset()

    client.post(
        "/tools/ng_add_layer",
        json={"name": "DefaultAnnotations", "layer_type": "annotation"},
    )
    layer = next(
        l
        for l in CURRENT_STATE.data["layers"]
        if l["name"] == "DefaultAnnotations"
    )
    assert layer["annotationColor"] == "#cecd11"


def test_annotation_layer_color_via_dispatcher():
    """Color is correctly set when the layer is created through the tool dispatcher."""
    _reset()

    _execute_tool_by_name(
        "ng_add_layer",
        {
            "name": "BlueAnnotations",
            "layer_type": "annotation",
            "annotation_color": "#0000ff",
        },
    )
    layer = next(
        l
        for l in CURRENT_STATE.data["layers"]
        if l["name"] == "BlueAnnotations"
    )
    assert layer["annotationColor"] == "#0000ff"
