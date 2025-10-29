"""Test annotation adding to match your exact examples."""
import json
from fastapi.testclient import TestClient
from neurogabber.backend.main import app, CURRENT_STATE

client = TestClient(app)

# Reset state
CURRENT_STATE.data = {
    "dimensions": {"x": [1e-9, "m"], "y": [1e-9, "m"], "z": [1e-9, "m"]},
    "position": [0, 0, 0],
    "layers": []
}

print("=" * 80)
print("TEST: Creating annotation layer and adding points")
print("=" * 80)

# Step 1: Create annotation layer
print("\n1. Creating annotation layer 'TestPoints'...")
response1 = client.post(
    "/tools/ng_add_layer",
    json={"name": "TestPoints", "layer_type": "annotation"}
)
print(f"   Status: {response1.status_code}")
print(f"   Response: {response1.json()}")

# Check layer structure
layer = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "TestPoints"), None)
print(f"\n   Layer structure:")
print(json.dumps(layer, indent=4))

# Step 2: Add annotation points
print("\n2. Adding two annotation points...")
response2 = client.post(
    "/tools/ng_annotations_add",
    json={
        "layer": "TestPoints",
        "items": [
            {"type": "point", "center": {"x": 5461.61474609375, "y": 6213.5, "z": 1086.072265625}, "id": "0b385a5d689f82fd33d31fca5e61b483c9f87f9d"},
            {"type": "point", "center": {"x": 5414.7724609375, "y": 6213.5, "z": 1083.7301025390625}, "id": "3811881a2683c1242f8fced03f3df0bbd1b057fc"}
        ]
    }
)
print(f"   Status: {response2.status_code}")
print(f"   Response: {response2.json()}")

# Check annotations
layer = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "TestPoints"), None)
print(f"\n   Annotations in layer:")
print(json.dumps(layer["annotations"], indent=4))

print("\n" + "=" * 80)
print("EXPECTED FORMAT:")
print("=" * 80)
expected = [
    {
        "point": [5461.61474609375, 6213.5, 1086.072265625],
        "type": "point",
        "id": "0b385a5d689f82fd33d31fca5e61b483c9f87f9d"
    },
    {
        "point": [5414.7724609375, 6213.5, 1083.7301025390625],
        "type": "point",
        "id": "3811881a2683c1242f8fced03f3df0bbd1b057fc"
    }
]
print(json.dumps(expected, indent=4))

print("\n" + "=" * 80)
print("COMPARISON:")
print("=" * 80)
if layer["annotations"] == expected:
    print("✅ MATCH! Annotations match expected format exactly.")
else:
    print("❌ MISMATCH!")
    print("\nActual:")
    print(json.dumps(layer["annotations"], indent=4))
    print("\nExpected:")
    print(json.dumps(expected, indent=4))
    
    # Detailed comparison
    for i, (actual, exp) in enumerate(zip(layer["annotations"], expected)):
        print(f"\nAnnotation {i}:")
        for key in set(list(actual.keys()) + list(exp.keys())):
            if actual.get(key) != exp.get(key):
                print(f"  {key}: {actual.get(key)} != {exp.get(key)}")

print("\n" + "=" * 80)
print("FULL LAYER STRUCTURE:")
print("=" * 80)
print(json.dumps(layer, indent=2))

# Test serialization
print("\n" + "=" * 80)
print("URL SERIALIZATION TEST:")
print("=" * 80)
try:
    url = CURRENT_STATE.to_url()
    print(f"✅ Successfully serialized to URL")
    print(f"   URL length: {len(url)} characters")
    
    # Decode and check
    from urllib.parse import unquote
    fragment = url.split("#!")[1]
    decoded = unquote(fragment)
    state_dict = json.loads(decoded)
    serialized_layer = next((l for l in state_dict["layers"] if l["name"] == "TestPoints"), None)
    
    print(f"\n   Serialized annotations count: {len(serialized_layer['annotations'])}")
    print(f"   Annotations preserved: {serialized_layer['annotations'] == expected}")
    
except Exception as e:
    print(f"❌ Serialization failed: {e}")
