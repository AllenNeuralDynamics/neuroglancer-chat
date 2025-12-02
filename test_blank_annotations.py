"""Test to reproduce the issue: annotations array is blank."""
import json
from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app, CURRENT_STATE

client = TestClient(app)

# Reset state
CURRENT_STATE.data = {
    "dimensions": {"x": [1e-9, "m"], "y": [1e-9, "m"], "z": [1e-9, "m"]},
    "position": [0, 0, 0],
    "layers": []
}

print("=" * 80)
print("REPRODUCING ISSUE: Annotations array blank after adding points")
print("=" * 80)

# Step 1: Create layer
print("\n1. Creating annotation layer...")
response1 = client.post("/tools/ng_add_layer", json={"name": "TestAnn", "layer_type": "annotation"})
print(f"   Status: {response1.status_code}")

# Check CURRENT_STATE directly
layer = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "TestAnn"), None)
print(f"   Annotations array after creation: {layer['annotations']}")
print(f"   Length: {len(layer['annotations'])}")

# Step 2: Add annotations
print("\n2. Adding annotation point...")
response2 = client.post(
    "/tools/ng_annotations_add",
    json={
        "layer": "TestAnn",
        "items": [{"type": "point", "center": {"x": 100, "y": 200, "z": 300}}]
    }
)
print(f"   Status: {response2.status_code}")
print(f"   Response: {response2.json()}")

# Check CURRENT_STATE directly AGAIN
print("\n3. Checking CURRENT_STATE after adding annotation...")
layer = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "TestAnn"), None)
print(f"   Annotations array: {layer['annotations']}")
print(f"   Length: {len(layer['annotations'])}")

if len(layer['annotations']) > 0:
    print(f"   ✅ Annotation added successfully!")
    print(f"   First annotation: {json.dumps(layer['annotations'][0], indent=4)}")
else:
    print(f"   ❌ Annotations array is EMPTY!")

# Step 4: Check via state_summary endpoint
print("\n4. Checking via /tools/ng_state_summary endpoint...")
response3 = client.post("/tools/ng_state_summary", json={"detail": "full"})
summary = response3.json()
summary_layer = next((l for l in summary.get("layers", []) if l.get("name") == "TestAnn"), None)
if summary_layer:
    print(f"   Layer in summary: {json.dumps(summary_layer, indent=4)}")
    if "annotations" in summary_layer:
        print(f"   Annotations count in summary: {len(summary_layer['annotations'])}")
    else:
        print(f"   ❌ No 'annotations' field in summary!")

# Step 5: Check via state_save (URL generation)
print("\n5. Checking via /tools/state_save endpoint...")
response4 = client.post("/tools/state_save")
url_data = response4.json()
url = url_data.get("url", "")

if url and "#!" in url:
    from urllib.parse import unquote
    fragment = url.split("#!")[1]
    decoded = unquote(fragment)
    state_dict = json.loads(decoded)
    saved_layer = next((l for l in state_dict.get("layers", []) if l.get("name") == "TestAnn"), None)
    if saved_layer:
        print(f"   Layer in saved state: {json.dumps(saved_layer, indent=4)}")
        if "annotations" in saved_layer:
            print(f"   ✅ Annotations count in saved state: {len(saved_layer['annotations'])}")
        else:
            print(f"   ❌ No 'annotations' field in saved state!")

print("\n" + "=" * 80)
print("DIAGNOSIS:")
print("=" * 80)
print("If annotations show in CURRENT_STATE but not in saved state,")
print("the issue is in the state serialization or URL generation.")
print("\nIf annotations are empty in CURRENT_STATE too,")
print("the issue is in the add_annotations method.")
