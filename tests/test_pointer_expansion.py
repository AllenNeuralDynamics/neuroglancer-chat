"""
Tests for Neuroglancer JSON pointer expansion functionality.
"""

import json
import pytest
from unittest.mock import Mock, patch
from typing import Dict, Any

from neuroglancer_chat.backend.tools.pointer_expansion import (
    expand_if_pointer_and_generate_inline,
    is_pointer_url,
    resolve_neuroglancer_pointer,
    neuroglancer_state_to_url,
    _is_probably_json,
    _percent_decode,
    _percent_encode_minified,
    _fetch_http,
    _fetch_s3,
    _fetch_gs,
    _default_fetch
)


class TestPointerDetection:
    """Test pointer URL detection functionality."""
    
    def test_is_pointer_url_with_s3_pointer(self):
        """Test detection of s3:// pointers."""
        url = "https://example.com/#!s3://bucket/file.json"
        assert is_pointer_url(url) is True
    
    def test_is_pointer_url_with_gs_pointer(self):
        """Test detection of gs:// pointers."""
        url = "https://example.com/#!gs://bucket/file.json"
        assert is_pointer_url(url) is True
    
    def test_is_pointer_url_with_http_pointer(self):
        """Test detection of http:// pointers."""
        url = "https://example.com/#!https://other.com/file.json"
        assert is_pointer_url(url) is True
    
    def test_is_pointer_url_with_inline_json(self):
        """Test detection of inline JSON (not a pointer)."""
        url = "https://example.com/#!%7B%22test%22%3A%22value%22%7D"
        assert is_pointer_url(url) is False
    
    def test_is_pointer_url_without_fragment(self):
        """Test URL without fragment."""
        url = "https://example.com/"
        assert is_pointer_url(url) is False
    
    def test_is_pointer_url_with_just_pointer(self):
        """Test just pointer without base URL."""
        url = "s3://bucket/file.json"
        assert is_pointer_url(url) is False  # No #! fragment


class TestJsonDetection:
    """Test JSON detection helper."""
    
    def test_is_probably_json_valid(self):
        """Test valid JSON detection."""
        assert _is_probably_json('{"test": "value"}') is True
        assert _is_probably_json('  {"nested": {"key": "val"}}  ') is True
    
    def test_is_probably_json_invalid(self):
        """Test non-JSON detection."""
        assert _is_probably_json('s3://bucket/file.json') is False
        assert _is_probably_json('{"incomplete": ') is False
        assert _is_probably_json('') is False


class TestUrlEncoding:
    """Test URL encoding/decoding utilities."""
    
    def test_percent_decode(self):
        """Test percent decoding."""
        encoded = "%7B%22test%22%3A%22value%22%7D"
        decoded = _percent_decode(encoded)
        assert decoded == '{"test":"value"}'
    
    def test_percent_encode_minified(self):
        """Test percent encoding with minification."""
        obj = {"test": "value", "nested": {"key": "val"}}
        encoded = _percent_encode_minified(obj)
        # Should be minified (no spaces) and encoded
        assert " " not in encoded
        assert "%22" in encoded  # Quotes should be encoded


class TestResolvePointer:
    """Test pointer resolution functionality."""
    
    def test_resolve_inline_json(self):
        """Test resolving inline JSON."""
        fragment = '{"test": "value"}'
        state, was_pointer = resolve_neuroglancer_pointer(fragment)
        assert state == {"test": "value"}
        assert was_pointer is False
    
    def test_resolve_encoded_inline_json(self):
        """Test resolving percent-encoded inline JSON."""
        fragment = '%7B%22test%22%3A%22value%22%7D'
        state, was_pointer = resolve_neuroglancer_pointer(fragment)
        assert state == {"test": "value"}
        assert was_pointer is False
    
    def test_resolve_pointer_with_mock_fetcher(self):
        """Test resolving pointer with mock fetcher."""
        mock_json = '{"dimensions": {"x": [1e-9, "m"]}, "position": [0, 0, 0]}'
        
        def mock_fetcher(url: str) -> str:
            assert url == "s3://bucket/state.json"
            return mock_json
        
        fragment = "s3://bucket/state.json"
        state, was_pointer = resolve_neuroglancer_pointer(fragment, fetcher=mock_fetcher)
        assert state == {"dimensions": {"x": [1e-9, "m"]}, "position": [0, 0, 0]}
        assert was_pointer is True
    
    def test_resolve_pointer_invalid_json(self):
        """Test error handling for invalid JSON."""
        def bad_fetcher(url: str) -> str:
            return "not json"
        
        fragment = "s3://bucket/bad.json"
        with pytest.raises(ValueError, match="not valid JSON"):
            resolve_neuroglancer_pointer(fragment, fetcher=bad_fetcher)
    
    def test_resolve_pointer_fetch_error(self):
        """Test error handling for fetch failures."""
        def failing_fetcher(url: str) -> str:
            raise ConnectionError("Network error")
        
        fragment = "s3://bucket/missing.json"
        with pytest.raises(ValueError, match="Failed to fetch content"):
            resolve_neuroglancer_pointer(fragment, fetcher=failing_fetcher)
    
    def test_resolve_malformed_json_fragment(self):
        """Test error handling for malformed inline JSON."""
        fragment = '{"incomplete": '
        with pytest.raises(ValueError, match="Failed to fetch content from pointer"):
            resolve_neuroglancer_pointer(fragment)


class TestStateToUrl:
    """Test state serialization to URL."""
    
    def test_neuroglancer_state_to_url(self):
        """Test basic state to URL conversion."""
        state = {"dimensions": {"x": [1e-9, "m"]}, "position": [0, 0, 0]}
        base_url = "https://neuroglancer.example.com"
        
        url = neuroglancer_state_to_url(state, base_url)
        assert url.startswith(base_url + "/#!")
        assert "dimensions" in url
    
    def test_neuroglancer_state_to_url_removes_ng_link(self):
        """Test that ng_link is removed from state."""
        state = {
            "dimensions": {"x": [1e-9, "m"]},
            "ng_link": "should_be_removed"
        }
        base_url = "https://neuroglancer.example.com"
        
        url = neuroglancer_state_to_url(state, base_url)
        # ng_link should not appear in URL
        assert "ng_link" not in url
        assert "should_be_removed" not in url
    
    def test_neuroglancer_state_to_url_trailing_slash(self):
        """Test base URL with trailing slash is handled."""
        state = {"test": "value"}
        base_url = "https://neuroglancer.example.com/"
        
        url = neuroglancer_state_to_url(state, base_url)
        assert url.startswith("https://neuroglancer.example.com/#!")


class TestExpandPointer:
    """Test full pointer expansion workflow."""
    
    def test_expand_inline_url(self):
        """Test expansion of URL with inline JSON (no-op)."""
        inline_url = "https://neuroglancer.example.com/#!%7B%22test%22%3A%22value%22%7D"
        
        canonical, state, was_pointer = expand_if_pointer_and_generate_inline(inline_url)
        assert state == {"test": "value"}
        assert was_pointer is False
        # Should generate canonical URL
        assert canonical.startswith("https://neuroglancer.example.com/#!")
    
    def test_expand_pointer_url(self):
        """Test expansion of URL with pointer."""
        pointer_url = "https://neuroglancer.example.com/#!s3://bucket/state.json"
        mock_state = {"dimensions": {"x": [1e-9, "m"]}, "position": [100, 200, 300]}
        
        def mock_fetcher(url: str) -> str:
            assert url == "s3://bucket/state.json"
            return json.dumps(mock_state)
        
        canonical, state, was_pointer = expand_if_pointer_and_generate_inline(
            pointer_url, fetcher=mock_fetcher
        )
        assert state == mock_state
        assert was_pointer is True
        assert canonical.startswith("https://neuroglancer.example.com/#!")
        # Should contain encoded state
        assert "dimensions" in canonical
    
    def test_expand_fragment_only(self):
        """Test expansion of fragment-only input."""
        fragment = "s3://bucket/state.json"
        mock_state = {"test": "value"}
        
        def mock_fetcher(url: str) -> str:
            return json.dumps(mock_state)
        
        canonical, state, was_pointer = expand_if_pointer_and_generate_inline(
            fragment, fetcher=mock_fetcher
        )
        assert state == mock_state
        assert was_pointer is True
        # Should use default base URL
        assert canonical.startswith("https://neuroglancer-demo.appspot.com/#!")
    
    def test_expand_with_custom_base(self):
        """Test expansion preserves custom base URL."""
        pointer_url = "https://custom.neuroglancer.com/#!gs://bucket/state.json"
        mock_state = {"test": "value"}
        
        def mock_fetcher(url: str) -> str:
            return json.dumps(mock_state)
        
        canonical, state, was_pointer = expand_if_pointer_and_generate_inline(
            pointer_url, fetcher=mock_fetcher
        )
        assert canonical.startswith("https://custom.neuroglancer.com/#!")


class TestFetchers:
    """Test cloud storage fetchers."""
    
    @patch('neurogabber.backend.tools.pointer_expansion._HAS_BOTO3', True)
    @patch('neurogabber.backend.tools.pointer_expansion.boto3')
    def test_fetch_s3_success(self, mock_boto3):
        """Test successful S3 fetch."""
        mock_s3_client = Mock()
        mock_boto3.client.return_value = mock_s3_client
        
        mock_body = Mock()
        mock_body.read.return_value.decode.return_value = '{"test": "value"}'
        mock_response = {'Body': mock_body}
        mock_s3_client.get_object.return_value = mock_response
        
        result = _fetch_s3("s3://test-bucket/path/to/file.json")
        assert result == '{"test": "value"}'
        
        mock_s3_client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="path/to/file.json"
        )
    
    @patch('neurogabber.backend.tools.pointer_expansion._HAS_BOTO3', False)
    def test_fetch_s3_missing_boto3(self):
        """Test S3 fetch without boto3 installed."""
        with pytest.raises(RuntimeError, match="boto3 not installed"):
            _fetch_s3("s3://bucket/file.json")
    
    def test_fetch_s3_invalid_url(self):
        """Test S3 fetch with invalid URL."""
        with pytest.raises(ValueError, match="Not a valid s3 URL"):
            _fetch_s3("invalid://url")
    
    @patch('neurogabber.backend.tools.pointer_expansion._HAS_GCS', True)
    @patch('neurogabber.backend.tools.pointer_expansion.gcs')
    def test_fetch_gs_success(self, mock_gcs):
        """Test successful GS fetch."""
        mock_client = Mock()
        mock_gcs.Client.return_value = mock_client
        
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_blob.download_as_text.return_value = '{"test": "gs_value"}'
        mock_bucket.blob.return_value = mock_blob
        mock_client.bucket.return_value = mock_bucket
        
        result = _fetch_gs("gs://test-bucket/path/to/file.json")
        assert result == '{"test": "gs_value"}'
        
        mock_client.bucket.assert_called_once_with("test-bucket")
        mock_bucket.blob.assert_called_once_with("path/to/file.json")
    
    @patch('neurogabber.backend.tools.pointer_expansion._HAS_GCS', False)
    def test_fetch_gs_missing_gcs(self):
        """Test GS fetch without google-cloud-storage installed."""
        with pytest.raises(RuntimeError, match="google-cloud-storage not installed"):
            _fetch_gs("gs://bucket/file.json")
    
    def test_fetch_gs_invalid_url(self):
        """Test GS fetch with invalid URL."""
        with pytest.raises(ValueError, match="Not a valid gs URL"):
            _fetch_gs("invalid://url")
    
    @patch('urllib.request.urlopen')
    def test_fetch_http_success(self, mock_urlopen):
        """Test successful HTTP fetch."""
        mock_response = Mock()
        mock_response.read.return_value.decode.return_value = '{"test": "http_value"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = _fetch_http("https://example.com/state.json")
        assert result == '{"test": "http_value"}'
    
    def test_default_fetch_routing(self):
        """Test default fetcher routes to correct sub-fetchers."""
        # Test unsupported scheme
        with pytest.raises(ValueError, match="Unsupported pointer scheme"):
            _default_fetch("ftp://example.com/file.json")


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""
    
    def test_hemibrain_gs_example(self):
        """Test with realistic hemibrain GS URL."""
        url = "https://hemibrain-dot-neuroglancer-demo.appspot.com/#!gs://neuroglancer-janelia-flyem-hemibrain/v1.0/neuroglancer_demo_states/base.json"
        
        # Mock realistic neuroglancer state
        mock_state = {
            "dimensions": {"x": [8e-9, "m"], "y": [8e-9, "m"], "z": [8e-9, "m"]},
            "position": [16000, 16000, 16000],
            "crossSectionScale": 1,
            "layers": [
                {
                    "type": "image",
                    "source": "precomputed://gs://neuroglancer-janelia-flyem-hemibrain/v1.0/em",
                    "name": "em"
                }
            ]
        }
        
        def mock_fetcher(url: str) -> str:
            assert url.startswith("gs://neuroglancer-janelia-flyem-hemibrain")
            return json.dumps(mock_state)
        
        canonical, state, was_pointer = expand_if_pointer_and_generate_inline(
            url, fetcher=mock_fetcher
        )
        
        assert was_pointer is True
        assert state == mock_state
        assert canonical.startswith("https://hemibrain-dot-neuroglancer-demo.appspot.com/#!")
        assert len(canonical) > len(url)  # Should be longer due to inline JSON
    
    def test_aind_s3_example(self):
        """Test with realistic AIND S3 URL."""
        url = "https://aind-neuroglancer-sauujisjxq-uw.a.run.app/#!s3://aind-open-data/HCR_754803-03_2025-04-04_13-00-00/raw_data.json"
        
        mock_state = {
            "dimensions": {"x": [2.45e-7, "m"], "y": [2.45e-7, "m"], "z": [1e-6, "m"]},
            "position": [48.5, -5423.5, 584.5],
            "layers": [
                {
                    "type": "image",
                    "source": "zarr://s3://aind-open-data/HCR_754803-03_2025-04-04_13-00-00/SPIM.ome.zarr",
                    "name": "raw_data"
                }
            ]
        }
        
        def mock_fetcher(url: str) -> str:
            assert url.startswith("s3://aind-open-data")
            return json.dumps(mock_state)
        
        canonical, state, was_pointer = expand_if_pointer_and_generate_inline(
            url, fetcher=mock_fetcher
        )
        
        assert was_pointer is True
        assert state == mock_state
        assert canonical.startswith("https://aind-neuroglancer-sauujisjxq-uw.a.run.app/#!")
    
    def test_roundtrip_consistency(self):
        """Test that expand -> serialize -> expand is consistent."""
        original_state = {
            "dimensions": {"x": [1e-9, "m"], "y": [1e-9, "m"], "z": [1e-9, "m"]},
            "position": [100, 200, 300],
            "layers": [{"type": "image", "source": "test://data", "name": "test"}]
        }
        
        def mock_fetcher(url: str) -> str:
            return json.dumps(original_state)
        
        # First expansion
        pointer_url = "https://example.com/#!s3://bucket/state.json"
        canonical1, state1, was_pointer1 = expand_if_pointer_and_generate_inline(
            pointer_url, fetcher=mock_fetcher
        )
        
        # Second expansion on canonical URL (should be no-op)
        canonical2, state2, was_pointer2 = expand_if_pointer_and_generate_inline(canonical1)
        
        assert was_pointer1 is True
        assert was_pointer2 is False
        assert state1 == state2 == original_state
        # URLs might not be identical due to key ordering, but states should match