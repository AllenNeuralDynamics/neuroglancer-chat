import os, json, httpx, asyncio, re, panel as pn, io
from datetime import datetime
from contextlib import contextmanager
from panel.chat import ChatInterface
from panel_neuroglancer import Neuroglancer
import polars as pl
import pandas as pd

# Import pointer expansion functionality
from neurogabber.backend.tools.pointer_expansion import (
    expand_if_pointer_and_generate_inline,
    is_pointer_url
)

# setup debug logging
import logging
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

# Mutation detection now handled server-side; state link returned directly when mutated.

# Settings widgets
auto_load_checkbox = pn.widgets.Checkbox(name="Auto-load view", value=True)
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
        return {
            "answer": answer or "(no response)",
            "mutated": mutated,
            "url": state_link.get("url"),
            "masked": state_link.get("masked_markdown"),
            "tool_trace": tool_trace,
            "views_table": data.get("views_table"),
            "ng_views": ng_views,
        }

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
                    # Check if safe_answer contains a table (has pipe characters in multiple lines)
                    # If so, wrap in Markdown pane to ensure proper rendering
                    if safe_answer and "|" in safe_answer and safe_answer.count("\n") > 2:
                        yield pn.pane.Markdown(safe_answer)
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


workspace_body = pn.Column(
    pn.pane.Markdown("### Workspace\n_Add notes, context, or future controls here._"),
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