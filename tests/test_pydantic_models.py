"""Tests for Pydantic model-based endpoints.

Verifies that all endpoints using Pydantic models work correctly via:
1. HTTP calls (FastAPI request parsing)
2. Internal dispatcher calls (tool execution from LLM)
3. No Body object leaks into state
"""

import pytest
from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app, CURRENT_STATE, DATA_MEMORY, _execute_tool_by_name
from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before each test."""
    global CURRENT_STATE
    from neuroglancer_chat.backend.main import CURRENT_STATE as _cs
    # Reset to fresh state
    _cs.data = {
        "dimensions": {"x": [1e-9, "m"], "y": [1e-9, "m"], "z": [1e-9, "m"]},
        "position": [0, 0, 0],
        "crossSectionScale": 1.0,
        "projectionScale": 1024,
        "layers": [],
        "layout": "xy",
    }
    yield
    # Cleanup after test
    DATA_MEMORY.files.clear()
    DATA_MEMORY.summaries.clear()
    DATA_MEMORY.plots.clear()


class TestAddLayer:
    """Tests for ng_add_layer endpoint (critical bug fix)."""
    
    def test_add_layer_via_http(self, client):
        """Test adding layer via HTTP request."""
        response = client.post(
            "/tools/ng_add_layer",
            json={"name": "test_layer", "layer_type": "image", "visible": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["layer"] == "test_layer"
        
    def test_add_layer_via_dispatcher(self):
        """Test adding layer via internal dispatcher."""
        result = _execute_tool_by_name(
            "ng_add_layer",
            {"name": "test_layer", "layer_type": "image", "visible": True}
        )
        assert result["ok"] is True
        assert result["layer"] == "test_layer"
        
    def test_add_annotation_layer_no_source(self):
        """Test adding annotation layer without source (the bug scenario)."""
        # This was failing because Body(None) was stored instead of being resolved
        result = _execute_tool_by_name(
            "ng_add_layer",
            {"name": "ann", "layer_type": "annotation"}
        )
        assert result["ok"] is True
        
        # Verify layer was added correctly
        from neuroglancer_chat.backend.main import CURRENT_STATE
        layers = CURRENT_STATE.data.get("layers", [])
        ann_layer = next((l for l in layers if l["name"] == "ann"), None)
        assert ann_layer is not None
        assert ann_layer["type"] == "annotation"
        # Source should be a string or dict, never a Body object
        assert isinstance(ann_layer["source"], (str, dict))
        
    def test_add_layer_with_source(self, client):
        """Test adding layer with explicit source."""
        response = client.post(
            "/tools/ng_add_layer",
            json={
                "name": "img_layer",
                "layer_type": "image",
                "source": "precomputed://s3://bucket/layer",
                "visible": True
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        
    def test_add_layer_invalid_type(self, client):
        """Test adding layer with invalid type."""
        response = client.post(
            "/tools/ng_add_layer",
            json={"name": "bad_layer", "layer_type": "invalid"}
        )
        assert response.status_code == 422  # Pydantic validation error


class TestAnnotationWorkflow:
    """Test the complete annotation workflow that was failing."""
    
    def test_create_annotation_layer_then_add_point(self):
        """Test creating annotation layer then adding point (the original bug)."""
        from neuroglancer_chat.backend.main import CURRENT_STATE
        
        # Step 1: Create annotation layer via dispatcher (simulates LLM call)
        result1 = _execute_tool_by_name(
            "ng_add_layer",
            {"name": "ann", "layer_type": "annotation"}
        )
        assert result1["ok"] is True
        
        # Verify layer was created in state with correct schema
        layers = CURRENT_STATE.data.get("layers", [])
        ann_layer = next((l for l in layers if l["name"] == "ann"), None)
        assert ann_layer is not None, "Annotation layer was not added to state"
        assert ann_layer["type"] == "annotation"
        assert isinstance(ann_layer["source"], dict), "Annotation layer source should be dict"
        assert ann_layer["source"].get("url") == "local://annotations", "Source should have url field"
        assert "annotations" in ann_layer, "Annotation layer missing 'annotations' array at layer level"
        assert "tool" in ann_layer, "Annotation layer missing 'tool' field"
        assert "tab" in ann_layer, "Annotation layer missing 'tab' field"
        assert "annotationColor" in ann_layer, "Annotation layer missing 'annotationColor' field"
        initial_count = len(ann_layer["annotations"])
        
        # Step 2: Add annotation point
        result2 = _execute_tool_by_name(
            "ng_annotations_add",
            {
                "layer": "ann",
                "items": [
                    {"type": "point", "center": {"x": 100, "y": 200, "z": 50}}
                ]
            }
        )
        assert result2["ok"] is True
        
        # Step 3: Verify annotation was actually added to state dict (at layer level, not in source)
        layers = CURRENT_STATE.data.get("layers", [])
        ann_layer = next((l for l in layers if l["name"] == "ann"), None)
        assert ann_layer is not None, "Annotation layer disappeared from state"
        annotations = ann_layer["annotations"]  # At layer level now
        assert len(annotations) == initial_count + 1, f"Annotation not added. Expected {initial_count + 1}, got {len(annotations)}"
        
        # Verify the annotation has correct structure
        added_annotation = annotations[-1]
        assert "point" in added_annotation, "Annotation missing 'point' key"
        assert "type" in added_annotation, "Annotation missing 'type' key"
        assert added_annotation["type"] == "point", "Annotation type should be 'point'"
        assert added_annotation["point"] == [100, 200, 50], f"Point coordinates incorrect: {added_annotation['point']}"
        
        # Step 4: Verify state can be serialized to URL (this was failing)
        try:
            url = CURRENT_STATE.to_url()
            assert "neuroglancer" in url
            assert "#!" in url
        except TypeError as e:
            pytest.fail(f"Failed to serialize state to URL: {e}")
        
        # Step 5: Verify the annotation persists in serialized state
        import json
        from urllib.parse import unquote
        fragment = url.split("#!")[1]
        decoded = unquote(fragment)
        state_dict = json.loads(decoded)
        serialized_layers = state_dict.get("layers", [])
        serialized_ann = next((l for l in serialized_layers if l["name"] == "ann"), None)
        assert serialized_ann is not None, "Annotation layer not in serialized state"
        serialized_annotations = serialized_ann["annotations"]  # At layer level now
        assert len(serialized_annotations) == 1, f"Annotation not in serialized state: {serialized_annotations}"
            
    def test_annotation_layer_source_not_body_object(self):
        """Verify annotation layer source is never a Body object."""
        # Create layer
        _execute_tool_by_name(
            "ng_add_layer",
            {"name": "ann", "layer_type": "annotation"}
        )
        
        # Get layer and check source type
        from neuroglancer_chat.backend.main import CURRENT_STATE
        layers = CURRENT_STATE.data.get("layers", [])
        ann_layer = next((l for l in layers if l["name"] == "ann"), None)
        
        # Source should never be a Body object
        source = ann_layer["source"]
        assert not hasattr(source, 'embed')  # Body objects have 'embed' attribute
        assert not str(type(source).__name__).endswith('Body')
        assert isinstance(source, (str, dict))
    
    def test_annotation_persistence_via_http(self, client):
        """Test that annotations persist in CURRENT_STATE when added via HTTP endpoint."""
        from neuroglancer_chat.backend.main import CURRENT_STATE
        
        # Step 1: Create annotation layer via HTTP
        response1 = client.post(
            "/tools/ng_add_layer",
            json={"name": "persist_test", "layer_type": "annotation"}
        )
        assert response1.status_code == 200
        
        # Step 2: Verify layer exists in global CURRENT_STATE with correct schema
        layers = CURRENT_STATE.data.get("layers", [])
        ann_layer = next((l for l in layers if l["name"] == "persist_test"), None)
        assert ann_layer is not None, "Layer not found in CURRENT_STATE after HTTP creation"
        assert ann_layer["source"].get("url") == "local://annotations", "Source should use local://annotations URL"
        initial_count = len(ann_layer["annotations"])  # At layer level now
        
        # Step 3: Add annotation via HTTP
        response2 = client.post(
            "/tools/ng_annotations_add",
            json={
                "layer": "persist_test",
                "items": [
                    {"type": "point", "center": {"x": 10, "y": 20, "z": 30}},
                    {"type": "point", "center": {"x": 40, "y": 50, "z": 60}}
                ]
            }
        )
        assert response2.status_code == 200
        assert response2.json()["ok"] is True
        
        # Step 4: CRITICAL - Verify annotations actually persisted in CURRENT_STATE (at layer level)
        layers = CURRENT_STATE.data.get("layers", [])
        ann_layer = next((l for l in layers if l["name"] == "persist_test"), None)
        assert ann_layer is not None, "Layer disappeared from CURRENT_STATE after adding annotations"
        current_count = len(ann_layer["annotations"])  # At layer level now
        assert current_count == initial_count + 2, \
            f"Annotations not persisted. Expected {initial_count + 2}, got {current_count}. " \
            f"Annotations: {ann_layer['annotations']}"
        
        # Step 5: Verify annotation data is correct (with type field)
        annotations = ann_layer["annotations"]  # At layer level now
        assert annotations[-2]["point"] == [10, 20, 30]
        assert annotations[-2]["type"] == "point", "Annotation should have type field"
        assert annotations[-1]["point"] == [40, 50, 60]
        assert annotations[-1]["type"] == "point", "Annotation should have type field"
        
        # Step 6: Verify state can still serialize to URL
        url = CURRENT_STATE.to_url()
        assert "neuroglancer" in url
        
        # Step 7: Verify annotations persist in serialized form
        import json
        from urllib.parse import unquote
        fragment = url.split("#!")[1]
        decoded = unquote(fragment)
        state_dict = json.loads(decoded)
        serialized_ann = next((l for l in state_dict["layers"] if l["name"] == "persist_test"), None)
        assert serialized_ann is not None
        assert len(serialized_ann["annotations"]) == current_count  # At layer level now


class TestSetLayerVisibility:
    """Tests for ng_set_layer_visibility endpoint."""
    
    def test_set_visibility_via_http(self, client):
        """Test setting layer visibility via HTTP."""
        # First add a layer
        client.post("/tools/ng_add_layer", json={"name": "test", "layer_type": "image"})
        
        # Then toggle visibility
        response = client.post(
            "/tools/ng_set_layer_visibility",
            json={"name": "test", "visible": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["visible"] is False
        
    def test_set_visibility_via_dispatcher(self):
        """Test setting layer visibility via dispatcher."""
        # Add layer first
        _execute_tool_by_name("ng_add_layer", {"name": "test", "layer_type": "image"})
        
        # Toggle visibility
        result = _execute_tool_by_name(
            "ng_set_layer_visibility",
            {"name": "test", "visible": False}
        )
        assert result["ok"] is True


class TestStateLoad:
    """Tests for state_load and demo_load endpoints."""
    
    def test_state_load_via_http(self, client):
        """Test loading state via HTTP."""
        # Create a simple state URL
        from neuroglancer_chat.backend.main import CURRENT_STATE
        url = CURRENT_STATE.to_url()
        
        response = client.post("/tools/state_load", json={"link": url})
        assert response.status_code == 200
        assert response.json()["ok"] is True
        
    def test_state_load_via_dispatcher(self):
        """Test loading state via dispatcher."""
        from neuroglancer_chat.backend.main import CURRENT_STATE
        url = CURRENT_STATE.to_url()
        
        result = _execute_tool_by_name("state_load", {"link": url})
        assert result["ok"] is True
        
    def test_demo_load_same_as_state_load(self, client):
        """Verify demo_load uses same StateLoad model."""
        from neuroglancer_chat.backend.main import CURRENT_STATE
        url = CURRENT_STATE.to_url()
        
        response = client.post("/tools/demo_load", json={"link": url})
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestStateSummary:
    """Tests for ng_state_summary endpoint."""
    
    def test_state_summary_default_detail(self, client):
        """Test state summary with default detail level."""
        response = client.post("/tools/ng_state_summary", json={})
        assert response.status_code == 200
        data = response.json()
        assert "layers" in data
        assert "layout" in data
        
    def test_state_summary_custom_detail(self, client):
        """Test state summary with custom detail level."""
        response = client.post("/tools/ng_state_summary", json={"detail": "full"})
        assert response.status_code == 200
        data = response.json()
        assert data["detail"] == "full"
        
    def test_state_summary_via_dispatcher(self):
        """Test state summary via dispatcher."""
        result = _execute_tool_by_name("ng_state_summary", {"detail": "minimal"})
        assert "layers" in result
        assert result["detail"] == "minimal"


class TestDataTools:
    """Tests for data tool endpoints."""
    
    @pytest.fixture
    def uploaded_file(self, client):
        """Upload a test CSV file."""
        import io
        csv_content = b"cell_id,x,y,z,volume\n1,100,200,50,1000\n2,150,250,60,1200\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}
        response = client.post("/upload_file", files=files)
        assert response.status_code == 200
        return response.json()["file"]["file_id"]
    
    def test_data_info_via_http(self, client, uploaded_file):
        """Test data_info via HTTP."""
        response = client.post(
            "/tools/data_info",
            json={"file_id": uploaded_file, "sample_rows": 2}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["file_id"] == uploaded_file
        assert data["n_rows"] == 2
        
    def test_data_info_via_dispatcher(self, uploaded_file):
        """Test data_info via dispatcher."""
        result = _execute_tool_by_name(
            "data_info",
            {"file_id": uploaded_file, "sample_rows": 2}
        )
        assert result["file_id"] == uploaded_file
        
    def test_data_preview_via_http(self, client, uploaded_file):
        """Test data_preview via HTTP."""
        response = client.post(
            "/tools/data_preview",
            json={"file_id": uploaded_file, "n": 1}
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["rows"]) == 1
        
    def test_data_describe_via_http(self, client, uploaded_file):
        """Test data_describe via HTTP."""
        response = client.post(
            "/tools/data_describe",
            json={"file_id": uploaded_file}
        )
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "rows" in data


class TestDataQueryPolars:
    """Tests for data_query_polars endpoint."""
    
    @pytest.fixture
    def uploaded_file(self, client):
        """Upload a test CSV file."""
        import io
        csv_content = b"cell_id,x,y,z,volume\n1,100,200,50,1000\n2,150,250,60,1200\n3,200,300,70,800\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}
        response = client.post("/upload_file", files=files)
        assert response.status_code == 200
        return response.json()["file"]["file_id"]
    
    def test_query_via_http(self, client, uploaded_file):
        """Test data query via HTTP."""
        response = client.post(
            "/tools/data_query_polars",
            json={
                "file_id": uploaded_file,
                "expression": "df.filter(pl.col('volume') > 900)",
                "limit": 100
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["rows"] == 2  # Two rows with volume > 900
        
    def test_query_via_dispatcher(self, uploaded_file):
        """Test data query via dispatcher."""
        result = _execute_tool_by_name(
            "data_query_polars",
            {
                "file_id": uploaded_file,
                "expression": "df.filter(pl.col('volume') > 900)",
                "limit": 100
            }
        )
        assert result["ok"] is True
        assert result["rows"] == 2


class TestDataPlot:
    """Tests for data_plot endpoint."""
    
    @pytest.fixture
    def uploaded_file(self, client):
        """Upload a test CSV file."""
        import io
        csv_content = b"cell_id,x,y,z,volume\n1,100,200,50,1000\n2,150,250,60,1200\n3,200,300,70,800\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}
        response = client.post("/upload_file", files=files)
        assert response.status_code == 200
        return response.json()["file"]["file_id"]
    
    def test_plot_via_http(self, client, uploaded_file):
        """Test data plot via HTTP."""
        response = client.post(
            "/tools/data_plot",
            json={
                "file_id": uploaded_file,
                "plot_type": "scatter",
                "x": "x",
                "y": "volume"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["plot_type"] == "scatter"
        
    def test_plot_via_dispatcher(self, uploaded_file):
        """Test data plot via dispatcher."""
        result = _execute_tool_by_name(
            "data_plot",
            {
                "file_id": uploaded_file,
                "plot_type": "scatter",
                "x": "x",
                "y": "volume"
            }
        )
        assert result["ok"] is True


class TestNgViewsTable:
    """Tests for data_ng_views_table endpoint."""
    
    @pytest.fixture
    def uploaded_file(self, client):
        """Upload a test CSV file."""
        import io
        csv_content = b"cell_id,x,y,z,volume\n1,100,200,50,1000\n2,150,250,60,1200\n3,200,300,70,800\n"
        files = {"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}
        response = client.post("/upload_file", files=files)
        assert response.status_code == 200
        return response.json()["file"]["file_id"]
    
    def test_ng_views_via_http(self, client, uploaded_file):
        """Test ng_views_table via HTTP."""
        response = client.post(
            "/tools/data_ng_views_table",
            json={
                "file_id": uploaded_file,
                "top_n": 2,
                "id_column": "cell_id",
                "center_columns": ["x", "y", "z"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["n"] == 2
        assert len(data["rows"]) == 2
        
    def test_ng_views_via_dispatcher(self, uploaded_file):
        """Test ng_views_table via dispatcher."""
        result = _execute_tool_by_name(
            "data_ng_views_table",
            {
                "file_id": uploaded_file,
                "top_n": 2,
                "id_column": "cell_id",
                "center_columns": ["x", "y", "z"]
            }
        )
        assert result["n"] == 2
        assert len(result["rows"]) == 2
        
    def test_ng_views_no_body_objects_in_params(self, uploaded_file):
        """Verify no Body objects leak through in ng_views_table (the complex endpoint)."""
        # This endpoint had 30+ lines of defensive Body object checks
        # Now with Pydantic models, those checks are unnecessary
        result = _execute_tool_by_name(
            "data_ng_views_table",
            {
                "file_id": uploaded_file,
                "top_n": 1,
                "descending": True,
                "annotations": False
            }
        )
        assert "error" not in result or "Body" not in result.get("error", "")
        assert result["n"] == 1


class TestPydanticValidation:
    """Test that Pydantic validation works correctly."""
    
    def test_missing_required_field(self, client):
        """Test that missing required fields return validation errors."""
        response = client.post(
            "/tools/ng_add_layer",
            json={"layer_type": "image"}  # Missing required 'name'
        )
        assert response.status_code == 422  # Validation error
        
    def test_invalid_enum_value(self, client):
        """Test that invalid enum values return validation errors."""
        response = client.post(
            "/tools/ng_add_layer",
            json={"name": "test", "layer_type": "invalid_type"}
        )
        assert response.status_code == 422
        
    def test_invalid_type(self, client):
        """Test that invalid types return validation errors."""
        response = client.post(
            "/tools/data_info",
            json={"file_id": "test", "sample_rows": "not_a_number"}
        )
        assert response.status_code == 422
        
    def test_default_values_work(self, client):
        """Test that default values are applied correctly."""
        # StateSummary has detail="standard" as default
        response = client.post("/tools/ng_state_summary", json={})
        assert response.status_code == 200
        # Should use default value
        data = response.json()
        assert data["detail"] == "standard"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

