# neuroglancer-chat

[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)
![Code Style](https://img.shields.io/badge/code%20style-black-black)
[![semantic-release: angular](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release)
![Interrogate](https://img.shields.io/badge/interrogate-46.1%25-red)
![Coverage](https://img.shields.io/badge/coverage-20%25-red)
![Python](https://img.shields.io/badge/python->=3.10-blue?logo=python)

## To run

### Manual start:
**Backend**
```bash
cd src\neuroglancer_chat
$env:TIMING_MODE = "true"  # Optional
uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```
**Frontend**
```bash
cd src\neuroglancer_chat
$env:BACKEND = "http://127.0.0.1:8000"
uv run python -m panel serve panel\panel_app.py --autoreload --port 8006 --address 127.0.0.1 --allow-websocket-origin=127.0.0.1:8006 --allow-websocket-origin=localhost:8006
```
+ open browser: http://localhost:8006

+ debug mode: $env:NEUROGLANCER_CHAT_DEBUG = "1" 

    

### Quick start with launch scripts:
+ Bash: `./start.sh` or `./start.sh --timing` (enable performance monitoring)
+ PowerShell: `.\start.ps1` or `.\start.ps1 -Timing` (enable performance monitoring)
+ `.\start_backend.ps1` or `.\start_backend.ps1 -Timing`
+ `.\start_panel.ps1` 

### Tests
    + `uv run -m coverage run -m pytest`
    + `uv run -m coverage report`

    + Integration test: `uv run python -m pytest tests/test_integration_query_with_links.py -v -s`

## Installation
To use the software, in the root directory, run
```bash
pip install -e .
```

To develop the code, run
```bash
pip install -e . --group dev
```
Note: --group flag is available only in pip versions >=25.1

Alternatively, if using `uv`, run
```bash
uv sync
```

For cloud storage support (optional), install additional dependencies:
```bash
# For S3 pointer expansion
uv add boto3

# For Google Cloud Storage pointer expansion  
uv add google-cloud-storage

# Or install both
uv add boto3 google-cloud-storage
```

##

+ https://hemibrain-dot-neuroglancer-demo.appspot.com/#!gs://neuroglancer-janelia-flyem-hemibrain/v1.0/neuroglancer_demo_states/base.json
+ https://aind-neuroglancer-sauujisjxq-uw.a.run.app/#!s3://aind-open-data/HCR_754803-03_2025-04-04_13-00-00/raw_data.json

## JSON Pointer Expansion

The panel app now automatically detects and expands JSON pointer URLs that reference external state files in cloud storage. This enables easy sharing of complex Neuroglancer states via simple links.

### Supported URL Schemes

* **S3**: `s3://bucket/path/to/state.json` (requires `pip install boto3`)
* **Google Cloud Storage**: `gs://bucket/path/to/state.json` (requires `pip install google-cloud-storage`)
* **HTTP/HTTPS**: `http://example.com/state.json` or `https://example.com/state.json`

### Usage Examples

Simply paste any of these URL formats into the Neuroglancer URL field:

```
# Google Cloud Storage pointer
https://neuroglancer-demo.appspot.com/#!gs://neuroglancer-janelia-flyem-hemibrain/v1.0/neuroglancer_demo_states/base.json

# S3 pointer
https://aind-neuroglancer.com/#!s3://aind-open-data/dataset/state.json

# HTTP pointer
https://neuroglancer-demo.appspot.com/#!https://example.com/states/hemibrain.json

# Direct pointer (no base URL)
gs://my-bucket/states/cortex-view.json
```

The panel will automatically:
1. Detect the JSON pointer in the URL
2. Fetch the JSON content from cloud storage or HTTP
3. Expand it into a canonical Neuroglancer URL with inline state
4. Update both the viewer and backend state

### Error Handling

* Missing cloud dependencies (boto3, google-cloud-storage) are handled gracefully
* Network failures fall back to the original URL
* Status messages keep you informed of expansion progress
* Invalid JSON or malformed URLs are handled with clear error messages

### Debounce Configuration

To prevent excessive backend updates during URL editing, the panel includes configurable debounce logic:

* **Update Interval**: Adjustable from 1 second to infinity (default: 5 seconds)
* **User Changes**: Debounced according to the configured interval
* **Programmatic Changes**: Immediate synchronization without debounce
* **Settings Widget**: Located in the panel interface for easy adjustment


## Features

* Chat-driven Neuroglancer view manipulation via tool calls
* Iterative server-side tool execution loop (model -> tools -> model) for grounded answers
* FastAPI backend with pluggable data & visualization tools (Polars-based dataframe utilities)
* Panel-based UI prototype embedding a Neuroglancer viewer
* Full Neuroglancer state retention (layers, transforms, shader controls, layout) with deterministic URL round‑trip
* Class-based Neuroglancer state API (`NeuroglancerState`) with chainable mutators and `clone()` for safe ephemeral derivations
* Layer management tools: add image/segmentation/annotation layers (`ng_add_layer`) and toggle visibility (`ng_set_layer_visibility`)
* Optional auto-load toggle for applying newly generated Neuroglancer views
* `data_info` tool for dataframe metadata (shape, columns, dtypes, sample rows)
* `data_sample` tool for quick unbiased random row sampling (optional seed)
* `data_ng_views_table` tool to generate ranked multi-view Neuroglancer links (top N by a metric)
* Tool execution trace returned with each chat + debug endpoint for recent full traces
* **JSON Pointer Expansion**: Automatic detection and expansion of s3://, gs://, and http(s):// pointer URLs
* **Configurable Debounce**: User-adjustable update interval with intelligent programmatic bypass
* **Cloud Storage Integration**: Optional boto3 and google-cloud-storage support with graceful dependency handling
* **Performance Monitoring**: Optional timing instrumentation for agent loop performance analysis (see `docs/timing.md`)

## Neuroglancer State Handling

The backend preserves the *entire* Neuroglancer JSON state parsed from any loaded URL (including multi-panel layouts, per-layer transforms, shader code/controls, shader ranges, dimensions, etc.).

### Class API

All state mutation now goes through the `NeuroglancerState` class (procedural helper functions were removed). Methods mutate in place and return `self` for optional chaining:

```python
from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState

state = NeuroglancerState()
state.set_view({"x": 10, "y": 20, "z": 30}, "fit", "xy") \
    .add_layer("em", layer_type="image", source="precomputed://bucket/em") \
    .set_lut("em", 0, 255) \
    .add_annotations("ROIs", [{"point": [10,20,30], "id": "r1"}])

url = state.to_url()          # serialize
state2 = NeuroglancerState.from_url(url)  # parse

# Safe ephemeral copy for experimentation (no shared references):
scratch = state.clone().set_view({"x": 0, "y": 0, "z": 0}, None, None)
```

Available mutators:
* `set_view(center, zoom, orientation)`
* `set_lut(layer_name, vmin, vmax)`
* `add_layer(name, layer_type, source, **kwargs)` (idempotent on duplicate name)
* `set_layer_visibility(name, visible)`
* `add_annotations(layer_name, iterable_of_annotation_dicts)`
* `clone()` – deep JSON copy (faster & cleaner than URL round‑trip)

Low-level helpers `to_url(obj)` and `from_url(str)` accept either a raw dict, a `NeuroglancerState` instance, a full URL, a hash fragment, or raw JSON. `to_url(to_url(state))` is idempotent.

### Mutating Tools

Server-exposed tool endpoints wrap class methods:
* `ng_set_view`
* `ng_set_lut`
* `ng_add_layer`
* `ng_set_layer_visibility`
* `ng_annotations_add`

Each mutator is minimal and never strips unrelated keys. Position updates preserve a 4th component if present (e.g. time).

### Cloning Strategy

Multi-view generation (`data_ng_views_table`) uses `CURRENT_STATE.clone()` for each candidate row to avoid repeated URL encode/decode overhead and to eliminate accidental shared nested references. Only the first generated view becomes the new `CURRENT_STATE` for continuity.

### Deterministic Serialization

`to_url()` produces compact, sorted-key JSON so tests (and downstream caching) can rely on stable string equality: `from_url(to_url(state_dict)) == state_dict` for typical states.

### Migration Note

Legacy procedural helpers (`new_state`, `set_view`, `set_lut`, `add_annotations`, etc.) were removed in favor of the class API; update any external prototypes accordingly.

## Auto‑Load Toggle

In the Panel UI a Settings card provides an "Auto-load view" checkbox (default ON). When disabled, generated URLs are shown in chat and placed in a read‑only "Latest NG URL" field; click "Open latest link" to manually apply. This affords manual inspection or batching of tool operations before updating the viewer.

## Sampling & Multi-View Workflow

Common exploration pattern:
1. Upload CSV of ROIs / detections.
2. Ask: "Show me a random sample of 5 rows from file XYZ" -> invokes `data_sample`.
3. Ask: "Create Neuroglancer views for the top 8 by mean_intensity" -> model calls `data_ng_views_table` with `sort_by=mean_intensity` and `top_n=8`.
4. Panel displays a table of rows (id + metric + masked link); the first view auto-loads (if enabled). Clicking other rows navigates without requiring new LLM calls.

`data_ng_views_table` returns both raw `link` and `masked_link` so advanced clients can decide how to render. A summary table (kind `ng_views`) is stored allowing follow-up queries like: "Filter the previous views summary where mean_intensity > 0.8 then regenerate views".

## Tool Trace

Each chat response includes a concise `tool_trace` listing executed tools, argument keys, and result keys. For deeper debugging hit `/debug/tool_trace?n=5` to retrieve recent full traces (in-memory, bounded). This aids reproducibility and performance analysis without inflating LLM context.

