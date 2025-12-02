# Annotation Workflow Improvements

## Summary of Changes

This update addresses the critical issue where the LLM was unable to create annotations from query results. The problem was that `data_query_polars` sends results to the frontend (not the LLM), making it impossible to chain queries with annotation creation.

## What Was Fixed

### 1. New Tool: `data_ng_annotations_from_data`

**Purpose**: Create Neuroglancer annotations directly from dataframe rows.

**Why It's Needed**: The previous workflow (`data_query_polars` → `ng_annotations_add`) failed because:
- Query results are hidden from the LLM (sent to frontend only)
- The LLM never received the actual coordinate values to pass to `ng_annotations_add`
- This caused the LLM to call `ng_annotations_add` with dummy coordinates (0,0,0)

**How It Works**:
```python
# New workflow (CORRECT):
data_ng_annotations_from_data(
    file_id="12345",
    layer_name="Clusters",
    center_columns=["centroid_x", "centroid_y", "centroid_z"],
    color="#00ff00",
    filter_expression="df.group_by('cluster_label').agg(pl.first('centroid_x'), pl.first('centroid_y'), pl.first('centroid_z'), pl.max('log_volume'))"
)

# Old workflow (BROKEN):
# 1. data_query_polars(expression="...") → LLM doesn't see results!
# 2. ng_annotations_add(items=[...]) → LLM doesn't have coordinates!
```

**Parameters**:
- `file_id` or `summary_id`: Source data (auto-selects most recent if omitted)
- `layer_name`: Name of annotation layer (created if doesn't exist)
- `annotation_type`: "point", "box", or "ellipsoid"
- `center_columns`: Column names for x,y,z coordinates (default: ["x", "y", "z"])
- `size_columns`: For box/ellipsoid types (width, height, depth columns)
- `id_column`: Optional column to use for annotation IDs
- `color`: Hex color like "#00ff00" for green, "#ff0000" for red
- `filter_expression`: Optional Polars expression to transform/filter data first
- `limit`: Max annotations to create (default: 1000, max: 5000)

### 2. Enhanced System Prompt

#### A. Prominent Polars Syntax Warning Box
Added a visually distinct warning section at the top highlighting common errors:

```
═══════════════════════════════════════════════════════════════════════
🚨 POLARS SYNTAX - CRITICAL DIFFERENCES FROM PANDAS 🚨
═══════════════════════════════════════════════════════════════════════

❌ WRONG (pandas):          ✅ CORRECT (Polars):
   df.groupby('col')            df.group_by('col')         [underscore!]
   .sort(reverse=True)          .sort(descending=True)     [different param!]
   df['col'].max()              df.select(pl.max('col'))   [use pl functions!]
```

This makes syntax differences impossible to miss.

#### B. Workflow Recipe Book
Added concrete examples for common tasks:

**Recipe 1: Add Annotation Points from Data**
```
✅ CORRECT: Use data_ng_annotations_from_data directly
❌ WRONG: Don't use data_query_polars + ng_annotations_add
```

**Recipe 2: Get Top N by Metric**
Shows correct Polars aggregation syntax with spatial columns included.

**Recipe 3: Interactive View Table**
Explains when to use `data_ng_views_table` for clickable link tables.

### 3. Updated Constants
Added `data_ng_annotations_from_data` to the `MUTATING_TOOLS` set so the system correctly tracks state changes.

## User Prompt That Previously Failed

**Original Prompt:**
> "Can you get the top_volume in each cluster_label. include spatial coordinates. Then make a new annotation layer with a point for each cell. Call the layer "Clusters". Make it Green."

**What Happened Before:**
1. LLM tried multiple Polars queries with syntax errors (groupby vs group_by, reverse vs descending)
2. Eventually succeeded at querying the data
3. Called `ng_annotations_add` twice with dummy coordinates (0,0,0)
4. No actual annotations were created at the correct locations

**What Happens Now:**
The LLM will:
1. Recognize this as a "create annotations from data" workflow
2. Call `data_ng_annotations_from_data` with:
   - `filter_expression`: The Polars query to get top volume per cluster
   - `layer_name`: "Clusters"
   - `color`: "#00ff00"
   - `center_columns`: ["centroid_x", "centroid_y", "centroid_z"]
3. The tool executes the query internally and creates annotations in one step
4. Actual annotation points appear at the correct coordinates

## Testing

Run the test script:
```bash
# Start the backend first
uv run uvicorn backend.main:app --reload --port 8000

# In another terminal, run the test
uv run python test_annotations_from_data.py
```

The test validates:
- Basic annotation creation from all rows
- Filtered annotation creation using group_by aggregation
- Layer creation with custom colors
- Multiple annotation layers

## Example Chat Interactions

### Example 1: Simple Points
**User:** "Add annotation points for all cells in the dataset. Make them blue."

**LLM Response:**
```
Calling data_ng_annotations_from_data(
    layer_name="cells",
    color="#0000ff",
    center_columns=["centroid_x", "centroid_y", "centroid_z"]
)
```

### Example 2: Filtered Points
**User:** "Show me the largest cell in each cluster as red points."

**LLM Response:**
```
Calling data_ng_annotations_from_data(
    layer_name="top_cells",
    color="#ff0000",
    center_columns=["centroid_x", "centroid_y", "centroid_z"],
    filter_expression="df.group_by('cluster_label').agg(
        pl.first('centroid_x'),
        pl.first('centroid_y'),
        pl.first('centroid_z'),
        pl.first('cell_id'),
        pl.max('log_volume')
    )"
)
```

### Example 3: Conditional Points
**User:** "Add green points for cells where elongation > 0.8."

**LLM Response:**
```
Calling data_ng_annotations_from_data(
    layer_name="elongated_cells",
    color="#00ff00",
    center_columns=["centroid_x", "centroid_y", "centroid_z"],
    filter_expression="df.filter(pl.col('elongation') > 0.8)"
)
```

## Architecture Notes

### Why This Design?
The new tool follows the same pattern as `data_ng_views_table`:
- Accepts both raw data (`file_id`) and derived tables (`summary_id`)
- Supports optional Polars filtering/transformation
- Mutates the Neuroglancer state directly
- Returns clear success/error messages

### Data Flow
```
User: "Add points for top cells per cluster"
  ↓
LLM: Calls data_ng_annotations_from_data with filter_expression
  ↓
Backend: 
  1. Loads dataframe (file_id or summary_id)
  2. Applies filter_expression (if provided)
  3. Extracts coordinates from each row
  4. Creates annotation items
  5. Adds to CURRENT_STATE
  ↓
Frontend: Auto-loads updated state with annotations
```

### Comparison to Old Broken Flow
```
OLD (BROKEN):
User → LLM → data_query_polars → [Results to Frontend only]
                                   LLM never sees data!
     → LLM → ng_annotations_add(dummy coordinates) → ❌ Wrong locations

NEW (WORKING):
User → LLM → data_ng_annotations_from_data(with filter_expression)
           → Backend executes query + creates annotations internally
           → ✅ Correct locations
```

## Files Modified

1. **src/neuroglancer_chat/backend/models.py**
   - Added `NgAnnotationsFromData` Pydantic model

2. **src/neuroglancer_chat/backend/main.py**
   - Added `t_data_ng_annotations_from_data()` endpoint implementation
   - Added dispatcher case for the new tool
   - Added import for new model

3. **src/neuroglancer_chat/backend/adapters/llm.py**
   - Enhanced system prompt with Polars syntax warning box
   - Added workflow recipe book section
   - Added tool schema for `data_ng_annotations_from_data`

4. **src/neuroglancer_chat/backend/tools/constants.py**
   - Added `data_ng_annotations_from_data` to `MUTATING_TOOLS`

## Future Enhancements

Potential improvements for consideration:

1. **Conditional Preview Mode**: Add `preview=True` parameter that returns annotation count/preview without mutating state

2. **Batch Annotations**: Support creating annotations from multiple dataframes in one call

3. **Annotation Styling**: Support per-annotation colors/sizes based on dataframe columns

4. **Validation Preview**: Show a sample of annotations before creating all of them

5. **Query Result Preview**: For queries with `save_as`, optionally include first few rows in LLM response for debugging

## Rollout Checklist

- [x] Implementation complete
- [x] Syntax validation passes
- [x] Test file created
- [ ] Backend server restart with new code
- [ ] Test with original failing prompt
- [ ] Test with edge cases (empty results, missing columns)
- [ ] Monitor LLM tool selection (confirm it chooses new tool)
- [ ] Update main architecture docs if needed

## Migration Guide

If you have existing code or prompts using the old pattern:

**Old Pattern:**
```python
# Step 1: Query (results go to frontend, LLM doesn't see them)
data_query_polars(
    file_id="...",
    expression="df.filter(...)"
)

# Step 2: Try to annotate (LLM doesn't have coordinates!)
ng_annotations_add(
    layer="...",
    items=[...]  # Can't populate this without coordinates!
)
```

**New Pattern:**
```python
# Single call that handles both query and annotation
data_ng_annotations_from_data(
    file_id="...",
    layer_name="...",
    filter_expression="df.filter(...)",  # Same Polars expression
    center_columns=["x", "y", "z"],
    color="#00ff00"
)
```

## Troubleshooting

### "Missing required center columns"
- Check that your dataframe has the coordinate columns
- Default is ["x", "y", "z"], but your data might use ["centroid_x", "centroid_y", "centroid_z"]
- Set `center_columns` parameter explicitly

### "filter_expression failed"
- Verify Polars syntax (use `group_by` not `groupby`, `descending` not `reverse`)
- Ensure expression returns a DataFrame
- Test the expression with `data_query_polars` first

### "No valid annotation items created"
- Check for NaN/null values in coordinate columns
- Verify coordinate columns contain numeric data
- Check the limit parameter (default 1000)

### LLM still uses old pattern
- Clear chat history and start new conversation
- Explicitly mention "use the new annotation tool"
- System prompt changes take effect immediately (no cache warming needed)

