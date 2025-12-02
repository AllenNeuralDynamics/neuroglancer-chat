# Neuroglancer-Chat Architecture

## System Overview

Neuroglancer-Chat is a neuroimaging chat application that combines LLM-powered natural language interaction with Neuroglancer visualization and data analysis tools.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Neuroglancer-Chat SYSTEM                                │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Panel)                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  panel_app.py (Main UI)                                                 │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │ │
│  │  │  Chat UI     │  │ Neuroglancer │  │  Workspace   │                 │ │
│  │  │  Interface   │  │    Viewer    │  │    Tabs      │                 │ │
│  │  │              │  │              │  │              │                 │ │
│  │  │ • Streaming  │  │ • 3D Viewer  │  │ • Results    │                 │ │
│  │  │ • Messages   │  │ • URL Sync   │  │ • Data Upload│                 │ │
│  │  │ • User Input │  │ • Debouncing │  │ • Tables     │                 │ │
│  │  │              │  │ • Auto-load  │  │ • Plots      │                 │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                 │ │
│  │         │                  │                  │                         │ │
│  │         └──────────────────┴──────────────────┘                         │ │
│  │                            │                                            │ │
│  │                     HTTP/WebSocket                                      │ │
│  └────────────────────────────┼────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           BACKEND (FastAPI)                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  main.py (API Server)                                                   │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │ │
│  │  │   Agent      │  │   Endpoints  │  │  State Sync  │                 │ │
│  │  │   Chat       │  │              │  │              │                 │ │
│  │  │              │  │ • /agent/    │  │ • state_load │                 │ │
│  │  │ • Streaming  │  │   chat       │  │ • state_save │                 │ │
│  │  │ • Non-stream │  │ • /agent/    │  │ • URL gen    │                 │ │
│  │  │ • Tool exec  │  │   chat/      │  │              │                 │ │
│  │  │              │  │   stream     │  │              │                 │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────────────┘                 │ │
│  │         │                  │                                            │ │
│  │         ├──────────────────┘                                            │ │
│  │         │                                                                │ │
│  │         ▼                                                                │ │
│  │  ┌────────────────────────────────────────────────────────────────────┐ │ │
│  │  │                     TOOL DISPATCHER                                 │ │ │
│  │  │  • Routes tool calls to appropriate handlers                       │ │ │
│  │  │  • Manages mutation tracking                                       │ │ │
│  │  │  • Aggregates responses                                            │ │ │
│  │  └──────────────────────────┬─────────────────────────────────────────┘ │ │
│  │                             │                                            │ │
│  └─────────────────────────────┼────────────────────────────────────────────┘ │
└─────────────────────────────────┼────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TOOL MODULES                                    │
│                                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐               │
│  │  Neuroglancer  │  │  Data Tools    │  │  Plot Tools    │               │
│  │     Tools      │  │                │  │                │               │
│  │                │  │ • data_query   │  │ • data_plot    │               │
│  │ • ng_set_view  │  │ • data_filter  │  │ • plot specs   │               │
│  │ • ng_set_lut   │  │ • data_preview │  │ • validation   │               │
│  │ • ng_add_layer │  │ • groupby/agg  │  │                │               │
│  │ • ng_multiview │  │                │  │                │               │
│  │ • state mgmt   │  │                │  │                │               │
│  └────────┬───────┘  └────────┬───────┘  └────────┬───────┘               │
│           │                   │                    │                       │
│           └───────────────────┴────────────────────┘                       │
│                               │                                             │
└───────────────────────────────┼─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STORAGE & STATE                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  storage/data.py (DataMemory)                                           │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │ │
│  │  │    Files     │  │   Summaries  │  │    Plots     │                 │ │
│  │  │              │  │              │  │              │                 │ │
│  │  │ • CSV files  │  │ • Groupby    │  │ • PlotRecord │                 │ │
│  │  │ • Metadata   │  │ • Aggregated │  │ • Plot specs │                 │ │
│  │  │ • Polars DF  │  │ • Filtered   │  │ • Plot data  │                 │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                 │ │
│  │                                                                          │ │
│  │  storage/states.py (CURRENT_STATE)                                      │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐   │ │
│  │  │              NeuroglancerState (Global)                          │   │ │
│  │  │  • dimensions (preserves order!)                                 │   │ │
│  │  │  • position                                                      │   │ │
│  │  │  • layers                                                        │   │ │
│  │  │  • view settings                                                 │   │ │
│  │  └─────────────────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LLM INTEGRATION                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  adapters/llm.py                                                        │ │
│  │  ┌──────────────────────────────────────────────────────────────────┐  │ │
│  │  │                     OpenAI Function Calling                       │  │ │
│  │  │  • Tool schemas (JSON)                                            │  │ │
│  │  │  • System prompts                                                 │  │ │
│  │  │  • Response parsing                                               │  │ │
│  │  │  • Streaming support                                              │  │ │
│  │  └──────────────────────────────────────────────────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       SUPPORTING UTILITIES                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐               │
│  │  Observability │  │ Pointer Expand │  │   Constants    │               │
│  │                │  │                │  │                │               │
│  │ • Timing       │  │ • JSON ptr     │  │ • Tool names   │               │
│  │ • Tracing      │  │ • URL expand   │  │ • Config       │               │
│  │ • Debug logs   │  │ • Canonical    │  │                │               │
│  └────────────────┘  └────────────────┘  └────────────────┘               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. User Query Flow
```
User Input → ChatInterface → respond() → agent_call() 
    ↓
Backend /agent/chat endpoint → Tool Dispatcher
    ↓
Tool Execution (ng_set_view, data_query, data_plot, etc.)
    ↓
Response with: answer, ng_views, query_data, plot_data, mutated state
    ↓
Frontend Rendering: Tables (Tabulator), Plots (hvPlot), NG State Update
    ↓
Workspace Update: Add to Results tab
```

### 2. Neuroglancer State Synchronization
```
User interacts with NG Viewer (Frontend)
    ↓
viewer.url changes (debounced) → _on_url_change()
    ↓
Pointer expansion (if needed) → expand_if_pointer_and_generate_inline()
    ↓
Backend /tools/state_load → CURRENT_STATE = NeuroglancerState.from_url()
    ↓
State preserved with dimension order intact (no sort_keys!)
```

### 3. Plot Generation Flow
```
User: "plot x vs y"
    ↓
LLM generates: data_plot tool call with expression
    ↓
Backend execute_plot():
  • Validates data
  • Applies Polars expression (filter, groupby, agg)
  • Returns plot_kwargs + transformed data rows
    ↓
Frontend receives plot_data:
  • Creates Polars DataFrame from data rows
  • Calls df.hvplot.scatter/line/bar/heatmap(**plot_kwargs)
  • Wraps in pn.pane.HoloViews() for native rendering
    ↓
Display in chat + "Add to Workspace" button
```

### 4. Data Query Flow
```
User: "show cells where volume > 100"
    ↓
LLM generates: data_query tool call with expression
    ↓
Backend execute_query():
  • Applies Polars expression
  • Generates ng_views for spatial data
  • Returns structured query_data (data dict, columns, ng_views)
    ↓
Frontend receives query_data:
  • Creates Tabulator widget directly from data
  • Adds View buttons for spatial navigation
  • Enables click-to-view in Neuroglancer
    ↓
Display in chat + "Add to Workspace" button
```

## Key Components

### Frontend (`src/Neuroglancer-Chat/panel/`)
- **panel_app.py**: Main Panel application
  - Chat interface with streaming support
  - Neuroglancer viewer integration
  - Workspace tabs (Results, Data Upload)
  - Settings controls

### Backend (`src/Neuroglancer-Chat/backend/`)
- **main.py**: FastAPI server with endpoints
  - `/agent/chat`: Non-streaming chat
  - `/agent/chat/stream`: Server-Sent Events streaming
  - `/tools/*`: Direct tool endpoints
  - `/upload_file`: CSV file upload

### Tools (`src/Neuroglancer-Chat/backend/tools/`)
- **neuroglancer_state.py**: NG state management (dimension order preserved!)
- **io.py**: Data query and filtering tools
- **plots.py**: Plot generation and validation
- **pointer_expansion.py**: JSON pointer URL expansion

### Storage (`src/Neuroglancer-Chat/backend/storage/`)
- **data.py**: In-memory DataMemory store
- **states.py**: Global CURRENT_STATE

### Adapters (`src/Neuroglancer-Chat/backend/adapters/`)
- **llm.py**: OpenAI integration with tool schemas

## Critical Design Patterns

### 1. Dimension Order Preservation
**Problem**: JSON serialization with `sort_keys=True` reordered dimensions (x,y,z,t → t,x,y,z), breaking position array mapping.

**Solution**: Removed `sort_keys=True` from `to_url()` in `neuroglancer_state.py`. Python 3.7+ dict insertion order is preserved.

### 2. Native Panel Rendering
**Problem**: HTML serialization of plots caused Bokeh rendering errors.

**Solution**: Backend sends `plot_kwargs` + transformed data rows → Frontend creates DataFrame and renders natively with `pn.pane.HoloViews()`.

### 3. Transformed Data Flow
**Problem**: Frontend was fetching untransformed source data after backend applied aggregations.

**Solution**: Backend includes `"data": df.to_dicts()` in plot_data response. Frontend uses this directly instead of re-fetching.

### 4. Debounced State Sync
**Problem**: Rapid NG viewer interactions caused excessive backend calls.

**Solution**: Programmatic vs user-driven updates tracked separately. User updates debounced with configurable interval (default 5s).

### 5. Spatial Navigation
**Problem**: Query results needed clickable navigation to NG coordinates.

**Solution**: Backend generates `ng_views` list with row_index + URL. Frontend renders Tabulator with View button column that calls `_load_internal_link()`.

## Configuration

### Environment Variables
- `BACKEND`: Backend URL (default: http://127.0.0.1:8000)
- `USE_STREAMING`: Enable streaming chat (default: true)
- `Neuroglancer-Chat_DEBUG`: Enable debug logging
- `NEUROGLANCER_BASE`: NG base URL (default: neuroglancer-demo.appspot.com)
- `OPENAI_API_KEY`: OpenAI API key for LLM

### Settings (UI)
- Auto-load view: Auto-open NG links
- Show query tables in plots: Display tables alongside plots
- Update state interval: Debounce interval for NG sync
- NG links open internal: Use internal viewer vs external
- Trace history: Enable tool execution tracing

## Technology Stack

- **Frontend**: Panel, Bokeh, HoloViews, hvPlot
- **Backend**: FastAPI, Uvicorn
- **Data**: Polars (DataFrames), PyArrow
- **LLM**: OpenAI API with function calling
- **Visualization**: Neuroglancer, hvPlot
- **Testing**: pytest, httpx

## Performance Optimizations

1. **Interactivity Threshold**: Plots > 200 points render as static (configurable)
2. **Workspace Limits**: Max 10 results in workspace (FIFO)
3. **Debouncing**: NG state sync throttled to prevent excessive calls
4. **Streaming**: Server-Sent Events for real-time chat responses
5. **Native Rendering**: Avoid HTML serialization overhead

## Security & Error Handling

- Safe expression evaluation with Polars AST
- Input validation for tool parameters
- Comprehensive error responses with structured messages
- Trace history for debugging tool execution
- Pointer expansion for secure JSON state sharing

