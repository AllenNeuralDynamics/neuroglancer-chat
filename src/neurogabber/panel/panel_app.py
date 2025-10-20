import os, json, httpx, asyncio, re, panel as pn, io
from datetime import datetime
from contextlib import contextmanager
from panel.chat import ChatInterface
from panel_neuroglancer import Neuroglancer
import polars as pl
import pandas as pd
import logging

# Import pointer expansion functionality
from neurogabber.backend.tools.pointer_expansion import (
    expand_if_pointer_and_generate_inline,
    is_pointer_url
)

# setup debug logging

FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
def reconfig_basic_config(format_=FORMAT, level=logging.INFO):
    """(Re-)configure logging"""
    logging.basicConfig(format=format_, level=level, force=True)
    logging.info("Logging.basicConfig completed successfully")

reconfig_basic_config()
logger = logging.getLogger(name="app")

# get version from package metadata init
from importlib.metadata import version
version = version("neurogabber")
pn.extension(
    'tabulator',
    'filedropper',
    'floatpanel',
    theme='dark',
    css_files=[
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css"
    ],
)

BACKEND = os.environ.get("BACKEND", "http://127.0.0.1:8000")
USE_STREAMING = os.environ.get("USE_STREAMING", "true").lower() == "true"

viewer = Neuroglancer()
status = pn.pane.Markdown("Ready.")

# Track last loaded Neuroglancer URL (dedupe reloads)
last_loaded_url: str | None = None
_trace_history = []
_full_table_data = {}  # Store full table data for modal: {message_id: full_table_text}

# Mutation detection now handled server-side; state link returned directly when mutated.

# Settings widgets
auto_load_checkbox = pn.widgets.Checkbox(name="Auto-load view", value=True)
show_query_tables = pn.widgets.Checkbox(name="Show query tables in plots", value=False)
latest_url = pn.widgets.TextInput(name="Latest NG URL", value="", disabled=True)
update_state_interval = pn.widgets.IntInput(name="Update state interval (sec)", value=5, start=1)
trace_history_checkbox = pn.widgets.Checkbox(name="Trace history", value=True)
trace_history_length = pn.widgets.IntInput(name="History N", value=5)
trace_download = pn.widgets.FileDownload(label="Download traces", filename="trace_history.json", button_type="primary", disabled=True)
_trace_history: list[dict] = []
_recent_traces_view = pn.pane.Markdown("No traces yet.", sizing_mode="stretch_width")
_recent_traces_accordion = pn.Accordion(("Recent Traces", _recent_traces_view), active=[])
ng_links_internal = pn.widgets.Checkbox(name="NG links open internal", value=True)
views_table = pn.widgets.Tabulator(pd.DataFrame(), disabled=True, height=250, visible=False)
# NOTE: Tabulator expects a pandas.DataFrame. Do NOT pass a polars DataFrame or a class placeholder.
# Always convert upstream objects (lists of dicts, polars.DataFrame) to pandas before assignment.

# Track whether we've already added the row selection watcher to avoid inspecting internal watcher structures.
_views_table_watcher_added = False

# --- Debounce & programmatic load tracking state ---
_programmatic_load: bool = False  # True while we intentionally set viewer.url in code
_last_user_state_sync: float = 0.0  # monotonic time of last backend sync caused by user interaction
_scheduled_user_state_task: asyncio.Task | None = None  # pending delayed sync task

@contextmanager
def _programmatic_viewer_update():
    """Context manager marking a viewer.url change as programmatic.

    Programmatic (agent / app) initiated changes should sync immediately and not
    be throttled/debounced like rapid manual user edits in the Neuroglancer UI.
    """
    global _programmatic_load
    _programmatic_load = True
    try:
        yield
    finally:
        _programmatic_load = False

def _open_latest(_):
    if latest_url.value:
        with _programmatic_viewer_update():
            viewer.url = latest_url.value

open_latest_btn = pn.widgets.Button(name="Open latest link", button_type="primary")
open_latest_btn.on_click(_open_latest)

async def _notify_backend_state_load(url: str):
    """Inform backend that the widget loaded a new NG URL so CURRENT_STATE is in sync.
    
    If URL contains a JSON pointer, expand it first before syncing to backend.
    """
    try:
        status.object = "Syncing state to backend…"
        
        # Check if URL contains a pointer and expand if needed
        sync_url = url
        if is_pointer_url(url):
            try:
                status.object = "Expanding JSON pointer…"
                canonical_url, state_dict, was_pointer = expand_if_pointer_and_generate_inline(url)
                if was_pointer:
                    sync_url = canonical_url
                    status.object = "Pointer expanded, syncing state…"
            except Exception as e:
                status.object = f"Pointer expansion failed: {e}"
                # Fall back to syncing original URL
                sync_url = url
        
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{BACKEND}/tools/state_load", json={"link": sync_url})
            data = resp.json()
            if not data.get("ok"):
                status.object = f"Error syncing link: {data.get('error', 'unknown error')}"
                return
        status.object = f"**Opened:** {sync_url}"
    except Exception as e:
        status.object = f"Error syncing: {e}"

def _on_url_change(event):
    """Handle Neuroglancer URL changes with pointer expansion and debouncing."""
    new_url = event.new
    if not new_url:
        return
    
    # Immediate path for programmatic updates
    if _programmatic_load:
        asyncio.create_task(_handle_url_change_immediate(new_url))
        return
    
    # Debounce user-driven changes
    global _last_user_state_sync, _scheduled_user_state_task
    loop = asyncio.get_event_loop()
    now = loop.time()
    
    try:
        interval = max(1, int(update_state_interval.value or 5))
    except Exception:
        interval = 5
    
    elapsed = now - _last_user_state_sync
    if elapsed >= interval:
        _last_user_state_sync = now
        asyncio.create_task(_handle_url_change_immediate(new_url))
    else:
        # Schedule one future call if not already scheduled
        if _scheduled_user_state_task is None or _scheduled_user_state_task.done():
            delay = interval - elapsed
            async def _delayed_sync():
                await asyncio.sleep(delay)
                cur = viewer.url
                if cur:
                    global _last_user_state_sync
                    _last_user_state_sync = loop.time()
                    await _handle_url_change_immediate(cur)
            _scheduled_user_state_task = asyncio.create_task(_delayed_sync())

async def _handle_url_change_immediate(url: str):
    """Handle URL change immediately with pointer expansion and viewer update."""
    try:
        # Check if URL contains a pointer and expand if needed
        if is_pointer_url(url):
            canonical_url, state_dict, was_pointer = expand_if_pointer_and_generate_inline(url)
            if was_pointer:
                # Update viewer with canonical URL to avoid re-triggering
                with _programmatic_viewer_update():
                    viewer.url = canonical_url
                # Sync the expanded state
                await _notify_backend_state_load(canonical_url)
                return
        
        # Regular URL handling
        await _notify_backend_state_load(url)
    except Exception as e:
        status.object = f"URL handling error: {e}"
        # Fallback: try to sync original URL
        await _notify_backend_state_load(url)

# Watch the Neuroglancer widget URL; use its built-in Demo/Load buttons
viewer.param.watch(_on_url_change, 'url')
async def agent_call(prompt: str) -> dict:
    """Call backend iterative chat once; backend executes tools.

    Returns:
      answer: final assistant message (enhanced with View column if ng_views present)
      mutated: bool indicating any mutating tool executed server-side
      url/masked: Neuroglancer link info if mutated (present only when mutated)
      ng_views: structured list of {row_index, url} if spatial query was executed
    """
    async with httpx.AsyncClient(timeout=120) as client:
        chat_payload = {"messages": [{"role": "user", "content": prompt}]}
        resp = await client.post(f"{BACKEND}/agent/chat", json=chat_payload)
        data = resp.json()
        answer = None
        ng_views = data.get("ng_views")  # Extract ng_views from backend response
        
        if data.get("choices"):
            msg = data["choices"][0].get("message", {})
            answer = msg.get("content")
        
        # If ng_views found, enhance the answer with View column
        if ng_views and answer:
            answer = _enhance_table_with_ng_views(answer, ng_views)
        
        mutated = bool(data.get("mutated"))
        state_link = data.get("state_link") or {}
        tool_trace = data.get("tool_trace") or []
        query_data = data.get("query_data")  # Raw query result from backend
        plot_data = data.get("plot_data")  # Raw plot result from backend
        
        return {
            "answer": answer or "(no response)",
            "mutated": mutated,
            "url": state_link.get("url"),
            "masked": state_link.get("masked_markdown"),
            "tool_trace": tool_trace,
            "views_table": data.get("views_table"),
            "ng_views": ng_views,
            "ng_views_raw": ng_views,  # Keep raw ng_views for Tabulator rendering
            "query_data": query_data,  # Pass through query_data for direct rendering
            "plot_data": plot_data,  # Pass through plot_data for direct rendering
        }


# Removed _truncate_table_columns - Tabulator handles wide tables with horizontal scrolling

def _create_tabulator_from_query_data(query_data: dict) -> pn.widgets.Tabulator:
    """Create Tabulator widget directly from backend query_data structure.
    
    Args:
        query_data: Dict with keys: data (dict of lists), columns, ng_views, etc.
    
    Returns:
        Panel Tabulator widget
    """
    import pandas as pd
    
    # Extract data
    data_dict = query_data.get("data", {})
    columns = query_data.get("columns", [])
    ng_views = query_data.get("ng_views", [])
    
    if not data_dict or not columns:
        return pn.pane.Markdown("*No data to display*")
    
    # Convert to DataFrame
    df = pd.DataFrame(data_dict)
    
    # If no ng_views, return simple tabulator
    if not ng_views:
        return pn.widgets.Tabulator(
            df,
            disabled=True,
            show_index=False,
            sizing_mode="stretch_width",
            height=min(400, len(df) * 35 + 50),
            layout="fit_data_table",
            pagination="local" if len(df) > 20 else None,
            page_size=20,
        )
    
    # Create URL mapping for ng_views
    url_map = {view["row_index"]: view["url"] for view in ng_views if "row_index" in view and "url" in view}
    
    # Add _ng_url column for View buttons at the end
    df['_ng_url'] = df.index.map(lambda i: url_map.get(i, ""))
    
    # Reorder columns to put _ng_url last
    cols = [c for c in df.columns if c != '_ng_url'] + ['_ng_url']
    df = df[cols]
    
    # Create Tabulator with button formatter
    tabulator = pn.widgets.Tabulator(
        df,
        disabled=False,
        show_index=False,
        sizing_mode="stretch_width",
        height=min(400, len(df) * 35 + 50),
        layout="fit_data_table",
        pagination="local" if len(df) > 20 else None,
        page_size=20,
        buttons={'_ng_url': '<i class="fa fa-eye"></i>'},
        titles={'_ng_url': 'View'},
        hidden_columns=[],
        widths={'_ng_url': 60},  # Narrow column, just wide enough for icon button
    )
    
    # Set up click handler
    def on_click(event):
        if event.column == '_ng_url' and event.row is not None:
            try:
                url = df.iloc[event.row]['_ng_url']
                if url:
                    _load_internal_link(url)
            except Exception as e:
                logger.error(f"Error loading neuroglancer link: {e}")
    
    tabulator.on_click(on_click)
    
    return tabulator


def _create_tabulator_from_markdown(text: str, ng_views: list = None, max_rows: int = 500) -> pn.widgets.Tabulator:
    """Convert markdown table to interactive Tabulator widget with clickable View buttons.
    
    Args:
        text: Markdown table text
        ng_views: List of {"row_index": i, "url": "https://..."} from backend
        max_rows: Maximum rows to display
    
    Returns:
        Panel Tabulator widget with clickable View buttons
    """
    import pandas as pd
    
    # Parse markdown table
    lines = [l.strip() for l in text.split("\n") if "|" in l]
    if len(lines) < 2:
        return pn.pane.Markdown(text)  # Not a table
    
    # Extract header
    header_parts = [p.strip() for p in lines[0].split("|") if p.strip()]
    
    # Skip separator line, extract data rows
    data_rows = []
    for line in lines[2:]:
        parts = [p.strip() for p in line.split("|") if p.strip()]
        # Skip separator-like lines
        if all(c in "-:|" for p in parts for c in p.replace(" ", "")):
            continue
        if len(parts) == len(header_parts):
            data_rows.append(parts)
    
    if not data_rows:
        return pn.pane.Markdown(text)
    
    # Create DataFrame
    df = pd.DataFrame(data_rows[:max_rows], columns=header_parts)
    
    # If no ng_views, return simple tabulator
    if not ng_views:
        return pn.widgets.Tabulator(
            df,
            disabled=True,
            show_index=False,
            sizing_mode="stretch_width",
            height=min(300, len(df) * 35 + 40),
        )
    
    # Create URL mapping
    url_map = {view["row_index"]: view["url"] for view in ng_views if "row_index" in view and "url" in view}
    
    # Remove existing View column if present (contains markdown link text)
    if 'View' in df.columns:
        df = df.drop(columns=['View'])
    
    # Add _ng_url column with URLs for button formatter
    df['_ng_url'] = df.index.map(lambda i: url_map.get(i, ""))
    
    # Reorder columns to put _ng_url last
    cols = [c for c in df.columns if c != '_ng_url'] + ['_ng_url']
    df = df[cols]
    
    # Create Tabulator with button formatter for View column
    tabulator = pn.widgets.Tabulator(
        df,
        disabled=False,  # Enable interaction
        show_index=False,
        sizing_mode="stretch_width",
        height=min(400, len(df) * 35 + 40),
        buttons={'_ng_url': '<i class="fa fa-eye"></i>'},
        titles={'_ng_url': 'View'},  # Column header for the button column
        hidden_columns=[],  # Don't hide _ng_url - it becomes the visible View button column
        widths={'_ng_url': 60},  # Narrow column, just wide enough for icon button
    )
    
    # Set up click handler for view buttons
    def on_click(event):
        if event.column == '_ng_url' and event.row is not None:
            url = df.iloc[event.row]['_ng_url']
            if url:
                _load_internal_link(url)
    
    tabulator.on_click(on_click)
    
    return tabulator


def _enhance_table_with_ng_views(text: str, ng_views: list) -> str:
    """Enhance markdown table by adding View column with clickable links.
    
    Args:
        text: Markdown text that may contain a table
        ng_views: List of {"row_index": i, "url": "https://..."} from backend
    
    Returns:
        Enhanced text with View column added to table, or original text if no table found
    """
    if not ng_views or not text:
        return text
    
    # Create row_index -> url mapping
    url_map = {view["row_index"]: view["url"] for view in ng_views if "row_index" in view and "url" in view}
    if not url_map:
        return text
    
    lines = text.split("\n")
    enhanced_lines = []
    in_table = False
    table_row_idx = 0  # Track data rows (starts at 0 for first data row)
    
    for line in lines:
        # Detect table by markdown syntax: | col1 | col2 |
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            # Filter empty parts from leading/trailing |
            parts = [p for p in parts if p]
            
            if not in_table:
                # First table row - add "View" header
                in_table = True
                table_row_idx = 0
                enhanced_lines.append(line.rstrip() + " View |")
            elif all(p.replace("-", "").replace(":", "").strip() == "" for p in parts):
                # Separator row (---)
                enhanced_lines.append(line.rstrip() + " --- |")
            else:
                # Data row - add link if available
                if table_row_idx in url_map:
                    url = url_map[table_row_idx]
                    enhanced_lines.append(line.rstrip() + f" [view]({url}) |")
                else:
                    enhanced_lines.append(line.rstrip() + " - |")
                table_row_idx += 1  # Increment AFTER using the index
        else:
            # Not a table line - reset table tracking
            if in_table:
                table_row_idx = 0
            in_table = False
            enhanced_lines.append(line)
    
    return "\n".join(enhanced_lines)


def _mask_client_side(text: str) -> str:
    """Safety net masking on frontend: collapse raw Neuroglancer URLs.

    Mirrors backend labeling but simpler (does not number multiple distinct URLs).
    Skips URLs that are already inside markdown links to avoid double-wrapping.
    """
    if not text:
        return text
    
    # Pattern that matches raw URLs NOT already inside markdown link syntax [text](url)
    # Negative lookbehind (?<!\]\() ensures we don't match URLs after ](
    url_pattern = re.compile(r"(?<!\]\()https?://[^\s)]+")
    
    def repl(m):
        u = m.group(0)
        if 'neuroglancer' in u:
            return f"[Updated Neuroglancer view]({u})"
        return u
    return url_pattern.sub(repl, text)


def _load_internal_link(url: str):
    if not url:
        return
    with _programmatic_viewer_update():
        viewer.url = url
        viewer._load_url()
    # Sync handled by _on_url_change in programmatic context

async def respond(contents: str, user: str, **kwargs):
    """Async generator that streams agent responses token by token."""
    global last_loaded_url, _trace_history
    status.object = "Running…"
    
    if USE_STREAMING:
        # Streaming path
        try:
            accumulated_message = ""
            tool_names = []
            mutated = False
            state_link = None
            has_yielded = False
            event_count = 0
            
            async with httpx.AsyncClient(timeout=120) as client:
                chat_payload = {"messages": [{"role": "user", "content": contents}]}
                
                async with client.stream(
                    "POST",
                    f"{BACKEND}/agent/chat/stream",
                    json=chat_payload
                ) as response:
                    # Buffer for accumulating text
                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        
                        # Split on double newlines (SSE event separator)
                        while "\n\n" in buffer:
                            event_text, buffer = buffer.split("\n\n", 1)
                            
                            # Each event should start with "data: "
                            if not event_text.startswith("data: "):
                                continue
                            
                            data_str = event_text[6:]  # Remove "data: " prefix
                            try:
                                event = json.loads(data_str)
                                event_count += 1
                                event_type = event.get("type")
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse SSE event")
                                continue
                            
                            # Process the event
                            if event_type == "content":
                                accumulated_message += event.get("delta", "")
                                yield _mask_client_side(accumulated_message)
                                has_yielded = True
                            
                            elif event_type == "tool_start":
                                tool = event.get("tool")
                                if tool:
                                    tool_names.append(tool)
                                    status.object = f"Tools: {' → '.join(tool_names)}"
                            
                            elif event_type == "final":
                                mutated = event.get("mutated", False)
                                state_link = event.get("state_link")
                                # Use content from final event if we haven't streamed any
                                final_content = event.get("content", "")
                                if not has_yielded and final_content:
                                    accumulated_message = final_content
                                    yield _mask_client_side(accumulated_message)
                                    has_yielded = True
                            
                            elif event_type == "error":
                                error_msg = event.get("error", "Unknown error")
                                logger.error(f"Stream error: {error_msg}")
                                yield f"Error: {error_msg}"
                                has_yielded = True
                                break
                            
                            elif event_type == "complete":
                                break
            
            # Handle state link and multi-view table (similar to non-streaming)
            if mutated and state_link:
                link = state_link.get("url")
                latest_url.value = link
                if link != last_loaded_url and auto_load_checkbox.value:
                    with _programmatic_viewer_update():
                        viewer.url = link
                        viewer._load_url()
                    last_loaded_url = link
                    status.object = f"**Opened:** {link}"
                else:
                    status.object = "New link generated (auto-load off)."
            elif tool_names:
                status.object = f"Tools: {' → '.join(tool_names)}"
            else:
                status.object = "Done (no view change)."
            
            # Only yield at the end if we haven't yielded anything yet
            if not has_yielded:
                if accumulated_message:
                    masked_msg = _mask_client_side(accumulated_message)
                    # Wrap tables in Markdown pane for proper rendering
                    if "|" in masked_msg and masked_msg.count("\n") > 2:
                        yield pn.pane.Markdown(masked_msg)
                    else:
                        yield masked_msg
                else:
                    yield "(no response)"
            
        except Exception as e:
            status.object = f"Streaming error: {e}"
            yield f"Error: {e}"
    
    else:
        # Fallback to non-streaming
        try:
            result = await agent_call(contents)
            link = result.get("url")
            mutated = bool(result.get("mutated"))
            safe_answer = _mask_client_side(result.get("answer")) if result.get("answer") else None
            ng_views_data = result.get("ng_views_raw")  # Raw ng_views for Tabulator rendering
            query_data = result.get("query_data")  # Raw query result from backend for direct rendering
            plot_data = result.get("plot_data")  # Plot result from backend for rendering
            trace = result.get("tool_trace") or []
            vt = result.get("views_table")
            if trace:
                # Build concise status line of executed tool names in order
                tool_names = [t.get("tool") or t.get("name") for t in trace if t]
                if tool_names:
                    status.object = f"Tools: {' → '.join(tool_names)}"

            # Optional trace history retrieval
            if trace_history_checkbox.value:
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        hist_resp = await client.get(f"{BACKEND}/debug/tool_trace", params={"n": trace_history_length.value})
                    hist_data = hist_resp.json()
                    _trace_history = hist_data.get("traces", [])
                    if _trace_history:
                        def _payload():
                            payload = {
                                "exported_at": datetime.utcnow().isoformat() + 'Z',
                                "count": len(_trace_history),
                                "traces": _trace_history,
                            }
                            return io.BytesIO(json.dumps(payload, indent=2).encode('utf-8'))
                        trace_download.callback = _payload
                        ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                        trace_download.filename = f"trace_history_{ts}.json"
                        trace_download.disabled = False
                        # Update recent traces markdown (summaries only)
                        lines: list[str] = []
                        for i, t in enumerate(reversed(_trace_history), start=1):
                            steps = t.get("steps", [])
                            tool_chain = " → ".join(s.get("tool") for s in steps if s.get("tool"))
                            mutated_flag = "✅" if t.get("mutated") else "–"
                            final_msg = (t.get("final_message", {}).get("content") or "").strip()
                            final_msg = final_msg[:120] + ("…" if len(final_msg) > 120 else "")
                            lines.append(f"**{i}.** {mutated_flag} {tool_chain or '(no tools)'}\n> {final_msg}")
                        if lines:
                            _recent_traces_view.object = "\n\n".join(lines)
                            _recent_traces_accordion.active = [0]
                        else:
                            _recent_traces_view.object = "No traces yet."
                except Exception as e:  # pragma: no cover
                    status.object += f" | Trace err: {e}"

            # Render multi-view table if present
            # If multi-view tool returned an error, surface it clearly (and any warnings)
            if vt and isinstance(vt, dict) and vt.get("error"):
                warn_txt = ""
                if vt.get("warnings"):
                    warn_txt = "\n\nWarnings:\n- " + "\n- ".join(vt.get("warnings") or [])
                status.object = f"Multi-view error: {vt.get('error')}{warn_txt}"
            embedded_table_component = None
            # Render multi-view table if present and successful
            if vt and isinstance(vt, dict) and vt.get("rows"):
                rows = vt["rows"]
                # Build DataFrame-like structure for Tabulator. Hide raw link column, show masked_link clickable.
                import pandas as pd
                df_rows = []
                for r in rows:
                    display = {k: v for k, v in r.items() if k not in ("link", "masked_link")}
                    raw = r.get("link")
                    # Provide a simple HTML anchor; Tabulator with html=True will render it.
                    if raw:
                        display["view"] = f"<a href='{raw}' target='_blank'>link</a>"
                    df_rows.append(display)
                if df_rows:
                    views_table.value = pd.DataFrame(df_rows)
                    views_table.visible = True
                    views_table.disabled = False
                    # Configure columns (if available) to allow HTML rendering
                    try:
                        views_table.formatters = {"view": {"type": "html"}}
                    except Exception:
                        pass
                    # Create a lightweight embedded table (copy) for chat message rendering
                    embedded_table_component = pn.widgets.Tabulator(
                        views_table.value.copy(), height=220, disabled=True, selectable=False, pagination=None
                    )
                    try:
                        embedded_table_component.formatters = {"view": {"type": "html"}}
                    except Exception:
                        pass
                    # Add click behavior: when selecting a row, open link
                    def _on_select(event):  # pragma: no cover UI callback
                        if not ng_links_internal.value:
                            return
                        try:
                            data = views_table.value
                            if data is not None and hasattr(data, "index") and len(data.index) > 0 and event.new:
                                idxs = event.new
                                if isinstance(idxs, list) and idxs:
                                    # Reconstruct raw link from view cell href if needed
                                    href = data.iloc[idxs[0]].get("view")
                                    if isinstance(href, str) and "href='" in href:
                                        try:
                                            raw_link = href.split("href='",1)[1].split("'",1)[0]
                                            _load_internal_link(raw_link)
                                        except Exception:
                                            pass
                        except Exception:
                            pass
                    global _views_table_watcher_added
                    if not _views_table_watcher_added:
                        try:
                            views_table.param.watch(_on_select, 'selection')
                            _views_table_watcher_added = True
                        except Exception:
                            # Fallback: silently ignore if watcher cannot be set (should not happen normally)
                            pass
                # Auto-load first link if auto-load enabled
                if ng_links_internal.value and auto_load_checkbox.value and rows:
                    _load_internal_link(rows[0].get("link"))

            if mutated and link and not vt:  # avoid duplicate load after views_table logic
                latest_url.value = link
                masked = result.get("masked") or f"[Updated Neuroglancer view]({link})"
                if link != last_loaded_url:
                    if auto_load_checkbox.value:
                        with _programmatic_viewer_update():
                            viewer.url = link
                            viewer._load_url()
                        last_loaded_url = link
                        status.object = f"**Opened:** {link}"
                    else:
                        status.object = "New link generated (auto-load off)."
                else:
                    status.object = "State updated (no link change)."
                if safe_answer:
                    yield f"{safe_answer}\n\n{masked}"
                else:
                    yield masked
            else:
                if not trace:
                    status.object = "Done (no view change)."
                # If we have an embedded table, return a structured chat message containing both text & component
                if embedded_table_component is not None:
                    # Wrap answer + table in a single Column so ChatInterface doesn't display list repr.
                    if safe_answer:
                        yield pn.Column(pn.pane.Markdown(safe_answer), embedded_table_component, sizing_mode="stretch_width")
                    else:
                        yield pn.Column(embedded_table_component, sizing_mode="stretch_width")
                else:
                    # Check if we have query_data for direct Tabulator rendering
                    logger.info(f"Checking query_data: present={query_data is not None}, type={type(query_data) if query_data else 'None'}")
                    if query_data:
                        logger.info(f"query_data keys: {list(query_data.keys()) if isinstance(query_data, dict) else 'not a dict'}")
                        if isinstance(query_data, dict):
                            logger.info(f"query_data['data'] present: {'data' in query_data}, rows: {query_data.get('rows')}")
                    
                    if query_data and isinstance(query_data, dict) and query_data.get("data"):
                        # Backend provided structured data - render directly as Tabulator
                        logger.info(f"✅ Rendering Tabulator from query_data: {query_data.get('rows')} rows")
                        
                        # Check if we also have plot_data - if so, skip table unless show_query_tables is True
                        tabulator_widget = None
                        if plot_data and isinstance(plot_data, dict) and plot_data.get("plot_kwargs"):
                            if not show_query_tables.value:
                                logger.info("Skipping query table rendering because plot_data is present and show_query_tables=False")
                                # Skip the table, let the plot rendering happen in the elif below
                            else:
                                # Show both table and plot
                                tabulator_widget = _create_tabulator_from_query_data(query_data)
                        else:
                            # No plot data, always create the table
                            tabulator_widget = _create_tabulator_from_query_data(query_data)
                        
                        # Extract and display the Polars expression
                        expression = query_data.get("expression", "")
                        expression_display = None
                        if expression:
                            # Format expression in a code block
                            expression_display = pn.pane.Markdown(
                                f"```python\n{expression}\n```",
                                sizing_mode="stretch_width",
                                margin=(5, 5, 10, 5)
                            )
                        
                        # Create workspace button
                        workspace_button = pn.widgets.Button(
                            name="📊 Add to Workspace",
                            button_type="primary",
                            sizing_mode="fixed",
                            width=150,
                            margin=(5, 0)
                        )
                        
                        # Capture data in closure
                        captured_data = query_data
                        
                        def add_to_workspace(event):
                            _add_result_to_workspace_from_data(captured_data)
                            workspace_button.name = "✓ Added to Workspace"
                            workspace_button.button_type = "success"
                            workspace_button.disabled = True
                        
                        workspace_button.on_click(add_to_workspace)
                        
                        # Build components to display
                        components = []
                        
                        # Add LLM context if present (strip out code blocks since expression is shown separately)
                        if safe_answer and safe_answer.strip():
                            llm_text = safe_answer.strip()
                            
                            # Remove code blocks (expression is rendered separately by frontend)
                            import re
                            llm_text = re.sub(r'```[a-z]*\n.*?\n```', '', llm_text, flags=re.DOTALL)
                            llm_text = llm_text.strip()
                            
                            # Filter out if it looks like the LLM is listing data rows
                            # (has many lines with colons indicating key-value pairs)
                            if llm_text:
                                line_count = llm_text.count("\n")
                                colon_count = llm_text.count(":")
                                # If it has many colons and lines, it's probably formatting data
                                if not (line_count > 5 and colon_count > line_count):
                                    components.append(pn.pane.Markdown(llm_text, sizing_mode="stretch_width", margin=(5, 5, 5, 5)))
                        
                        # Always add expression display (already created above)
                        if expression_display:
                            components.append(expression_display)
                        
                        # Add table and button (only if table was created)
                        if tabulator_widget is not None:
                            components.append(tabulator_widget)
                        components.append(workspace_button)
                        
                        # Return all components in a column
                        yield pn.Column(
                            *components,
                            sizing_mode="stretch_width"
                        )
                    # Check if we have plot_data for direct plot rendering
                    elif plot_data and isinstance(plot_data, dict) and plot_data.get("plot_kwargs"):
                        # Backend provided plot spec - render natively with hvplot
                        logger.info(f"✅ Rendering plot from plot_data: type={plot_data.get('plot_type')}, interactive={plot_data.get('is_interactive')}")
                        
                        # Fetch the dataframe from backend to recreate plot
                        try:
                            source_id = plot_data.get("source_id")
                            plot_kwargs = plot_data.get("plot_kwargs", {})
                            plot_type = plot_data.get("plot_type", "scatter")
                            expression = plot_data.get("expression", "")
                            
                            # Fetch data from backend
                            async with httpx.AsyncClient(timeout=30) as client:
                                # Determine if source is file or summary
                                if source_id:
                                    # Try to get the dataframe data via preview endpoint
                                    preview_resp = await client.post(
                                        f"{BACKEND}/tools/data_preview",
                                        json={"file_id": source_id, "n": 10000}  # Get up to 10k rows for plotting
                                    )
                                    preview_data = preview_resp.json()
                                    
                                    if "rows" in preview_data:
                                        # Convert to polars dataframe for hvplot
                                        import polars as pl
                                        df = pl.DataFrame(preview_data["rows"])
                                        
                                        # Import hvplot.polars to enable .hvplot accessor
                                        import hvplot.polars
                                        
                                        # Create the plot using hvplot
                                        if plot_type == "scatter":
                                            plot = df.hvplot.scatter(**plot_kwargs)
                                        elif plot_type == "line":
                                            plot = df.hvplot.line(**plot_kwargs)
                                        elif plot_type == "bar":
                                            plot = df.hvplot.bar(**plot_kwargs)
                                        elif plot_type == "heatmap":
                                            plot = df.hvplot.heatmap(**plot_kwargs)
                                        else:
                                            plot = df.hvplot(**plot_kwargs)
                                        
                                        # Wrap in Panel's HoloViews pane for native rendering
                                        plot_pane = pn.pane.HoloViews(
                                            object=plot,
                                            sizing_mode="stretch_both",
                                            min_height=400
                                        )
                                        
                                        # Build components
                                        components = []
                                        
                                        # Add LLM context if present
                                        if safe_answer and safe_answer.strip():
                                            llm_text = safe_answer.strip()
                                            import re
                                            llm_text = re.sub(r'```[a-z]*\n.*?\n```', '', llm_text, flags=re.DOTALL)
                                            llm_text = llm_text.strip()
                                            if llm_text:
                                                components.append(pn.pane.Markdown(llm_text, sizing_mode="stretch_width", margin=(5, 5, 5, 5)))
                                        
                                        # Add expression if present
                                        if expression:
                                            expression_display = pn.pane.Markdown(
                                                f"**Data transformation:**\n```python\n{expression}\n```",
                                                sizing_mode="stretch_width",
                                                margin=(5, 5, 10, 5)
                                            )
                                            components.append(expression_display)
                                        
                                        # Add plot info
                                        plot_info = f"**{plot_type.capitalize()}** plot • "
                                        plot_info += f"{'Interactive' if plot_data.get('is_interactive') else 'Static'} • "
                                        plot_info += f"{plot_data.get('row_count', 0)} points"
                                        components.append(pn.pane.Markdown(plot_info, sizing_mode="stretch_width", margin=(5, 5, 5, 5)))
                                        
                                        # Add the plot
                                        components.append(plot_pane)
                                        
                                        # Add workspace button
                                        workspace_button = pn.widgets.Button(
                                            name="📊 Add Plot to Workspace",
                                            button_type="primary",
                                            sizing_mode="fixed",
                                            width=180,
                                            margin=(5, 0)
                                        )
                                        
                                        # Capture plot info in closure
                                        captured_plot_pane = plot_pane
                                        captured_plot_type = plot_type
                                        captured_x = plot_kwargs.get('x', '')
                                        captured_y = plot_kwargs.get('y', '')
                                        plot_summary = f"{captured_x} vs {captured_y}" if captured_x and captured_y else None
                                        
                                        def add_plot_to_workspace(event):
                                            _add_plot_to_workspace(captured_plot_pane, captured_plot_type, plot_summary)
                                            workspace_button.name = "✓ Added to Workspace"
                                            workspace_button.button_type = "success"
                                            workspace_button.disabled = True
                                        
                                        workspace_button.on_click(add_plot_to_workspace)
                                        components.append(workspace_button)
                                        
                                        # Return all components
                                        yield pn.Column(
                                            *components,
                                            sizing_mode="stretch_width"
                                        )
                                    else:
                                        yield f"Error: Could not fetch data for plotting: {preview_data.get('error', 'Unknown error')}"
                                else:
                                    yield "Error: No source_id provided for plot data"
                        except Exception as e:
                            logger.exception("Failed to render plot")
                            yield f"Error rendering plot: {str(e)}"
                    # Check if safe_answer contains a table (has pipe characters in multiple lines)
                    elif safe_answer and "|" in safe_answer and safe_answer.count("\n") > 2:
                        # Legacy: LLM generated markdown table
                        tabulator_widget = _create_tabulator_from_markdown(safe_answer, ng_views_data)
                        
                        # Create "Add to Workspace" button
                        workspace_button = pn.widgets.Button(
                            name="📊 Add to Workspace",
                            button_type="primary",
                            sizing_mode="fixed",
                            width=150,
                            margin=(5, 0)
                        )
                        
                        # Capture table and ng_views in closure
                        captured_table = safe_answer
                        captured_ng_views = ng_views_data
                        
                        def add_to_workspace(event):
                            _add_result_to_workspace(captured_table, captured_ng_views)
                            workspace_button.name = "✓ Added to Workspace"
                            workspace_button.button_type = "success"
                            workspace_button.disabled = True
                        
                        workspace_button.on_click(add_to_workspace)
                        
                        yield pn.Column(
                            tabulator_widget,
                            workspace_button,
                            sizing_mode="stretch_width"
                        )
                    else:
                        yield safe_answer if safe_answer else "(no response)"
        except Exception as e:
            status.object = f"Error: {e}"
            yield f"Error: {e}"

# ---------------- Chat UI ----------------
chat = ChatInterface(
    user="User",
    avatar="👤",
    callback_user="Agent",
    show_activity_dot=False,
    callback=respond,         # async callback
    height=1000,
    show_button_name=False,
    show_avatar=False,
    show_reaction_icons=False,
    show_copy_icon=False,
    show_timestamp=False,
    widgets=[
        pn.chat.ChatAreaInput(placeholder="Ask a question or issue a command..."),
    ],
    message_params={
        "stylesheets": [
            """
            .message {
                font-size: 1em;
                padding: 4px;
            }
            .name { font-size: 0.9em; }
            .timestamp { font-size: 0.9em; }
            """
        ]
     }
)

# ---------------- Settings UI ----------------
settings_card = pn.Card(
    pn.Column(
        auto_load_checkbox,
        show_query_tables,
        latest_url,
        open_latest_btn,
        ng_links_internal,
        update_state_interval,
        trace_history_checkbox,
        trace_history_length,
        trace_download,
        _recent_traces_accordion,
        status,
    ),
    title="Settings",
    collapsed=False,
)

# ---------------- Data Upload & Summaries UI ----------------
# NOTE: We keep upload + table refresh synchronous to avoid early event-loop timing issues
# during Panel server warm start on some platforms (Windows). Async is still used for
# LLM/chat + state sync, but simple data listing uses blocking httpx calls.
file_drop = pn.widgets.FileDropper(name="Drop CSV files here", multiple=True, accepted_filetypes=["text/csv", ".csv"],sizing_mode="stretch_width")
upload_notice = pn.pane.Markdown("")
try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

if pd is not None:
    uploaded_table = pn.widgets.Tabulator(
        pd.DataFrame(columns=["file_id","name","size","n_rows","n_cols"]),
        height=0,  # start collapsed until data present
        disabled=True,
        show_index=False,
        buttons={
            'preview': "<i class='fa fa-eye' title='Preview file'></i>",
        },
    )
    summaries_table = pn.widgets.Tabulator(
        pd.DataFrame(columns=["summary_id","source_file_id","kind","n_rows","n_cols"]),
        height=0,
        disabled=True,
        show_index=False,
    )
else:
    uploaded_table = pn.pane.Markdown("pandas not available")
    summaries_table = pn.pane.Markdown("pandas not available")

# Helper to update upload card title with dynamic file count
def _update_upload_card_title(n: int):
    try:
        label = "file" if n == 1 else "files"
        upload_card.title = f"Data Upload (📁 {n} {label})"
    except Exception:
        # Fallback silently; title update is non-critical
        pass

def _refresh_files():
    if pd is None:
        return
    try:
        with httpx.Client(timeout=30) as client:
            lst = client.post(f"{BACKEND}/tools/data_list_files")
            data = lst.json().get("files", [])
        _update_upload_card_title(len(data))
        if data:
            df = pd.DataFrame(data)
            # Reorder with name first, keep file_id (hidden) at end for potential future use
            desired = [c for c in ["name","size","n_rows","n_cols","file_id"] if c in df.columns]
            df = df[desired]
            # Rename display columns
            rename_map = {"name":"Name","size":"Size","n_rows":"Rows","n_cols":"Cols"}
            df = df.rename(columns=rename_map)
            uploaded_table.value = df
            # Hide file_id if present
            hidden_cols = [c for c in ["file_id"] if c in df.columns]
            if hidden_cols:
                uploaded_table.hidden_columns = hidden_cols
            # Dynamic height: ~40px per row (estimated row height incl. header). Cap at 5 rows.
            n_rows = len(df)
            per = 50
            cap = 10
            shown = min(n_rows, cap)
            uploaded_table.height =  (shown * per) + 40  # extra for header
            if n_rows > cap:
                uploaded_table.scroll = True
            else:
                uploaded_table.scroll = False
            uploaded_table.visible = True
        else:
            # Empty: collapse table height & clear
            uploaded_table.value = pd.DataFrame(columns=["Name","Size","Rows","Cols"])
            uploaded_table.height = 0
            uploaded_table.visible = False
    except Exception as e:  # pragma: no cover
        upload_notice.object = f"File list error: {e}"
        _update_upload_card_title(0)

def _refresh_summaries():
    if pd is None:
        return
    try:
        with httpx.Client(timeout=30) as client:
            lst = client.post(f"{BACKEND}/tools/data_list_summaries")
            data = lst.json().get("summaries", [])
        if data:
            df = pd.DataFrame(data)
            # Reorder with kind first; retain IDs (hidden) for possible referencing
            desired_order = [c for c in ["kind","n_rows","n_cols","summary_id","source_file_id"] if c in df.columns]
            df = df[desired_order]
            rename_map = {"kind":"Kind","n_rows":"Rows","n_cols":"Cols"}
            df = df.rename(columns=rename_map)
            summaries_table.value = df
            hidden_cols = [c for c in ["summary_id","source_file_id"] if c in df.columns]
            if hidden_cols:
                summaries_table.hidden_columns = hidden_cols
            n_rows = len(df)
            per = 40
            cap = 5
            shown = min(n_rows, cap)
            summaries_table.height = (shown * per) + 40
            if n_rows > cap:
                summaries_table.scroll = True
            else:
                summaries_table.scroll = False
            summaries_table.visible = True
        else:
            summaries_table.value = pd.DataFrame(columns=["Kind","Rows","Cols"])
            summaries_table.height = 0
            summaries_table.visible = False
    except Exception as e:  # pragma: no cover
        upload_notice.object = f"Summary list error: {e}"

def _handle_file_upload(evt):
    files = evt.new or {}
    if not files:
        return
    msgs: list[str] = []
    # FileDropper provides mapping name -> bytes
    with httpx.Client(timeout=60) as client:
        for name, raw in files.items():
            try:
                # Some widgets may give dicts with 'content' or 'body'
                if isinstance(raw, dict):
                    raw_bytes = raw.get("content") or raw.get("body") or b""
                else:
                    raw_bytes = raw
                resp = client.post(
                    f"{BACKEND}/upload_file",
                    files={"file": (name, raw_bytes, "text/csv")},
                )
                rj = resp.json()

                # dont show response here
                # if rj.get("ok"):
                #     msgs.append(f"✅ {name} → {rj['file']['file_id']}")
                # else:
                #     msgs.append(f"❌ {name} error: {rj.get('error')}")
            except Exception as e:  # pragma: no cover
                msgs.append(f"❌ {name} exception: {e}")
    upload_notice.object = "\n".join(msgs)
    _refresh_files()
    _refresh_summaries()

file_drop.param.watch(_handle_file_upload, "value")

def _initial_refresh():
    _refresh_files()
    _refresh_summaries()

upload_card = pn.Card(
    pn.Column(
        file_drop,
        upload_notice,
        #pn.pane.Markdown("**Uploaded Files**"),
        uploaded_table,
        #pn.pane.Markdown("**Summaries**"),
        #summaries_table,
    ),
    title="Data Upload",
    collapsed=False,
    width=450,
)

# Initialize title with zero count until first refresh occurs
_update_upload_card_title(0)


# Workspace results management
workspace_results_list = []  # Track result cards for management

def _add_result_to_workspace_from_data(query_data: dict, query_summary: str = None):
    """Add a query result card to the workspace from structured query_data.
    
    Args:
        query_data: Dict with data, columns, ng_views from backend
        query_summary: Optional summary like '10 rows × 14 columns'
    """
    global workspace_results_list
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # Generate summary if not provided
    if not query_summary:
        rows = query_data.get("rows", 0)
        cols = len(query_data.get("columns", []))
        query_summary = f"{rows} rows × {cols} columns"
    
    # Create Tabulator widget directly from data
    tabulator_widget = _create_tabulator_from_query_data(query_data)
    
    # Create collapsible card
    result_card = pn.Card(
        tabulator_widget,
        title=f"📊 Query @ {timestamp} - {query_summary}",
        collapsed=False,
        sizing_mode="stretch_width",
        margin=(0, 0, 10, 0),
        header_background="#2b3e50",
    )
    
    # Add to container
    workspace_results_container.append(result_card)
    workspace_results_list.append(result_card)
    
    # Expand workspace card
    workspace_card.collapsed = False
    
    # Limit to last 10 results
    if len(workspace_results_list) > 10:
        oldest = workspace_results_list.pop(0)
        workspace_results_container.remove(oldest)
    
    # Update header
    workspace_header.object = f"### Query Results ({len(workspace_results_list)})\n_Click card headers to collapse/expand._"


def _add_result_to_workspace(full_table_text: str, ng_views_data: list = None, query_summary: str = None):
    """Add a query result card to the workspace.
    
    Args:
        full_table_text: Full table markdown text
        ng_views_data: List of ng_views data for interactive buttons
        query_summary: Optional summary like '10 rows × 14 columns'
    """
    global workspace_results_list
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # Count rows and columns from table
    if not query_summary:
        lines = [l for l in full_table_text.split("\n") if "|" in l]
        if len(lines) >= 2:
            header_parts = [p.strip() for p in lines[0].split("|") if p.strip()]
            data_lines = [l for l in lines[2:] if not all(c in "-:|" for c in l.replace(" ", ""))]
            query_summary = f"{len(data_lines)} rows × {len(header_parts)} columns"
    
    # Create card content with Tabulator widget
    tabulator_widget = _create_tabulator_from_markdown(full_table_text, ng_views_data)
    card_content = pn.Column(
        tabulator_widget,
        sizing_mode="stretch_width",
    )
    
    # Create collapsible card
    result_card = pn.Card(
        card_content,
        title=f"📊 Query @ {timestamp} - {query_summary or 'results'}",
        collapsed=False,  # Start expanded
        sizing_mode="stretch_width",
        margin=(0, 0, 10, 0),
        header_background="#2b3e50",
    )
    
    # Add to container
    workspace_results_container.append(result_card)
    workspace_results_list.append(result_card)
    
    # Expand workspace card
    workspace_card.collapsed = False
    
    # Limit to last 10 results
    if len(workspace_results_list) > 10:
        oldest = workspace_results_list.pop(0)
        workspace_results_container.remove(oldest)
    
    # Update header
    workspace_header.object = f"### Query Results ({len(workspace_results_list)})\n_Click card headers to collapse/expand._"


def _add_plot_to_workspace(plot_pane, plot_type: str = "plot", plot_summary: str = None):
    """Add a plot to the workspace.
    
    Args:
        plot_pane: The Panel pane containing the plot
        plot_type: Type of plot (scatter, line, bar, heatmap)
        plot_summary: Optional description like 'log_volume vs elongation'
    """
    global workspace_results_list
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # Generate summary if not provided
    if not plot_summary:
        plot_summary = f"{plot_type} plot"
    
    # Create collapsible card
    result_card = pn.Card(
        plot_pane,
        title=f"📈 {plot_type.title()} Plot @ {timestamp} - {plot_summary}",
        collapsed=False,
        sizing_mode="stretch_width",
        margin=(0, 0, 10, 0),
        header_background="#2b3e50",
    )
    
    # Add to container
    workspace_results_container.append(result_card)
    workspace_results_list.append(result_card)
    
    # Expand workspace card
    workspace_card.collapsed = False
    
    # Limit to last 10 results
    if len(workspace_results_list) > 10:
        oldest = workspace_results_list.pop(0)
        workspace_results_container.remove(oldest)
    
    # Update header
    workspace_header.object = f"### Query Results ({len(workspace_results_list)})\n_Click card headers to collapse/expand._"


workspace_header = pn.pane.Markdown("### Query Results\n_Full tables and visualizations appear here._", margin=(0, 0, 10, 0))
workspace_results_container = pn.Column(sizing_mode="stretch_width")

workspace_body = pn.Column(
    workspace_header,
    workspace_results_container,
    sizing_mode="stretch_width",
    scroll=True,
)
# Constrain height to 400px with scrolling inside
workspace_card = pn.Card(
    workspace_body,
    title="Workspace",
    collapsed=True,
    sizing_mode="stretch_width",
    styles={"maxHeight": "400px", "overflow": "auto"},
)
app = pn.template.FastListTemplate(
    title=f"Neurogabber v {version}",
    sidebar=[upload_card,chat], #views_table (dont need below)
    right_sidebar=settings_card,
    collapsed_right_sidebar = True,
    main=[workspace_card, viewer],
    sidebar_width=450,
    theme="dark",
)

app.servable()


# prompt inject example
# pn.state.onload(_initial_refresh)

# prompt_btn = pn.widgets.Button(name="Draft prompt for first file", button_type="primary")

# def _inject_prompt(_):
#     if pd is None: return
#     if hasattr(uploaded_table, 'value') and not uploaded_table.value.empty:
#         fid = uploaded_table.value.iloc[0]["file_id"]
#         chat.send(f"Preview file {fid}")

# prompt_btn.on_click(_inject_prompt)