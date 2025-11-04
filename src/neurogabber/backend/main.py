import os
import re
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), '.env'))

from fastapi import FastAPI, UploadFile, Body, Query, File
from fastapi.responses import StreamingResponse
from .models import (
    ChatRequest, SetView, SetLUT, AddAnnotations, HistogramReq, IngestCSV, SaveState,
    AddLayer, SetLayerVisibility, StateLoad, StateSummary,
    DataInfo, DataPreview, DataDescribe, DataQuery, DataPlot, NgViewsTable, NgAnnotationsFromData
)
from .tools.neuroglancer_state import (
    NeuroglancerState,
    to_url,
    from_url,
)
from .tools.plots import sample_voxels, histogram
from .tools.io import load_csv, top_n_rois
from .storage.states import save_state, load_state
from .adapters.llm import run_chat, run_chat_stream, SYSTEM_PROMPT, MODEL
from .tools.constants import is_mutating_tool
from .storage.data import DataMemory, InteractionMemory
from .observability.timing import TimingCollector
import polars as pl

import logging

# Enable verbose debug logging when NEUROGABBER_DEBUG is set (1/true/yes)
DEBUG_ENABLED = os.getenv("NEUROGABBER_DEBUG", "").lower() in ("1", "true", "yes")

# Configure logging level based on debug flag
log_level = logging.DEBUG if DEBUG_ENABLED else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(levelname)s: %(asctime)s | %(name)s | %(message)s",
    force=True  # Force reconfiguration even if uvicorn already configured logging
)

# Also configure the root logger and uvicorn's loggers explicitly
# Uvicorn configures logging after module import, so we need to be aggressive
if DEBUG_ENABLED:
    # Set root logger to DEBUG
    logging.getLogger().setLevel(logging.DEBUG)
    
    # Configure uvicorn and our backend loggers
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "backend.main", __name__]:
        logging.getLogger(logger_name).setLevel(logging.DEBUG)
    
    # Silence noisy third-party libraries - keep them at INFO even in debug mode
    for noisy_logger in ["openai", "httpx", "httpcore", "python_multipart.multipart"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def _dbg(msg: str):  # lightweight wrapper to centralize debug guard
    """Debug logging wrapper - now uses proper logger.debug()"""
    logger.debug(msg)

app = FastAPI()

# Log debug mode status on startup
if DEBUG_ENABLED:
    logger.warning("🔍 DEBUG MODE ENABLED - Verbose logging active (NEUROGABBER_DEBUG=1)")
else:
    logger.info("Debug mode disabled. Set NEUROGABBER_DEBUG=1 to enable verbose logging.")

# Configuration: Control what tool results the LLM sees
# Set to False to hide query data from LLM (sends minimal acknowledgment instead)
# Set to True to send full data results to LLM (original behavior)
SEND_DATA_TO_LLM = False

# In-memory working state per session (MVP). Replace with DB keyed by user/session.
CURRENT_STATE = NeuroglancerState()
DATA_MEMORY = DataMemory()
INTERACTION_MEMORY = InteractionMemory()
_TRACE_HISTORY: list[dict] = []  # store recent full traces (in-memory, capped)
_TRACE_HISTORY_MAX = 50
LAST_QUERY_SUMMARY_ID = None  # Track most recent query result for easy reference


def _detect_spatial_columns(df) -> tuple[list[str], str] | None:
    """Detect spatial coordinate columns in a dataframe.
    
    Returns:
        Tuple of (column_names, pattern) or None if not found.
        Patterns: 'xyz', 'centroid_xyz', etc.
    """
    import polars as pl
    cols = df.columns
    
    # Try common patterns in order of preference
    patterns = [
        (['x', 'y', 'z'], 'xyz'),
        (['centroid_x', 'centroid_y', 'centroid_z'], 'centroid_xyz'),
        (['center_x', 'center_y', 'center_z'], 'center_xyz'),
        (['pos_x', 'pos_y', 'pos_z'], 'pos_xyz'),
        (['X', 'Y', 'Z'], 'XYZ'),
    ]
    
    for col_names, pattern in patterns:
        if all(c in cols for c in col_names):
            return (col_names, pattern)
    
    return None


def _generate_ng_links_for_rows(df, spatial_cols: list[str]) -> list[str]:
    """Generate Neuroglancer URLs for each row based on spatial coordinates.
    
    Hybrid approach: Returns raw URLs. Frontend will render them as clickable links.
    
    Args:
        df: Polars DataFrame with spatial columns
        spatial_cols: List of [x_col, y_col, z_col] column names
        
    Returns:
        List of raw NG URLs, one per row
    """
    global CURRENT_STATE
    
    links = []
    for row in df.to_dicts():
        try:
            cx, cy, cz = row[spatial_cols[0]], row[spatial_cols[1]], row[spatial_cols[2]]
            # Skip rows with null coordinates
            if cx is None or cy is None or cz is None:
                links.append("")
                continue
                
            # Clone current state and set view to this row's coordinates
            state_copy = CURRENT_STATE.clone()
            state_copy.set_view({"x": cx, "y": cy, "z": cz}, None, None)
            link_url = state_copy.to_url()
            
            # Return raw URL (frontend will create markdown link)
            links.append(link_url)
        except Exception as e:
            _dbg(f"Failed to generate link for row: {e}")
            links.append("")
    
    return links


@app.post("/tools/ng_set_view")
def t_set_view(args: SetView):
    global CURRENT_STATE
    CURRENT_STATE.set_view(args.center.model_dump(), args.zoom, args.orientation)
    return {"ok": True}

@app.post("/tools/ng_set_lut")
def t_set_lut(args: SetLUT):
    global CURRENT_STATE
    CURRENT_STATE.set_lut(args.layer, args.vmin, args.vmax)
    return {"ok": True}

@app.post("/tools/ng_add_layer")
def t_add_layer(args: AddLayer):
    """Add a new layer to the Neuroglancer state if it does not already exist.

    The source parameter is passed through verbatim; clients are responsible for supplying a valid Neuroglancer source spec.
    For annotation layers, annotation_color can specify the color (hex or name).
    """
    global CURRENT_STATE
    try:
        kwargs = {"visible": args.visible}
        if args.annotation_color:
            kwargs["annotation_color"] = args.annotation_color
        CURRENT_STATE.add_layer(name=args.name, layer_type=args.layer_type, source=args.source, **kwargs)
        return {"ok": True, "layer": args.name, "layer_type": args.layer_type}
    except ValueError as ve:
        return {"ok": False, "error": str(ve)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add layer: {e}"}

@app.post("/tools/ng_set_layer_visibility")
def t_set_layer_visibility(args: SetLayerVisibility):
    """Set the visibility flag on an existing layer.

    Adds a 'visible' key if not already present; silently no-ops if layer not found.
    """
    global CURRENT_STATE
    CURRENT_STATE.set_layer_visibility(name=args.name, visible=args.visible)
    return {"ok": True, "layer": args.name, "visible": args.visible}

@app.post("/tools/ng_annotations_add")
def t_add_annotations(args: AddAnnotations):
    global CURRENT_STATE
    items = []
    for a in args.items:
        if a.type == "point":
            # Must include 'type' field as per Neuroglancer schema
            items.append({
                "point": [a.center.x, a.center.y, a.center.z],
                "type": "point",
                "id": a.id or None
            })
        elif a.type == "box":
            items.append({
                "type": "box",
                "point": [a.center.x, a.center.y, a.center.z],
                "size": [a.size.x, a.size.y, a.size.z],
                "id": a.id or None
            })
        elif a.type == "ellipsoid":
            items.append({
                "type": "ellipsoid",
                "center": [a.center.x, a.center.y, a.center.z],
                "radii": [a.size.x/2, a.size.y/2, a.size.z/2],
                "id": a.id or None
            })
    CURRENT_STATE.add_annotations(args.layer, items)
    return {"ok": True}

@app.post("/tools/data_plot_histogram")
def t_hist(args: HistogramReq):
    vox = sample_voxels(args.layer, args.roi)
    hist, edges = histogram(vox)
    return {"hist": hist.tolist(), "edges": edges.tolist()}

@app.post("/tools/data_ingest_csv_rois")
def t_csv(args: IngestCSV):
    df = load_csv(args.file_id)
    rows = top_n_rois(df)
    return {"rows": rows}

@app.post("/tools/state_save")
def t_save_state(_: SaveState, mask: bool = Query(False, description="Return masked markdown link label instead of raw URL")):
    """Persist current state and return its ID and URL.

    If mask=true, also include 'masked_markdown' with a concise hyperlink label.
    We do masking here (where state is definitively updated) instead of during
    synthetic assistant message generation to avoid presenting stale links.
    """
    sid = save_state(CURRENT_STATE.as_dict())
    url = CURRENT_STATE.to_url()
    if mask:
        masked = _mask_ng_urls(url)
        # If masking logic chooses not to transform (unlikely since it's a NG URL), fall back to manual label.
        if masked == url:
            masked = f"[Updated Neuroglancer view]({url})"
        return {"sid": sid, "url": url, "masked_markdown": masked}
    return {"sid": sid, "url": url}


@app.post("/tools/state_load")
def t_state_load(args: StateLoad):
    """Load state from a Neuroglancer URL or fragment and set CURRENT_STATE."""
    global CURRENT_STATE
    try:
        CURRENT_STATE = NeuroglancerState.from_url(args.link)
        return {"ok": True}
    except Exception as e:
        logger.exception("Failed to load state from link")
        return {"ok": False, "error": str(e)}


@app.post("/tools/demo_load")
def t_demo_load(args: StateLoad):
    """Convenience: same as state_load, named for demos."""
    return t_state_load(args)

# TODO
#Optional (alternative path): if you prefer “read-only” to still be tool-based, 
#add a tiny GET tool like ng_list_layers to the toolset. But since you asked for “no tool” for 
#that query, the state-summary + system prompt approach above fits better.
def _state_dict(state) -> dict:
    """Return underlying dict for either raw dict or NeuroglancerState."""
    if isinstance(state, NeuroglancerState):
        return state.as_dict()
    return state

def _summarize_state(state) -> str:
    # Keep it short and deterministic. Expand as needed later.
    sd = _state_dict(state)
    layers = sd.get("layers", [])
    lines = []
    lines.append(f"Layout: {sd.get('layout','xy')}")
    pos = sd.get("position", [0,0,0])
    lines.append(f"Position: {pos}")
    if layers:
        lines.append("Layers:")
        for L in layers:
            name = L.get("name","(unnamed)")
            ltype = L.get("type","unknown")
            lines.append(f"- {name} ({ltype})")
    else:
        lines.append("Layers: (none)")
    return "\n".join(lines)


def _data_context_block(max_files: int = 10, max_summaries: int = 10) -> str:
    files = DATA_MEMORY.list_files()[:max_files]
    sums = DATA_MEMORY.list_summaries()[:max_summaries]
    parts = ["Data context:"]
    if files:
        # Highlight the most recent file
        most_recent = files[-1] if files else None
        if most_recent:
            # Check for spatial columns in the most recent file
            try:
                df = DATA_MEMORY.get_df(most_recent['file_id'])
                spatial_info = _detect_spatial_columns(df)
                spatial_note = ""
                if spatial_info:
                    spatial_cols, pattern = spatial_info
                    spatial_note = f" [HAS SPATIAL COLS: {', '.join(spatial_cols)} - include these in queries for auto NG links]"
                parts.append(f"Most recent file (use this by default): file_id='{most_recent['file_id']}' name='{most_recent['name']}' rows={most_recent['n_rows']} cols={most_recent['columns']}{spatial_note}")
            except:
                parts.append(f"Most recent file (use this by default): file_id='{most_recent['file_id']}' name='{most_recent['name']}' rows={most_recent['n_rows']} cols={most_recent['columns']}")
        
        if len(files) > 1:
            parts.append("Other files:")
            for f in files[:-1]:
                parts.append(f"- {f['file_id']} {f['name']} rows={f['n_rows']} cols={f['n_cols']} cols={f['columns'][:6]}...")
    else:
        parts.append("Files: (none)")
    if sums:
        parts.append("Summaries:")
        for s in sums:
            parts.append(f"- {s['summary_id']} from {s['source_file_id']} kind={s['kind']} rows={s['n_rows']} cols={s['n_cols']}")
    else:
        parts.append("Summaries: (none)")
    mem = INTERACTION_MEMORY.recall()
    if mem:
        parts.append(f"Recent interactions: {mem}")
    return "\n".join(parts)


@app.post("/agent/chat/stream")
async def agent_chat_stream(req: ChatRequest = Body(...)):
    """Stream agent chat responses using Server-Sent Events."""
    _dbg("📨 /agent/chat/stream endpoint called")
    
    import json
    import asyncio
    
    async def event_generator():
        try:
            # Get current state summary
            summary_text = _summarize_state(CURRENT_STATE)
            
            # Build conversation with system prompt and state context
            conversation = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": f"Current viewer state summary:\n{summary_text}"}
            ]
            conversation.extend([m.model_dump() for m in req.messages])
            
            max_iters = 10
            total_content = ""
            overall_mutated = False
            
            for iteration in range(max_iters):
                # Send iteration start event
                yield f"data: {json.dumps({'type': 'iteration', 'iteration': iteration})}\n\n"
                
                # Stream LLM response
                accumulated_message = None
                tool_calls = None
                
                for chunk in run_chat_stream(conversation):
                    if chunk["type"] == "content":
                        total_content += chunk["delta"]
                        yield f"data: {json.dumps({'type': 'content', 'delta': chunk['delta']})}\n\n"
                        await asyncio.sleep(0)  # Allow other tasks to run
                    
                    elif chunk["type"] == "tool_calls":
                        tool_calls = chunk["tool_calls"]
                        yield f"data: {json.dumps({'type': 'tool_calls', 'tool_calls': tool_calls})}\n\n"
                    
                    elif chunk["type"] == "done":
                        accumulated_message = chunk["message"]
                        usage = chunk.get("usage", {})
                        yield f"data: {json.dumps({'type': 'llm_done', 'usage': usage})}\n\n"
                
                # If no tool calls, we're done
                if not tool_calls:
                    break
                
                # Execute tools
                conversation.append(accumulated_message)
                
                for tc in tool_calls:
                    func = tc.get("function") or {}
                    tool_name = func.get("name")
                    args_str = func.get("arguments", "{}")
                    
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool': tool_name})}\n\n"
                    
                    try:
                        args = json.loads(args_str)
                        result = _execute_tool_by_name(tool_name, args)
                        
                        # Track if this tool mutates state
                        if is_mutating_tool(tool_name):
                            overall_mutated = True
                        
                        # Apply data hiding for data_query_polars if SEND_DATA_TO_LLM is False
                        llm_result = result
                        if tool_name == "data_query_polars" and not SEND_DATA_TO_LLM:
                            if isinstance(result, dict) and result.get("ok"):
                                llm_result = {
                                    "ok": True,
                                    "rows": result.get("rows"),
                                    "columns": result.get("columns"),
                                    "expression": result.get("expression"),
                                    "message": "✅ Query executed successfully. Data is being rendered in an interactive table widget. Do NOT format, display, or summarize the data - it's already handled by the frontend."
                                }
                        
                        # Apply data hiding for data_plot if SEND_DATA_TO_LLM is False
                        if tool_name == "data_plot" and not SEND_DATA_TO_LLM:
                            if isinstance(result, dict) and result.get("ok"):
                                llm_result = {
                                    "ok": True,
                                    "plot_id": result.get("plot_id"),
                                    "plot_type": result.get("plot_type"),
                                    "row_count": result.get("row_count"),
                                    "source_id": result.get("source_id"),
                                    "message": "✅ Plot generated successfully. The interactive plot is being rendered in the workspace. Do NOT describe or summarize the plot - it's already displayed."
                                }
                        
                        # Convert result to string safely for streaming
                        result_str = str(llm_result) if llm_result is not None else ""
                        # Limit very large results to prevent memory issues
                        if len(result_str) > 5000:
                            result_str = result_str[:5000] + "... (truncated)"
                        yield f"data: {json.dumps({'type': 'tool_done', 'tool': tool_name, 'result': result_str})}\n\n"
                        
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "name": tool_name,
                            "content": json.dumps(llm_result)
                        })
                    except Exception as e:
                        error_msg = f"Tool {tool_name} error: {e}"
                        yield f"data: {json.dumps({'type': 'tool_error', 'tool': tool_name, 'error': str(e)})}\n\n"
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "name": tool_name,
                            "content": json.dumps({"error": str(e)})
                        })
            
            # After loop completes, send final event with accumulated content
            state_link = None
            if overall_mutated:
                url = CURRENT_STATE.to_url()
                masked = _mask_ng_urls(url)
                state_link = {"url": url, "masked_markdown": masked}
            
            yield f"data: {json.dumps({'type': 'final', 'content': total_content, 'mutated': overall_mutated, 'state_link': state_link})}\n\n"
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/agent/chat")
def chat(req: ChatRequest):
    """Iterative chat with server-side tool execution.

    Loop:
      model -> (tool calls?) -> execute tools -> append tool messages -> model ...
    Stops when model returns no tool calls or max iterations reached.
    Returns the final model response (with intermediate tool messages NOT included
    to keep client payload small) plus optional `state_link` if a mutating tool ran.
    """
    _dbg("📨 /agent/chat endpoint called")
    
    # Initialize timing collector
    user_prompt = next((m.content for m in req.messages if m.role == "user"), "")
    timing = TimingCollector(user_prompt=user_prompt or "")
    timing.mark("request_received")
    
    # Prompt assembly phase
    with timing.phase("prompt_assembly"):
        import time as _time
        t_state_start = _time.perf_counter()
        state_summary = _summarize_state(CURRENT_STATE)
        t_state = _time.perf_counter() - t_state_start
        
        t_data_start = _time.perf_counter()
        data_context = _data_context_block()
        t_data = _time.perf_counter() - t_data_start
        
        t_memory_start = _time.perf_counter()
        # Interaction memory is accessed within _data_context_block, so we approximate
        t_memory = _time.perf_counter() - t_memory_start
        
        # Estimate total chars in context
        total_chars = len(SYSTEM_PROMPT) + len(state_summary) + len(data_context)
        timing.set_context_timing(t_state, t_data, t_memory, total_chars)
        
        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"Current viewer state summary:\n{state_summary}"},
            {"role": "system", "content": data_context},
        ]
        conversation = base_messages + [m.model_dump() for m in req.messages]
    
    max_iters = 6
    overall_mutated = False
    tool_execution_records = []  # truncated records for response
    full_trace_steps = []  # full detail trace retained server-side
    aggregated_views_table = None
    aggregated_ng_views = None  # Track ng_views from data_query_polars
    aggregated_query_data = None  # Track full data result from data_query_polars for frontend rendering
    aggregated_plot_data = None  # Track plot result from data_plot for frontend rendering

    timing.start_agent_loop()
    
    for iteration in range(max_iters):
        iter_timing = timing.start_iteration(iteration)
        
        _dbg(f"Iteration {iteration} start; messages so far={len(conversation)}")
        
        # LLM call with timing
        with timing.llm_call(iter_timing, model=MODEL) as llm_ctx:
            out = run_chat(conversation)
            # Extract token usage if available
            usage = out.get("usage", {})
            if usage:
                llm_ctx.set_tokens(
                    prompt=usage.get("prompt_tokens", 0),
                    completion=usage.get("completion_tokens", 0)
                )
        
        choices = out.get("choices") or []
        if not choices:
            _dbg("No choices returned by model; breaking loop")
            break
        msg = choices[0].get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content")
        if tool_calls:
            _dbg("Model tool_calls=" + ", ".join([(tc.get('function') or {}).get('name','?') for tc in tool_calls]))
        else:
            _dbg("Model returned no tool_calls; finishing")
        # If there are no tool calls we're done
        if not tool_calls:
            # Final masking before return
            if isinstance(content, str):
                msg["content"] = _mask_ng_urls(content)
            conversation.append(msg)
            break

        # Synthesize placeholder content if empty
        if (content is None or (isinstance(content, str) and not content.strip())) and tool_calls:
            msg["content"] = _synthesize_tool_call_message(tool_calls)
        conversation.append(msg)  # assistant with tool calls

        # Execute each tool call
        import json as _json
        for tc in tool_calls:
            fn = (tc.get("function") or {}).get("name")
            raw_args = (tc.get("function") or {}).get("arguments") or "{}"
            try:
                args = _json.loads(raw_args)
            except Exception:
                args = {}
            _dbg(f"Executing tool '{fn}' args={args}")
            
            # Tool execution with timing
            with timing.tool_execution(iter_timing, fn) as tool_ctx:
                result_payload = _execute_tool_by_name(fn, args)
                # Measure sizes
                tool_ctx.set_sizes(
                    args=len(_json.dumps(args)),
                    result=len(_json.dumps(result_payload))
                )
            
            _dbg(f"Tool '{fn}' result keys={list(result_payload.keys())}")
            
            # Capture full query result from data_query_polars for frontend rendering
            if fn == "data_query_polars":
                _dbg(f"data_query_polars result: ok={result_payload.get('ok')}, type={type(result_payload)}")
                if isinstance(result_payload, dict) and "ok" in result_payload and result_payload["ok"]:
                    # Store the complete query result for frontend
                    aggregated_query_data = {
                        "data": result_payload["data"],
                        "columns": result_payload["columns"],
                        "rows": result_payload["rows"],
                        "expression": result_payload.get("expression"),
                        "ng_views": result_payload.get("ng_views"),
                        "spatial_columns": result_payload.get("spatial_columns"),
                    }
                    aggregated_ng_views = result_payload.get("ng_views")
                    _dbg(f"✅ Captured query data: {result_payload['rows']} rows, {len(result_payload['columns'])} columns for frontend rendering")
                    
                    # Optionally hide data from LLM to prevent it from summarizing
                    if not SEND_DATA_TO_LLM:
                        # Replace result_payload with minimal acknowledgment for LLM
                        result_payload = {
                            "ok": True,
                            "rows": result_payload["rows"],
                            "columns": result_payload["columns"],
                            "expression": result_payload.get("expression"),
                            "message": "✅ Query executed successfully. Data is being rendered in an interactive table widget. Do NOT format, display, or summarize the data - it's already handled by the frontend."
                        }
                        _dbg(f"📦 Sending minimal acknowledgment to LLM (SEND_DATA_TO_LLM=False)")
                else:
                    _dbg(f"❌ data_query_polars result not captured - ok={result_payload.get('ok')}, keys={list(result_payload.keys())}")
            
            # Capture plot result from data_plot for frontend rendering
            if fn == "data_plot":
                _dbg(f"data_plot result: ok={result_payload.get('ok')}, type={type(result_payload)}")
                if isinstance(result_payload, dict) and "ok" in result_payload and result_payload["ok"]:
                    # Store the complete plot result for frontend
                    aggregated_plot_data = {
                        "plot_kwargs": result_payload["plot_kwargs"],
                        "plot_id": result_payload.get("plot_id"),
                        "plot_type": result_payload.get("plot_type"),
                        "is_interactive": result_payload.get("is_interactive"),
                        "row_count": result_payload.get("row_count"),
                        "expression": result_payload.get("expression"),
                        "source_id": result_payload.get("source_id"),
                        "data": result_payload.get("data"),  # Include transformed data for frontend
                        "ng_links_placeholder": result_payload.get("ng_links_placeholder"),
                    }
                    _dbg(f"✅ Captured plot data: type={result_payload['plot_type']}, interactive={result_payload['is_interactive']}")
                    
                    # Hide plot HTML from LLM (similar to query data)
                    if not SEND_DATA_TO_LLM:
                        result_payload = {
                            "ok": True,
                            "plot_id": result_payload.get("plot_id"),
                            "plot_type": result_payload.get("plot_type"),
                            "row_count": result_payload.get("row_count"),
                            "message": "✅ Plot generated successfully. The interactive plot is being rendered in the workspace. Do NOT describe or summarize the plot - it's already displayed."
                        }
                        _dbg(f"📦 Sending minimal acknowledgment to LLM (SEND_DATA_TO_LLM=False)")
                else:
                    error_msg = result_payload.get('error', 'Unknown error')
                    _dbg(f"❌ data_plot result not captured - ok={result_payload.get('ok')}, keys={list(result_payload.keys())}")
                    _dbg(f"❌ data_plot error message: {error_msg}")
            
            if fn == "data_ng_views_table" and isinstance(result_payload, dict):
                if "error" in result_payload and "rows" not in result_payload:
                    # Surface error to client (Option A) & log details (Option C)
                    trace_snip = None
                    if isinstance(result_payload.get("trace"), str):
                        trace_snip = result_payload["trace"][:400]
                    aggregated_views_table = {
                        "error": result_payload.get("error"),
                        "trace_snip": trace_snip,
                        "args": args,
                        # Surface warnings (new) so user sees per-row issues like missing coords
                        "warnings": result_payload.get("warnings"),
                    }
                    _dbg(f"views_table error surfaced error='{result_payload.get('error')}' trace_snip_len={len(trace_snip) if trace_snip else 0}")
                else:
                    aggregated_views_table = {
                        k: v for k, v in result_payload.items() if k in {"file_id","summary","n","rows","warnings","first_link"}
                    }
                    _dbg(f"Aggregated views_table set; keys={list(aggregated_views_table.keys()) if aggregated_views_table else None}; rows_len={len((aggregated_views_table or {}).get('rows',[]))}")
            if is_mutating_tool(fn):
                overall_mutated = True
            # Truncate large structures for token safety
            truncated = _truncate_tool_output(result_payload)
            # Store minimal trace info (avoid huge payloads)
            tool_execution_records.append({
                "tool": fn,
                "args": {k: (v if isinstance(v, (int, float, str, bool)) else str(v)[:120]) for k, v in (args or {}).items()},
                "result_keys": list(result_payload.keys())[:12],
            })
            full_trace_steps.append({
                "tool": fn,
                "raw_args": args,
                "full_result": result_payload,
            })
            conversation.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "name": fn,
                "content": truncated,
            })
        # Continue loop for next model reasoning pass
    
    # If we exhausted max_iters but still have pending tool results, get final response
    if iteration == max_iters - 1:
        # Check if last message is a tool result (not assistant)
        if conversation and conversation[-1].get("role") == "tool":
            _dbg("Max iterations reached but last message is tool result; making final LLM call")
            iter_timing = timing.start_iteration(max_iters)
            
            with timing.llm_call(iter_timing, model=MODEL) as llm_ctx:
                out = run_chat(conversation)
                usage = out.get("usage", {})
                if usage:
                    llm_ctx.set_tokens(
                        prompt=usage.get("prompt_tokens", 0),
                        completion=usage.get("completion_tokens", 0)
                    )
            
            choices = out.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    msg["content"] = _mask_ng_urls(content)
                conversation.append(msg)
                _dbg("Final response added after max_iters")
    
    timing.end_agent_loop()
    
    # After loop, optionally append state link if mutated and user likely wants it
    with timing.phase("response_assembly"):
        state_link_block = None
        if overall_mutated:
            try:
                url = CURRENT_STATE.to_url()
                masked = _mask_ng_urls(url)
                state_link_block = {"url": url, "masked_markdown": masked}
            except Exception:  # pragma: no cover
                logger.exception("Failed generating state link")

        # Update interaction memory (store last user + final assistant short snippet)
        try:
            user_last = next((m.content for m in reversed(req.messages) if m.role == "user"), None)
            if user_last:
                INTERACTION_MEMORY.remember(f"User:{(user_last or '')[:120]}")
            # Find last assistant message in conversation
            for cm in reversed(conversation):
                if cm.get("role") == "assistant" and cm.get("content"):
                    INTERACTION_MEMORY.remember(f"Assistant:{cm['content'][:300]}")
                    break
        except Exception:  # pragma: no cover
            logger.exception("Failed to update interaction memory")

        # Prepare final response shaped like OpenAI response with extra fields
        final_assistant = None
        for cm in reversed(conversation):
            if cm.get("role") == "assistant":
                final_assistant = cm
                break
        if final_assistant is None:
            final_assistant = {"role": "assistant", "content": "(no response)"}

        # Persist full trace (bounded)
        try:
            _TRACE_HISTORY.append({
                "mutated": overall_mutated,
                "final_message": final_assistant,
                "steps": full_trace_steps,
            })
            if len(_TRACE_HISTORY) > _TRACE_HISTORY_MAX:
                del _TRACE_HISTORY[:-_TRACE_HISTORY_MAX]
        except Exception:  # pragma: no cover
            logger.exception("Failed storing trace history")

        # If multi-view tool ran, override state_link with its first_link for continuity
        if aggregated_views_table and aggregated_views_table.get("first_link") and state_link_block is None:
            try:
                first_url = aggregated_views_table["first_link"]
                state_link_block = {"url": first_url, "masked_markdown": _mask_ng_urls(first_url)}
            except Exception:
                pass

    final_payload = {
        "model": "iterative",
        "choices": [{"index": 0, "message": final_assistant, "finish_reason": "stop"}],
        "usage": {},
        "mutated": overall_mutated,
        "state_link": state_link_block,
        "tool_trace": tool_execution_records,
        "views_table": aggregated_views_table,
        "ng_views": aggregated_ng_views,  # Expose ng_views for frontend rendering
        "query_data": aggregated_query_data,  # Expose full query result for frontend Tabulator rendering
        "plot_data": aggregated_plot_data,  # Expose plot result for frontend rendering
    }
    
    timing.mark("response_sent")
    timing.finalize()
    
    _dbg(f"Returning payload mutated={overall_mutated} state_link?={bool(state_link_block)} views_table_rows={len((aggregated_views_table or {}).get('rows', [])) if aggregated_views_table else 0}")
    _dbg(f"query_data present: {aggregated_query_data is not None}, rows: {aggregated_query_data.get('rows') if aggregated_query_data else 'N/A'}")
    _dbg(f"plot_data present: {aggregated_plot_data is not None}, type: {aggregated_plot_data.get('plot_type') if aggregated_plot_data else 'N/A'}")
    return final_payload


@app.get("/debug/test-logging")
def debug_test_logging():
    """Test endpoint to verify debug logging is working."""
    logger.debug("🧪 DEBUG log from test endpoint")
    logger.info("🧪 INFO log from test endpoint")
    logger.warning("🧪 WARNING log from test endpoint")
    _dbg("🧪 _dbg() call from test endpoint")
    return {
        "debug_enabled": DEBUG_ENABLED,
        "log_level": logging.getLevelName(logger.level),
        "root_level": logging.getLevelName(logging.getLogger().level),
        "message": "Check your console for log messages"
    }


@app.get("/debug/tool_trace")
def debug_tool_trace(n: int = 1):
    """Return the last n full tool traces (untruncated)."""
    n = max(1, min(n, 10))
    return {"traces": _TRACE_HISTORY[-n:]}


@app.get("/debug/timing")
def debug_timing(n: Optional[int] = None):
    """Return timing statistics and recent timing records.
    
    Args:
        n: Number of recent records to include (default: all available, max 100)
    
    Returns:
        JSON with summary stats and recent timing records table
    """
    from .observability.timing import get_timing_stats, get_recent_records
    
    stats = get_timing_stats()
    records = get_recent_records(n)
    
    return {
        "stats": stats,
        "records": records,
        "count": len(records)
    }


@app.get("/debug/logging-check")
def debug_logging_check():
    """Simple endpoint to test if debug logs appear in console."""
    print("🔥 PRINT: debug_logging_check endpoint was called!")
    logger.debug("🧪 DEBUG: This is a debug-level log")
    logger.info("🧪 INFO: This is an info-level log")
    logger.warning("🧪 WARNING: This is a warning-level log")
    _dbg("🧪 _DBG: This is a _dbg() call")
    
    return {
        "status": "ok",
        "debug_enabled": DEBUG_ENABLED,
        "logger_level": logging.getLevelName(logger.level),
        "root_logger_level": logging.getLevelName(logging.getLogger().level),
        "message": "Check your backend console for 5 log messages (1 print + 4 logs)"
    }


def _truncate_tool_output(obj, max_chars: int = 4000):
    import json as _json
    try:
        s = _json.dumps(obj)[:max_chars]
        return s
    except Exception:
        return str(obj)[:max_chars]


def _resolve_summary_id(summary_id: str | None) -> str | None:
    """Resolve special summary_id values like 'last' to actual IDs.
    
    Allows users/LLM to reference the most recent query result without
    needing to track the exact summary_id.
    """
    if summary_id == "last" or summary_id == "latest":
        if LAST_QUERY_SUMMARY_ID:
            _dbg(f"Resolved summary_id='{summary_id}' to '{LAST_QUERY_SUMMARY_ID}'")
            return LAST_QUERY_SUMMARY_ID
        else:
            _dbg(f"summary_id='{summary_id}' requested but no previous query exists")
            return None
    return summary_id


def _execute_tool_by_name(name: str, args: dict):
    """Dispatcher for internal tool execution (server-side)."""
    # Directly call the endpoint functions with Pydantic model instantiation
    try:
        if name == "ng_set_view":
            from .models import SetView
            return t_set_view(SetView(**args))
        if name == "ng_set_lut":
            from .models import SetLUT
            return t_set_lut(SetLUT(**args))
        if name == "ng_add_layer":
            from .models import AddLayer
            return t_add_layer(AddLayer(**args))
        if name == "ng_set_layer_visibility":
            from .models import SetLayerVisibility
            return t_set_layer_visibility(SetLayerVisibility(**args))
        if name == "ng_annotations_add":
            from .models import AddAnnotations
            return t_add_annotations(AddAnnotations(**args))
        if name == "data_plot_histogram":
            from .models import HistogramReq
            return t_hist(HistogramReq(**args))
        if name == "data_ingest_csv_rois":
            from .models import IngestCSV
            return t_csv(IngestCSV(**args))
        if name == "state_save":
            from .models import SaveState
            return t_save_state(SaveState())
        if name == "state_load":
            from .models import StateLoad
            return t_state_load(StateLoad(**args))
        if name == "ng_state_summary":
            from .models import StateSummary
            return t_state_summary(StateSummary(**args))
        if name == "ng_state_link":
            return t_state_link()
        if name == "data_list_files":
            return t_data_list_files()
        if name == "data_info":
            from .models import DataInfo
            return t_data_info(DataInfo(**args))
        if name == "data_preview":
            from .models import DataPreview
            return t_data_preview(DataPreview(**args))
        if name == "data_describe":
            from .models import DataDescribe
            return t_data_describe(DataDescribe(**args))
        if name == "data_list_summaries":
            return t_data_list_summaries()
        if name == "data_query_polars":
            from .models import DataQuery
            _dbg(f"Dispatching data_query_polars with args: {args}")
            return t_data_query_polars(DataQuery(**args))
        if name == "data_plot":
            from .models import DataPlot
            _dbg(f"Dispatching data_plot with args: {args}")
            return t_data_plot(DataPlot(**args))
        if name == "data_ng_views_table":
            from .models import NgViewsTable
            return t_data_ng_views_table(NgViewsTable(**args))
        if name == "data_ng_annotations_from_data":
            from .models import NgAnnotationsFromData
            _dbg(f"Dispatching data_ng_annotations_from_data with args: {args}")
            return t_data_ng_annotations_from_data(NgAnnotationsFromData(**args))
        if name == "data_list_plots":
            return t_data_list_plots()
    except Exception as e:  # pragma: no cover
        logger.exception("Tool execution error")
        return {"error": str(e)}
    return {"error": f"Unknown tool {name}"}


def _mask_ng_urls(text: str) -> str:
    """Replace full Neuroglancer URLs with a concise markdown hyperlink.

    Each distinct URL is collapsed to the label 'Updated Neuroglancer view'. If
    multiple different URLs appear, they will receive a numeric suffix to
    differentiate: 'Updated Neuroglancer view (2)', etc.
    
    Skips masking if the text already contains markdown table with [view](...) links
    to avoid double-wrapping.
    """
    logger.info(f"{text}")
    import re
    
    # Check if text contains markdown table with [view](...) links (from query results)
    # Pattern: | ... | [view](https://...) |
    if re.search(r'\|\s*\[view\]\(https?://[^\)]+\)\s*\|', text):
        _dbg("Skipping URL masking - text contains markdown table with [view] links")
        return text
    
    url_pattern = re.compile(r"https?://[^\s)]+")
    candidates = url_pattern.findall(text)
    urls = [u for u in candidates if 'neuroglancer' in u]
    # Also detect tokens missing scheme but containing neuroglancer + fragment (#!%7B)
    if 'neuroglancer' in text and '#!%7B' in text:
        tokens = re.split(r"\s+", text)
        for tok in tokens:
            if 'neuroglancer' in tok and '#!%7B' in tok and 'http' not in tok:
                urls.append(tok)
    if not urls:
        return text
    ordered = []
    seen = set()
    for u in urls:
        if u not in seen:
            ordered.append(u)
            seen.add(u)
    label_map = {}
    for idx, u in enumerate(ordered):
        base = "Updated Neuroglancer view" if idx == 0 else f"Updated Neuroglancer view ({idx+1})"
        label_map[u] = f"[{base}]({u})"
    for raw_url, repl in label_map.items():
        text = text.replace(raw_url, repl)
    return text


@app.post("/tools/ng_state_link")
def t_state_link():
    """Return current state link and masked markdown without persisting a new save id."""
    url = CURRENT_STATE.to_url()
    masked = _mask_ng_urls(url)
    if masked == url:
        masked = f"[Updated Neuroglancer view]({url})"
    return {"url": url, "masked_markdown": masked}


def _synthesize_tool_call_message(tool_calls) -> str:
    """Create a concise assistant message summarizing tool calls (no link).

    We intentionally do NOT embed a Neuroglancer state URL here because at this
    point the client has not yet executed the tool calls; embedding a link
    would show a stale pre-mutation state. The client can separately call
    /tools/state_save (optionally with masking) AFTER applying tools to obtain
    the authoritative updated link.
    """
    try:
        names = []
        for tc in tool_calls:
            fn = (tc.get("function") or {}).get("name") or tc.get("type") or "tool"
            names.append(fn)
        tool_list = ", ".join(names)
        return f"Applied tools: {tool_list}."
    except Exception:
        return "Applied tools."  # fallback


def summarize_state_struct(state, detail: str = "standard") -> dict:
    """Produce a structured summary for LLM inspection.

    detail levels:
      - minimal: only layer name & type
      - standard: adds counts & ranges
      - full: adds shader length and source kinds
    """
    layers_out = []
    sd = _state_dict(state)
    for L in sd.get("layers", []):
        base = {"name": L.get("name"), "type": L.get("type")}
        ltype = L.get("type")
        if detail in ("standard", "full"):
            if ltype == "image":
                src = L.get("source")
                if isinstance(src, list):
                    base["num_sources"] = len(src)
                    kinds = []
                    for s in src:
                        if isinstance(s, dict):
                            url = s.get("url", "")
                            if "://" in url:
                                kinds.append(url.split("://",1)[0])
                    if kinds:
                        base["source_kinds"] = sorted(set(kinds))
                rng = (L.get("shaderControls") or {}).get("normalized", {}).get("range")
                if rng:
                    base["normalized_range"] = rng
            elif ltype == "annotation":
                # Annotations are now at layer level, not in source
                anns = L.get("annotations") or []
                base["annotation_count"] = len(anns)
        if detail == "full":
            shader = L.get("shader")
            if shader:
                base["shader_len"] = len(shader)
        layers_out.append(base)

    annotation_layers = []
    for L in sd.get("layers", []):
        if L.get("type") == "annotation":
            # Annotations are now at layer level, not in source
            anns = L.get("annotations") or []
            types = set()
            for a in anns:
                t = a.get("type") or ("point" if "point" in a else None)
                if t:
                    types.add(t)
            annotation_layers.append({
                "name": L.get("name"),
                "count": len(anns),
                "types": sorted(types)
            })

    return {
    "layout": sd.get("layout"),
    "position": sd.get("position"),
    "dimensions": sd.get("dimensions"),
        "layers": layers_out,
        "annotation_layers": annotation_layers,
        "flags": {
            "showAxisLines": sd.get("showAxisLines"),
            "showScaleBar": sd.get("showScaleBar"),
        },
        "version": 1,
        "detail": detail,
    }


@app.post("/tools/ng_state_summary")
def t_state_summary(args: StateSummary):
    return summarize_state_struct(CURRENT_STATE, detail=args.detail)

# ------------------- Data tool endpoints -------------------

@app.post("/upload_file")
async def upload_file(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        meta = DATA_MEMORY.add_file(file.filename, raw)
        return {"ok": True, "file": meta}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/tools/data_list_files")
def t_data_list_files():
    return {"files": DATA_MEMORY.list_files()}

@app.post("/tools/data_info")
def t_data_info(args: DataInfo):
    try:
        df = DATA_MEMORY.get_df(args.file_id)
        sample_rows = max(1, min(args.sample_rows, 20))
        sample = df.head(sample_rows).to_dicts()
        dtypes = {c: str(dt) for c, dt in zip(df.columns, df.dtypes)}
        return {
            "file_id": args.file_id,
            "n_rows": df.height,
            "n_cols": df.width,
            "columns": df.columns,
            "dtypes": dtypes,
            "sample": sample,
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/tools/data_preview")
def t_data_preview(args: DataPreview):
    try:
        df = DATA_MEMORY.get_df(args.file_id)
        n = max(1, min(args.n, 100))
        return {"file_id": args.file_id, "rows": df.head(n).to_dicts(), "columns": df.columns}
    except Exception as e:
        return {"error": str(e)}

@app.post("/tools/data_describe")
def t_data_describe(args: DataDescribe):
    try:
        df = DATA_MEMORY.get_df(args.file_id)
        desc = df.describe()
        meta = DATA_MEMORY.add_summary(args.file_id, "describe", desc, note="numeric describe")
        return {"summary": meta, "rows": desc.to_dicts()}
    except Exception as e:
        return {"error": str(e)}

@app.post("/tools/data_list_summaries")
def t_data_list_summaries():
    return {"summaries": DATA_MEMORY.list_summaries()}


# ==============================================================================
# Core Tool Logic Functions
# ==============================================================================
# These functions contain pure business logic and can be called from:
# 1. HTTP endpoints (via wrapper functions below)
# 2. Internal tool dispatcher (direct calls from LLM)
# 
# Benefits:
# - No Body() object handling needed
# - Easy to test without FastAPI
# - Clean separation of HTTP concerns from business logic
# - Reusable in other contexts (CLI, SDK, etc.)
# ==============================================================================

def execute_query_polars(
    file_id: str | None = None,
    summary_id: str | None = None,
    expression: str = None,
    save_as: str | None = None,
    limit: int = 100
) -> dict:
    """Core logic for executing Polars expressions on dataframes.
    
    Pure business logic with no FastAPI dependencies. Can be called from
    HTTP endpoints or internal dispatcher.
    
    Args:
        file_id: Source file ID (mutually exclusive with summary_id)
        summary_id: Source summary table ID (mutually exclusive with file_id)
        expression: Polars expression to execute
        save_as: Optional name to save result as summary table
        limit: Maximum rows to return
        
    Returns:
        Dict with result data or error message
    """
    import polars as pl
    
    _dbg(f"execute_query_polars: file_id={repr(file_id)}, summary_id={repr(summary_id)}, save_as={repr(save_as)}, limit={limit}, expression={expression[:50] if expression else 'None'}...")
    
    # Get source dataframe
    if file_id and summary_id:
        return {
            "error": f"Provide either file_id OR summary_id, not both. Received file_id='{str(file_id)}' and summary_id='{str(summary_id)}'. Use file_id for uploaded files or summary_id for previously saved results."
        }
    
    if not file_id and not summary_id:
        # Auto-select most recent file if available
        files = DATA_MEMORY.list_files()
        if files:
            file_id = files[-1]["file_id"]  # Most recent file
            _dbg(f"No file_id or summary_id provided, auto-using most recent file: {file_id}")
        else:
            summaries = DATA_MEMORY.list_summaries()
            return {
                "error": "No file_id or summary_id provided and no files uploaded.",
                "available_summaries": [s["summary_id"] for s in summaries] if summaries else [],
                "hint": "Upload a file first, or provide summary_id to query a saved result."
            }
    
    try:
        if file_id:
            df = DATA_MEMORY.get_df(file_id)
            source_id = file_id
            if df is None:
                return {"error": f"File '{file_id}' not found"}
        else:
            df = DATA_MEMORY.get_summary_df(summary_id)
            source_id = summary_id
            if df is None:
                return {"error": f"Summary '{summary_id}' not found"}
    except Exception as e:
        return {"error": f"Failed to load dataframe: {e}"}
    
    # Execute in restricted namespace (only Polars, no builtins)
    namespace = {
        'pl': pl,
        'df': df,
        '__builtins__': {}  # Critical: blocks import, open, eval, exec, etc.
    }
    
    try:
        result = eval(expression, namespace, {})
        
        # Handle different result types
        if isinstance(result, pl.DataFrame):
            # Standard DataFrame result
            pass
        elif isinstance(result, pl.Series):
            # Convert Series to single-column DataFrame
            result = pl.DataFrame({result.name or "value": result})
        elif isinstance(result, list):
            # List result (e.g., from .to_list()) - wrap in DataFrame
            result = pl.DataFrame({"values": result})
        elif isinstance(result, dict):
            # Dict result - try to convert to DataFrame
            try:
                result = pl.DataFrame(result)
            except Exception:
                # If conversion fails, wrap the dict
                result = pl.DataFrame({"result": [str(result)]})
        elif isinstance(result, (int, float, str, bool, type(None))):
            # Scalar result - wrap in DataFrame
            result = pl.DataFrame({"result": [result]})
        else:
            return {
                "error": f"Expression must return a DataFrame, Series, list, dict, or scalar value. Got {type(result).__name__}. "
                "Hint: Remove .to_list() or .to_dict() and just return the DataFrame/Series."
            }
        
        # Apply limit
        if len(result) > limit:
            result = result.limit(limit)
            truncated = True
        else:
            truncated = False
        
        # Round numeric columns to 2 decimal places for readability
        for col in result.columns:
            if result[col].dtype in [pl.Float32, pl.Float64]:
                result = result.with_columns(pl.col(col).round(2))
        
        # Detect spatial columns and generate Neuroglancer links
        spatial_info = _detect_spatial_columns(result)
        ng_links = None
        if spatial_info and len(result) > 0 and len(result) <= 100:  # Only for reasonable row counts
            spatial_cols, pattern = spatial_info
            _dbg(f"Detected spatial columns: {spatial_cols} (pattern: {pattern})")
            ng_links = _generate_ng_links_for_rows(result, spatial_cols)
            _dbg(f"Generated {len([l for l in ng_links if l])} NG links")
        
        # Always save query results (auto-save if save_as not provided)
        global LAST_QUERY_SUMMARY_ID
        
        if not save_as:
            # Auto-generate a summary name based on timestamp
            import time
            save_as = f"query_{int(time.time() * 1000) % 1000000}"  # Last 6 digits of timestamp
        
        summary_meta = DATA_MEMORY.add_summary(source_id, "query", result, note=f"Query: {expression[:100]}")
        summary_id = summary_meta["summary_id"]
        LAST_QUERY_SUMMARY_ID = summary_id  # Track for 'last' reference
        
        _dbg(f"Query result auto-saved as summary_id: {summary_id}")
        
        # Return result with hint about reusing data
        return_data = {
            "ok": True,
            "data": result.to_dict(as_series=False),
            "rows": len(result),
            "columns": result.columns,
            "truncated": truncated,
            "summary_id": summary_id,  # Always include the auto-saved summary_id
            "saved_as": save_as,
            "expression": expression  # Include the expression for code formatting
        }
        
        # Add structured NG views if generated (hybrid approach: backend provides URLs, frontend renders)
        if ng_links:
            # Convert to structured format with row indices
            return_data["ng_views"] = [
                {"row_index": i, "url": url} 
                for i, url in enumerate(ng_links) if url
            ]
            return_data["spatial_columns"] = spatial_info[0]
        
        # Add message about how to use the saved result
        if len(result) > 0:
            return_data["message"] = f"✅ Query executed successfully. Data is being rendered in an interactive table widget. Do NOT format, display, or summarize the data - it's already handled by the frontend. Result saved as summary_id='{summary_id}' ({len(result)} rows). You can use this summary_id in follow-up tools like data_ng_annotations_from_data, data_plot, or for further queries."
        else:
            return_data["message"] = f"✅ Query executed successfully (0 rows). Result saved as summary_id='{summary_id}'."
        
        return return_data
    
    except NameError as e:
        _dbg(f"NameError in expression: {e}")
        return {"error": f"Invalid expression: {e}. Only 'df' and 'pl' are available."}
    except SyntaxError as e:
        _dbg(f"SyntaxError in expression: {e}")
        return {"error": f"Syntax error in expression: {e}"}
    except Exception as e:
        _dbg(f"Exception executing expression: {type(e).__name__}: {e}")
        return {"error": f"Expression execution failed: {type(e).__name__}: {e}"}


@app.post("/tools/data_query_polars")
def t_data_query_polars(args: DataQuery):
    """HTTP endpoint wrapper for data_query_polars.
    
    Extracts parameters from Pydantic model and delegates to core logic.
    """
    return execute_query_polars(
        file_id=args.file_id,
        summary_id=args.summary_id,
        expression=args.expression,
        save_as=args.save_as,
        limit=args.limit
    )


@app.post("/tools/data_ng_views_table")
def t_data_ng_views_table(args: NgViewsTable):
    """Generate multiple Neuroglancer view links (not persisted) and return a table.

    Strategy: mutate state sequentially but finalize CURRENT_STATE to the FIRST view
    for user continuity. Returns table rows with raw + masked links and stores a
    summary table in DataMemory (kind='ng_views').
    """
    from copy import deepcopy
    global CURRENT_STATE
    warnings: list[str] = []
    
    # Extract parameters from Pydantic model
    file_id = args.file_id
    summary_id = args.summary_id
    sort_by = args.sort_by
    descending = args.descending
    top_n = args.top_n
    id_column = args.id_column
    center_columns = args.center_columns
    include_columns = args.include_columns
    lut = args.lut
    annotations = args.annotations
    link_label_column = args.link_label_column
    
    if DEBUG_ENABLED:
        _dbg(f"NgViewsTable params -> file_id={file_id} summary_id={summary_id}")
    
    if not file_id and not summary_id:
        return {"error": "Must provide file_id or summary_id"}
    try:
        if file_id and summary_id:
            warnings.append("Both file_id and summary_id provided; using summary_id")
        if summary_id:
            df = DATA_MEMORY.get_summary_df(summary_id)
            source_fid = DATA_MEMORY.get_summary_record(summary_id).source_file_id
        else:
            df = DATA_MEMORY.get_df(file_id)  # type: ignore[arg-type]
            source_fid = file_id  # type: ignore[assignment]
        top_n = max(1, min(top_n, 50))
        cols_needed = set([id_column, *center_columns])
        missing = [c for c in cols_needed if c not in df.columns]
        if missing:
            return {"error": f"Missing required columns: {missing}"}
        work_df = df
        if sort_by:
            if sort_by not in df.columns:
                return {"error": f"sort_by column '{sort_by}' not found", "available_columns": df.columns}
            work_df = df.sort(sort_by, descending=descending)
        subset = work_df.head(top_n)
        if DEBUG_ENABLED:
            _dbg(f"views_table subset height={subset.height} top_n={top_n} sort_by={sort_by} descending={descending}")
            if subset.height:
                # Log first row preview (selected key columns only)
                fr = subset.head(1).to_dicts()[0]
                preview_keys = [id_column, *center_columns]
                preview = {k: fr.get(k) for k in preview_keys if k in fr}
                _dbg(f"views_table first_row_preview={preview}")
        include_columns = include_columns or []
        missing_includes = [c for c in include_columns if c not in df.columns]
        if missing_includes:
            warnings.append(f"Ignored missing include columns: {missing_includes}")
            include_columns = [c for c in include_columns if c in df.columns]

        rows = []
        first_state = None
        # We'll generate links from ephemeral mutated copies; not persisting with save_state
        for idx, row in enumerate(subset.to_dicts()):
            # mutate copy of CURRENT_STATE using cheap deep clone
            state_copy = CURRENT_STATE.clone()
            try:
                # set view center; reuse internal set_view logic
                cx, cy, cz = (row[center_columns[0]], row[center_columns[1]], row[center_columns[2]])
                state_copy.set_view({"x": cx, "y": cy, "z": cz}, None, None)
                # LUT optionally
                if lut and lut.get("layer") and "min" in lut and "max" in lut:
                    state_copy.set_lut(lut["layer"], lut.get("min"), lut.get("max"))
                # annotation optionally
                if annotations:
                    ann_items = [
                        {"point": [cx, cy, cz], "id": str(row.get(id_column, idx))}
                    ]
                    state_copy.add_annotations("annotations", ann_items)
                link_url = state_copy.to_url()
                masked = _mask_ng_urls(link_url)
                if masked == link_url:
                    masked = f"[link]({link_url})"
                else:
                    # Replace default label text with simple 'link'
                    masked = re.sub(r"\[(Updated Neuroglancer view(?: \(\d+\))?)\]", "[link]", masked)
                record = {
                    id_column: row.get(id_column),
                    "link": link_url,
                    "masked_link": masked,
                }
                for c in include_columns:
                    record[c] = row.get(c)
                if link_label_column and link_label_column in row:
                    record["label"] = row[link_label_column]
                rows.append(record)
                if first_state is None:
                    first_state = state_copy
                if DEBUG_ENABLED:
                    _dbg(f"views_table row {idx} processed id={record.get(id_column)}")
            except Exception as e:  # pragma: no cover
                warnings.append(f"Row {idx} error: {e}")
                if DEBUG_ENABLED:
                    _dbg(f"views_table row {idx} exception: {e}")
                continue
        if not rows:
            if DEBUG_ENABLED:
                _dbg(f"views_table abort: 0 rows succeeded; warnings_count={len(warnings)}")
            return {"error": "No rows processed", "warnings": warnings}
        # finalize CURRENT_STATE to first view state
        if first_state is not None:
            CURRENT_STATE = first_state
        # Build summary dataframe (exclude raw link?) keep masked link + metrics
        table_df = pl.DataFrame([
            {k: v for k, v in r.items() if k != "link"} for r in rows
        ])
        meta = DATA_MEMORY.add_summary(source_fid, "ng_views", table_df, note="multi-view table")
        return {
            "file_id": source_fid,
            "summary": meta,
            "n": len(rows),
            "rows": rows,
            "warnings": warnings,
            "first_link": rows[0]["link"],
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "trace": traceback.format_exc()}


@app.post("/tools/data_ng_annotations_from_data")
def t_data_ng_annotations_from_data(args: NgAnnotationsFromData):
    """Create Neuroglancer annotations directly from dataframe rows.
    
    Each row in the source dataframe becomes one annotation. This is the preferred
    way to add annotations from tabular data (rather than data_query_polars + ng_annotations_add
    which doesn't work due to data isolation).
    """
    global CURRENT_STATE
    
    file_id = args.file_id
    summary_id = _resolve_summary_id(args.summary_id)  # Resolve 'last' or 'latest' to actual ID
    layer_name = args.layer_name
    annotation_type = args.annotation_type
    center_columns = args.center_columns
    size_columns = args.size_columns
    id_column = args.id_column
    color = args.color
    filter_expression = args.filter_expression
    limit = args.limit
    
    if DEBUG_ENABLED:
        _dbg(f"data_ng_annotations_from_data -> file_id={file_id} summary_id={summary_id} layer={layer_name}")
    
    # Validate inputs
    if not file_id and not summary_id:
        # Auto-select: prefer most recent query result, fallback to most recent file
        if LAST_QUERY_SUMMARY_ID:
            summary_id = LAST_QUERY_SUMMARY_ID
            _dbg(f"Auto-selected most recent query result: {summary_id}")
        else:
            files = DATA_MEMORY.list_files()
            if files:
                file_id = files[-1]["file_id"]
                _dbg(f"No recent query, auto-selected most recent file: {file_id}")
            else:
                return {"error": "No file_id or summary_id provided and no files uploaded"}
    
    if file_id and summary_id:
        return {"error": "Provide either file_id OR summary_id, not both"}
    
    try:
        # Get source dataframe
        if file_id:
            df = DATA_MEMORY.get_df(file_id)
            source_fid = file_id
        else:
            df = DATA_MEMORY.get_summary_df(summary_id)
            source_fid = DATA_MEMORY.get_summary_record(summary_id).source_file_id
        
        # Apply filter expression if provided
        if filter_expression:
            _dbg(f"Applying filter_expression: {filter_expression[:200]}")
            try:
                namespace = {'pl': pl, 'df': df, '__builtins__': {}}
                result = eval(filter_expression, namespace, {})
                
                if isinstance(result, pl.DataFrame):
                    df = result
                elif isinstance(result, pl.Series):
                    df = pl.DataFrame({result.name or "value": result})
                else:
                    return {"error": f"filter_expression must return a DataFrame or Series, got {type(result).__name__}"}
            except Exception as e:
                return {"error": f"filter_expression failed: {e}"}
        
        # Validate required columns exist
        missing_cols = [c for c in center_columns if c not in df.columns]
        if missing_cols:
            return {"error": f"Missing required center columns: {missing_cols}", "available_columns": df.columns}
        
        if annotation_type in ["box", "ellipsoid"] and not size_columns:
            return {"error": f"annotation_type '{annotation_type}' requires size_columns parameter"}
        
        if size_columns:
            missing_size_cols = [c for c in size_columns if c not in df.columns]
            if missing_size_cols:
                return {"error": f"Missing size columns: {missing_size_cols}", "available_columns": df.columns}
        
        # Limit rows
        if df.height > limit:
            _dbg(f"Limiting from {df.height} to {limit} rows")
            df = df.head(limit)
        
        # Create annotation layer if it doesn't exist, or ensure it exists with color
        layer_exists = any(L.get("name") == layer_name and L.get("type") == "annotation" 
                          for L in CURRENT_STATE.data.get("layers", []))
        
        if not layer_exists:
            CURRENT_STATE.add_layer(layer_name, "annotation", annotation_color=color)
            _dbg(f"Created annotation layer '{layer_name}' with color {color}")
        elif color:
            # Update color on existing layer
            for L in CURRENT_STATE.data.get("layers", []):
                if L.get("name") == layer_name and L.get("type") == "annotation":
                    L["annotationColor"] = color
                    _dbg(f"Updated color on existing layer '{layer_name}' to {color}")
                    break
        
        # Build annotation items from dataframe rows
        items = []
        for idx, row in enumerate(df.to_dicts()):
            try:
                cx = float(row[center_columns[0]])
                cy = float(row[center_columns[1]])
                cz = float(row[center_columns[2]])
                
                # Generate unique ID: prefer id_column if provided, otherwise generate UUID
                if id_column and id_column in row:
                    ann_id = str(row[id_column])
                else:
                    import uuid
                    ann_id = str(uuid.uuid4())
                
                if annotation_type == "point":
                    items.append({
                        "point": [cx, cy, cz],
                        "type": "point",
                        "id": ann_id
                    })
                elif annotation_type == "box":
                    sx = float(row[size_columns[0]])
                    sy = float(row[size_columns[1]])
                    sz = float(row[size_columns[2]])
                    items.append({
                        "type": "axis_aligned_bounding_box",
                        "pointA": [cx - sx/2, cy - sy/2, cz - sz/2],
                        "pointB": [cx + sx/2, cy + sy/2, cz + sz/2],
                        "id": ann_id
                    })
                elif annotation_type == "ellipsoid":
                    rx = float(row[size_columns[0]]) / 2
                    ry = float(row[size_columns[1]]) / 2
                    rz = float(row[size_columns[2]]) / 2
                    items.append({
                        "type": "ellipsoid",
                        "center": [cx, cy, cz],
                        "radii": [rx, ry, rz],
                        "id": ann_id
                    })
            except Exception as e:
                _dbg(f"Skipping row {idx} due to error: {e}")
                continue
        
        if not items:
            return {"error": "No valid annotation items created from dataframe"}
        
        # Add annotations to the layer
        CURRENT_STATE.add_annotations(layer_name, items)
        
        _dbg(f"Added {len(items)} annotations to layer '{layer_name}'")
        
        return {
            "ok": True,
            "layer": layer_name,
            "annotation_type": annotation_type,
            "count": len(items),
            "source": source_fid,
            "message": f"✅ Added {len(items)} {annotation_type} annotations to layer '{layer_name}'"
        }
        
    except Exception as e:
        import traceback
        logger.exception("data_ng_annotations_from_data error")
        return {"error": str(e), "trace": traceback.format_exc()}


# ==============================================================================
# Plotting Tools
# ==============================================================================

def execute_plot(
    file_id: str | None = None,
    summary_id: str | None = None,
    plot_type: str = "scatter",
    x: str = None,
    y: str = None,
    by: str | None = None,
    size: str | None = None,
    color: str | None = None,
    stacked: bool = False,
    title: str | None = None,
    expression: str | None = None,
    save_plot: bool = True,
    width: int = 700,
    height: int = 400,
    interactive_override: bool | None = None
) -> dict:
    """Core logic for generating plot specifications from dataframes.
    
    Returns plot parameters and data reference so frontend can render natively in Panel.
    
    Args:
        file_id: Source file ID (mutually exclusive with summary_id)
        summary_id: Source summary table ID (mutually exclusive with file_id)
        plot_type: 'scatter', 'line', 'bar', or 'heatmap'
        x: X-axis column name
        y: Y-axis column name
        by: Grouping column
        size: Point size column (scatter only)
        color: Point color column (scatter only)
        stacked: Stack bars (bar only)
        title: Plot title
        expression: Optional Polars expression to transform data first
        save_plot: Store plot in DataMemory
        width: Plot width in pixels
        height: Plot height in pixels
        interactive_override: Force interactive on/off (None = auto)
        
    Returns:
        Dict with plot_kwargs, source_id, and metadata or error
    """
    from .tools.plotting import validate_plot_requirements, build_plot_spec
    
    _dbg(f"execute_plot: file_id={file_id}, summary_id={summary_id}, plot_type={plot_type}, x={x}, y={y}")
    
    # Validate inputs
    if not x or not y:
        return {"error": "Both 'x' and 'y' parameters are required"}
    
    if file_id and summary_id:
        return {"error": "Provide either file_id OR summary_id, not both"}
    
    # Auto-select most recent file if neither provided
    if not file_id and not summary_id:
        files = DATA_MEMORY.list_files()
        if files:
            file_id = files[-1]["file_id"]
            _dbg(f"Auto-selected most recent file: {file_id}")
        else:
            return {"error": "No file_id or summary_id provided and no files uploaded"}
    
    # Get source dataframe
    try:
        if file_id:
            df = DATA_MEMORY.get_df(file_id)
            source_id = file_id
        else:
            df = DATA_MEMORY.get_summary_df(summary_id)
            source_id = summary_id
    except Exception as e:
        return {"error": f"Failed to load dataframe: {e}"}
    
    # Apply expression if provided
    if expression:
        _dbg(f"Applying expression before plotting: {expression[:100]}")
        try:
            namespace = {'pl': pl, 'df': df, '__builtins__': {}}
            result = eval(expression, namespace, {})
            
            if isinstance(result, pl.DataFrame):
                df = result
            elif isinstance(result, pl.Series):
                df = pl.DataFrame({result.name or "value": result})
            else:
                return {"error": f"Expression must return a DataFrame or Series, got {type(result).__name__}"}
        except Exception as e:
            return {"error": f"Expression execution failed: {e}"}
    
    # Ensure spatial columns are included if they exist and aren't already
    spatial_info = _detect_spatial_columns(df)
    if spatial_info:
        spatial_cols, pattern = spatial_info
        # Check if all spatial columns are present
        missing_spatial = [c for c in spatial_cols if c not in df.columns]
        if missing_spatial:
            _dbg(f"Spatial columns detected in source but missing after expression: {missing_spatial}")
    
    # Validate plot requirements
    params = {'x': x, 'y': y, 'by': by, 'size': size, 'color': color}
    validation = validate_plot_requirements(df, plot_type, params)
    
    if not validation['valid']:
        return {
            "error": "Plot validation failed",
            "issues": validation['issues'],
            "suggestions": validation['suggestions']
        }
    
    # Build plot specification
    plot_result = build_plot_spec(
        df=df,
        plot_type=plot_type,
        x=x,
        y=y,
        by=by,
        size=size,
        color=color,
        stacked=stacked,
        title=title,
        width=width,
        height=height,
        interactive_override=interactive_override
    )
    
    if 'error' in plot_result:
        return plot_result
    
    # Store plot spec if requested
    plot_id = None
    if save_plot:
        plot_spec = plot_result['plot_kwargs'].copy()
        plot_spec['plot_type'] = plot_type
        plot_meta = DATA_MEMORY.add_plot(
            source_id=source_id,
            plot_type=plot_type,
            plot_html="",  # No HTML, frontend will render
            plot_spec=plot_spec,
            expression=expression
        )
        plot_id = plot_meta['plot_id']
    
    # Convert transformed dataframe to dict format for frontend
    plot_data_rows = df.to_dicts()
    
    return {
        "ok": True,
        "plot_id": plot_id,
        "plot_kwargs": plot_result['plot_kwargs'],
        "plot_type": plot_result['plot_type'],
        "is_interactive": plot_result['is_interactive'],
        "row_count": plot_result['row_count'],
        "ng_links_placeholder": plot_result.get('ng_links_placeholder'),
        "expression": expression,
        "source_id": source_id,
        "data": plot_data_rows,  # Send the transformed data directly
        "warnings": validation.get('suggestions', [])
    }


@app.post("/tools/data_plot")
def t_data_plot(args: DataPlot):
    """HTTP endpoint wrapper for data_plot.
    
    Generates interactive plot from dataframe data.
    """
    return execute_plot(
        file_id=args.file_id,
        summary_id=args.summary_id,
        plot_type=args.plot_type,
        x=args.x,
        y=args.y,
        by=args.by,
        size=args.size,
        color=args.color,
        stacked=args.stacked,
        title=args.title,
        expression=args.expression,
        save_plot=args.save_plot,
        width=args.width,
        height=args.height,
        interactive_override=args.interactive_override
    )


@app.post("/tools/data_list_plots")
def t_data_list_plots():
    """List all generated plots (metadata only)."""
    return {"plots": DATA_MEMORY.list_plots()}


# ==============================================================================
# End Plotting Tools
# ==============================================================================

@app.post("/system/reset")
def system_reset():
    """Reset the entire application state - clear all memory, data, and chat history."""
    global CURRENT_STATE, DATA_MEMORY, INTERACTION_MEMORY, _TRACE_HISTORY, LAST_QUERY_SUMMARY_ID
    
    logger.info("System reset requested - clearing all state")
    
    # Reset all global state variables to fresh instances
    CURRENT_STATE = NeuroglancerState()
    DATA_MEMORY = DataMemory()
    INTERACTION_MEMORY = InteractionMemory()
    _TRACE_HISTORY = []
    LAST_QUERY_SUMMARY_ID = None
    
    logger.info("System reset complete - all memory flushed")
    
    return {
        "status": "success",
        "message": "Application state has been reset. All data, chat history, and memory have been cleared."
    }