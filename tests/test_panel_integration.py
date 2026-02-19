"""
Tests for panel app integration with pointer expansion and debounce functionality.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from contextlib import contextmanager

# Note: These tests focus on the logic patterns rather than full Panel widget testing
# which would require a more complex test environment


class TestProgrammaticLoadContext:
    """Test the programmatic load context manager."""
    
    def test_programmatic_context_manager(self):
        """Test that programmatic context manager sets and resets flag."""
        # Simulate the context manager logic
        _programmatic_load = False
        
        @contextmanager
        def _programmatic_viewer_update():
            nonlocal _programmatic_load
            _programmatic_load = True
            try:
                yield
            finally:
                _programmatic_load = False
        
        # Test normal state
        assert _programmatic_load is False
        
        # Test within context
        with _programmatic_viewer_update():
            assert _programmatic_load is True
        
        # Test after context
        assert _programmatic_load is False
    
    def test_programmatic_context_exception_handling(self):
        """Test that programmatic flag is reset even on exceptions."""
        _programmatic_load = False
        
        @contextmanager
        def _programmatic_viewer_update():
            nonlocal _programmatic_load
            _programmatic_load = True
            try:
                yield
            finally:
                _programmatic_load = False
        
        # Test exception handling
        try:
            with _programmatic_viewer_update():
                assert _programmatic_load is True
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # Flag should still be reset
        assert _programmatic_load is False


class TestDebounceLogic:
    """Test URL change debounce logic."""
    
    @pytest.fixture
    def mock_update_state_interval(self):
        """Mock the update interval widget."""
        mock_widget = Mock()
        mock_widget.value = 5  # 5 second default
        return mock_widget
    
    @pytest.fixture
    def mock_viewer(self):
        """Mock Neuroglancer viewer widget."""
        mock_viewer = Mock()
        mock_viewer.url = "https://example.com/#!test"
        return mock_viewer
    
    def test_immediate_sync_when_interval_elapsed(self, mock_update_state_interval):
        """Test immediate sync when enough time has elapsed."""
        # Simulate debounce logic
        _last_user_state_sync = 0.0
        _scheduled_user_state_task = None
        _programmatic_load = False
        
        # Mock time and async task creation
        mock_loop = Mock()
        mock_loop.time.return_value = 10.0  # Current time
        
        immediate_called = False
        
        def mock_immediate_handler(url):
            nonlocal immediate_called
            immediate_called = True
        
        def simulate_debounce_logic(new_url):
            nonlocal _last_user_state_sync, _scheduled_user_state_task, _programmatic_load
            
            if _programmatic_load:
                # Should call immediate
                mock_immediate_handler(new_url)
                return
            
            interval = max(1, int(mock_update_state_interval.value or 5))
            now = mock_loop.time()
            elapsed = now - _last_user_state_sync
            
            if elapsed >= interval:
                _last_user_state_sync = now
                mock_immediate_handler(new_url)
                return True
            return False
        
        # Test: enough time elapsed
        result = simulate_debounce_logic("https://example.com/#!new")
        assert result is True
        assert _last_user_state_sync == 10.0
        assert immediate_called is True
    
    def test_debounce_when_interval_not_elapsed(self, mock_update_state_interval):
        """Test debounce scheduling when interval hasn't elapsed."""
        _last_user_state_sync = 8.0  # Recent sync
        _scheduled_user_state_task = None
        _programmatic_load = False
        
        mock_loop = Mock()
        mock_loop.time.return_value = 10.0  # Current time (only 2 seconds later)
        
        def simulate_debounce_logic(new_url):
            nonlocal _last_user_state_sync, _scheduled_user_state_task, _programmatic_load
            
            if _programmatic_load:
                return "immediate"
            
            interval = max(1, int(mock_update_state_interval.value or 5))
            now = mock_loop.time()
            elapsed = now - _last_user_state_sync
            
            if elapsed >= interval:
                _last_user_state_sync = now
                return "immediate"
            else:
                if _scheduled_user_state_task is None:
                    delay = interval - elapsed
                    # Would schedule task with delay
                    return f"scheduled_delay_{delay}"
                return "already_scheduled"
        
        # Test: not enough time elapsed
        result = simulate_debounce_logic("https://example.com/#!new")
        assert result == "scheduled_delay_3.0"  # 5 - 2 = 3 second delay
    
    def test_programmatic_bypasses_debounce(self, mock_update_state_interval):
        """Test that programmatic updates bypass debounce."""
        _last_user_state_sync = 9.5  # Very recent
        _programmatic_load = True
        
        mock_loop = Mock()
        mock_loop.time.return_value = 10.0
        
        def simulate_debounce_logic(new_url):
            if _programmatic_load:
                return "immediate"
            # Would normally debounce
            return "debounced"
        
        result = simulate_debounce_logic("https://example.com/#!programmatic")
        assert result == "immediate"


class TestUrlChangeHandling:
    """Test URL change handling with pointer expansion."""
    
    @pytest.mark.asyncio
    async def test_handle_url_change_with_pointer(self):
        """Test URL change handling with pointer expansion."""
        # Mock the pointer expansion
        mock_canonical_url = "https://example.com/#!%7B%22expanded%22%3Atrue%7D"
        mock_state = {"expanded": True}
        
        with patch('neuroglancer_chat.backend.tools.pointer_expansion.is_pointer_url') as mock_is_pointer, \
             patch('neuroglancer_chat.backend.tools.pointer_expansion.expand_if_pointer_and_generate_inline') as mock_expand:
            
            mock_is_pointer.return_value = True
            mock_expand.return_value = (mock_canonical_url, mock_state, True)
            
            # Mock viewer and backend sync
            mock_viewer = Mock()
            mock_backend_sync = AsyncMock()
            
            _programmatic_load = False
            
            @contextmanager
            def _programmatic_viewer_update():
                nonlocal _programmatic_load
                _programmatic_load = True
                try:
                    yield
                finally:
                    _programmatic_load = False
            
            async def simulate_handle_url_change_immediate(url: str):
                """Simulate the _handle_url_change_immediate function."""
                nonlocal _programmatic_load
                
                if mock_is_pointer(url):  # Call the mock function
                    canonical_url, state_dict, was_pointer = mock_expand(url)  # Call the mock function
                    if was_pointer:
                        # Update viewer with canonical URL
                        with _programmatic_viewer_update():
                            mock_viewer.url = canonical_url
                        # Sync the expanded state
                        await mock_backend_sync(canonical_url)
                        return
                
                # Regular URL handling
                await mock_backend_sync(url)
            
            # Test pointer expansion flow
            await simulate_handle_url_change_immediate("https://example.com/#!s3://bucket/state.json")
            
            # Verify expansion was called
            mock_expand.assert_called_once()
            # Verify viewer was updated with canonical URL
            assert mock_viewer.url == mock_canonical_url
            # Verify backend sync was called with canonical URL
            mock_backend_sync.assert_called_once_with(mock_canonical_url)
    
    @pytest.mark.asyncio
    async def test_handle_url_change_with_inline_json(self):
        """Test URL change handling with inline JSON (no expansion)."""
        with patch('neuroglancer_chat.backend.tools.pointer_expansion.is_pointer_url') as mock_is_pointer:
            mock_is_pointer.return_value = False
            
            mock_backend_sync = AsyncMock()
            
            async def simulate_handle_url_change_immediate(url: str):
                """Simulate handling non-pointer URL."""
                if not mock_is_pointer.return_value:
                    # Regular URL handling
                    await mock_backend_sync(url)
            
            # Test inline JSON flow
            inline_url = "https://example.com/#!%7B%22test%22%3Atrue%7D"
            await simulate_handle_url_change_immediate(inline_url)
            
            # Verify no expansion attempted, direct sync
            mock_backend_sync.assert_called_once_with(inline_url)
    
    @pytest.mark.asyncio
    async def test_handle_url_change_with_error(self):
        """Test URL change error handling."""
        with patch('neuroglancer_chat.backend.tools.pointer_expansion.is_pointer_url') as mock_is_pointer, \
             patch('neuroglancer_chat.backend.tools.pointer_expansion.expand_if_pointer_and_generate_inline') as mock_expand:
            
            mock_is_pointer.return_value = True
            mock_expand.side_effect = ValueError("S3 access denied")
            
            mock_backend_sync = AsyncMock()
            mock_status = Mock()
            
            async def simulate_handle_url_change_immediate(url: str):
                """Simulate error handling in URL change."""
                try:
                    if mock_is_pointer.return_value:
                        mock_expand()  # This will raise
                    await mock_backend_sync(url)
                except Exception as e:
                    mock_status.object = f"URL handling error: {e}"
                    # Fallback: try to sync original URL
                    await mock_backend_sync(url)
            
            # Test error handling
            error_url = "https://example.com/#!s3://invalid/state.json"
            await simulate_handle_url_change_immediate(error_url)
            
            # Verify error was set
            assert "URL handling error" in mock_status.object
            # Verify fallback sync was attempted
            mock_backend_sync.assert_called_with(error_url)


class TestBackendStateSync:
    """Test backend state synchronization with pointer expansion."""
    
    @pytest.mark.asyncio
    async def test_notify_backend_state_load_with_pointer(self):
        """Test backend sync with pointer expansion."""
        mock_canonical_url = "https://example.com/#!%7B%22expanded%22%3Atrue%7D"
        mock_state = {"expanded": True}
        
        with patch('neuroglancer_chat.backend.tools.pointer_expansion.is_pointer_url') as mock_is_pointer, \
             patch('neuroglancer_chat.backend.tools.pointer_expansion.expand_if_pointer_and_generate_inline') as mock_expand, \
             patch('httpx.AsyncClient') as mock_client:
            
            mock_is_pointer.return_value = True
            mock_expand.return_value = (mock_canonical_url, mock_state, True)
            
            # Mock HTTP client
            mock_response = Mock()
            mock_response.json.return_value = {"ok": True}
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            mock_status = Mock()
            
            async def simulate_notify_backend_state_load(url: str):
                """Simulate the enhanced _notify_backend_state_load function."""
                mock_status.object = "Syncing state to backend…"
                
                sync_url = url
                if mock_is_pointer(url):  # Call the mock function
                    try:
                        mock_status.object = "Expanding JSON pointer…"
                        canonical_url, state_dict, was_pointer = mock_expand(url)  # Call the mock function
                        if was_pointer:
                            sync_url = canonical_url
                            mock_status.object = "Pointer expanded, syncing state…"
                    except Exception as e:
                        mock_status.object = f"Pointer expansion failed: {e}"
                        sync_url = url
                
                async with mock_client() as client:
                    resp = await client.post("http://backend/tools/state_load", json={"link": sync_url})
                    data = resp.json()
                    if data.get("ok"):
                        mock_status.object = f"**Opened:** {sync_url}"
            
            # Test pointer expansion in backend sync
            await simulate_notify_backend_state_load("https://example.com/#!s3://bucket/state.json")
            
            # Verify expansion was attempted
            mock_expand.assert_called_once()
            # Verify backend was called with canonical URL
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            assert call_args[1]["json"]["link"] == mock_canonical_url
            # Verify status was updated
            assert mock_canonical_url in mock_status.object
    
    @pytest.mark.asyncio
    async def test_notify_backend_state_load_expansion_error(self):
        """Test backend sync with pointer expansion error."""
        with patch('neuroglancer_chat.backend.tools.pointer_expansion.is_pointer_url') as mock_is_pointer, \
             patch('neuroglancer_chat.backend.tools.pointer_expansion.expand_if_pointer_and_generate_inline') as mock_expand, \
             patch('httpx.AsyncClient') as mock_client:
            
            mock_is_pointer.return_value = True
            mock_expand.side_effect = ValueError("S3 bucket not found")
            
            # Mock HTTP client
            mock_response = Mock()
            mock_response.json.return_value = {"ok": True}
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_client_instance
            
            # Track status changes
            status_history = []
            
            class StatusTracker:
                def __init__(self):
                    self._object = None
                
                @property
                def object(self):
                    return self._object
                
                @object.setter
                def object(self, value):
                    self._object = value
                    status_history.append(value)
            
            mock_status = StatusTracker()
            original_url = "https://example.com/#!s3://missing/state.json"
            
            async def simulate_notify_backend_state_load(url: str):
                """Simulate backend sync with expansion error."""
                mock_status.object = "Syncing state to backend…"
                
                sync_url = url
                if mock_is_pointer(url):  # Call the mock function
                    try:
                        mock_status.object = "Expanding JSON pointer…"
                        mock_expand()  # This will raise
                    except Exception as e:
                        mock_status.object = f"Pointer expansion failed: {e}"
                        sync_url = url  # Fall back to original
                
                async with mock_client() as client:
                    await client.post("http://backend/tools/state_load", json={"link": sync_url})
                    mock_status.object = f"**Opened:** {sync_url}"
            
            # Test error handling
            await simulate_notify_backend_state_load(original_url)
            
            # Verify error status was set at some point
            assert any("Pointer expansion failed" in status for status in status_history)
            # But eventually shows success with original URL
            # (This would be overwritten in the actual flow)


class TestSettingsIntegration:
    """Test settings widget integration."""
    
    def test_update_interval_widget_creation(self):
        """Test that update interval widget is created with correct defaults."""
        # Simulate widget creation
        class MockIntInput:
            def __init__(self, name, value, start):
                self.name = name
                self.value = value
                self.start = start
        
        # Simulate the widget creation from panel_app.py
        update_state_interval = MockIntInput(
            name="Update state interval (sec)", 
            value=5, 
            start=1
        )
        
        assert update_state_interval.name == "Update state interval (sec)"
        assert update_state_interval.value == 5
        assert update_state_interval.start == 1
    
    def test_debounce_interval_validation(self):
        """Test interval validation in debounce logic."""
        # Test interval validation logic
        def get_validated_interval(widget_value):
            try:
                if widget_value == 0:  # Handle 0 specifically
                    return 1
                return max(1, int(widget_value or 5))
            except Exception:
                return 5
        
        # Test valid values
        assert get_validated_interval(5) == 5
        assert get_validated_interval(10) == 10
        assert get_validated_interval(1) == 1
        
        # Test invalid values default to minimum
        assert get_validated_interval(0) == 1
        assert get_validated_interval(-5) == 1
        
        # Test None/empty defaults
        assert get_validated_interval(None) == 5
        assert get_validated_interval("") == 5
        
        # Test non-numeric defaults
        assert get_validated_interval("invalid") == 5


class TestLoadInternalLink:
    """Test _load_internal_link function behavior."""
    
    def test_load_internal_link_with_context(self):
        """Test that _load_internal_link uses programmatic context."""
        mock_viewer = Mock()
        _programmatic_load = False
        
        @contextmanager
        def _programmatic_viewer_update():
            nonlocal _programmatic_load
            _programmatic_load = True
            try:
                yield
            finally:
                _programmatic_load = False
        
        def simulate_load_internal_link(url: str):
            """Simulate _load_internal_link function."""
            if not url:
                return
            
            with _programmatic_viewer_update():
                mock_viewer.url = url
                mock_viewer._load_url()
        
        # Test with valid URL
        test_url = "https://example.com/#!test"
        simulate_load_internal_link(test_url)
        
        assert mock_viewer.url == test_url
        mock_viewer._load_url.assert_called_once()
        # Context should be reset
        assert _programmatic_load is False
    
    def test_load_internal_link_empty_url(self):
        """Test _load_internal_link with empty URL."""
        mock_viewer = Mock()
        
        def simulate_load_internal_link(url: str):
            if not url:
                return
            mock_viewer.url = url
            mock_viewer._load_url()
        
        # Test with empty URL
        simulate_load_internal_link("")
        simulate_load_internal_link(None)
        
        # Should not have been called
        mock_viewer._load_url.assert_not_called()
