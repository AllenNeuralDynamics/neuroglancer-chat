"""Diagnostic script to check annotation workflow end-to-end."""
import json
import requests

BASE_URL = "http://localhost:8000"  # Adjust if your backend is on a different port

print("=" * 80)
print("DIAGNOSTIC: Testing annotation workflow against running backend")
print("=" * 80)

# Test 1: Create annotation layer
print("\n1. Creating annotation layer...")
try:
    response = requests.post(
        f"{BASE_URL}/tools/ng_add_layer",
        json={"name": "DiagnosticTest", "layer_type": "annotation"}
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
    if response.status_code != 200:
        print("   ❌ FAILED to create layer")
        exit(1)
except Exception as e:
    print(f"   ❌ ERROR: {e}")
    print("   (Is the backend running? Try: uvicorn neurogabber.backend.main:app)")
    exit(1)

# Test 2: Add annotation points
print("\n2. Adding annotation points...")
try:
    response = requests.post(
        f"{BASE_URL}/tools/ng_annotations_add",
        json={
            "layer": "DiagnosticTest",
            "items": [
                {
                    "type": "point",
                    "center": {"x": 100, "y": 200, "z": 300},
                    "id": "test-point-1"
                }
            ]
        }
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
    if response.status_code != 200:
        print("   ❌ FAILED to add annotation")
        print(f"   Error: {response.text}")
        exit(1)
except Exception as e:
    print(f"   ❌ ERROR: {e}")
    exit(1)

# Test 3: Get state summary
print("\n3. Checking state summary...")
try:
    response = requests.post(
        f"{BASE_URL}/tools/ng_state_summary",
        json={"detail": "full"}
    )
    print(f"   Status: {response.status_code}")
    summary = response.json()
    print(f"   Layers: {summary.get('layers', [])}")
    
    # Find our layer
    diag_layer = next((l for l in summary.get('layers', []) if l.get('name') == 'DiagnosticTest'), None)
    if diag_layer:
        print(f"\n   DiagnosticTest layer found:")
        print(json.dumps(diag_layer, indent=6))
    else:
        print("   ❌ DiagnosticTest layer NOT found in state!")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

# Test 4: Get full state URL
print("\n4. Getting state URL...")
try:
    response = requests.post(f"{BASE_URL}/tools/state_save")
    print(f"   Status: {response.status_code}")
    data = response.json()
    url = data.get('url', '')
    
    if url:
        print(f"   ✅ URL generated: {url[:100]}...")
        
        # Decode and check
        from urllib.parse import unquote
        if "#!" in url:
            fragment = url.split("#!")[1]
            decoded = unquote(fragment)
            state_dict = json.loads(decoded)
            
            diag_layer = next((l for l in state_dict.get('layers', []) if l.get('name') == 'DiagnosticTest'), None)
            if diag_layer:
                print(f"\n   ✅ DiagnosticTest in serialized state:")
                print(f"      Annotations count: {len(diag_layer.get('annotations', []))}")
                print(f"      Annotations: {diag_layer.get('annotations', [])}")
            else:
                print("   ❌ DiagnosticTest NOT in serialized state!")
    else:
        print("   ❌ No URL in response")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

print("\n" + "=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)
print("\nIf all tests passed but points don't show in Neuroglancer:")
print("  1. Check that the frontend is loading the updated state URL")
print("  2. Check browser console for JavaScript errors")
print("  3. Verify the annotation layer is visible (not hidden)")
print("  4. Check that the coordinate system matches your data")
