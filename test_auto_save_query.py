"""Test the auto-save query results functionality."""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_auto_save_and_chain():
    """Test that query results are auto-saved and can be chained."""
    
    print("="*70)
    print("Testing Auto-Save Query Results with Chaining")
    print("="*70)
    
    # Step 1: Upload test data
    print("\n1. Uploading test CSV...")
    test_csv = """cell_id,centroid_x,centroid_y,centroid_z,cluster_label,log_volume
1,100,200,300,A,5.2
2,150,250,350,A,6.1
3,200,300,400,A,4.8
4,250,350,450,B,5.5
5,300,400,500,B,7.2
6,350,450,550,B,6.8
7,400,500,600,C,8.1
8,450,550,650,C,7.5
9,500,600,700,C,6.9
10,550,650,750,D,5.9
"""
    
    files = {"file": ("test_cells.csv", test_csv, "text/csv")}
    r = requests.post(f"{BASE_URL}/upload_file", files=files)
    assert r.status_code == 200
    data = r.json()
    file_id = data["file_id"]
    print(f"   ✓ Uploaded file_id: {file_id}")
    print(f"   ✓ Rows: {data['n_rows']}, Columns: {data['n_cols']}")
    
    # Step 2: Run a query (aggregation) - should auto-save
    print("\n2. Running aggregation query (should auto-save)...")
    query_payload = {
        "file_id": file_id,
        "expression": "df.group_by('cluster_label').agg(pl.first('centroid_x'), pl.first('centroid_y'), pl.first('centroid_z'), pl.first('cell_id'), pl.max('log_volume').alias('max_volume'))"
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_query_polars", json=query_payload)
    assert r.status_code == 200
    result = r.json()
    print(f"   ✓ Query succeeded: {result.get('ok')}")
    print(f"   ✓ Rows returned: {result.get('rows')}")
    
    # Check that summary_id was returned (auto-save proof)
    assert "summary_id" in result, "summary_id should be auto-generated!"
    summary_id = result["summary_id"]
    print(f"   ✓ Auto-saved as summary_id: {summary_id}")
    print(f"   ✓ Message: {result.get('message', '')[:100]}...")
    
    # Step 3: Use that summary_id to create annotations (chaining test)
    print(f"\n3. Creating annotations from query result (using summary_id={summary_id})...")
    annotation_payload = {
        "summary_id": summary_id,  # Use the auto-saved query result
        "layer_name": "Top_Per_Cluster",
        "annotation_type": "point",
        "center_columns": ["centroid_x", "centroid_y", "centroid_z"],
        "id_column": "cell_id",
        "color": "#00ff00"
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_ng_annotations_from_data", json=annotation_payload)
    assert r.status_code == 200
    result = r.json()
    print(f"   ✓ Annotation creation: {result.get('ok')}")
    print(f"   ✓ Annotations created: {result.get('count')}")
    print(f"   ✓ Layer name: {result.get('layer')}")
    
    # Should create exactly 4 annotations (one per cluster: A, B, C, D)
    assert result.get("count") == 4, f"Expected 4 annotations (one per cluster), got {result.get('count')}"
    print(f"   ✓ Correct count verified (4 clusters = 4 annotations)")
    
    # Step 4: Test 'last' shorthand
    print("\n4. Testing 'last' summary_id shorthand...")
    annotation_payload2 = {
        "summary_id": "last",  # Should resolve to the most recent query
        "layer_name": "Latest_Query_Points",
        "annotation_type": "point",
        "center_columns": ["centroid_x", "centroid_y", "centroid_z"],
        "color": "#ff0000"
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_ng_annotations_from_data", json=annotation_payload2)
    assert r.status_code == 200
    result = r.json()
    print(f"   ✓ 'last' resolved successfully")
    print(f"   ✓ Annotations created: {result.get('count')}")
    assert result.get("count") == 4, "Should still be 4 annotations"
    
    # Step 5: Verify state has both layers
    print("\n5. Verifying Neuroglancer state...")
    r = requests.post(f"{BASE_URL}/tools/ng_state_summary", json={"detail": "standard"})
    summary = r.json()
    layer_names = [l['name'] for l in summary.get('layers', [])]
    print(f"   ✓ Layers in state: {layer_names}")
    
    assert "Top_Per_Cluster" in layer_names
    assert "Latest_Query_Points" in layer_names
    
    # Step 6: Verify the WRONG pattern doesn't work
    print("\n6. Testing incorrect pattern (should create 10 annotations from full dataset)...")
    wrong_payload = {
        "file_id": file_id,  # Using original file_id instead of summary_id
        "layer_name": "Wrong_Pattern",
        "annotation_type": "point",
        "center_columns": ["centroid_x", "centroid_y", "centroid_z"],
        "color": "#0000ff"
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_ng_annotations_from_data", json=wrong_payload)
    assert r.status_code == 200
    result = r.json()
    print(f"   ✓ Created {result.get('count')} annotations")
    assert result.get("count") == 10, "Should create 10 annotations (all rows)"
    print(f"   ✓ Verified: Using file_id creates annotations from ALL rows (not filtered)")
    
    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED!")
    print("="*70)
    print("\nKey Takeaways:")
    print("  • Query results are automatically saved with summary_id")
    print("  • Using summary_id creates annotations from QUERY RESULT (4 rows)")
    print("  • Using file_id creates annotations from ORIGINAL DATA (10 rows)")
    print("  • The 'last' shorthand works for referencing recent queries")
    print()

if __name__ == "__main__":
    test_auto_save_and_chain()
