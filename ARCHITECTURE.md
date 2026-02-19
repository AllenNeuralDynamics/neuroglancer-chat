# neuroglancer-chat Architecture

Chat-driven navigation of massive neuroimaging data in Neuroglancer, plus lightweight in-session analysis of user-supplied tabular data (CSVs). The LLM acts as an orchestrator: it interprets user intent, selects tools, and the backend executes state mutations and data operations.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (Panel)                                    │
│  panel_app.py                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  Chat UI     │  │ Neuroglancer │  │  Workspace   │                      │
│  │  Interface   │  │    Viewer    │  │    Tabs      │                      │
│  │ • Streaming  │  │ • 3D Viewer  │  │ • Results    │                      │
│  │ • Messages   │  │ • URL Sync   │  │ • Data Upload│                      │
│  │ • User Input │  │ • Debouncing │  │ • Tables     │                      │
│  │              │  │ • Auto-load  │  │ • Plots      │                      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                      │
│         └──────────────────┴──────────────────┘                              │
│                            │ HTTP / SSE                                      │
└────────────────────────────┼─────────────────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (FastAPI)                                   │
│  main.py                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  Agent Loop  │  │  Endpoints   │  │  State Sync  │                      │
│  │ • Streaming  │  │ /agent/chat  │  │ • state_load │                      │
│  │ • Non-stream │  │ /agent/chat/ │  │ • state_save │                      │
│  │ • Tool exec  │  │   stream     │  │ • URL gen    │                      │
│  │ • max 10 iter│  │ /tools/*     │  │              │                      │
│  └──────┬───────┘  └──────────────┘  └──────────────┘                      │
│         ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  TOOL DISPATCHER — routes calls, tracks mutations, aggregates resp  │    │
│  └─────────────────────────────┬───────────────────────────────────────┘    │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            TOOL MODULES                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │ Neuroglancer     │  │ Data Tools       │  │ Plot Tools       │          │
│  │ neuroglancer_    │  │ io.py            │  │ plots.py /       │          │
│  │ state.py         │  │ • data_query_    │  │ plotting.py      │          │
│  │ • ng_set_view    │  │   polars         │  │ • data_plot      │          │
│  │ • ng_set_lut     │  │ • data_ng_views_ │  │ • scatter/line/  │          │
│  │ • ng_add_layer   │  │   table          │  │   bar/heatmap    │          │
│  │ • ng_annotations │  │ • data_ng_annot_ │  │                  │          │
│  │ • ng_set_layer_  │  │   ations_from_   │  │                  │          │
│  │   visibility     │  │   data           │  │                  │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STORAGE & STATE                                      │
│  storage/data.py — DataMemory                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                      │
│  │  Files       │  │  Summaries   │  │  Plots       │                      │
│  │ • CSV files  │  │ • Query res  │  │ • PlotRecord │                      │
│  │ • Polars DF  │  │ • LRU evict  │  │ • Plot specs │                      │
│  └──────────────┘  └──────────────┘  └──────────────┘                      │
│  storage/states.py — CURRENT_STATE (NeuroglancerState, global)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LLM INTEGRATION                                       │
│  adapters/llm.py — OpenAI function calling                                   │
│  • Tool schemas (JSON)   • System prompts   • Streaming support             │
└─────────────────────────────────────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SUPPORTING UTILITIES                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                │
│  │ Observability  │  │ Pointer Expand │  │  Constants     │                │
│  │ timing.py      │  │ pointer_       │  │ constants.py   │                │
│  │ • JSONL logs   │  │ expansion.py   │  │ • Tool names   │                │
│  │ • /debug/      │  │ • s3/gs/https  │  │ • MUTATING_    │                │
│  │   timing       │  │ • URL expand   │  │   TOOLS set    │                │
│  └────────────────┘  └────────────────┘  └────────────────┘                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### User Query
```
User Input → Panel ChatInterface → POST /agent/chat
  ↓
Backend builds context: system prompt + NG state summary + data context + interaction memory
  ↓
LLM proposes tool calls → Tool Dispatcher executes → tool outputs fed back to LLM
  ↓ (iterates up to 10 times)
Final response: answer + ng_views + query_data + plot_data + mutated flag
  ↓
Frontend: Tabulator tables, hvPlot plots, Neuroglancer state update, Workspace tab
```

### Neuroglancer State Sync
```
User interacts with NG Viewer → viewer.url changes (debounced) → _on_url_change()
  ↓
Pointer expansion (s3://, gs://, https://) if needed
  ↓
POST /tools/state_load → CURRENT_STATE = NeuroglancerState.from_url()
State preserved with dimension order intact (no sort_keys!)
```

### Plot Generation
```
LLM: data_plot tool call with Polars expression
  ↓
Backend: validates data → applies expression → returns plot_kwargs + transformed rows
  ↓
Frontend: creates Polars DataFrame → df.hvplot.scatter/line/bar/heatmap(**plot_kwargs)
  → wrapped in pn.pane.HoloViews() for native Panel rendering
```

### Data Query (with chaining)
```
LLM: data_query_polars → backend executes Polars expression → result auto-saved as summary_id
  ↓
Full data sent to frontend Tabulator; LLM receives only row count + columns + summary_id
  ↓
LLM can chain: data_ng_annotations_from_data(summary_id="query_xyz") → uses saved result
```

## Source Layout

```
src/neuroglancer_chat/
├── backend/
│   ├── main.py                 # FastAPI app, agent loop, tool dispatcher
│   ├── models.py               # Pydantic schemas (Vec3, SetView, ...)
│   ├── adapters/
│   │   └── llm.py              # OpenAI tool-calling adapter, system prompt, streaming
│   ├── tools/
│   │   ├── neuroglancer_state.py  # NeuroglancerState class
│   │   ├── io.py               # CSV ingest, data query, annotation-from-data, views table
│   │   ├── plots.py            # Plot generation and validation
│   │   ├── plotting.py         # Plot rendering utilities
│   │   ├── pointer_expansion.py   # JSON pointer URL expansion
│   │   └── constants.py        # Tool names, MUTATING_TOOLS set
│   ├── storage/
│   │   ├── data.py             # DataMemory (uploads + summaries + LRU eviction)
│   │   └── states.py           # Global CURRENT_STATE
│   └── observability/
│       └── timing.py           # Timing instrumentation (see docs/timing.md)
└── panel/
    └── panel_app.py            # Panel UI (~1500 lines): chat, viewer, workspace, upload
```

## Memory Layer

Three context sources are injected into every LLM request:

1. **System prompt** — tool descriptions, Polars syntax rules, workflow recipes
2. **NG state summary** — current layers, layout, camera position
3. **Data context** — uploaded file metadata + derived summary metadata + recent interaction history

Interaction memory is a rolling window of recent `"User: ..."` / `"Assistant: ..."` strings, trimmed by count and total character cap to keep prompts bounded.

## Tool Surface

### Neuroglancer / State
| Endpoint | Mutating |
|----------|---------|
| `POST /tools/ng_set_view` | Yes |
| `POST /tools/ng_set_lut` | Yes |
| `POST /tools/ng_add_layer` | Yes (idempotent) |
| `POST /tools/ng_set_layer_visibility` | Yes |
| `POST /tools/ng_annotations_add` | Yes |
| `POST /tools/ng_state_summary` | No |
| `POST /tools/ng_state_link` | No |
| `POST /tools/state_save` | Explicit |
| `POST /tools/state_load` / `demo_load` | Yes |

### Data (Polars)
| Endpoint | Description |
|----------|-------------|
| `POST /upload_file` | Multipart CSV upload (validated, size-capped) |
| `POST /tools/data_list_files` | List uploaded file metadata |
| `POST /tools/data_preview` | First N rows |
| `POST /tools/data_info` | Shape, columns, dtypes, sample rows |
| `POST /tools/data_describe` | Numeric stats (stored as summary) |
| `POST /tools/data_select` | Column subset + simple filters |
| `POST /tools/data_query_polars` | Execute arbitrary Polars expressions; auto-saves result |
| `POST /tools/data_sample` | Random row sample (optional seed) |
| `POST /tools/data_list_summaries` | List derived tables |
| `POST /tools/data_plot` | Generate scatter/line/bar/heatmap plot |
| `POST /tools/data_list_plots` | List generated plots |
| `POST /tools/data_ng_views_table` | Ranked rows with per-row NG links |
| `POST /tools/data_ng_annotations_from_data` | Create annotations directly from dataframe rows |

### Debug / Observability
| Endpoint | Description |
|----------|-------------|
| `GET /debug/tool_trace` | Recent full tool execution traces |
| `GET /debug/timing` | Real-time timing data (requires `TIMING_MODE=true`) |
| `GET /debug/test-logging` | Verify debug logging is active |

## Critical Design Patterns

### 1. Dimension Order Preservation
**Problem:** JSON serialization with `sort_keys=True` reordered dimensions (x,y,z,t → t,x,y,z), breaking position array mapping.

**Solution:** Removed `sort_keys=True` from `to_url()` in `neuroglancer_state.py`. Python 3.7+ dict insertion order is guaranteed.

### 2. Native Panel Rendering
**Problem:** HTML serialization of plots caused Bokeh rendering errors.

**Solution:** Backend sends `plot_kwargs` + transformed data rows → Frontend creates DataFrame and renders natively via `pn.pane.HoloViews()`.

### 3. Transformed Data Flow
**Problem:** Frontend was re-fetching untransformed source data after backend applied aggregations.

**Solution:** Backend includes `"data": df.to_dicts()` in `plot_data` response. Frontend uses this directly.

### 4. Debounced State Sync
**Problem:** Rapid NG viewer interactions caused excessive backend calls.

**Solution:** Programmatic vs user-driven updates tracked separately. User updates debounced with configurable interval (default 5s).

### 5. Spatial Navigation
**Problem:** Query results needed clickable navigation to NG coordinates.

**Solution:** Backend generates `ng_views` list with `row_index` + URL. Frontend renders Tabulator with a View button column that calls `_load_internal_link()`.

### 6. Query Result Chaining
**Problem:** LLM cannot see query results (sent to frontend only), so it cannot pass filtered data to annotation tools.

**Solution:** `data_query_polars` auto-saves every result with a `summary_id`. Follow-up tools (`data_ng_annotations_from_data`, `data_plot`) accept `summary_id` to reference the saved result. See [docs/development-notes.md](docs/development-notes.md).

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Global in-process DataMemory (no user scoping) | Introduce session/user keys; TTL or LRU eviction |
| Memory growth with many uploads | 20 MB/file cap; LRU eviction on summaries |
| Prompt bloat from data/interaction context | Hard caps on counts + char trimming |
| Tool mis-selection by LLM | Explicit system rules; non-overlapping tool semantics; workflow recipes |
| Cross-origin embed limitations | Same-origin NG bundle + message channel (planned) |
| Large CSV parse latency | Use `pl.scan_csv` + lazy operations when needed |
| Cloud volume egress cost | Mip-level sampling, ROI bounding, caching |

## Why Not LangChain?

Current scope: small tool surface (<25), single-model orchestration, explicit prompt assembly. A custom adapter keeps dependency and cognitive load low and makes debugging transparent. Re-evaluate when we need multi-step planning loops, tool parallelism, retrieval pipelines, or pluggable memory summarization. The existing `TOOLS` list + system preface builder structure makes migration straightforward.

## Technology Stack

- **Frontend**: Panel, Bokeh, HoloViews, hvPlot, panel-neuroglancer
- **Backend**: FastAPI, Uvicorn
- **Data**: Polars, PyArrow
- **LLM**: OpenAI API with function calling
- **Cloud storage**: boto3 (S3), google-cloud-storage (GCS) — optional
- **Testing**: pytest, httpx
- **Package management**: uv

## Configuration

See [docs/configuration.md](docs/configuration.md) for all environment variables and runtime settings.
