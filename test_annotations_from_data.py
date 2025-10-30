"""Test the new data_ng_annotations_from_data tool."""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_annotation_tool():
    """Test creating annotations directly from data."""
    
    # First, upload some test data
    print("1. Uploading test CSV...")
    test_csv = """cell_id,centroid_x,centroid_y,centroid_z,cluster_label,log_volume
1,100,200,300,A,5.2
2,150,250,350,A,6.1
3,200,300,400,B,4.8
4,250,350,450,B,5.5
5,300,400,500,C,7.2
"""
    
    files = {"file": ("test_cells.csv", test_csv, "text/csv")}
    r = requests.post(f"{BASE_URL}/upload_file", files=files)
    assert r.status_code == 200
    data = r.json()
    file_id = data["file_id"]
    print(f"   Uploaded file_id: {file_id}")
    
    # Test 1: Add all points as annotations
    print("\n2. Adding all points as green annotations...")
    payload = {
        "file_id": file_id,
        "layer_name": "All_Cells",
        "annotation_type": "point",
        "center_columns": ["centroid_x", "centroid_y", "centroid_z"],
        "id_column": "cell_id",
        "color": "#00ff00",
        "limit": 1000
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_ng_annotations_from_data", json=payload)
    print(f"   Status: {r.status_code}")
    result = r.json()
    print(f"   Result: {json.dumps(result, indent=2)}")
    assert result.get("ok") == True
    assert result.get("count") == 5
    
    # Test 2: Add filtered points (using group_by to get max log_volume per cluster)
    print("\n3. Adding top cell per cluster with filter_expression...")
    payload2 = {
        "file_id": file_id,
        "layer_name": "Top_Per_Cluster",
        "annotation_type": "point",
        "center_columns": ["centroid_x", "centroid_y", "centroid_z"],
        "id_column": "cell_id",
        "color": "#ff0000",
        "filter_expression": "df.group_by('cluster_label').agg(pl.first('centroid_x'), pl.first('centroid_y'), pl.first('centroid_z'), pl.first('cell_id'), pl.max('log_volume')).sort('log_volume', descending=True)"
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_ng_annotations_from_data", json=payload2)
    print(f"   Status: {r.status_code}")
    result2 = r.json()
    print(f"   Result: {json.dumps(result2, indent=2)}")
    assert result2.get("ok") == True
    assert result2.get("count") == 3  # One per cluster
    
    # Test 3: Verify state has both layers
    print("\n4. Getting state summary...")
    r = requests.post(f"{BASE_URL}/tools/ng_state_summary", json={"detail": "standard"})
    summary = r.json()
    print(f"   Layers: {[l['name'] for l in summary.get('layers', [])]}")
    
    layer_names = [l['name'] for l in summary.get('layers', [])]
    assert "All_Cells" in layer_names
    assert "Top_Per_Cluster" in layer_names
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    test_annotation_tool()
