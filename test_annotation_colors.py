"""Test annotation color customization."""
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
print("TEST: Annotation layer color customization")
print("=" * 80)

# Test 1: Create annotation layer with green color
print("\n1. Creating green annotation layer...")
response1 = client.post(
    "/tools/ng_add_layer",
    json={"name": "GreenAnnotations", "layer_type": "annotation", "annotation_color": "#00ff00"}
)
print(f"   Status: {response1.status_code}")
print(f"   Response: {response1.json()}")

layer1 = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "GreenAnnotations"), None)
print(f"   Color: {layer1['annotationColor']}")
assert layer1['annotationColor'] == "#00ff00", f"Expected #00ff00, got {layer1['annotationColor']}"
print("   ✅ Green color applied!")

# Test 2: Create annotation layer with red color
print("\n2. Creating red annotation layer...")
response2 = client.post(
    "/tools/ng_add_layer",
    json={"name": "RedAnnotations", "layer_type": "annotation", "annotation_color": "#ff0000"}
)
print(f"   Status: {response2.status_code}")

layer2 = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "RedAnnotations"), None)
print(f"   Color: {layer2['annotationColor']}")
assert layer2['annotationColor'] == "#ff0000", f"Expected #ff0000, got {layer2['annotationColor']}"
print("   ✅ Red color applied!")

# Test 3: Create annotation layer without color (should use default)
print("\n3. Creating annotation layer without color...")
response3 = client.post(
    "/tools/ng_add_layer",
    json={"name": "DefaultAnnotations", "layer_type": "annotation"}
)
print(f"   Status: {response3.status_code}")

layer3 = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "DefaultAnnotations"), None)
print(f"   Color: {layer3['annotationColor']}")
assert layer3['annotationColor'] == "#cecd11", f"Expected #cecd11, got {layer3['annotationColor']}"
print("   ✅ Default color applied!")

# Test 4: Via dispatcher (simulating LLM call)
print("\n4. Creating blue annotation via dispatcher...")
from neurogabber.backend.main import _execute_tool_by_name

result = _execute_tool_by_name(
    "ng_add_layer",
    {"name": "BlueAnnotations", "layer_type": "annotation", "annotation_color": "#0000ff"}
)
print(f"   Result: {result}")

layer4 = next((l for l in CURRENT_STATE.data["layers"] if l["name"] == "BlueAnnotations"), None)
print(f"   Color: {layer4['annotationColor']}")
assert layer4['annotationColor'] == "#0000ff", f"Expected #0000ff, got {layer4['annotationColor']}"
print("   ✅ Blue color applied via dispatcher!")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print("✅ All color tests passed!")
print("✅ LLM can now specify custom annotation colors")
print("\nExample LLM call:")
print('  ng_add_layer(name="MyAnnotations", layer_type="annotation", annotation_color="#00ff00")')
