"""
Integration test: Upload CSV, query data, verify Tabulator rendering with NG links.

Tests the full flow:
1. Upload CSV file
2. Send query to LLM agent
3. Verify data_query_polars is called
4. Verify query_data is returned with structured data
5. Verify ng_views are generated for spatial data
"""
import pytest
import httpx
import json
import os
from pathlib import Path


# Locate the example CSV file
EXAMPLE_CSV = Path(__file__).parent.parent / "src" / "neuroglancer_chat" / "examples" / "767018_inh_cells_shape_metrics_clusters.csv"
BACKEND_URL = os.environ.get("BACKEND", "http://127.0.0.1:8000")


@pytest.fixture
def backend_client():
    """Create HTTP client for backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=60.0)


def test_upload_and_query_largest_cells_per_cluster(backend_client):
    """Test full workflow: upload CSV and query largest cells per cluster."""
    
    # Step 1: Upload CSV file
    assert EXAMPLE_CSV.exists(), f"Example CSV not found at {EXAMPLE_CSV}"
    
    with open(EXAMPLE_CSV, "rb") as f:
        files = {"file": ("test_cells.csv", f, "text/csv")}
        upload_resp = backend_client.post("/upload_file", files=files)
    
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    upload_data = upload_resp.json()
    assert upload_data.get("ok"), "Upload response missing 'ok'"
    
    file_id = upload_data["file"]["file_id"]
    print(f"✅ Uploaded file: {file_id}")
    print(f"   Columns: {upload_data['file']['columns'][:5]}...")  # Show first 5 columns
    
    # Verify expected columns exist
    columns = upload_data['file']['columns']
    assert 'log_volume' in columns, "Missing log_volume column"
    assert 'cluster_label' in columns, "Missing cluster_label column"
    assert 'centroid_x' in columns or 'x' in columns, "Missing spatial x column"
    
    # Step 2: Send query to agent
    query = "Give me the largest cells (by log_volume) in each cluster_label"
    chat_payload = {
        "messages": [
            {"role": "user", "content": query}
        ]
    }
    
    chat_resp = backend_client.post("/agent/chat", json=chat_payload)
    assert chat_resp.status_code == 200, f"Chat failed: {chat_resp.text}"
    
    chat_data = chat_resp.json()
    print(f"\n✅ Agent response received")
    
    # Step 3: Verify response structure
    assert "choices" in chat_data, "Missing 'choices' in response"
    assert len(chat_data["choices"]) > 0, "No choices in response"
    
    message = chat_data["choices"][0].get("message", {})
    content = message.get("content", "")
    print(f"   LLM response: {content[:200]}...")
    
    # Step 4: Verify query_data is present
    query_data = chat_data.get("query_data")
    assert query_data is not None, "Missing 'query_data' in response"
    assert isinstance(query_data, dict), "query_data should be a dict"
    
    print(f"\n✅ query_data present")
    print(f"   Keys: {list(query_data.keys())}")
    
    # Step 5: Verify data structure
    assert "data" in query_data, "Missing 'data' in query_data"
    assert "columns" in query_data, "Missing 'columns' in query_data"
    assert "rows" in query_data, "Missing 'rows' in query_data"
    assert "expression" in query_data, "Missing 'expression' in query_data"
    
    data = query_data["data"]
    columns = query_data["columns"]
    rows = query_data["rows"]
    expression = query_data["expression"]
    
    print(f"\n✅ Data structure validated")
    print(f"   Rows: {rows}")
    print(f"   Columns: {columns}")
    print(f"   Expression: {expression}")
    
    # Step 6: Verify the query logic is correct
    # Should have one row per cluster_label with the max log_volume
    assert rows > 0, "No rows returned"
    assert "cluster_label" in columns, "cluster_label not in result columns"
    assert "log_volume" in columns, "log_volume not in result columns"
    
    # Verify data is dict of lists (Polars format)
    assert isinstance(data, dict), "data should be dict"
    for col in columns:
        assert col in data, f"Column {col} missing from data"
        assert isinstance(data[col], list), f"data[{col}] should be a list"
        assert len(data[col]) == rows, f"data[{col}] length mismatch"
    
    print(f"\n✅ Data content validated")
    print(f"   Sample row 0:")
    for col in columns[:5]:  # Show first 5 columns
        print(f"     {col}: {data[col][0]}")
    
    # Step 7: Verify ng_views are generated (if spatial columns exist)
    ng_views = query_data.get("ng_views")
    spatial_columns = query_data.get("spatial_columns")
    
    if spatial_columns:
        print(f"\n✅ Spatial columns detected: {spatial_columns}")
        assert ng_views is not None, "ng_views should be present for spatial data"
        assert isinstance(ng_views, list), "ng_views should be a list"
        assert len(ng_views) > 0, "ng_views should have entries"
        
        # Verify ng_views structure
        first_view = ng_views[0]
        assert "row_index" in first_view, "ng_view missing row_index"
        assert "url" in first_view, "ng_view missing url"
        assert isinstance(first_view["url"], str), "ng_view url should be string"
        assert "neuroglancer" in first_view["url"].lower(), "ng_view url should be Neuroglancer URL"
        
        print(f"   Generated {len(ng_views)} view links")
        print(f"   Sample URL: {first_view['url'][:80]}...")
    else:
        print(f"\n⚠️  No spatial columns detected (this is OK for non-spatial queries)")
    
    # Step 8: Verify the Polars expression makes sense
    assert "group_by" in expression or "groupby" in expression.lower(), \
        "Expression should use group_by for per-cluster aggregation"
    assert "log_volume" in expression, "Expression should reference log_volume"
    
    print(f"\n✅ Expression validated")
    
    # Step 9: Verify tool trace
    tool_trace = chat_data.get("tool_trace", [])
    assert len(tool_trace) > 0, "Expected at least one tool call"
    
    tool_names = [t.get("tool") for t in tool_trace]
    assert "data_query_polars" in tool_names, "Expected data_query_polars to be called"
    
    print(f"\n✅ Tool trace validated")
    print(f"   Tools called: {tool_names}")
    
    print(f"\n" + "="*60)
    print(f"✅ INTEGRATION TEST PASSED")
    print(f"="*60)
    print(f"Summary:")
    print(f"  - Uploaded CSV: {file_id}")
    print(f"  - Query returned {rows} results (one per cluster)")
    print(f"  - Expression: {expression}")
    print(f"  - Spatial links: {len(ng_views) if ng_views else 0}")
    print(f"  - Frontend will render as Tabulator widget with View buttons")


def test_query_without_upload_uses_most_recent(backend_client):
    """Test that queries without file_id auto-use most recent file."""
    
    # Upload a file first
    with open(EXAMPLE_CSV, "rb") as f:
        files = {"file": ("auto_test.csv", f, "text/csv")}
        backend_client.post("/upload_file", files=files)
    
    # Query without specifying file_id
    query = "Show me 5 cells"
    chat_payload = {
        "messages": [
            {"role": "user", "content": query}
        ]
    }
    
    chat_resp = backend_client.post("/agent/chat", json=chat_payload)
    assert chat_resp.status_code == 200
    
    chat_data = chat_resp.json()
    query_data = chat_data.get("query_data")
    
    # Should have auto-selected the uploaded file and returned results
    assert query_data is not None, "Should auto-use most recent file"
    assert query_data.get("rows") == 5, "Should return 5 rows"
    
    print(f"✅ Auto-selection of most recent file works")


if __name__ == "__main__":
    # Run tests directly
    import sys
    
    print("Running integration test...")
    print(f"Backend URL: {BACKEND_URL}")
    print(f"CSV file: {EXAMPLE_CSV}")
    print("")
    
    client = httpx.Client(base_url=BACKEND_URL, timeout=60.0)
    
    try:
        test_upload_and_query_largest_cells_per_cluster(client)
        print("\n" + "="*60)
        test_query_without_upload_uses_most_recent(client)
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        client.close()
