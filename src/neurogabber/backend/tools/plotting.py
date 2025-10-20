"""
Plotting utilities using hvPlot for interactive visualizations.

Supports scatter, line, bar, and heatmap plots with Neuroglancer link generation
for individual observations.
"""
import polars as pl
import pandas as pd
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)

# Configuration: Maximum points for interactive plots (default 200)
# Above this limit, plots become static to avoid performance issues
MAX_INTERACTIVE_POINTS = 200


def validate_plot_requirements(
    df: pl.DataFrame, 
    plot_type: str, 
    params: dict
) -> dict:
    """Validate that dataframe has required columns and appropriate data types.
    
    Args:
        df: Polars DataFrame to validate
        plot_type: One of 'scatter', 'line', 'bar', 'heatmap'
        params: Plot parameters (x, y, by, etc.)
        
    Returns:
        Dict with 'valid' (bool), 'issues' (list[str]), 'suggestions' (list[str])
    """
    issues = []
    suggestions = []
    cols = df.columns
    
    # Check required columns exist
    x_col = params.get('x')
    y_col = params.get('y')
    by_col = params.get('by')
    
    if x_col and x_col not in cols:
        issues.append(f"Column '{x_col}' not found in dataframe. Available: {cols}")
    if y_col and y_col not in cols:
        issues.append(f"Column '{y_col}' not found in dataframe. Available: {cols}")
    if by_col and by_col not in cols:
        issues.append(f"Column '{by_col}' not found in dataframe. Available: {cols}")
    
    if issues:
        return {"valid": False, "issues": issues, "suggestions": suggestions}
    
    # Type validation
    if plot_type == 'scatter':
        if y_col and df[y_col].dtype not in [pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64, pl.Float32, pl.Float64]:
            issues.append(f"Scatter plot y-axis ('{y_col}') should be numeric, got {df[y_col].dtype}")
            
    elif plot_type == 'line':
        if y_col and df[y_col].dtype not in [pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64, pl.Float32, pl.Float64]:
            issues.append(f"Line plot y-axis ('{y_col}') should be numeric, got {df[y_col].dtype}")
            
    elif plot_type == 'bar':
        if y_col and df[y_col].dtype not in [pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64, pl.Float32, pl.Float64]:
            issues.append(f"Bar plot y-axis ('{y_col}') should be numeric, got {df[y_col].dtype}")
    
    # Check for empty dataframe
    if len(df) == 0:
        issues.append("Dataframe is empty (no rows)")
    
    # Performance suggestions
    if len(df) > 10000:
        suggestions.append(f"Dataframe has {len(df)} rows. Consider filtering or sampling for better performance.")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "suggestions": suggestions
    }


def build_plot_spec(
    df: pl.DataFrame,
    plot_type: str,
    x: str,
    y: str,
    by: Optional[str] = None,
    size: Optional[str] = None,
    color: Optional[str] = None,
    stacked: bool = False,
    title: Optional[str] = None,
    width: int = 700,
    height: int = 400,
    interactive_override: Optional[bool] = None
) -> dict:
    """Build hvPlot specification without rendering.
    
    Returns plot parameters that can be used to recreate the plot on the frontend.
    This follows the pattern from the hvplot chat example where we send parameters,
    not HTML, and let Panel render natively.
    
    Args:
        df: Polars DataFrame
        plot_type: 'scatter', 'line', 'bar', or 'heatmap'
        x: X-axis column name
        y: Y-axis column name
        by: Grouping column (creates multiple series)
        size: Column for point size (scatter only)
        color: Column for point color (scatter only)
        stacked: Stack bars (bar only)
        title: Plot title
        width: Plot width in pixels
        height: Plot height in pixels
        interactive_override: Force interactive on/off (None = auto based on row count)
        
    Returns:
        Dict with 'plot_kwargs', 'plot_type', 'is_interactive', 'row_count', etc.
    """
    try:
        import hvplot.polars  # Verify hvplot is available
    except ImportError as e:
        return {
            "error": "hvplot not installed. Run: uv add hvplot",
            "details": str(e)
        }
    
    row_count = len(df)
    
    # Determine if plot should be interactive
    if interactive_override is not None:
        is_interactive = interactive_override
    else:
        is_interactive = row_count <= MAX_INTERACTIVE_POINTS
    
    # Build hvplot kwargs based on plot type
    plot_kwargs = {
        'x': x,
        'y': y,
        'title': title or f"{plot_type.capitalize()} Plot",
        'responsive': True,  # Use responsive by default for Panel
    }
    
    # Add optional parameters
    if by:
        plot_kwargs['by'] = by
    
    if plot_type == 'scatter':
        if size:
            plot_kwargs['s'] = size
        if color:
            plot_kwargs['c'] = color
    elif plot_type == 'bar':
        # For bar plots, ensure ungrouped/side-by-side bars by default
        plot_kwargs['stacked'] = stacked
        # Additional parameters to prevent unwanted stacking behavior
        if not stacked:
            # When not stacking, ensure bars appear side-by-side
            plot_kwargs['alpha'] = 0.8  # Slight transparency for overlapping bars
    elif plot_type == 'heatmap':
        # Remove x/y for heatmap
        plot_kwargs.pop('x', None)
        plot_kwargs.pop('y', None)
    
    # Placeholder for Neuroglancer links (to be implemented)
    ng_links_placeholder = None
    if plot_type == 'scatter' and row_count > 0:
        ng_links_placeholder = {
            "enabled": False,
            "row_count": row_count,
            "note": "Neuroglancer click-to-view links will be implemented in future"
        }
    
    return {
        "plot_kwargs": plot_kwargs,
        "plot_type": plot_type,
        "is_interactive": is_interactive,
        "row_count": row_count,
        "ng_links_placeholder": ng_links_placeholder
    }
