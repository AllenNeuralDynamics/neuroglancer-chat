# Features TODO

## Phase 3: Streaming Chat Parity Enhancements

**Goal:** Bring streaming chat handler to feature parity with non-streaming handler to provide better UX and eventually deprecate non-streaming mode.

**Status:** Not started (blocked on Phase 1 & 2 completion)

### Background

Currently, the streaming chat mode (`USE_STREAMING=true`) provides a better user experience with real-time token-by-token response streaming, but lacks several sophisticated features that only exist in the non-streaming mode:

- Direct rendering of structured `query_data` → Tabulator widgets
- Native plot rendering from `plot_data` (hvplot integration)  
- "Add to Workspace" buttons with closures for queries and plots
- Polars expression display in code blocks
- Smart filtering of LLM responses (removing code blocks, data dumps)
- Conditional table display based on `show_query_tables` setting
- Multi-view table rendering with clickable links

### Implementation Plan

#### 3.1 Backend Changes (FastAPI `/agent/chat/stream`)

**Add new SSE event types** to stream structured data alongside text:

```python
# Current event types:
# - content (delta text)
# - tool_start (tool name)
# - final (mutated flag, state_link)
# - error (error message)
# - complete (end of stream)

# New event types to add:
{
    "type": "query_data",
    "data": {
        "data": {...},        # Dict of lists (DataFrame columns)
        "columns": [...],     # Column names
        "rows": 100,          # Row count
        "expression": "...",  # Polars expression used
        "ng_views": [...]     # Optional spatial view data
    }
}

{
    "type": "plot_data",
    "data": {
        "plot_type": "scatter",
        "plot_kwargs": {...},
        "data": [...],           # Transformed data rows
        "expression": "...",     # Polars expression
        "is_interactive": true,
        "row_count": 150
    }
}

{
    "type": "ng_views",
    "data": {
        "rows": [...],        # View table rows with links
        "warnings": [...],    # Any generation warnings
        "first_link": "..."   # First view URL for auto-load
    }
}
```

**Changes required in `backend/main.py`:**

1. After tool execution loop completes, check if `query_data` or `plot_data` exist in result
2. Emit appropriate SSE events before the `final` event
3. Ensure data is JSON-serializable (convert DataFrames to dicts)

#### 3.2 Frontend Changes (`panel_app.py`)

**Enhance `respond_streaming()` to accumulate and render structured data:**

```python
async def respond_streaming(contents: str, user: str, **kwargs):
    """Handle streaming chat with full feature parity."""
    
    accumulated_message = ""
    tool_names = []
    mutated = False
    state_link = None
    query_data = None      # NEW: Accumulate query data
    plot_data = None       # NEW: Accumulate plot data
    ng_views_data = None   # NEW: Accumulate multi-view data
    has_yielded = False
    
    async with httpx.AsyncClient(timeout=120) as client:
        # ... SSE streaming loop ...
        
        if event_type == "query_data":
            query_data = event.get("data")
            # Don't yield yet - wait for content or final
        
        elif event_type == "plot_data":
            plot_data = event.get("data")
            # Don't yield yet - wait for content or final
        
        elif event_type == "ng_views":
            ng_views_data = event.get("data")
            # Auto-load first view if enabled
            if ng_views_data and ng_views_data.get("first_link"):
                # ... auto-load logic ...
    
    # After stream completes, render final structured components
    if query_data:
        # Use existing helper functions from Phase 1
        tabulator_widget = _create_tabulator_from_query_data(query_data)
        workspace_button = _create_workspace_button_for_query(query_data)
        components = _build_query_result_components(
            accumulated_message, 
            query_data.get("expression", ""),
            tabulator_widget, 
            workspace_button
        )
        yield pn.Column(*components, sizing_mode="stretch_width")
    
    elif plot_data:
        # Render plot using helper functions
        # ... similar to non-streaming implementation ...
    
    elif ng_views_data:
        # Render multi-view table
        # ... similar to non-streaming implementation ...
    
    else:
        # Fallback to text-only response
        yield accumulated_message or "(no response)"
```

**Key changes:**
- Add state variables to accumulate `query_data`, `plot_data`, `ng_views_data`
- Handle new SSE event types without yielding immediately
- After stream completes, use Phase 1 helper functions to render final components
- Reuse workspace button creation and component building logic

#### 3.3 Testing Strategy

**Backend tests (`test_streaming.py` - new file):**
- Test new SSE event emission for query tools
- Test new SSE event emission for plot tools  
- Test new SSE event emission for multi-view tools
- Verify event order (content → structured data → final → complete)
- Test error handling (malformed data in events)

**Frontend integration tests:**
- Mock SSE stream with query_data events → verify Tabulator rendering
- Mock SSE stream with plot_data events → verify plot rendering
- Mock SSE stream with ng_views events → verify view table rendering
- Verify workspace buttons work correctly in streaming mode
- Test `show_query_tables` setting affects streaming responses
- Compare streaming vs non-streaming output for same query

**Manual testing checklist:**
- [ ] Enable streaming: `USE_STREAMING=true`
- [ ] Run query that generates table → verify Tabulator appears with "Add to Workspace" button
- [ ] Run query that generates plot → verify plot appears with workspace button
- [ ] Run spatial query with views → verify view table appears with clickable links
- [ ] Test workspace button clicks → verify items added to workspace correctly
- [ ] Toggle `show_query_tables` setting → verify behavior matches non-streaming
- [ ] Compare UX side-by-side with non-streaming mode → verify parity

#### 3.4 Migration Path

**Step 1:** Backend SSE events (deploy, test with frontend fallback)
- Add new event types to `/agent/chat/stream` endpoint
- Frontend initially ignores new events (no breaking changes)
- Test that existing streaming still works

**Step 2:** Frontend structured data handling (deploy, test)
- Update `respond_streaming()` to handle new events
- Use Phase 1 helper functions for rendering
- Test feature parity with non-streaming

**Step 3:** Documentation & default mode switch
- Update README to recommend streaming mode
- Change `USE_STREAMING` default to `true` in `.env.example`
- Document non-streaming as legacy fallback

**Step 4:** Deprecation (future)
- Mark non-streaming as deprecated
- Remove after confidence in streaming stability
- Simplify codebase by removing `respond_non_streaming()`

### Success Criteria

- [ ] Streaming mode can render query tables with workspace buttons
- [ ] Streaming mode can render plots with workspace buttons  
- [ ] Streaming mode can render multi-view tables with clickable links
- [ ] All Phase 1 helper functions work correctly in streaming context
- [ ] Manual testing confirms UX is equivalent or better than non-streaming
- [ ] Integration tests pass for both modes
- [ ] Performance is acceptable (no significant latency increase)

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| SSE event ordering issues | Add sequence numbers to events; buffer and sort if needed |
| Large data payloads in SSE | Implement size limits; fall back to text-only for huge tables |
| Browser SSE buffer limits | Stream text progressively; accumulate structured data in final event |
| Breaking existing streaming | Deploy backend changes first; frontend gracefully ignores unknown events |
| Increased complexity | Leverage Phase 1 helpers; extensive integration tests |

### Dependencies

- **Blocked by:** Phase 1 (helper functions) and Phase 2 (handler separation)
- **Requires:** Backend changes to `/agent/chat/stream` endpoint
- **Optional:** Observability improvements (latency tracking, event metrics)

### Estimated Effort

- Backend changes: ~4 hours
- Frontend changes: ~6 hours  
- Testing: ~4 hours
- Documentation: ~2 hours
- **Total: ~16 hours (2 days)**

### Future Enhancements (Post-Phase 3)

- **Incremental table rendering:** Stream table rows as they're generated
- **Partial plot updates:** Stream plot data points for real-time visualization
- **Progress indicators:** Show tool execution progress during streaming
- **Cancellation support:** Allow users to cancel in-flight streaming requests
- **Retry logic:** Automatic reconnection for dropped SSE connections

---

**Last Updated:** November 1, 2025  
**Status:** Planning complete, awaiting Phase 1 & 2 deployment
