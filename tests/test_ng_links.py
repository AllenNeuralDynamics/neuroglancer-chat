"""Test automatic Neuroglancer link generation for spatial data."""
import polars as pl
from neurogabber.backend.main import _detect_spatial_columns, _generate_ng_links_for_rows
from neurogabber.backend.main import CURRENT_STATE


def test_spatial_detection_xyz():
    """Test detection of x,y,z spatial columns."""
    df = pl.DataFrame({
        'id': [1, 2, 3],
        'x': [100, 200, 300],
        'y': [150, 250, 350],
        'z': [10, 20, 30],
        'value': [1.5, 2.5, 3.5]
    })
    
    result = _detect_spatial_columns(df)
    assert result is not None
    cols, pattern = result
    assert cols == ['x', 'y', 'z']
    assert pattern == 'xyz'


def test_spatial_detection_centroid():
    """Test detection of centroid_x,y,z spatial columns."""
    df = pl.DataFrame({
        'id': [1, 2, 3],
        'centroid_x': [100, 200, 300],
        'centroid_y': [150, 250, 350],
        'centroid_z': [10, 20, 30],
        'value': [1.5, 2.5, 3.5]
    })
    
    result = _detect_spatial_columns(df)
    assert result is not None
    cols, pattern = result
    assert cols == ['centroid_x', 'centroid_y', 'centroid_z']
    assert pattern == 'centroid_xyz'


def test_no_spatial_columns():
    """Test non-spatial DataFrame returns None."""
    df = pl.DataFrame({
        'id': [1, 2, 3],
        'name': ['a', 'b', 'c'],
        'value': [1.5, 2.5, 3.5]
    })
    
    result = _detect_spatial_columns(df)
    assert result is None


def test_ng_links_raw_urls():
    """Test that generated links are raw URLs without markdown wrapper."""
    # Set up a minimal CURRENT_STATE
    global CURRENT_STATE
    from neurogabber.backend.tools.neuroglancer_state import NeuroglancerState
    
    if CURRENT_STATE is None:
        CURRENT_STATE = NeuroglancerState()
    
    df = pl.DataFrame({
        'id': [1, 2, 3],
        'x': [100, 200, 300],
        'y': [150, 250, 350],
        'z': [10, 20, 30]
    })
    
    spatial_cols = ['x', 'y', 'z']
    links = _generate_ng_links_for_rows(df, spatial_cols)
    
    assert len(links) == 3
    # Check that URLs are raw (start with https://)
    for link in links:
        assert link.startswith('https://'), f"Expected raw URL, got: {link}"
        assert not link.startswith('[view]'), f"URL should not have markdown wrapper: {link}"


if __name__ == '__main__':
    print("Testing spatial column detection...")
    test_spatial_detection_xyz()
    print("✓ xyz detection works")
    
    test_spatial_detection_centroid()
    print("✓ centroid_xyz detection works")
    
    test_no_spatial_columns()
    print("✓ non-spatial detection works")
    
    print("\nTesting NG link generation...")
    test_ng_links_raw_urls()
    print("✓ Raw URLs generated correctly (no markdown wrapper)")
    
    print("\n✅ All tests passed! Phase 1 backend complete.")
