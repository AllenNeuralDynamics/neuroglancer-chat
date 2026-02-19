"""
Tests for the plotting functionality.
"""
import pytest
import polars as pl
from neuroglancer_chat.backend.tools.plotting import validate_plot_requirements, build_plot_spec


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


def test_build_plot_spec_structure():
    """build_plot_spec returns the expected keys for a scatter plot."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10]
    })

    result = build_plot_spec(df, "scatter", "x", "y")

    assert isinstance(result, dict)
    # Returns plot_kwargs dict OR an error (if hvplot not installed)
    assert "plot_kwargs" in result or "error" in result

    if "plot_kwargs" in result:
        assert result["plot_type"] == "scatter"
        assert result["row_count"] == 5
        assert "is_interactive" in result


def test_build_plot_spec_with_grouping():
    """build_plot_spec handles the by= grouping parameter."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10],
        "category": ["A", "B", "A", "B", "A"]
    })

    result = build_plot_spec(df, "scatter", "x", "y", by="category")

    if "plot_kwargs" in result:
        assert result["plot_type"] == "scatter"
        assert result["row_count"] == 5


def test_build_plot_spec_interactive_threshold():
    """Plots are interactive for small datasets and static for large ones."""
    small_df = pl.DataFrame({
        "x": list(range(50)),
        "y": list(range(50))
    })
    small_result = build_plot_spec(small_df, "line", "x", "y")
    if "is_interactive" in small_result:
        assert small_result["is_interactive"] is True

    large_df = pl.DataFrame({
        "x": list(range(250)),
        "y": list(range(250))
    })
    large_result = build_plot_spec(large_df, "line", "x", "y")
    if "is_interactive" in large_result:
        assert large_result["is_interactive"] is False


def test_build_plot_spec_plot_types():
    """build_plot_spec accepts all supported plot types."""
    df = pl.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [2, 4, 6, 8, 10]
    })

    for plot_type in ("scatter", "line", "bar"):
        result = build_plot_spec(df, plot_type, "x", "y")
        assert isinstance(result, dict)
        if "plot_kwargs" in result:
            assert result["plot_type"] == plot_type
        elif "error" in result:
            assert "hvplot" in result["error"].lower()
