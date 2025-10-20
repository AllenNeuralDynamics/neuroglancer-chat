# Configuration Guide

## SEND_DATA_TO_LLM Flag

**Location:** `src/neurogabber/backend/main.py` (line ~49)

**Purpose:** Controls whether the LLM receives full query data results or minimal acknowledgments.

### Setting: `SEND_DATA_TO_LLM = False` (Recommended)

**Behavior:**
- When `data_query_polars` executes, the LLM receives a minimal acknowledgment:
  ```json
  {
    "ok": true,
    "rows": 20,
    "columns": ["cluster_label", "log_volume", ...],
    "expression": "df.group_by('cluster_label').agg(...)",
    "message": "✅ Query executed successfully. Data is being rendered..."
  }
  ```
- The LLM **cannot** see the actual data values
- The LLM **will not** try to format/summarize data rows
- Full data goes directly to frontend for Tabulator rendering

**LLM Response Example:**
```
Here are the top log_volume per cluster:
```python
df.group_by('cluster_label').agg(pl.max('log_volume'))
```
```

**Benefits:**
- ✅ Clean, concise responses
- ✅ No data summarization/formatting waste
- ✅ Faster LLM responses (less tokens)
- ✅ Expression always visible

---

### Setting: `SEND_DATA_TO_LLM = True` (Original Behavior)

**Behavior:**
- When `data_query_polars` executes, the LLM receives the complete result:
  ```json
  {
    "ok": true,
    "data": [{"cluster_label": "Pvalb-Tac1", "log_volume": 6.90}, ...],
    "rows": 20,
    "columns": [...],
    "expression": "...",
    "ng_views": [...]
  }
  ```
- The LLM **can** see all data values
- The LLM **may** try to format/summarize results
- Useful if you want the LLM to answer follow-up questions about the data

**LLM Response Example:**
```
cluster_label: Pvalb-Tac1-Slc17a7-Reln
cell_id: 36454
log_volume: 6.90
centroid_x: 52
centroid_y: 29
centroid_z: 713
...
```

**Use Cases:**
- You want the LLM to analyze/interpret the data
- You want conversational follow-ups about specific values
- You're debugging query results

---

## How to Toggle

**Option 1: Edit directly in code**
```python
# In src/neurogabber/backend/main.py around line 49
SEND_DATA_TO_LLM = False  # Change to True to send full data
```

**Option 2: Environment variable (future enhancement)**
```bash
# Add to .env file
NEUROGABBER_SEND_DATA_TO_LLM=false
```

---

## What Changed

### Backend (`backend/main.py`)
1. **Added `SEND_DATA_TO_LLM` flag** (line ~49)
2. **Non-streaming path** (line ~536): Checks flag, replaces result with minimal acknowledgment
3. **Streaming path** (line ~357): Checks flag, replaces result with minimal acknowledgment

### Frontend (`panel/panel_app.py`)
1. **Expression always displayed** (line ~760): Extracts `expression` from `query_data` and shows in code block
2. **Smart LLM filtering** (line ~790): Filters out data formatting from LLM responses
3. **Clean component layout**: Expression → Table → Button (expression always visible)

---

## Testing

Run the integration test to verify behavior:
```bash
pytest tests/test_integration_query_with_links.py -v -s
```

With `SEND_DATA_TO_LLM=False`:
- ✅ LLM response should be minimal (just expression + brief context)
- ✅ No data row formatting in LLM output
- ✅ Test passes with clean responses

With `SEND_DATA_TO_LLM=True`:
- ⚠️ LLM may include data summaries
- ⚠️ LLM responses longer
- ✅ LLM can reference specific values
