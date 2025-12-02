"""Direct test of what add_annotations creates."""
import json
from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState

state = NeuroglancerState()

print("=" * 80)
print("STEP 1: Create annotation layer")
print("=" * 80)
state.add_layer("TestAnn", "annotation")
print(json.dumps(state.data, indent=2))

print("\n" + "=" * 80)
print("STEP 2: Add annotation point (with type field)")
print("=" * 80)
state.add_annotations("TestAnn", [
    {"point": [100, 200, 300], "type": "point", "id": "test-id-123"}
])
print(json.dumps(state.data, indent=2))

print("\n" + "=" * 80)
print("WHAT NEUROGLANCER EXPECTS:")
print("=" * 80)
expected = {
    "type": "annotation",
    "source": {
        "url": "local://annotations",
    },
    "annotations": [  # <-- AT LAYER LEVEL, NOT IN SOURCE
        {
            "point": [100, 200, 300],
            "type": "point",  # <-- TYPE FIELD REQUIRED
            "id": "test-id-123"
        }
    ],
    "name": "TestAnn"
}
print(json.dumps(expected, indent=2))
