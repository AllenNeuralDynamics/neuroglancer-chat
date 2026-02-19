import polars as pl
from fastapi.testclient import TestClient

from neuroglancer_chat.backend.main import app, execute_query_polars, DATA_MEMORY
from neuroglancer_chat.backend.storage.data import UploadedFileRecord

client = TestClient(app)

CSV_CONTENT = b"id,x,y,z,size_x,size_y,size_z\n1,1,2,3,4,5,6\n2,2,3,4,5,6,7\n"

def test_upload_and_list_files():
    resp = client.post("/upload_file", files={"file": ("test.csv", CSV_CONTENT, "text/csv")})
    data = resp.json()
    assert data["ok"], data
    fid = data["file"]["file_id"]

    lst = client.post("/tools/data_list_files").json()
    assert any(f["file_id"] == fid for f in lst["files"])


def test_preview_and_describe():
    resp = client.post("/upload_file", files={"file": ("t2.csv", CSV_CONTENT, "text/csv")}).json()
    fid = resp["file"]["file_id"]
    prev = client.post("/tools/data_preview", json={"file_id": fid, "n": 1}).json()
    assert prev["rows"] and len(prev["rows"]) == 1
    desc = client.post("/tools/data_describe", json={"file_id": fid}).json()
    assert "summary" in desc
    assert desc["rows"], desc


def test_select_filter():
    resp = client.post("/upload_file", files={"file": ("t3.csv", CSV_CONTENT, "text/csv")}).json()
    fid = resp["file"]["file_id"]
    sel = client.post(
        "/tools/data_select",
        json={
            "file_id": fid,
            "columns": ["id", "x", "size_x"],
            "filters": [{"column": "id", "op": ">", "value": 1}],
            "limit": 5,
        },
    ).json()
    assert "summary" in sel, sel
    assert sel["preview_rows"], sel


def test_list_summaries():
    # Ensure at least one summary from previous tests
    resp = client.post("/tools/data_list_summaries").json()
    assert "summaries" in resp


def test_data_sample_basic_and_seed():
    resp = client.post("/upload_file", files={"file": ("sample.csv", CSV_CONTENT, "text/csv")}).json()
    fid = resp["file"]["file_id"]
    sample = client.post("/tools/data_sample", json={"file_id": fid, "n": 2}).json()
    assert sample["returned"] == 2
    assert len(sample["rows"]) == 2
    # Seeded reproducibility
    s1 = client.post("/tools/data_sample", json={"file_id": fid, "n": 2, "seed": 42}).json()
    s2 = client.post("/tools/data_sample", json={"file_id": fid, "n": 2, "seed": 42}).json()
    assert s1["rows"] == s2["rows"], "Seeded samples should match"
    # Without replacement uniqueness
    ids = [r["id"] for r in sample["rows"]]
    assert len(ids) == len(set(ids))


def test_data_ng_views_table_basic():
    # Build a dataframe with required columns
    content = b"cell_id,x,y,z,mean_intensity\n1,10,20,30,5.5\n2,11,21,31,6.5\n3,12,22,32,7.5\n"
    resp = client.post("/upload_file", files={"file": ("cells.csv", content, "text/csv")}).json()
    fid = resp["file"]["file_id"]
    mv = client.post("/tools/data_ng_views_table", json={
        "file_id": fid,
        "sort_by": "mean_intensity",
        "top_n": 2,
        "include_columns": ["mean_intensity"],
    }).json()
    assert mv.get("n") == 2, mv
    assert mv["rows"][0]["cell_id"] in (1,2,3)
    assert "link" in mv["rows"][0]
    assert mv.get("first_link") == mv["rows"][0]["link"], mv
    assert "summary" in mv, mv


# ---------------------------------------------------------------------------
# execute_query_polars unit tests (no HTTP / TestClient required)
# ---------------------------------------------------------------------------

_QUERY_CSV = b"id,value,category\n1,10,A\n2,20,B\n3,30,A\n4,40,B\n5,50,A\n"


def _add_test_file(name: str = "qtest.csv") -> str:
    """Add a small CSV to DATA_MEMORY and return its file_id."""
    meta = DATA_MEMORY.add_file(name, _QUERY_CSV)
    return meta["file_id"]


def test_execute_query_polars_filter():
    """execute_query_polars filters rows correctly."""
    fid = _add_test_file("qtest_filter.csv")
    result = execute_query_polars(
        file_id=fid, expression='df.filter(pl.col("value") > 20)'
    )
    assert result.get("ok") is True
    assert result.get("rows") == 3


def test_execute_query_polars_aggregation():
    """execute_query_polars handles aggregation expressions."""
    fid = _add_test_file("qtest_agg.csv")
    result = execute_query_polars(
        file_id=fid, expression='df.select([pl.max("value"), pl.mean("value")])'
    )
    assert result.get("ok") is True


def test_execute_query_polars_missing_file():
    """execute_query_polars returns an error for unknown file_id."""
    result = execute_query_polars(
        file_id="nonexistent_xyz",
        expression='df.select([pl.col("value")])',
    )
    assert "error" in result


def test_execute_query_polars_auto_select():
    """execute_query_polars picks the most recent file when file_id is omitted."""
    _add_test_file("qtest_autoselect.csv")
    result = execute_query_polars(expression='df.select([pl.col("id")])')
    assert result.get("ok") is True
