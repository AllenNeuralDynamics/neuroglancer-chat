"""
Test to verify our annotation schema matches the manual Neuroglancer example.
"""
import json
from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState

# Create annotation layer
state = NeuroglancerState()
state.add_layer("AnnTest", "annotation", annotationColor="#7300ff")

# Add a point annotation
state.add_annotations("AnnTest", [
    {
        "point": [4998.87158203125, 6216.5, 1175.0694580078125],
        "type": "point",
        "id": "bb79d5acc705a03fad2cc116a192df2c8a41e249"
    }
])

# Get the layer
ann_layer = next(l for l in state.data["layers"] if l["name"] == "AnnTest")

print("=" * 80)
print("VERIFICATION: Our Schema vs Manual Neuroglancer Schema")
print("=" * 80)

# Check all required fields
checks = {
    "✅ Layer type is 'annotation'": ann_layer["type"] == "annotation",
    "✅ Source has 'url' field": "url" in ann_layer["source"],
    "✅ Source URL is 'local://annotations'": ann_layer["source"]["url"] == "local://annotations",
    "✅ Has 'tool' field": "tool" in ann_layer,
    "✅ Has 'tab' field": "tab" in ann_layer,
    "✅ Has 'annotationColor' field": "annotationColor" in ann_layer,
    "✅ Annotations at layer level": "annotations" in ann_layer and isinstance(ann_layer["annotations"], list),
    "✅ Annotation has 'point' field": "point" in ann_layer["annotations"][0],
    "✅ Annotation has 'type' field": "type" in ann_layer["annotations"][0],
    "✅ Annotation has 'id' field": "id" in ann_layer["annotations"][0],
    "✅ Annotation type is 'point'": ann_layer["annotations"][0]["type"] == "point",
}

for check, result in checks.items():
    status = check if result else check.replace("✅", "❌")
    print(f"  {status}")

all_passed = all(checks.values())

print("\n" + "=" * 80)
print("RESULT")
print("=" * 80)
if all_passed:
    print("🎉 SUCCESS! Our schema matches Neuroglancer's manual annotation format!")
else:
    print("❌ FAILED! Some checks did not pass.")
    
print("\n" + "=" * 80)
print("FULL LAYER STRUCTURE:")
print("=" * 80)
print(json.dumps(ann_layer, indent=2))
