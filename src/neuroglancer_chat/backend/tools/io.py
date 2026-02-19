import os, polars as pl
from typing import List, Dict


S3_BUCKET = os.getenv("S3_BUCKET")


# Ingest CSV: local path or s3://bucket/key


def load_csv(path_or_key: str) -> pl.DataFrame:
    if path_or_key.startswith("s3://"):
        return pl.read_csv(path_or_key)




def top_n_rois(df: pl.DataFrame, n: int = 20) -> List[Dict]:
# expects columns: id, x, y, z, size_x, size_y, size_z (adapt to your schema)
    have = set(df.columns)
    needed = {"id","x","y","z","size_x","size_y","size_z"}
    assert needed.issubset(have), f"CSV missing columns: {needed - have}"
    return (
        df.with_columns((pl.col("size_x")*pl.col("size_y")*pl.col("size_z")).alias("vol"))
        .sort("vol", descending=True)
        .head(n)
        .to_dicts()
    )