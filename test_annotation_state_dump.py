"""Test to dump the neuroglancer state after adding annotations."""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_state_dump():
    """Create annotations and check if they appear in state."""
    
    # Reset state first
    print("1. Resetting backend state...")
    r = requests.post(f"{BASE_URL}/system/reset")
    print(f"   Reset: {r.status_code}")
    
    # Upload test data with spatial coordinates
    print("\n2. Uploading test CSV...")
    test_csv = """cell_id,x,y,z,gene
1,100.5,200.3,300.7,GeneA
2,150.2,250.8,350.1,GeneB
3,200.9,300.5,400.3,GeneC
"""
    
    files = {"file": ("test_spots.csv", test_csv, "text/csv")}
    r = requests.post(f"{BASE_URL}/upload_file", files=files)
    print(f"   Upload status: {r.status_code}")
    data = r.json()
    file_id = data.get("file", {}).get("file_id") or data.get("file_id")
    print(f"   Uploaded file_id: {file_id}")
    
    # Add annotations from data
    print("\n3. Adding annotations...")
    payload = {
        "file_id": file_id,
        "layer_name": "test_spots",
        "annotation_type": "point",
        "center_columns": ["x", "y", "z"],
        "id_column": "cell_id",
        "color": "#00ff00",
        "limit": 1000
    }
    
    r = requests.post(f"{BASE_URL}/tools/data_ng_annotations_from_data", json=payload)
    print(f"   Status: {r.status_code}")
    result = r.json()
    print(f"   Result: {json.dumps(result, indent=2)}")
    
    # Get state summary
    print("\n4. Getting state summary...")
    r = requests.post(f"{BASE_URL}/tools/ng_state_summary", json={"detail": "full"})
    summary = r.json()
    
    print(f"\n   Layers: {len(summary.get('layers', []))}")
    for layer in summary.get('layers', []):
        print(f"     - {layer['name']} (type: {layer['type']})")
        if layer['type'] == 'annotation':
            annotation_count = layer.get('annotation_count', 'N/A')
            print(f"       annotation_count field: {annotation_count}")
            annotations_array = layer.get('annotations', [])
            print(f"       annotations array: {len(annotations_array)}")
    
    print(f"\n   annotation_layers field:")
    for ann_layer in summary.get('annotation_layers', []):
        print(f"     - {ann_layer['name']}: {ann_layer['count']} annotations of types {ann_layer['types']}")
    
    # Save raw state to file
    print("\n5. Saving raw state to file...")
    r = requests.get(f"{BASE_URL}/debug/raw_state")
    raw_state = r.json()
    
    with open("test_state_dump.json", "w") as f:
        json.dump(raw_state, f, indent=2)
    print("   Saved to test_state_dump.json")
    
    # Check annotations in raw state
    annotation_layers = [l for l in raw_state.get("layers", []) if l.get("type") == "annotation"]
    print(f"\n6. Annotation layers in raw state: {len(annotation_layers)}")
    for layer in annotation_layers:
        annotations = layer.get("annotations", [])
        print(f"   Layer '{layer['name']}': {len(annotations)} annotations")
        if annotations:
            print(f"     First: {annotations[0]}")
            print(f"     Keys in first: {list(annotations[0].keys())}")
    
    # Get the state URL that would be sent to frontend
    r = requests.post(f"{BASE_URL}/tools/state_save", json={}, params={"mask": False})
    print(f"\n7. State save response status: {r.status_code}")
    state_url_data = r.json()
    print(f"   State save response keys: {list(state_url_data.keys())}")
    state_url = state_url_data.get("url")
    
    print(f"   State URL length: {len(state_url) if state_url else 0}")
    if state_url:
        # Parse the URL to see what's in it
        from urllib.parse import unquote
        fragment = state_url.split('#!')[-1] if '#!' in state_url else state_url.split('#')[-1]
        decoded = unquote(fragment)
        parsed = json.loads(decoded)
        
        ann_layers = [l for l in parsed.get("layers", []) if l.get("type") == "annotation"]
        print(f"   Annotation layers in URL: {len(ann_layers)}")
        for layer in ann_layers:
            anns = layer.get("annotations", [])
            print(f"     Layer '{layer['name']}': {len(anns)} annotations")
    
    print("\n✅ Test complete! Check test_state_dump.json for full state")

if __name__ == "__main__":
    test_state_dump()
