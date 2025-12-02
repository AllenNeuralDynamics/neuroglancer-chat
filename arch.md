# Neurogabber — Architecture (Enhanced MVP)

Concise overview of the current repo, data flow, in‑memory data/memory model, and roadmap. Updated after adding ephemeral CSV upload support, dataframe tools (Polars), conversational memory, and JSON pointer expansion with debounce functionality.

## Goal
Chat-driven navigation of massive neuroimaging data in **Neuroglancer** plus lightweight in-session analysis of user-supplied tabular data (e.g., ROIs CSV). Start with **state links**, move toward **same-origin embedding**.

## Components
### Backend (FastAPI)
* Tool endpoints mutate Neuroglancer **state JSON**, compute plots, ingest & transform CSV data.
* LLM adapter for **tool-calling** (OpenAI-compatible) — custom lightweight layer (no LangChain yet) with explicit tool schema list.
* In‑memory stores:
  * `CURRENT_STATE` (viewer state JSON)
  * `DataMemory` — uploaded CSVs + derived summary tables (Polars DataFrames) by short IDs
  * `InteractionMemory` — rolling window of recent exchanges (trimmed by count and total chars)

### Frontends
* **Panel**: `ChatInterface` + `panel-neuroglancer` widget; drag‑and‑drop CSV upload; tables of uploaded files & summaries; helper prompt button; conditional auto-load of new Neuroglancer state links; JSON pointer expansion with debounce; configurable update interval (1-∞ seconds, default 5).
* **React/Next.js**: minimal chat prototype (execution orchestration pattern shared).

### Data layer
* Volumes / imagery: S3 **precomputed**; **CloudVolume** calls still stubbed (will power histogram & ROI queries).

### Neuroglancer hosting
* MVP: remote/public NG host via state URLs.
* v1: same-origin NG bundle for stable embed + bidirectional sync (`postMessage`).

### Memory Layer
* Data context = summary of uploaded files (name, size, row/column counts, first few column names) + derived summaries.
* Interaction memory = compact joined strings ("User: ...", "Assistant: ...").
* Injected each request as system messages: system prompt, state summary, data context.
* Truncation ensures bounded prompt size (configurable caps per list/type).

## Repo structure (current)
```
backend/
  main.py                 # FastAPI app, tool & data endpoints, prompt augmentation
  models.py               # Pydantic schemas (Vec3, SetView, ...)
  tools/
    neuroglancer_state.py # NeuroglancerState class (set_view, set_lut, add_layer, set_layer_visibility, add_annotations, clone, to_url/from_url)
    io.py                 # CSV ingest (top_n_rois)
    plots.py              # histogram sampling (stub)
    pointer_expansion.py  # JSON pointer expansion for s3://, gs://, http(s):// URLs
  adapters/
    llm.py                # tool-calling adapter (system prompt + tool schemas)
  storage/
    states.py             # in-memory NG state persistence
    data.py               # DataMemory (uploads/summaries) & InteractionMemory
panel/
  panel_app.py            # ChatInterface + upload UI + embedded Neuroglancer + pointer expansion + debounce
frontend/
  app/
    page.tsx              # minimal chat page
    api/chat/route.ts     # proxy to /agent/chat
tests/
  test_llm_tools.py       # validates exposed tool names
  test_data_tools.py      # covers upload, preview, describe, select flows
  test_pointer_expansion.py # tests JSON pointer expansion functionality
  test_panel_integration.py # tests panel app integration features
```

## JSON Pointer Expansion System

The panel app now includes automatic expansion of JSON pointer URLs that reference external JSON state files. This enables sharing of complex Neuroglancer states via cloud storage links.

### Supported URL Schemes
* **S3**: `s3://bucket/path/to/state.json` (requires boto3)
* **Google Cloud Storage**: `gs://bucket/path/to/state.json` (requires google-cloud-storage)
* **HTTP/HTTPS**: `http://example.com/state.json` or `https://example.com/state.json`

### Detection & Expansion Flow
1. **Detection**: URLs containing fragments with JSON pointers (e.g., `https://neuroglancer-demo.appspot.com/#!s3://bucket/state.json`) are automatically detected.
2. **Fetching**: The pointer URL is fetched using appropriate protocol handlers with graceful fallback for missing dependencies.
3. **Expansion**: JSON content is parsed and embedded into the Neuroglancer URL as an inline fragment.
4. **URL Update**: The panel viewer is updated with the canonical expanded URL.
5. **Backend Sync**: The expanded state is synchronized with the backend.

### Error Handling
* Network failures, invalid JSON, and missing cloud credentials are handled gracefully
* Status messages inform users of expansion progress and errors
* Failed expansions fall back to the original URL

### Debounce Logic
To prevent excessive backend updates, URL changes are debounced:
* **User-initiated changes**: Debounced with configurable interval (1-∞ seconds, default 5)
* **Programmatic changes**: Immediate synchronization without debounce
* **Update interval widget**: Allows users to customize the debounce delay

## Data flow (prompt → view + data)
1. UI sends user text → `POST /agent/chat`.
2. Backend builds system preface messages:
   * Core system guidance.
   * Neuroglancer state summary (layers, layout, position).
   * Data context block (uploaded files + summaries + recent interaction memory snapshot).
3. Backend performs iterative tool execution loop (up to 3 passes):
  * Model proposes tool calls.
  * Server executes each tool (Polars ops, state mutators, etc.).
  * Tool outputs are truncated JSON strings appended as `role=tool` messages.
  * Model is called again until no further tool calls.
4. Final assistant message plus `mutated` flag and (if any mutation) `state_link` object `{url, masked_markdown}` returned to client.
5. Panel displays answer; if `mutated` and auto-load enabled it loads the returned Neuroglancer URL.
6. CSV uploads: Panel posts each file to `/upload_file`, then refreshes file & summary tables via list endpoints.
7. **JSON Pointer Expansion**: Panel automatically detects and expands pointer URLs (s3://, gs://, http(s)://) to canonical Neuroglancer URLs with inline JSON state.
8. **Debounced Updates**: User-initiated URL changes are debounced with configurable interval; programmatic changes bypass debounce.
9. Persistence only when user explicitly asks (`/tools/state_save`).

### Mermaid: Chat + Data + Memory + Pointer Expansion Flow

```mermaid
flowchart TD
  subgraph Client[Panel Client]
    U[User Prompt]
    ChatUI[ChatInterface]
    Upload[CSV Drag & Drop]
    Viewer[Neuroglancer Widget]
    FilesTable[Files Table]
    SummariesTable[Summaries Table]
    UrlInput[URL Change]
    IntervalWidget[Update Interval Widget]
  end

  subgraph PointerSystem[JSON Pointer Expansion]
    Detection[Pointer Detection]
    S3Fetch[S3 Fetcher]
    GSFetch[GS Fetcher]
    HTTPFetch[HTTP Fetcher]
    JsonExpand[JSON Expansion]
    Debounce[Debounce Logic]
  end

  subgraph Backend[FastAPI Backend]
    ChatEP[/POST /agent/chat/]
    Tools[/POST /tools/*/]
    StateLink[/POST /tools/ng_state_link/]
    UploadEP[/POST /upload_file/]
    StateLoad[/POST /tools/state_load/]
    subgraph Memory[In‑Memory Stores]
      CurrentState[(CURRENT_STATE)]
      DataMem[(DataMemory\n(Polars DFs+Summaries))]
      InterMem[(InteractionMemory)]
    end
    LLM[LLM Adapter\n(OpenAI chat+tools)]
    Executor[Iterative Tool Loop]
  end

  U --> ChatUI --> ChatEP
  Upload --> UploadEP --> DataMem
  UrlInput --> Detection
  Detection -->|s3://| S3Fetch
  Detection -->|gs://| GSFetch
  Detection -->|http(s)://| HTTPFetch
  S3Fetch --> JsonExpand
  GSFetch --> JsonExpand
  HTTPFetch --> JsonExpand
  JsonExpand --> Debounce
  Debounce -->|User change| IntervalWidget
  Debounce -->|Programmatic| Viewer
  Debounce --> StateLoad
  
  ChatEP -->|Augment prompt with| InterMem
  ChatEP -->|Augment prompt with| DataMem
  ChatEP -->|Augment prompt with| CurrentState
  ChatEP --> LLM -->|tool_calls| Executor --> Tools
  Executor -->|tool outputs (tool messages)| LLM
  Tools -->|mutate| CurrentState
  Tools -->|read/write| DataMem
  Tools -->|log interactions| InterMem
  Tools --> StateLink --> ChatUI
  ChatUI -->|if mutated & auto-load| Viewer
  UploadEP --> FilesTable
  UploadEP --> SummariesTable
  Tools --> DataMem --> SummariesTable
  DataMem --> FilesTable
  InterMem --> ChatEP
  StateLoad --> CurrentState
```

## Tool surface (HTTP endpoints)
Neuroglancer / visualization:
* `POST /tools/ng_set_view` — center/zoom/orientation (mutating)
* `POST /tools/ng_set_lut` — LUT range (mutating)
* `POST /tools/ng_add_layer` — add new layer (image/segmentation/annotation) idempotently
* `POST /tools/ng_set_layer_visibility` — toggle visibility of existing layer
* `POST /tools/ng_annotations_add` — add annotations (mutating)
* `POST /tools/ng_state_summary` — structured snapshot (read-only)
* `POST /tools/ng_state_link` — URL + masked markdown (read-only)
* `POST /tools/state_save` — persist snapshot (explicit)
* `POST /tools/state_load` / `POST /tools/demo_load` — load link (mutating)

Data (Polars):
* `POST /upload_file` — multipart CSV upload (validated, size capped)
* `POST /tools/data_list_files` — list uploaded file metadata
* `POST /tools/data_preview` — first N rows
* `POST /tools/data_info` — rows/cols, columns, dtypes, head sample
* `POST /tools/data_describe` — numeric stats (stored as summary)
* `POST /tools/data_select` — column subset + simple filters (stores preview summary)
* `POST /tools/data_list_summaries` — list derived tables
* `POST /tools/data_ingest_csv_rois` — legacy ROI ingest (top‑N)
* `POST /tools/data_plot_histogram` — histogram (stub)
* `POST /tools/data_query_polars` — execute Polars expressions
* `POST /tools/data_plot` — generate interactive plots (scatter/line/bar/heatmap)
* `POST /tools/data_list_plots` — list generated plots

## Current features
* Prompt-driven navigation: set view, set LUT, add / hide layers, add annotations.
* CSV drag & drop → in-memory Polars DataFrames with short IDs.
* Data tools: list, preview, describe, select, list summaries.
* **Interactive plotting**: Generate scatter, line, bar, and heatmap plots using hvPlot.
  * Automatic spatial column inclusion in queries for future Neuroglancer integration.
  * Configurable interactivity (default: interactive for ≤200 points, static above).
  * Optional Polars expression for data transformation before plotting.
  * Plots stored in DataMemory with workspace integration.
* Interaction memory: rolling context appended to system messages.
* Histogram + ROI ingest stubs.
* Server-side orchestration of multi-step tool calls + conditional NG auto-load.
* `data_info` tool for quick dataframe metadata used in reasoning.
* Masking of raw Neuroglancer URLs (backend + frontend fallback).
* Tool execution trace (`tool_trace`) in chat response plus `/debug/tool_trace` for recent full traces.
* Random row sampling via `data_sample` (deterministic with optional seed, without replacement by default).
* Multi‑view generation via `data_ng_views_table` returning a table of ranked rows with per‑row NG links and auto‑loading the first view (uses `NeuroglancerState.clone()` for efficient ephemeral copies).
* **JSON Pointer Expansion**: Automatic detection and expansion of s3://, gs://, and http(s):// pointer URLs to canonical Neuroglancer URLs with inline JSON state.
* **Configurable Debounce**: User-adjustable update interval (1-∞ seconds) with immediate synchronization for programmatic changes.
* **Cloud Storage Integration**: Optional boto3 and google-cloud-storage support with graceful fallback for missing dependencies.

## Planned (near‑term)
* Real CloudVolume sampling (ROI support, multiscale) + caching.
* Layer registry, shader/value-range normalization, validation.
* ROI cycling / bookmarking flows.
* Session scoping & persistence for DataMemory (Redis/Postgres + temp object storage).
* Same-origin NG hosting + bidirectional messaging.
* Additional data tools: joins, stratified sampling, per-column value counts.
* Observability: tracing (OTel / Langfuse), structured tool logs, rate limits.
* Memory summarization / condensation (semantic compression) for long chats.
* Richer multi‑view workflows (pagination, client-side filtering, per-row annotation overlays).
* Row-level warning surfacing in UI for partial failures during multi-view generation.
* **Plot click-to-view**: Neuroglancer links for scatter plot points (click to navigate to spatial location).
* **Plot workspace**: Persistent plot gallery in Panel sidebar with thumbnails and replay.

## Tool Trace & Observability

Each `/agent/chat` response includes a lightweight `tool_trace` array showing executed tools, truncated arguments, and top-level result keys. Full (untruncated) details for the last N (default 50) interactions are stored in-memory and available at `/debug/tool_trace?n=K`. This enables:

* Fast debugging of unexpected tool chains.
* Post-hoc inspection without inflating model context (the full trace is not re-fed to the model).
* Potential future export for structured analytics (latency, error frequencies).

Trace design intentionally truncates large payloads (e.g., sampled rows, multi-view tables) to prevent UI bloat and accidental prompt echoing.

## Random Sampling (`data_sample`)

Purpose: Lightweight, unbiased inspection of a dataframe slice prior to column selection, filtering, or multi-view generation.

Behavior:
* Parameters: `file_id`, optional `n` (1..1000, clamped), optional `seed`, `replace` (default False).
* If `n` exceeds dataframe height (and `replace=False`), it is reduced to full height.
* Returns rows in random order (`shuffle=True`) with explicit `returned` count and echoed seed for reproducibility.
* Does not create a stored summary (avoids clutter for transient peeks).

Edge considerations:
* Invalid `file_id` returns error without raising.
* Seeds allow deterministic test coverage (used in unit tests).

## Multi‑View Generation (`data_ng_views_table`)

Purpose: Generate a ranked shortlist of candidate spatial positions (e.g., top N by a metric) and produce Neuroglancer links for rapid comparative inspection.

Key design points:
* Accepts either a raw `file_id` dataframe or an existing `summary_id` (derived table). If both provided, summary takes precedence (warning emitted server-side).
* Sorting: optional `sort_by` + `descending` (default True). If absent, preserves original order (then head `top_n`).
* Required columns: id column (default `cell_id`) + center coordinate columns (`x,y,z` by default). Missing columns return an error early.
* Optional include columns appended verbatim if present; missing ones are ignored with a warning.
* Optional LUT adjustment and per-row point annotation (writes to `annotations` layer) for each ephemeral view.
* Creates transient mutated copies of the current state to derive links using `CURRENT_STATE.clone()` (deep JSON copy); only the FIRST generated state's JSON replaces `CURRENT_STATE` for continuity.
* Returns: `{ file_id, summary (new summary metadata), n, rows[], warnings[], first_link }` where each row contains raw `link` and markdown-safe `masked_link` plus included metrics.
* Stores a summary table in `DataMemory` with kind `ng_views` (excludes raw link column) enabling later re-ranking or selection chaining.
* Chat response surfaces an aggregated `views_table`; Panel UI renders this in a Tabulator grid with click-to-load internal link behavior and auto-load of the first link (unless disabled).

Schema constraints:
* OpenAI function schema disallows top-level `oneOf`, so mutual exclusivity of `file_id` vs `summary_id` is enforced in code & documented rather than validated by JSON Schema.

Masking Logic:
* Raw NG links are transformed to `[Updated Neuroglancer view](...)` during general masking (idempotent).
* Within multi-view rows the label is normalized to `[link](...)` for compact tabular display; numeric suffix masking (for multiple distinct links in a single message) is removed here for simplicity.

Failure / resiliency:
* Per-row exceptions yield a warning entry; processing continues for remaining rows.
* If no rows succeed, returns `error` with accumulated warnings (no mutation performed).

## Masked Links

All Neuroglancer URLs returned in assistant messages are masked to concise markdown hyperlinks to reduce prompt noise and prevent accidental copying of extremely long fragments. Multiple distinct links in one message receive numeric suffixes. The masking function also detects certain fragment-only tokens.

Multi-view rows intentionally use a short `[link]` label for scannability; the full raw URL stays in the structured JSON row for advanced clients needing direct parsing.

## Ops / environment
* Python managed with **uv** (`uv run`, `uv add`).
* Key env vars: `OPENAI_API_KEY`, `NEUROGLANCER_BASE`, `S3_BUCKET` (future), optional panel `BACKEND` override.
* Dev ports: FastAPI **:8000**, Panel **:8006**, Next.js **:3000**.
* CORS (dev): allow `localhost` origins for UI embedding.

## Run (quick)
* Backend: `uv run uvicorn backend.main:app --reload --port 8000`
* Panel: `BACKEND=http://127.0.0.1:8000 uv run python -m panel serve panel/panel_app.py --port 8006 --address 127.0.0.1 --allow-websocket-origin=127.0.0.1:8006 --allow-websocket-origin=localhost:8006`
* Next.js (optional): `npm run dev`

## Risks & mitigations
| Risk | Mitigation |
|------|------------|
| Global in-process DataMemory (no user scoping) | Introduce session/user keys; TTL or LRU eviction |
| Memory growth with many uploads | 20 MB/file cap + future eviction & lazy scan_csv |
| Prompt bloat from data/interaction context | Hard caps on counts + char trimming |
| Tool mis-selection by LLM | Explicit system rules; non-overlapping tool semantics |
| Cross-origin embed limitations | Same-origin NG bundle + message channel |
| Large CSV parse latency | Use `pl.scan_csv` + lazy operations when needed |
| Cloud volume egress cost | Mip-level sampling, ROI bounding, caching |

## Why not LangChain (yet)?
Current scope: small tool surface (<20), single round tool selection, explicit prompt assembly. A custom adapter keeps dependency / cognitive load low and debugging transparent. Re-evaluate when we need multi-step planning loops, tool parallelism, retrieval pipelines, or pluggable memory summarizers. Existing separation (one `TOOLS` list + system preface builder) makes migration straightforward later.

## Open questions
* CSV/ROI schema standardization (coordinate frame, units, metadata columns?)
* Session & auth model: per-user isolation vs collaborative sessions.
* Priority order for React feature parity.
* Strategy for summarizing or vectorizing historical interaction memory.
* Persistence / export of derived summaries (download endpoints?).

---
Last updated: after data tools, memory integration, and JSON pointer expansion with debounce functionality.

