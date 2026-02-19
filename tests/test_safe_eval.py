"""Tests for secure Polars eval with restricted builtins namespace."""

import pytest
import polars as pl


def _make_namespace(df: pl.DataFrame) -> dict:
    """Return a restricted eval namespace matching what the backend uses."""
    return {"pl": pl, "df": df, "__builtins__": {}}


@pytest.fixture
def sample_df():
    """Small test DataFrame."""
    return pl.DataFrame(
        {"x": [1, 2, 3, 4, 5], "y": [10, 20, 30, 40, 50], "name": list("abcde")}
    )


def test_filter_expression(sample_df):
    """Basic filter returns correct subset."""
    ns = _make_namespace(sample_df)
    result = eval("df.filter(pl.col('x') > 2)", ns, {})  # noqa: S307
    assert result.height == 3


def test_select_and_filter(sample_df):
    """Chained filter + select returns requested columns."""
    ns = _make_namespace(sample_df)
    result = eval(
        "df.filter(pl.col('y') >= 30).select(['name', 'x'])", ns, {}
    )  # noqa: S307
    assert result.columns == ["name", "x"]
    assert result.height == 3


def test_aggregation(sample_df):
    """Aggregation expressions work correctly."""
    ns = _make_namespace(sample_df)
    result = eval("df.select([pl.sum('x'), pl.mean('y')])", ns, {})  # noqa: S307
    assert result["x"].item() == 15
    assert result["y"].item() == 30.0


def test_import_blocked(sample_df):
    """import statements are blocked in restricted namespace."""
    ns = _make_namespace(sample_df)
    with pytest.raises(Exception):
        eval("__import__('os')", ns, {})  # noqa: S307


def test_open_blocked(sample_df):
    """open() is blocked in restricted namespace."""
    ns = _make_namespace(sample_df)
    with pytest.raises((NameError, TypeError)):
        eval("open('/etc/passwd')", ns, {})  # noqa: S307
