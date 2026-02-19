from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState


def test_set_view_updates_position_and_scale():
    s = NeuroglancerState()
    s.set_view({"x": 5, "y": 6, "z": 7}, "fit", "xy")
    data = s.as_dict()
    assert data["position"][:3] == [5, 6, 7]
    assert data["crossSectionScale"] == 1.0


def test_add_annotations_appends_items():
    s = NeuroglancerState()
    s.add_annotations(
        "ROIs",
        [
            {"point": [1, 2, 3], "id": "a"},
            {"type": "box", "point": [0, 0, 0], "size": [1, 2, 3], "id": "b"},
        ],
    )
    # Adding more should append
    s.add_annotations("ROIs", [{"point": [4, 5, 6]}])
    data = s.as_dict()
    ann_layers = [L for L in data["layers"] if L.get("type") == "annotation"]
    assert len(ann_layers) == 1
    # Annotations are now at layer level, not in source
    anns = ann_layers[0]["annotations"]
    assert len(anns) == 3


def test_set_lut_no_error_when_layer_missing():
    s = NeuroglancerState()
    # No exception if layer not present
    s.set_lut("missing", 0.0, 1.0)
