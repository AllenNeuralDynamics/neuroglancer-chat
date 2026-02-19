# Development Notes

Reference material for developers: architectural decision records, known gotchas, and test prompts.

---

## Query Result Chaining (`summary_id` pattern)

### Why it exists

`data_query_polars` sends results to the frontend (Tabulator table) — the LLM never receives the actual data values. Without a chaining mechanism, the LLM has no way to pass query results to follow-up tools like `data_ng_annotations_from_data`.

**Before (broken):**
```
data_query_polars(expression="df.group_by(...)") → 20 rows sent to frontend
data_ng_annotations_from_data(file_id="abc123")  → uses ALL 5000 rows!
```

**After (correct):**
```
data_query_polars(expression="df.group_by(...)") → returns summary_id="query_456"
data_ng_annotations_from_data(summary_id="query_456") → uses the 20-row result
```

### How it works

- Every `data_query_polars` call auto-saves its result and returns a `summary_id`
- `summary_id="last"` or `summary_id="latest"` resolve to the most recent query
- `_resolve_summary_id()` in `backend/main.py` handles resolution
- LRU eviction (max 100 summaries) prevents memory bloat
- Both `file_id` and `summary_id` are accepted; providing both returns an error

### Memory estimate
100 summaries × 1000 rows × 10 columns × 8 bytes ≈ 8 MB — well within limits.

---

## Annotation Tool: `data_ng_annotations_from_data`

### Why it exists

The two-step pattern `data_query_polars` → `ng_annotations_add` is **fundamentally broken**: after a query, the LLM doesn't have the coordinate values to pass to `ng_annotations_add`. This caused the LLM to use dummy `(0,0,0)` coordinates.

`data_ng_annotations_from_data` fixes this by executing the query and creating annotations in one backend call.

**Data flow:**
```
User: "Add points for top cells per cluster"
  ↓
LLM: data_ng_annotations_from_data(filter_expression="df.group_by(...)")
  ↓
Backend: loads dataframe → applies filter → extracts coords → adds to CURRENT_STATE
  ↓
Frontend: auto-loads updated state with annotations
```

### Key parameters
- `file_id` or `summary_id`: source data (use `summary_id` after a prior query)
- `layer_name`: annotation layer (created if absent)
- `center_columns`: coordinate columns (default: `["x", "y", "z"]`)
- `filter_expression`: optional Polars expression to transform/filter first
- `color`: hex color string
- `limit`: max annotations (default 1000, max 5000)

---

## Neuroglancer Annotation JSON Schema

Ground-truth schema verified against a manual Neuroglancer annotation:

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
      "point": [4998.87, 6216.5, 1175.07],
      "type": "point",
      "id": "bb79d5acc705a03fad2cc116a192df2c8a41e249"
    }
  ],
  "name": "MyLayer"
}
```

**Critical structural rules:**
- `annotations` array is at the **layer level**, not inside `source`
- `source` is `{"url": "local://annotations"}` — not `{type: "pointAnnotation", points: [...]}`
- Each annotation item **must** have a `type` field (`"point"`, `"box"`, or `"ellipsoid"`)
- Layer metadata fields `tool`, `tab`, and `annotationColor` are required for proper UI integration

---

## Polars Syntax Reference (vs pandas)

Common LLM mistakes when generating Polars expressions:

| Operation | Wrong (pandas) | Correct (Polars) |
|-----------|---------------|-----------------|
| Group by | `df.groupby('col')` | `df.group_by('col')` |
| Sort descending | `.sort(reverse=True)` | `.sort(descending=True)` |
| Column max | `df['col'].max()` | `df.select(pl.max('col'))` |
| Filter | `df[df['col'] > 5]` | `df.filter(pl.col('col') > 5)` |

When a `filter_expression` fails, test it first with `data_query_polars` to validate syntax before using in `data_ng_annotations_from_data`.

---

## Debug Logging

Test that the backend debug logging endpoint is working:

```powershell
# Full JSON output
Invoke-WebRequest -Uri http://127.0.0.1:8000/debug/test-logging | Select-Object -ExpandProperty Content | ConvertFrom-Json | ConvertTo-Json

# Quick check
curl http://127.0.0.1:8000/debug/test-logging
```

You should see four log lines in the backend console: DEBUG, INFO, WARNING, and `_dbg()` from the test endpoint.

---

## Test Prompts

### Basic navigation
```
What are the unique values in the cluster_labels column?
Can you give me all the Pvalb clusters?
```

### Plotting
```
Sample 20 cells and scatter log_volume vs elongation
```

### Annotation — basic
```
Please add a new annotation layer "a1" with a point at the current camera position.
```

### Annotation — from query
```
Can you get the top log_volume in each cluster_label. Include spatial coordinates.
Then make a new annotation layer with a point for each cell. Call the layer "Clusters". Make it Green.
```

### Annotation — batch by gene
```
Identify unique genes. Then for cell 74330 make a new layer for each gene
(name it for the gene), random color, and plot xyz locations of the spots.
```

### Data queries
```
In the CSV, group_by cell_id and get the Sst cell with highest spot count.

Please make a scatter plot of dist and r columns for gene = Vip,
from the coregistered cells table.
```

### Multi-step spot workflow
```
Make an annotation layer "cell_spots".
Query the CSV for cell_id = 74330 and chan = 638, include spatial cols x y z.
Add annotation points for each location in the query.
```

### LUT control
```
Can you set the LUT to 90-600 for all image layers (but not the Cck layer)?
```
