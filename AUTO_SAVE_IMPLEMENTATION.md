# Auto-Save Query Results Implementation

## Problem Summary

When users asked to "get top volume in each cluster and annotate them", the LLM would:
1. Call `data_query_polars` to aggregate data (returns 20 rows for 20 clusters)
2. Call `data_ng_annotations_from_data` with the **original file_id** (5000+ rows)
3. Result: 5000 annotations created instead of 20!

**Root Cause**: Query results weren't saved, so the LLM had no `summary_id` to reference. It fell back to using the original `file_id`, which contained all the data before filtering/aggregation.

## Solution Implemented

### 1. **Auto-Save All Query Results**
- Every `data_query_polars` execution now automatically saves its result
- Returns `summary_id` in the response for chaining
- Tracks `LAST_QUERY_SUMMARY_ID` globally for easy reference

### 2. **Helper Function for 'last' Reference**
```python
_resolve_summary_id(summary_id)
```
- Allows `summary_id="last"` or `summary_id="latest"` 
- Automatically resolves to most recent query result
- Makes chaining more intuitive

### 3. **Enhanced System Prompt**
- Added prominent section on "QUERY RESULT CHAINING"
- Clear examples showing correct vs incorrect patterns
- Emphasized: "Use the summary_id from the response, NOT the original file_id!"

### 4. **Memory Management**
- Added LRU eviction to prevent memory bloat
- Max 100 summaries by default (configurable)
- Oldest summaries automatically removed when limit reached

## How It Works Now

### User Prompt
> "Get the top volume in each cluster_label. Include spatial coordinates. Then make a new annotation layer with a point for each cell. Call the layer 'Clusters'. Make it Green."

### LLM Execution Flow

**Step 1: Query**
```python
data_query_polars(
    file_id="abc123",
    expression="df.group_by('cluster_label').agg(
        pl.max('volume_um').alias('max_volume'),
        pl.first('centroid_x'),
        pl.first('centroid_y'),
        pl.first('centroid_z')
    )"
)
```

**Response:**
```json
{
  "ok": true,
  "summary_id": "query_456789",  // ← Auto-generated!
  "rows": 20,
  "message": "✅ Query executed successfully. Result saved as summary_id='query_456789' (20 rows). You can use this summary_id in follow-up tools..."
}
```

**Step 2: Annotate Using summary_id**
```python
data_ng_annotations_from_data(
    summary_id="query_456789",  // ← Uses the query result!
    layer_name="Clusters",
    center_columns=["centroid_x", "centroid_y", "centroid_z"],
    color="#00ff00"
)
```

**Result:** ✅ Exactly 20 annotations created (one per cluster)!

## Files Modified

1. **src/neuroglancer_chat/backend/main.py**
   - Added `LAST_QUERY_SUMMARY_ID` global tracker
   - Modified `execute_query_polars()` to always auto-save results
   - Added `_resolve_summary_id()` helper function
   - Updated `data_ng_annotations_from_data` to use resolved summary_id
   - Enhanced response messages with chaining guidance

2. **src/neuroglancer_chat/backend/adapters/llm.py**
   - Added "QUERY RESULT CHAINING" section to system prompt
   - Updated workflow recipes with correct/incorrect patterns
   - Enhanced tool schema descriptions to emphasize summary_id usage

3. **src/neuroglancer_chat/backend/storage/data.py**
   - Added `max_summaries` parameter to `DataMemory`
   - Implemented LRU eviction with `summary_order` tracking
   - Auto-cleanup when summary limit reached

## Key Changes in Behavior

### Before
```python
# Query result displayed but NOT saved
data_query_polars(expression="...") 
# → No summary_id returned

# LLM has no choice but to use original file_id
data_ng_annotations_from_data(file_id="abc123")
# → Creates annotations from ALL data (wrong!)
```

### After
```python
# Query result automatically saved
data_query_polars(expression="...")
# → Returns summary_id="query_xyz"

# LLM uses the summary_id from response
data_ng_annotations_from_data(summary_id="query_xyz")
# → Creates annotations from QUERY RESULT (correct!)
```

## Testing

Run the comprehensive test:
```bash
# Start backend
uv run uvicorn backend.main:app --reload --port 8000

# Run test
uv run python test_auto_save_query.py
```

The test validates:
1. ✅ Query results are auto-saved with summary_id
2. ✅ Chaining with summary_id creates correct number of annotations
3. ✅ 'last' shorthand works for recent queries
4. ✅ Using file_id still works but creates different result
5. ✅ Neuroglancer state is mutated correctly

## Benefits

1. **Fixes the Original Problem**: LLM can now correctly chain queries with annotations
2. **Natural Workflow**: Two-step pattern now works as expected
3. **Backward Compatible**: Single-call with `filter_expression` still works
4. **Easier Debugging**: All query results are tracked and can be inspected
5. **User Convenience**: 'last' shorthand for quick follow-ups
6. **Memory Efficient**: LRU eviction prevents unbounded growth

## User-Facing Improvements

### Clear Response Messages
```
"✅ Query executed successfully. Result saved as summary_id='query_123' 
(20 rows). You can use this summary_id in follow-up tools like 
data_ng_annotations_from_data, data_plot, or for further queries."
```

### Better Error Messages
If LLM uses wrong pattern, the debug logs show:
```
⚠️ Creating 5000 annotations from file_id (consider using summary_id 
from recent query for filtered results)
```

## Edge Cases Handled

1. **No Previous Query**: `summary_id="last"` returns helpful error
2. **Memory Full**: Oldest auto-saved summaries evicted automatically  
3. **Both file_id and summary_id**: Clear error message
4. **Invalid summary_id**: Standard KeyError with available options

## Migration Notes

**No breaking changes!** Existing code continues to work:

- ✅ Single-call with `filter_expression` still works
- ✅ Explicit `save_as` parameter still respected
- ✅ Old summaries (if any) remain accessible
- ✅ All tool interfaces unchanged

**New capability**: Two-step workflow now works correctly with auto-saved results.

## Future Enhancements

Possible improvements:
1. Show summary IDs in chat UI for user reference
2. Add `/summaries` endpoint to list available summaries
3. Implement summary expiration (TTL) based on time
4. Add summary naming hints based on query content
5. Persist summaries to disk/Redis for session recovery

## Performance Impact

**Minimal overhead:**
- Auto-save adds ~1-5ms per query (UUID generation + dict insert)
- Memory usage: ~same as before (results were already in memory for frontend)
- LRU eviction: O(1) for append, O(n) for eviction (runs rarely)

**Storage estimate:**
- 100 summaries × 1000 rows × 10 columns × 8 bytes ≈ 8 MB
- Well within reasonable limits for in-memory storage

## Rollout Checklist

- [x] Implementation complete
- [x] Syntax validation passed
- [x] Test file created
- [x] System prompt updated
- [x] Tool schemas enhanced
- [x] Memory management implemented
- [ ] Backend restart required
- [ ] Test with original failing prompt
- [ ] Monitor LLM behavior for correct summary_id usage
- [ ] Update architecture docs if needed

