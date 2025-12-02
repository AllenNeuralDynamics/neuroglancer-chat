# Neuroglancer Annotation Schema Update

## Summary
Updated the annotation layer implementation to match Neuroglancer's actual schema format based on manual annotation inspection.

## Key Changes

### 1. **Annotation Array Location** ✅
- **Before**: Annotations stored in `layer.source.annotations` 
- **After**: Annotations stored in `layer.annotations` (at layer level)

### 2. **Source Structure** ✅
- **Before**: `source: {type: "pointAnnotation", points: [...]}`
- **After**: `source: {url: "local://annotations"}`

### 3. **Annotation Item Structure** ✅
- **Before**: `{point: [x, y, z], id: "..."}`
- **After**: `{point: [x, y, z], type: "point", id: "..."}` 
  - Now includes required `type` field

### 4. **Layer Metadata** ✅
Added required Neuroglancer metadata fields:
- `tool`: "annotatePoint" (default)
- `tab`: "annotations" (default)
- `annotationColor`: "#cecd11" (default, customizable)

## Schema Comparison

### Manual Neuroglancer Schema (Ground Truth)
```json
{
  "type": "annotation",
  "source": {
    "url": "local://annotations",
    "transform": {
      "outputDimensions": {
        "x": [6e-9, "m"],
        "y": [6e-9, "m"],
        "z": [3e-8, "m"]
      }
    }
  },
  "tool": "annotatePoint",
  "tab": "annotations",
  "annotationColor": "#7300ff",
  "annotations": [
    {
      "point": [4998.87, 6216.5, 1175.07],
      "type": "point",
      "id": "bb79d5acc705a03fad2cc116a192df2c8a41e249"
    }
  ],
  "name": "AnnTest"
}
```

### Our Updated Implementation
```json
{
  "type": "annotation",
  "source": {
    "url": "local://annotations"
  },
  "tool": "annotatePoint",
  "tab": "annotations",
  "annotationColor": "#cecd11",
  "annotations": [
    {
      "point": [100, 200, 300],
      "type": "point",
      "id": "test-id-123"
    }
  ],
  "name": "TestAnn"
}
```

✅ **Schema now matches Neuroglancer's format!**

## Files Modified

### 1. `src/neurogabber/backend/tools/neuroglancer_state.py`

#### `add_layer()` method:
- Annotation layers now create proper source: `{url: "local://annotations"}`
- Added metadata fields: `tool`, `tab`, `annotationColor`
- Moved `annotations` array to layer level (not in source)

#### `add_annotations()` method:
- Updated to append to `layer.annotations` instead of `layer.source.annotations`
- Auto-creates layer if it doesn't exist
- Added docstring explaining schema

### 2. `src/neurogabber/backend/main.py`

#### `t_add_annotations()` endpoint:
- Added `"type"` field to all annotation items
- Point annotations now: `{point: [...], type: "point", id: ...}`
- Box annotations now: `{type: "box", point: [...], size: [...], id: ...}`
- Ellipsoid annotations now: `{type: "ellipsoid", center: [...], radii: [...], id: ...}`

### 3. `tests/test_pydantic_models.py`

Updated all annotation tests to verify:
- Annotations at layer level (`layer.annotations`, not `layer.source.annotations`)
- Proper source structure with `url` field
- Metadata fields present (`tool`, `tab`, `annotationColor`)
- Each annotation has `type` field

## Testing

All 31 tests passing:
- ✅ Annotation layer creation
- ✅ Annotation point addition (HTTP & dispatcher)
- ✅ Annotation persistence in state
- ✅ State serialization to URL
- ✅ Annotations persist in serialized state
- ✅ Type field present in all annotations

## Why This Matters

The previous implementation used an outdated schema that may have prevented annotations from appearing correctly in Neuroglancer. The updated schema:

1. **Matches Neuroglancer's current format** - based on real manual annotation
2. **Includes all required metadata** - tool, tab, color for proper UI integration
3. **Properly structures annotations** - at layer level with type field
4. **Uses correct source format** - `local://annotations` URL

## Optional Enhancements (Not Implemented Yet)

From the manual schema, we could also add:
- `transform.outputDimensions` for coordinate system alignment
- Allow custom `annotationColor` parameter in API calls

## Usage Example

```python
# Create annotation layer
state.add_layer("my_annotations", "annotation")

# Add point annotation (type field now required)
state.add_annotations("my_annotations", [
    {"point": [100, 200, 50], "type": "point", "id": "unique-id-123"}
])

# Result matches Neuroglancer schema!
```

Or via HTTP:
```python
# Create layer
POST /tools/ng_add_layer
{"name": "my_annotations", "layer_type": "annotation"}

# Add point
POST /tools/ng_annotations_add
{"layer": "my_annotations", "items": [
    {"type": "point", "center": {"x": 100, "y": 200, "z": 50}}
]}
```

Annotations should now appear correctly in Neuroglancer! 🎉
