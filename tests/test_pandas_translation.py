"""Tests for pandas → Polars expression auto-translation."""

import pytest

from neuroglancer_chat.backend.main import _translate_pandas_to_polars


@pytest.mark.parametrize(
    "input_expr, expected",
    [
        # groupby → group_by
        (
            "df.groupby('cell_id').agg(pl.first('x'))",
            "df.group_by('cell_id').agg(pl.first('x'))",
        ),
        # distinct → unique
        (
            "df.select(pl.col('gene').distinct())",
            "df.select(pl.col('gene').unique())",
        ),
        # reverse=True → descending=True
        (
            "df.sort('volume', reverse=True)",
            "df.sort('volume', descending=True)",
        ),
        # reverse=False → descending=False
        (
            "df.sort('volume', reverse=False)",
            "df.sort('volume', descending=False)",
        ),
        # Multiple translations in one expression
        (
            "df.groupby('cluster').agg(pl.max('val')).sort('val', reverse=False)",
            "df.group_by('cluster').agg(pl.max('val')).sort('val', descending=False)",
        ),
    ],
)
def test_translate_pandas_to_polars(input_expr, expected):
    """translate_pandas_to_polars converts deprecated pandas-style syntax."""
    assert _translate_pandas_to_polars(input_expr) == expected


def test_translate_noop_on_correct_syntax():
    """Already-correct Polars expressions are not altered."""
    expr = "df.group_by('cell_id').agg(pl.first('x'))"
    assert _translate_pandas_to_polars(expr) == expr
