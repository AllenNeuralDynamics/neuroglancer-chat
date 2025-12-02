"""Test to compare current annotation implementation vs manual Neuroglancer schema."""
import json
from neurogabber.backend.tools.neuroglancer_state import NeuroglancerState

# What Neuroglancer creates when you manually add a point
MANUAL_NEUROGLANCER_SCHEMA = {
    "type": "annotation",
    "source": {
        "url": "local://annotations",
        "transform": {
            "outputDimensions": {
                "x": [6.000000000000001e-9, "m"],
                "y": [6.000000000000001e-9, "m"],
                "z": [3.0000000000000004e-8, "m"]
            }
        }
    },
    "tool": "annotatePoint",
    "tab": "annotations",
    "annotationColor": "#7300ff",
    "annotations": [
        {
            "point": [4998.87158203125, 6216.5, 1175.0694580078125],
            "type": "point",
            "id": "bb79d5acc705a03fad2cc116a192df2c8a41e249"
        }
    ],
    "name": "AnnTest"
}

# What our current implementation creates
state = NeuroglancerState()
state.add_layer("AnnTest", "annotation")
state.add_annotations("AnnTest", [
    {"point": [4998.87158203125, 6216.5, 1175.0694580078125], "id": "bb79d5acc705a03fad2cc116a192df2c8a41e249"}
])

current_layer = next(l for l in state.data["layers"] if l["name"] == "AnnTest")

print("=" * 80)
print("MANUAL NEUROGLANCER SCHEMA:")
print("=" * 80)
print(json.dumps(MANUAL_NEUROGLANCER_SCHEMA, indent=2))

print("\n" + "=" * 80)
print("CURRENT IMPLEMENTATION:")
print("=" * 80)
print(json.dumps(current_layer, indent=2))

print("\n" + "=" * 80)
print("KEY DIFFERENCES:")
print("=" * 80)
print("\n1. SOURCE STRUCTURE:")
print(f"   Manual: {MANUAL_NEUROGLANCER_SCHEMA['source']}")
print(f"   Current: {current_layer['source']}")

print("\n2. MISSING FIELDS IN CURRENT:")
missing = []
for key in MANUAL_NEUROGLANCER_SCHEMA:
    if key not in current_layer:
        missing.append(key)
print(f"   {missing}")

print("\n3. ANNOTATION ITEM STRUCTURE:")
manual_ann = MANUAL_NEUROGLANCER_SCHEMA["annotations"][0]
if "annotations" in current_layer:
    current_ann = current_layer["annotations"][0]
    print(f"   Manual annotation has 'type': {manual_ann.get('type')}")
    print(f"   Current annotation has 'type': {current_ann.get('type')}")
elif "source" in current_layer and "annotations" in current_layer["source"]:
    current_ann = current_layer["source"]["annotations"][0]
    print(f"   Manual annotation has 'type': {manual_ann.get('type')}")
    print(f"   Current annotation has 'type': {current_ann.get('type')}")
else:
    print(f"   Current implementation stores annotations in unexpected location:")
    print(f"   {json.dumps(current_layer, indent=4)}")

print("\n" + "=" * 80)
print("RECOMMENDATIONS:")
print("=" * 80)
print("""
1. Source should be at layer level, not nested:
   - Move 'annotations' array to layer level (not in source)
   - Use source: {"url": "local://annotations"}
   
2. Add annotation-specific metadata:
   - tool: "annotatePoint" 
   - tab: "annotations"
   - annotationColor: "#7300ff" (or user-specified)
   
3. Annotation items should include 'type' field:
   - Current: {"point": [...], "id": "..."}
   - Should be: {"point": [...], "type": "point", "id": "..."}
   
4. Consider adding transform with outputDimensions
   - Helps with coordinate system alignment
""")
