"""
Tests for the plotting functionality.
"""
import pytest
import polars as pl
from neurogabber.backend.tools.plotting import validate_plot_requirements, generate_plot


def test_validate_plot_requirements_valid():
    """Test validation passes for valid plot parameters."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10],
        "category": ["A", "B", "A", "B", "A"]
    })
    
    params = {"x": "x", "y": "y", "by": "category"}
    result = validate_plot_requirements(df, "scatter", params)
    
    assert result["valid"] is True
    assert len(result["issues"]) == 0


def test_validate_plot_requirements_missing_column():
    """Test validation fails when column is missing."""
    df = pl.DataFrame({
        "x": [1, 2, 3],
        "y": [2, 4, 6]
    })
    
    params = {"x": "x", "y": "z"}  # z doesn't exist
    result = validate_plot_requirements(df, "scatter", params)
    
    assert result["valid"] is False
    assert len(result["issues"]) > 0
    assert "z" in str(result["issues"])


def test_validate_plot_requirements_empty_dataframe():
    """Test validation fails for empty dataframe."""
    df = pl.DataFrame({"x": [], "y": []})
    
    params = {"x": "x", "y": "y"}
    result = validate_plot_requirements(df, "scatter", params)
    
    assert result["valid"] is False
    assert any("empty" in str(issue).lower() for issue in result["issues"])


def test_validate_plot_requirements_large_dataframe():
    """Test validation suggests optimization for large dataframes."""
    df = pl.DataFrame({
        "x": list(range(15000)),
        "y": list(range(15000))
    })
    
    params = {"x": "x", "y": "y"}
    result = validate_plot_requirements(df, "scatter", params)
    
    # Should still be valid but suggest filtering
    assert result["valid"] is True
    assert len(result["suggestions"]) > 0


def test_generate_plot_structure():
    """Test that plot generation returns expected structure."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10]
    })
    
    result = generate_plot(df, "scatter", "x", "y")
    
    # Should return dict with expected keys
    assert isinstance(result, dict)
    # Check for plot_html OR error
    assert "plot_html" in result or "error" in result
    
    if "plot_html" in result:
        assert result["plot_type"] == "scatter"
        assert result["row_count"] == 5
        assert "is_interactive" in result


def test_generate_plot_with_grouping():
    """Test plot generation with grouping (by parameter)."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10],
        "category": ["A", "B", "A", "B", "A"]
    })
    
    result = generate_plot(df, "scatter", "x", "y", by="category")
    
    # Should handle grouping
    if "plot_html" in result:
        assert result["plot_type"] == "scatter"
        assert result["row_count"] == 5


def test_generate_plot_interactive_threshold():
    """Test that plots become non-interactive above threshold."""
    # Small dataset - should be interactive
    small_df = pl.DataFrame({
        "x": list(range(50)),
        "y": list(range(50))
    })
    
    small_result = generate_plot(small_df, "line", "x", "y")
    
    if "is_interactive" in small_result:
        assert small_result["is_interactive"] is True
    
    # Large dataset - should not be interactive
    large_df = pl.DataFrame({
        "x": list(range(250)),
        "y": list(range(250))
    })
    
    large_result = generate_plot(large_df, "line", "x", "y")
    
    if "is_interactive" in large_result:
        assert large_result["is_interactive"] is False


def test_generate_plot_types():
    """Test all supported plot types."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10]
    })
    
    plot_types = ["scatter", "line", "bar"]
    
    for plot_type in plot_types:
        result = generate_plot(df, plot_type, "x", "y")
        # Should either succeed or have error (hvplot might not be installed in test env)
        assert isinstance(result, dict)
        if "plot_html" in result:
            assert result["plot_type"] == plot_type
        elif "error" in result:
            # Expected if hvplot not installed
            assert "hvplot" in result["error"].lower()
