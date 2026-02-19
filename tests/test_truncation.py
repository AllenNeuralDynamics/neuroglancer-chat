"""Tests for smart column truncation of wide markdown tables."""

from neuroglancer_chat.panel.panel_app import _truncate_table_columns

_WIDE_TABLE = """Query results:

| id | cell_id | x | y | z | mean_intensity | max_intensity | volume | area | perimeter | circularity | eccentricity | cluster | marker | View |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 100 | 200 | 10 | 5 | 5.5 | 7.2 | 1000 | 500 | 80 | 0.9 | 0.3 | A | Pvalb | [view](https://ng.app#!v1) |
| 2 | 110 | 210 | 20 | 6 | 6.5 | 8.1 | 1100 | 520 | 82 | 0.85 | 0.35 | B | Sst | [view](https://ng.app#!v2) |
| 3 | 120 | 220 | 30 | 7 | 7.5 | 9.0 | 1200 | 540 | 84 | 0.88 | 0.32 | A | Vip | [view](https://ng.app#!v3) |

Total: 3 cells."""

_NARROW_TABLE = """Results:

| id | x | y | z | value | View |
|---:|---:|---:|---:|---:|---:|
| 1 | 100 | 200 | 10 | 5.5 | [view](https://ng.app#!v1) |
| 2 | 110 | 210 | 20 | 6.5 | [view](https://ng.app#!v2) |

Done."""


def test_wide_table_is_truncated():
    """A table with more than max_cols columns is truncated."""
    truncated, was_truncated, all_cols = _truncate_table_columns(
        _WIDE_TABLE, max_cols=5
    )
    assert was_truncated is True
    assert len(all_cols) > 5

    # The rendered output should have at most max_cols data columns
    for line in truncated.split("\n"):
        if "|" in line and line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            assert len(parts) <= 5
            break


def test_narrow_table_is_not_truncated():
    """A table with fewer columns than max_cols is left unchanged."""
    truncated, was_truncated, all_cols = _truncate_table_columns(
        _NARROW_TABLE, max_cols=5
    )
    assert was_truncated is False


def test_all_cols_reports_original_count():
    """all_cols always reflects the original column count regardless of truncation."""
    _, _, all_cols = _truncate_table_columns(_WIDE_TABLE, max_cols=5)
    assert len(all_cols) == 15  # 15 columns in _WIDE_TABLE
