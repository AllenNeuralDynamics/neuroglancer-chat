"""Test that dimension order is preserved during state serialization.

This is critical because Neuroglancer's position array is ordered according
to the dimension order in the dimensions object. If dimensions get reordered
(e.g., x,y,z,t -> t,x,y,z), the position values get mapped to the wrong axes.
"""
import json
from urllib.parse import unquote
from neurogabber.backend.tools.neuroglancer_state import NeuroglancerState, to_url, from_url


def test_dimension_order_preserved_in_serialization():
    """Verify that dimension order is maintained during to_url serialization."""
    # Create a state with explicit dimension order: x, y, z, t
    state_dict = {
        "dimensions": {
            "x": [2.473600491570986e-7, "m"],
            "y": [2.473600491570986e-7, "m"],
            "z": [0.000001, "m"],
            "t": [0.001, "s"]
        },
        "position": [1895.9427490234375, -2094.799560546875, 689, 0],
        "crossSectionScale": 12.182493960703479,
        "projectionScale": 8192,
        "layers": []
    }
    
    state = NeuroglancerState(state_dict)
    
    # Serialize to URL
    url = to_url(state)
    
    # Extract and decode the JSON from the URL
    fragment = url.split('#!')[1]
    decoded_json = unquote(fragment)
    parsed = json.loads(decoded_json)
    
    # Check that dimension order is preserved (should be x, y, z, t, NOT t, x, y, z)
    dimension_keys = list(parsed["dimensions"].keys())
    assert dimension_keys == ["x", "y", "z", "t"], \
        f"Dimension order changed! Expected ['x', 'y', 'z', 't'], got {dimension_keys}"
    
    # Verify position array is unchanged
    assert parsed["position"] == [1895.9427490234375, -2094.799560546875, 689, 0], \
        "Position array was modified"


def test_dimension_order_preserved_round_trip():
    """Verify dimension order is preserved through full round trip."""
    original_state = {
        "dimensions": {
            "x": [1e-6, "m"],
            "y": [1e-6, "m"],
            "z": [1e-6, "m"],
            "t": [0.001, "s"]
        },
        "position": [100, 200, 300, 0],
        "crossSectionScale": 1.0,
        "projectionScale": 1024,
        "layers": []
    }
    
    # Round trip: dict -> url -> dict
    url = to_url(original_state)
    restored_state = from_url(url)
    
    # Check dimension order is preserved
    original_dim_keys = list(original_state["dimensions"].keys())
    restored_dim_keys = list(restored_state["dimensions"].keys())
    
    assert original_dim_keys == restored_dim_keys, \
        f"Dimension order not preserved: {original_dim_keys} -> {restored_dim_keys}"
    
    # Check position is unchanged
    assert original_state["position"] == restored_state["position"], \
        "Position was modified during round trip"


def test_set_view_preserves_dimension_order():
    """Verify set_view doesn't corrupt dimension order."""
    state_dict = {
        "dimensions": {
            "x": [1e-6, "m"],
            "y": [1e-6, "m"],
            "z": [1e-6, "m"],
            "t": [0.001, "s"]
        },
        "position": [0, 0, 0, 0],
        "crossSectionScale": 1.0,
        "projectionScale": 1024,
        "layers": []
    }
    
    state = NeuroglancerState(state_dict)
    
    # Modify view position
    state.set_view({"x": 500, "y": 600, "z": 700}, zoom=5.0, orientation="xy")
    
    # Serialize and check dimension order
    url = to_url(state)
    fragment = url.split('#!')[1]
    decoded_json = unquote(fragment)
    parsed = json.loads(decoded_json)
    
    dimension_keys = list(parsed["dimensions"].keys())
    assert dimension_keys == ["x", "y", "z", "t"], \
        f"set_view corrupted dimension order: {dimension_keys}"
    
    # Verify position was updated correctly
    assert parsed["position"][:3] == [500, 600, 700], \
        "Position not updated correctly by set_view"
