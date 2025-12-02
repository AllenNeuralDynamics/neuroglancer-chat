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

# Enable verbose debug logging when NEUROGABBER_DEBUG is set (1/true/yes)
DEBUG_ENABLED = os.getenv("NEUROGABBER_DEBUG", "").lower() in ("1", "true", "yes")

FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
def reconfig_basic_config(format_=FORMAT, level=None):
    """(Re-)configure logging"""
    if level is None:
        level = logging.DEBUG if DEBUG_ENABLED else logging.INFO
    logging.basicConfig(format=format_, level=level, force=True)
    logging.info(f"Logging configured at {logging.getLevelName(level)} level")
    if DEBUG_ENABLED:
        logging.warning("🔍 FRONTEND DEBUG MODE ENABLED (NEUROGABBER_DEBUG=1)")

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

# Agent Activity Status Components
_session_prompt_tokens = 0
_session_completion_tokens = 0
_current_response_prompt_tokens = 0
_current_response_completion_tokens = 0
_agent_state = "🟢"  # 🟢 Idle / 🟡 Thinking / 🔵 Working / 🔴 Error
_current_tool_chain = []
_status_update_queue = []
_status_update_task = None

agent_status_line1 = pn.pane.Markdown(
    "🟢 **Ready**",
    sizing_mode="stretch_width",
    styles={"font-size": "14px", "padding": "2px 5px", "margin": "0"}
)
agent_status_line2 = pn.pane.Markdown(
    "This response: 0 tokens | Total: 0 tokens",
    sizing_mode="stretch_width",
    styles={"font-size": "12px", "padding": "2px 5px", "margin": "0", "font-family": "monospace"}
)

agent_status_card = pn.Card(
    agent_status_line1,
    agent_status_line2,
    title="Agent Activity",
    collapsed=False,
    sizing_mode="stretch_width",
    styles={"border": "1px solid #444"},
    margin=(5, 5, 10, 5)
)

# Preview card components - separate for Data Upload and Summaries tabs

# Data Upload preview
data_upload_preview_content = pn.Column(
    pn.pane.Markdown("*Click an eye icon to preview data*", sizing_mode="stretch_width"),
    sizing_mode="stretch_both",
    min_height=300,
)

data_upload_preview_close_btn = pn.widgets.Button(
    name="✕ Close Preview",
    button_type="default",
    sizing_mode="fixed",
    width=120,
    margin=(0, 0, 10, 0)
)

def _clear_data_upload_preview(event=None):
    """Clear data upload preview and show placeholder."""
    data_upload_preview_content.clear()
    data_upload_preview_content.append(
        pn.pane.Markdown("*Click an eye icon to preview data*", sizing_mode="stretch_width")
    )

data_upload_preview_close_btn.on_click(_clear_data_upload_preview)

data_upload_preview_card = pn.Card(
    data_upload_preview_close_btn,
    data_upload_preview_content,
    title="Preview",
    collapsed=False,
    sizing_mode="stretch_both",
    min_width=350,
    margin=(0, 0, 0, 10),
)

# Summaries preview
summaries_preview_content = pn.Column(
    pn.pane.Markdown("*Click an eye icon to preview summary*", sizing_mode="stretch_width"),
    sizing_mode="stretch_both",
    min_height=300,
)

summaries_preview_close_btn = pn.widgets.Button(
    name="✕ Close Preview",
    button_type="default",
    sizing_mode="fixed",
    width=120,
    margin=(0, 0, 10, 0)
)

def _clear_summaries_preview(event=None):
    """Clear summaries preview and show placeholder."""
    summaries_preview_content.clear()
    summaries_preview_content.append(
        pn.pane.Markdown("*Click an eye icon to preview summary*", sizing_mode="stretch_width")
    )

summaries_preview_close_btn.on_click(_clear_summaries_preview)

summaries_preview_card = pn.Card(
    summaries_preview_close_btn,
    summaries_preview_content,
    title="Preview",
    collapsed=False,
    sizing_mode="stretch_both",
    min_width=350,
    margin=(0, 0, 0, 10),
)

def _update_preview(file_id: str = None, summary_id: str = None, is_summary: bool = False):
    """Update preview card with data from backend."""
    # Choose the right preview card based on type
    if is_summary:
        preview_content = summaries_preview_content
    else:
        preview_content = data_upload_preview_content
    
    try:
        logger.info(f"Updating preview: file_id={file_id}, summary_id={summary_id}, is_summary={is_summary}")
        
        # Show loading
        preview_content.clear()
        preview_content.append(pn.pane.Markdown("Loading..."))
        
        # Fetch preview data from backend
        with httpx.Client(timeout=30) as client:
            if is_summary:
                resp = client.post(f"{BACKEND}/tools/data_preview", json={"file_id": summary_id, "n": 20})
            else:
                resp = client.post(f"{BACKEND}/tools/data_preview", json={"file_id": file_id, "n": 20})
            
            data = resp.json()
            
            if data.get("error"):
                preview_content.clear()
                preview_content.append(pn.pane.Markdown(f"**Error:** {data.get('error')}"))
                return
            
            # Create tabulator from preview data
            rows = data.get("rows", [])
            if rows:
                df = pd.DataFrame(rows)
                preview_table = pn.widgets.Tabulator(
                    df,
                    disabled=True,
                    show_index=False,
                    sizing_mode="stretch_both",
                    min_height=300,
                    pagination="local",
                    page_size=20,
                )
                title = f"**Preview:** {summary_id if is_summary else file_id} ({len(rows)} rows)"
                # Replace content
                preview_content.clear()
                preview_content.append(pn.pane.Markdown(title))
                preview_content.append(preview_table)
            else:
                preview_content.clear()
                preview_content.append(pn.pane.Markdown("No data to preview."))
                
    except Exception as e:
        logger.exception("Preview update error")
        preview_content.clear()
        preview_content.append(pn.pane.Markdown(f"**Error:** {e}"))

# Mutation detection now handled server-side; state link returned directly when mutated.

# Settings widgets
auto_load_checkbox = pn.widgets.Checkbox(name="Auto-load view", value=True)
show_query_tables = pn.widgets.Checkbox(name="Show query tables in plots", value=False)
show_agent_status = pn.widgets.Checkbox(name="Show Agent Status", value=True)
latest_url = pn.widgets.TextInput(name="Latest NG URL", value="", disabled=True)
update_state_interval = pn.widgets.IntInput(name="Update state interval (sec)", value=5, start=1)
trace_history_checkbox = pn.widgets.Checkbox(name="Trace history", value=True)
trace_history_length = pn.widgets.IntInput(name="History N", value=5)
trace_download = pn.widgets.FileDownload(label="Download traces", filename="trace_history.json", button_type="primary", disabled=True)
debug_prompt_btn = pn.widgets.Button(name="Debug Next Prompt", button_type="warning")
_trace_history: list[dict] = []
_recent_traces_view = pn.pane.Markdown("No traces yet.", sizing_mode="stretch_width")
_recent_traces_accordion = pn.Accordion(("Recent Traces", _recent_traces_view), active=[])
ng_links_internal = pn.widgets.Checkbox(name="NG links open internal", value=True)

# Wire up show agent status callback
def _toggle_agent_status(event):
    agent_status_card.visible = event.new

show_agent_status.param.watch(_toggle_agent_status, "value")

# Viewer settings widgets
viewer_show_scale_bar = pn.widgets.Checkbox(name="Show Scale Bar", value=True)
viewer_show_annotations = pn.widgets.Checkbox(name="Show Default Annotations", value=False)
viewer_show_axis_lines = pn.widgets.Checkbox(name="Show Axis Lines", value=False)
viewer_layout = pn.widgets.Select(
    name="Layout",
    options=["xy", "xz", "yz", "3d", "4panel"],
    value="xy"
)

# Wire up viewer settings callbacks
viewer_show_scale_bar.param.watch(
    lambda event: asyncio.create_task(_update_viewer_setting("showScaleBar", event.new)),
    "value"
)
viewer_show_annotations.param.watch(
    lambda event: asyncio.create_task(_update_viewer_setting("showDefaultAnnotations", event.new)),
    "value"
)
viewer_show_axis_lines.param.watch(
    lambda event: asyncio.create_task(_update_viewer_setting("showAxisLines", event.new)),
    "value"
)
viewer_layout.param.watch(
    lambda event: asyncio.create_task(_update_viewer_setting("layout", event.new)),
    "value"
)

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

def _reset_app(_):
    """Reset the application by calling backend reset then reloading the page."""
    try:
        status.object = "🔄 Resetting application..."
        logger.info("User requested app reset - clearing backend and reloading page")
        
        # First, reset the backend state
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(f"{BACKEND}/system/reset")
                if resp.status_code != 200:
                    status.object = f"❌ Backend reset failed: {resp.text}"
                    return
        except Exception as e:
            logger.error(f"Failed to reset backend: {e}")
            status.object = f"❌ Backend reset failed: {e}"
            return
        
        # Then reload the page to get fresh frontend
        def do_reload():
            pn.state.location.reload = True
        
        from bokeh.io import curdoc
        if curdoc():
            curdoc().add_next_tick_callback(do_reload)
        else:
            # Fallback if not in a document context
            status.object = "Please refresh your browser to reset the app"
        
    except Exception as e:
        logger.exception("Reset page reload failed")
        status.object = f"❌ Reset failed: {type(e).__name__}: {e}"

reset_app_btn = pn.widgets.Button(name="🔄 Reset App", button_type="danger", width=150)
reset_app_btn.on_click(_reset_app)

async def _update_viewer_setting(setting_name: str, value):
    """Sync a viewer setting change to the backend."""
    try:
        payload = {setting_name: value}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{BACKEND}/tools/ng_set_viewer_settings", json=payload)
            if resp.status_code != 200:
                logger.error(f"Failed to update viewer setting {setting_name}: {resp.text}")
    except Exception as e:
        logger.exception(f"Failed to update viewer setting {setting_name}")

async def _notify_backend_state_load(url: str):
    """Inform backend that the widget loaded a new NG URL so CURRENT_STATE is in sync.
    
    If URL contains a JSON pointer, expand it first before syncing to backend.
    Passes user's preferred defaults from settings panel to backend.
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
        
        # Gather user's preferred defaults from settings panel
        default_settings = {
            "showScaleBar": viewer_show_scale_bar.value,
            "showDefaultAnnotations": viewer_show_annotations.value,
            "showAxisLines": viewer_show_axis_lines.value,
            "layout": viewer_layout.value
        }
        
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{BACKEND}/tools/state_load",
                json={"link": sync_url, "default_settings": default_settings}
            )
            data = resp.json()
            if not data.get("ok"):
                status.object = f"Error syncing link: {data.get('error', 'unknown error')}"
                return
            
            # If backend applied defaults, it returns an updated_url - reload viewer with it
            updated_url = data.get("updated_url")
            if updated_url and updated_url != sync_url:
                logger.debug(f"Backend applied user's preferred defaults, reloading viewer with updated URL")
                with _programmatic_viewer_update():
                    viewer.url = updated_url
                    viewer._load_url()
            
            # After successful load, fetch viewer settings and update widgets
            # (This handles case where loaded URL already had some settings)
            try:
                summary_resp = await client.post(
                    f"{BACKEND}/tools/ng_state_summary",
                    json={"detail": "standard"}
                )
                if summary_resp.status_code == 200:
                    summary_data = summary_resp.json()
                    flags = summary_data.get("flags", {})
                    layout = summary_data.get("layout", "xy")
                    
                    # Update widgets to match loaded state
                    # (overrides user defaults if URL already had specific settings)
                    viewer_show_scale_bar.value = flags.get("showScaleBar", True)
                    viewer_show_annotations.value = flags.get("showDefaultAnnotations", False)
                    viewer_show_axis_lines.value = flags.get("showAxisLines", False)
                    viewer_layout.value = layout
                    logger.debug(f"Synced viewer settings from loaded state: {flags}")
            except Exception as sync_err:
                logger.exception("Failed to sync viewer settings from backend after load")
                
        status.object = "✓ State loaded"
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
async def agent_call(prompt: str, history: list = None) -> dict:
    """Call backend iterative chat once; backend executes tools.

    Args:
        prompt: Current user message
        history: Previous conversation messages (list of ChatMessage dicts)

    Returns:
      answer: final assistant message (enhanced with View column if ng_views present)
      mutated: bool indicating any mutating tool executed server-side
      url/masked: Neuroglancer link info if mutated (present only when mutated)
      ng_views: structured list of {row_index, url} if spatial query was executed
    """
    async with httpx.AsyncClient(timeout=120) as client:
        # Build messages list: history + current prompt
        messages = history or []
        messages.append({"role": "user", "content": prompt})
        chat_payload = {"messages": messages}
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
        usage = data.get("usage", {})  # Extract token usage from backend
        
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
            "usage": usage,  # Pass through token usage for agent status display
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


async def _process_status_updates():
    """Process queued status updates with delays to make them visible."""
    global _status_update_queue, _status_update_task
    
    while _status_update_queue:
        update = _status_update_queue.pop(0)
        
        # Apply the update
        state = update.get("state")
        tools = update.get("tools")
        prompt_tokens = update.get("prompt_tokens", 0)
        completion_tokens = update.get("completion_tokens", 0)
        clear_tokens = update.get("clear_tokens", False)
        
        global _agent_state, _current_tool_chain, _current_response_prompt_tokens, _current_response_completion_tokens
        global _session_prompt_tokens, _session_completion_tokens
        
        if clear_tokens:
            _current_tool_chain = []
        
        if state:
            _agent_state = state
        
        if tools is not None:
            _current_tool_chain = tools
        
        # Set current response tokens and add the delta to session totals
        if prompt_tokens or completion_tokens:
            # Calculate delta from previous values
            delta_prompt = prompt_tokens - _current_response_prompt_tokens
            delta_completion = completion_tokens - _current_response_completion_tokens
            
            # Update current response tokens
            _current_response_prompt_tokens = prompt_tokens
            _current_response_completion_tokens = completion_tokens
            
            # Add only the delta to session totals
            _session_prompt_tokens += delta_prompt
            _session_completion_tokens += delta_completion
        
        # Update line 1: state + tool chain
        if _current_tool_chain:
            tool_str = " → ".join([f"`{t}`" for t in _current_tool_chain[-3:]])  # Show last 3 tools
            if len(_current_tool_chain) > 3:
                tool_str = "... → " + tool_str
            agent_status_line1.object = f"{_agent_state} **Working:** {tool_str}"
        else:
            # Show appropriate text based on state
            if _agent_state == "🟡":
                agent_status_line1.object = f"{_agent_state} **Thinking...**"
            elif _agent_state == "🔴":
                agent_status_line1.object = f"{_agent_state} **Error**"
            else:
                agent_status_line1.object = f"{_agent_state} **Ready**"
        
        # Update line 2: token counts
        current_total = _current_response_prompt_tokens + _current_response_completion_tokens
        session_total = _session_prompt_tokens + _session_completion_tokens
        agent_status_line2.object = f"This response: {current_total:,} tokens ({_current_response_prompt_tokens:,}+{_current_response_completion_tokens:,}) | Total: {session_total:,} tokens"
        
        # Wait 200ms before processing next update
        await asyncio.sleep(0.4)
    
    _status_update_task = None


def _update_agent_status(state: str = None, tools: list = None, prompt_tokens: int = 0, completion_tokens: int = 0, reset: bool = False, clear_tokens: bool = False):
    """Update agent activity status display with queuing and delays.
    
    Args:
        state: Agent state indicator (🟢/🟡/🔵/🔴)
        tools: List of tool names being executed
        prompt_tokens: Prompt tokens for current response (will be added to session)
        completion_tokens: Completion tokens for current response (will be added to session)
        reset: If True, reset to idle state (deprecated, use clear_tokens instead)
        clear_tokens: If True, clear tool chain but keep token counts visible
    """
    global _status_update_queue, _status_update_task, _agent_state, _current_tool_chain
    
    if reset:
        # Legacy reset - clear everything immediately
        global _current_response_prompt_tokens, _current_response_completion_tokens
        _agent_state = "🟢"
        _current_tool_chain = []
        agent_status_line1.object = "🟢 **Ready**"
        # Keep current response tokens visible, don't reset to 0
        current_total = _current_response_prompt_tokens + _current_response_completion_tokens
        session_total = _session_prompt_tokens + _session_completion_tokens
        agent_status_line2.object = f"🎯 Last response: {current_total:,} tokens ({_current_response_prompt_tokens:,}+{_current_response_completion_tokens:,}) | 📊 Total: {session_total:,} tokens"
        return
    
    # Queue the update
    update = {
        "state": state,
        "tools": tools,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "clear_tokens": clear_tokens
    }
    _status_update_queue.append(update)
    
    # Start processing task if not already running
    if _status_update_task is None or _status_update_task.done():
        _status_update_task = asyncio.create_task(_process_status_updates())


def _load_internal_link(url: str):
    if not url:
        return
    with _programmatic_viewer_update():
        viewer.url = url
        viewer._load_url()
    # Sync handled by _on_url_change in programmatic context

# ============================================================================
# Common Utilities for Chat Handlers
# ============================================================================

def _handle_state_link_auto_load(mutated: bool, state_link: dict, link: str = None):
    """Handle auto-loading of Neuroglancer state links.
    
    Args:
        mutated: Whether a mutating tool was executed
        state_link: Dict with 'url' and 'masked' keys from backend
        link: Optional direct link (fallback if state_link is None)
    
    Returns:
        Tuple of (link_url, status_message)
    """
    global last_loaded_url
    
    if not mutated:
        return None, None
    
    link_url = (state_link or {}).get("url") or link
    if not link_url:
        return None, None
    
    latest_url.value = link_url
    
    if link_url != last_loaded_url and auto_load_checkbox.value:
        with _programmatic_viewer_update():
            viewer.url = link_url
            viewer._load_url()
        last_loaded_url = link_url
        return link_url, f"**Opened:** {link_url}"
    else:
        return link_url, "New link generated (auto-load off)."


async def _update_trace_history():
    """Fetch and update trace history display if enabled."""
    if not trace_history_checkbox.value:
        return
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            hist_resp = await client.get(f"{BACKEND}/debug/tool_trace", params={"n": trace_history_length.value})
        hist_data = hist_resp.json()
        global _trace_history
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
    except Exception as e:
        logger.exception("Trace history update failed")
        status.object += f" | Trace err: {e}"


def _debug_next_prompt(event):
    """Debug handler: Show the full prompt that would be sent to the agent next."""
    try:
        # Extract conversation history from ChatInterface
        history = []
        if hasattr(chat, 'serialize'):
            for msg in chat.serialize():
                if msg.get('role') in ['user', 'assistant']:
                    history.append({
                        'role': msg['role'],
                        'content': msg.get('object', '') if isinstance(msg.get('object'), str) else str(msg.get('object', ''))
                    })
        
        # Call debug endpoint
        import httpx
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{BACKEND}/debug/next-prompt",
                json={"messages": history}
            )
            data = resp.json()
            
            # Save to file
            from datetime import datetime
            import json
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_next_prompt_{ts}.json"
            filepath = os.path.join(os.path.expanduser("~"), "Desktop", filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            status.object = f"✅ Debug prompt saved to {filename}"
            print(f"\n{'='*80}")
            print(f"DEBUG NEXT PROMPT - saved to: {filepath}")
            print(f"{'='*80}")
            print(f"Message count: {data['message_count']}")
            print(f"Total characters: {data['character_counts']['total']:,}")
            print(f"Estimated tokens: {data['estimated_tokens']:,}")
            print(f"\nBreakdown:")
            print(f"  System prompt: {data['character_counts']['system_prompt']:,} chars")
            print(f"  State summary: {data['character_counts']['state_summary']:,} chars")
            print(f"  Data context: {data['character_counts']['data_context']:,} chars")
            print(f"  Conversation history: {data['character_counts']['conversation_history']:,} chars")
            print(f"{'='*80}\n")
            
    except Exception as e:
        logger.exception("Debug prompt failed")
        status.object = f"❌ Debug prompt failed: {e}"


debug_prompt_btn.on_click(_debug_next_prompt)


def _create_workspace_button_for_query(query_data: dict):
    """Create workspace button for query results with closure.
    
    Args:
        query_data: Query data dict from backend
    
    Returns:
        Panel Button widget
    """
    workspace_button = pn.widgets.Button(
        name="📊 Add to Workspace",
        button_type="primary",
        sizing_mode="fixed",
        width=150,
        margin=(5, 0)
    )
    
    captured_data = query_data
    
    def add_to_workspace(event):
        _add_result_to_workspace_from_data(captured_data)
        workspace_button.name = "✓ Added to Workspace"
        workspace_button.button_type = "success"
        workspace_button.disabled = True
    
    workspace_button.on_click(add_to_workspace)
    return workspace_button


def _create_workspace_button_for_plot(plot_pane, plot_type: str, x: str, y: str):
    """Create workspace button for plot results with closure.
    
    Args:
        plot_pane: The plot pane to add
        plot_type: Type of plot (scatter, line, bar, heatmap)
        x: X-axis column name
        y: Y-axis column name
    
    Returns:
        Panel Button widget
    """
    workspace_button = pn.widgets.Button(
        name="📊 Add Plot to Workspace",
        button_type="primary",
        sizing_mode="fixed",
        width=180,
        margin=(5, 0)
    )
    
    plot_summary = f"{x} vs {y}" if x and y else None
    
    def add_plot_to_workspace(event):
        _add_plot_to_workspace(plot_pane, plot_type, plot_summary)
        workspace_button.name = "✓ Added to Workspace"
        workspace_button.button_type = "success"
        workspace_button.disabled = True
    
    workspace_button.on_click(add_plot_to_workspace)
    return workspace_button


def _create_workspace_button_for_table(table_text: str, ng_views_data: list):
    """Create workspace button for markdown table with closure.
    
    Args:
        table_text: Markdown table text
        ng_views_data: List of ng_views for interactive buttons
    
    Returns:
        Panel Button widget
    """
    workspace_button = pn.widgets.Button(
        name="📊 Add to Workspace",
        button_type="primary",
        sizing_mode="fixed",
        width=200,
        margin=(5, 0)
    )
    
    captured_table = table_text
    captured_ng_views = ng_views_data
    
    def add_to_workspace(event):
        _add_result_to_workspace(captured_table, captured_ng_views)
        workspace_button.name = "✓ Added to Workspace"
        workspace_button.button_type = "success"
        workspace_button.disabled = True
    
    workspace_button.on_click(add_to_workspace)
    return workspace_button


def _build_query_result_components(safe_answer: str, expression: str, tabulator_widget, workspace_button):
    """Build components for query result display.
    
    Args:
        safe_answer: Masked LLM response text
        expression: Polars expression code
        tabulator_widget: The table widget (or None)
        workspace_button: Workspace button widget
    
    Returns:
        List of Panel components
    """
    components = []
    
    # Add LLM context if present (strip out code blocks since expression is shown separately)
    if safe_answer and safe_answer.strip():
        llm_text = safe_answer.strip()
        
        # Remove code blocks (expression is rendered separately by frontend)
        import re
        llm_text = re.sub(r'```[a-z]*\n.*?\n```', '', llm_text, flags=re.DOTALL)
        llm_text = llm_text.strip()
        
        # Filter out if it looks like the LLM is listing data rows
        if llm_text:
            line_count = llm_text.count("\n")
            colon_count = llm_text.count(":")
            if not (line_count > 5 and colon_count > line_count):
                components.append(pn.pane.Markdown(llm_text, sizing_mode="stretch_width", margin=(5, 5, 5, 5)))
    
    # Add expression display
    if expression:
        expression_display = pn.pane.Markdown(
            f"```python\n{expression}\n```",
            sizing_mode="stretch_width",
            margin=(5, 5, 10, 5)
        )
        components.append(expression_display)
    
    # Add table and button (only if table was created)
    if tabulator_widget is not None:
        components.append(tabulator_widget)
    components.append(workspace_button)
    
    return components


def _build_plot_result_components(safe_answer: str, expression: str, plot_pane, plot_info: str, workspace_button):
    """Build components for plot result display.
    
    Args:
        safe_answer: Masked LLM response text
        expression: Polars expression code
        plot_pane: The plot pane widget
        plot_info: Plot metadata string
        workspace_button: Workspace button widget
    
    Returns:
        List of Panel components
    """
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
    
    # Add plot info and plot
    components.append(pn.pane.Markdown(plot_info, sizing_mode="stretch_width", margin=(5, 5, 5, 5)))
    components.append(plot_pane)
    components.append(workspace_button)
    
    return components


# ============================================================================
# Streaming Chat Handler
# ============================================================================

async def respond_streaming(contents: str, user: str, **kwargs):
    """Handle streaming chat with Server-Sent Events.
    
    Args:
        contents: User message text
        user: User identifier
        **kwargs: Additional chat parameters (includes 'instance' with ChatInterface reference)
    
    Yields:
        Chat message content (text, markdown, or Panel components)
    """
    global last_loaded_url, _current_response_prompt_tokens, _current_response_completion_tokens
    
    # Start new response - reset current response token counters
    _current_response_prompt_tokens = 0
    _current_response_completion_tokens = 0
    _update_agent_status(state="🟡", tools=[])
    
    try:
        accumulated_message = ""
        tool_names = []
        mutated = False
        state_link = None
        has_yielded = False
        event_count = 0
        response_usage = {}
        
        # Extract conversation history from ChatInterface instance
        history = []
        instance = kwargs.get('instance')
        if instance and hasattr(instance, 'serialize'):
            # Get serialized messages and convert to API format
            for msg in instance.serialize():
                if msg.get('role') in ['user', 'assistant']:
                    history.append({
                        'role': msg['role'],
                        'content': msg.get('object', '') if isinstance(msg.get('object'), str) else str(msg.get('object', ''))
                    })
        
        async with httpx.AsyncClient(timeout=120) as client:
            # Build messages list: history + current prompt
            messages = history
            messages.append({"role": "user", "content": contents})
            chat_payload = {"messages": messages}
            
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
                                _update_agent_status(state="🔵", tools=tool_names)
                        
                        elif event_type == "final":
                            mutated = event.get("mutated", False)
                            state_link = event.get("state_link")
                            response_usage = event.get("usage", {})
                            # Use content from final event if we haven't streamed any
                            final_content = event.get("content", "")
                            if not has_yielded and final_content:
                                accumulated_message = final_content
                                yield _mask_client_side(accumulated_message)
                                has_yielded = True
                        
                        elif event_type == "error":
                            error_msg = event.get("error", "Unknown error")
                            logger.error(f"Stream error: {error_msg}")
                            _update_agent_status(state="🔴", tools=tool_names)
                            yield f"Error: {error_msg}"
                            has_yielded = True
                            break
                        
                        elif event_type == "complete":
                            break
        
        # Update token counts
        if response_usage:
            _update_agent_status(
                prompt_tokens=response_usage.get("prompt_tokens", 0),
                completion_tokens=response_usage.get("completion_tokens", 0)
            )
        
        # Handle state link auto-load
        link_url, status_msg = _handle_state_link_auto_load(mutated, state_link)
        if status_msg:
            # Abbreviate Neuroglancer URLs in status
            if "Opened:" in status_msg and "neuroglancer" in status_msg.lower():
                status.object = "🔗 View updated"
            else:
                status.object = status_msg
        elif tool_names:
            status.object = f"Tools: {' → '.join(tool_names)}"
        else:
            status.object = "✓ Ready"
        
        # Clear tool chain but keep tokens visible
        _update_agent_status(state="🟢", clear_tokens=True)
        
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


# ============================================================================
# Non-Streaming Chat Handler
# ============================================================================

async def respond_non_streaming(contents: str, user: str, **kwargs):
    """Handle non-streaming chat with single backend call.
    
    Args:
        contents: User message text
        user: User identifier
        **kwargs: Additional chat parameters (includes 'instance' with ChatInterface reference)
    
    Yields:
        Chat message content (text, markdown, or Panel components)
    """
    global last_loaded_url, _current_response_prompt_tokens, _current_response_completion_tokens
    
    # Start new response - reset current response token counters
    _current_response_prompt_tokens = 0
    _current_response_completion_tokens = 0
    _update_agent_status(state="🟡", tools=[])
    
    try:
        # Extract conversation history from ChatInterface instance
        history = []
        instance = kwargs.get('instance')
        if instance and hasattr(instance, 'serialize'):
            # Get serialized messages and convert to API format
            for msg in instance.serialize():
                if msg.get('role') in ['user', 'assistant']:
                    history.append({
                        'role': msg['role'],
                        'content': msg.get('object', '') if isinstance(msg.get('object'), str) else str(msg.get('object', ''))
                    })
        
        result = await agent_call(contents, history=history)
        link = result.get("url")
        mutated = bool(result.get("mutated"))
        safe_answer = _mask_client_side(result.get("answer")) if result.get("answer") else None
        ng_views_data = result.get("ng_views_raw")
        query_data = result.get("query_data")
        plot_data = result.get("plot_data")
        trace = result.get("tool_trace") or []
        vt = result.get("views_table")
        usage = result.get("usage", {})
        
        # Update status with tool names and agent activity
        tool_names = []
        if trace:
            tool_names = [t.get("tool") or t.get("name") for t in trace if t]
            if tool_names:
                status.object = f"Tools: {' → '.join(tool_names)}"
        
        # Update agent status with tools and tokens together
        if usage:
            prompt_toks = usage.get("prompt_tokens", 0)
            completion_toks = usage.get("completion_tokens", 0)
            logger.debug(f"Updating agent status with tokens: prompt={prompt_toks}, completion={completion_toks}")
            _update_agent_status(
                state="🔵" if tool_names else "🟡",
                tools=tool_names,
                prompt_tokens=prompt_toks,
                completion_tokens=completion_toks
            )
        else:
            logger.debug("No usage data received from backend")
        
        # Update trace history
        await _update_trace_history()
        
        # Handle multi-view table errors
        if vt and isinstance(vt, dict) and vt.get("error"):
            warn_txt = ""
            if vt.get("warnings"):
                warn_txt = "\n\nWarnings:\n- " + "\n- ".join(vt.get("warnings") or [])
            status.object = f"Multi-view error: {vt.get('error')}{warn_txt}"
        
        embedded_table_component = None
        
        # Render multi-view table if present and successful
        if vt and isinstance(vt, dict) and vt.get("rows"):
            rows = vt["rows"]
            import pandas as pd
            df_rows = []
            for r in rows:
                display = {k: v for k, v in r.items() if k not in ("link", "masked_link")}
                raw = r.get("link")
                if raw:
                    display["view"] = f"<a href='{raw}' target='_blank'>link</a>"
                df_rows.append(display)
            
            if df_rows:
                views_table.value = pd.DataFrame(df_rows)
                views_table.visible = True
                views_table.disabled = False
                try:
                    views_table.formatters = {"view": {"type": "html"}}
                except Exception:
                    pass
                
                embedded_table_component = pn.widgets.Tabulator(
                    views_table.value.copy(), height=220, disabled=True, selectable=False, pagination=None
                )
                try:
                    embedded_table_component.formatters = {"view": {"type": "html"}}
                except Exception:
                    pass
                
                # Add click behavior
                def _on_select(event):
                    if not ng_links_internal.value:
                        return
                    try:
                        data = views_table.value
                        if data is not None and hasattr(data, "index") and len(data.index) > 0 and event.new:
                            idxs = event.new
                            if isinstance(idxs, list) and idxs:
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
                        pass
                
                # Auto-load first link
                if ng_links_internal.value and auto_load_checkbox.value and rows:
                    _load_internal_link(rows[0].get("link"))
        
        # Handle state link for single mutations (not multi-view)
        if mutated and link and not vt:
            latest_url.value = link
            masked = result.get("masked") or f"[Updated Neuroglancer view]({link})"
            link_url, status_msg = _handle_state_link_auto_load(mutated, {"url": link}, link)
            if status_msg:
                status.object = status_msg
            
            if safe_answer:
                yield f"{safe_answer}\n\n{masked}"
            else:
                yield masked
        else:
            if not trace:
                status.object = "Done (no view change)."
            
            # Return embedded table if present
            if embedded_table_component is not None:
                if safe_answer:
                    yield pn.Column(pn.pane.Markdown(safe_answer), embedded_table_component, sizing_mode="stretch_width")
                else:
                    yield pn.Column(embedded_table_component, sizing_mode="stretch_width")
            
            # Render query_data and/or plot_data
            elif query_data or plot_data:
                components_to_yield = []
                
                # Render query_data as Tabulator (if present)
                if query_data and isinstance(query_data, dict) and query_data.get("data"):
                    logger.info(f"✅ Rendering Tabulator from query_data: {query_data.get('rows')} rows")
                    
                    # Check if we should skip table when plot is also present
                    tabulator_widget = None
                    if plot_data and isinstance(plot_data, dict) and plot_data.get("plot_kwargs"):
                        if not show_query_tables.value:
                            logger.info("Skipping query table rendering because plot_data is present and show_query_tables=False")
                        else:
                            tabulator_widget = _create_tabulator_from_query_data(query_data)
                    else:
                        tabulator_widget = _create_tabulator_from_query_data(query_data)
                    
                    if tabulator_widget:
                        expression = query_data.get("expression", "")
                        workspace_button = _create_workspace_button_for_query(query_data)
                        query_components = _build_query_result_components(safe_answer, expression, tabulator_widget, workspace_button)
                        
                        components_to_yield.append(pn.Column(
                            *query_components,
                            sizing_mode="stretch_width",
                            min_height=200,
                            margin=(0, 0, 20, 0)
                        ))
                
                # Render plot_data natively (if present)
                if plot_data and isinstance(plot_data, dict) and plot_data.get("plot_kwargs"):
                    logger.info(f"✅ Rendering plot from plot_data: type={plot_data.get('plot_type')}, interactive={plot_data.get('is_interactive')}")
                    
                    try:
                        source_id = plot_data.get("source_id")
                        plot_kwargs = plot_data.get("plot_kwargs", {})
                        plot_type = plot_data.get("plot_type", "scatter")
                        expression = plot_data.get("expression", "")
                        plot_data_rows = plot_data.get("data")
                        
                        if plot_data_rows:
                            import polars as pl
                            df = pl.DataFrame(plot_data_rows)
                            
                            # For bar plots, ensure x-axis column is categorical
                            if plot_type == "bar" and 'x' in plot_kwargs:
                                x_col = plot_kwargs['x']
                                if x_col in df.columns:
                                    df = df.with_columns(pl.col(x_col).cast(pl.Utf8))
                            
                            import hvplot.polars
                            
                            # Create the plot
                            if plot_type == "scatter":
                                plot = df.hvplot.scatter(**plot_kwargs)
                            elif plot_type == "line":
                                plot = df.hvplot.line(**plot_kwargs)
                            elif plot_type == "bar":
                                bar_kwargs = plot_kwargs.copy()
                                bar_kwargs.pop('by', None)
                                plot = df.hvplot.bar(**bar_kwargs)
                            elif plot_type == "heatmap":
                                plot = df.hvplot.heatmap(**plot_kwargs)
                            else:
                                plot = df.hvplot(**plot_kwargs)
                            
                            plot_pane = pn.pane.HoloViews(
                                object=plot,
                                sizing_mode="stretch_width",
                                height=400
                            )
                            
                            plot_info = f"**{plot_type.capitalize()}** plot • "
                            plot_info += f"{'Interactive' if plot_data.get('is_interactive') else 'Static'} • "
                            plot_info += f"{plot_data.get('row_count', 0)} points"
                            
                            x = plot_kwargs.get('x', '')
                            y = plot_kwargs.get('y', '')
                            workspace_button = _create_workspace_button_for_plot(plot_pane, plot_type, x, y)
                            plot_components = _build_plot_result_components(None if components_to_yield else safe_answer, expression, plot_pane, plot_info, workspace_button)
                            
                            components_to_yield.append(pn.Column(
                                *plot_components,
                                sizing_mode="stretch_width",
                                margin=(0, 0, 30, 0)
                            ))
                        else:
                            components_to_yield.append("Error: No plot data received from backend")
                    except Exception as e:
                        logger.exception("Failed to render plot")
                        components_to_yield.append(f"Error rendering plot: {str(e)}")
                
                # Yield all accumulated components (query table + plot)
                if components_to_yield:
                    yield pn.Column(*components_to_yield, sizing_mode="stretch_width")
            
            # Legacy markdown table rendering
            elif safe_answer and "|" in safe_answer and safe_answer.count("\n") > 2:
                tabulator_widget = _create_tabulator_from_markdown(safe_answer, ng_views_data)
                workspace_button = _create_workspace_button_for_table(safe_answer, ng_views_data)
                
                yield pn.Column(
                    tabulator_widget,
                    workspace_button,
                    sizing_mode="stretch_width",
                    min_height=200,
                    margin=(0, 0, 20, 0)
                )
            else:
                yield safe_answer if safe_answer else "(no response)"
        
        # Clear tool chain but keep tokens visible
        _update_agent_status(state="🟢", clear_tokens=True)
    
    except Exception as e:
        logger.exception("Chat error")
        status.object = f"Error: {e}"
        _update_agent_status(state="🔴", tools=[])
        yield f"Error: {e}"


# ============================================================================
# Main Chat Entry Point
# ============================================================================

async def respond(contents: str, user: str, **kwargs):
    """Main chat callback - dispatches to streaming or non-streaming handler.
    
    Args:
        contents: User message text
        user: User identifier
        **kwargs: Additional chat parameters
    
    Yields:
        Chat message content from appropriate handler
    """
    if USE_STREAMING:
        async for result in respond_streaming(contents, user, **kwargs):
            yield result
    else:
        async for result in respond_non_streaming(contents, user, **kwargs):
            yield result


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
viewer_settings_card = pn.Card(
    pn.Column(
        pn.pane.Markdown("**Viewer Display**"),
        viewer_show_scale_bar,
        viewer_show_annotations,
        viewer_show_axis_lines,
        viewer_layout,
    ),
    title="Viewer Settings",
    collapsed=False,
)

settings_card = pn.Card(
    pn.Column(
        pn.pane.Markdown("**System Controls**"),
        auto_load_checkbox,
        show_query_tables,
        show_agent_status,
        latest_url,
        open_latest_btn,
        ng_links_internal,
        update_state_interval,
        trace_history_checkbox,
        trace_history_length,
        trace_download,
        pn.pane.Markdown("**Debug Tools**"),
        debug_prompt_btn,
        _recent_traces_accordion,
        status,
    ),
    title="System Settings",
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
        disabled=False,  # Enable interaction for preview button
        show_index=False,
        sizing_mode="stretch_width",
        layout="fit_columns",  # Stretch columns to fill available width
        buttons={
            'preview': "<i class='fa fa-eye' title='Preview file'></i>",
            'delete': "<i class='fa fa-trash' title='Delete file'></i>",
        },
    )
    
    # Add click handler for uploaded_table preview and delete buttons
    def _on_uploaded_table_click(event):
        if event.row is not None:
            try:
                df = uploaded_table.value
                if df is not None and len(df) > event.row:
                    file_id = df.iloc[event.row].get('file_id')
                    if not file_id:
                        return
                    
                    if event.column == 'preview':
                        _update_preview(file_id=file_id, is_summary=False)
                    elif event.column == 'delete':
                        # Delete the file
                        try:
                            with httpx.Client(timeout=10) as client:
                                resp = client.post(f"{BACKEND}/delete_file", params={"file_id": file_id})
                                rj = resp.json()
                                if rj.get('ok'):
                                    upload_notice.object = "✅ File deleted"
                                    _refresh_files()
                                    _refresh_summaries()
                                else:
                                    upload_notice.object = f"❌ Delete failed: {rj.get('error')}"
                        except Exception as e:
                            upload_notice.object = f"❌ Delete error: {e}"
                            logger.error(f"Error deleting file: {e}")
            except Exception as e:
                logger.error(f"Error handling table click: {e}")
    
    uploaded_table.on_click(_on_uploaded_table_click)
    
    summaries_table = pn.widgets.Tabulator(
        pd.DataFrame(columns=["summary_id","source_file_id","kind","n_rows","n_cols"]),
        height=0,
        disabled=False,  # Enable interaction for preview button
        show_index=False,
        buttons={
            'preview': "<i class='fa fa-eye' title='Preview summary'></i>",
        },
    )
    
    # Add click handler for summaries_table preview button
    def _on_summaries_table_click(event):
        if event.column == 'preview' and event.row is not None:
            try:
                df = summaries_table.value
                if df is not None and len(df) > event.row:
                    summary_id = df.iloc[event.row].get('summary_id')
                    if summary_id:
                        _update_preview(summary_id=summary_id, is_summary=True)
            except Exception as e:
                logger.error(f"Error handling summary preview click: {e}")
    
    summaries_table.on_click(_on_summaries_table_click)
else:
    uploaded_table = pn.pane.Markdown("pandas not available")
    summaries_table = pn.pane.Markdown("pandas not available")

# Helper to update upload tab title with dynamic file count
def _update_upload_card_title(n: int):
    try:
        label = "file" if n == 1 else "files"
        # Update the tab title (will be set after workspace_tabs is created)
        # This is called during refresh, tabs will exist by then
        if 'workspace_tabs' in globals():
            workspace_tabs[0] = (f"Data Upload (📁 {n} {label})", data_upload_content)
    except Exception:
        # Fallback silently; title update is non-critical
        pass

# Helper to update summaries tab title with dynamic count
def _update_summaries_card_title(n: int):
    try:
        if 'workspace_tabs' in globals():
            workspace_tabs[1] = (f"Summaries (📋 {n})", summaries_content)
    except Exception:
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
            # Add preview and delete columns
            df['preview'] = ''
            df['delete'] = ''
            # Reorder with name first, action buttons at end, keep file_id (hidden)
            desired = [c for c in ["name","size","n_rows","n_cols","preview","delete","file_id"] if c in df.columns]
            df = df[desired]
            # Rename display columns
            rename_map = {"name":"Name","size":"Size","n_rows":"Rows","n_cols":"Cols","preview":"Preview","delete":"Delete"}
            df = df.rename(columns=rename_map)
            uploaded_table.value = df
            # Hide file_id if present
            hidden_cols = [c for c in ["file_id"] if c in df.columns]
            if hidden_cols:
                uploaded_table.hidden_columns = hidden_cols
            # Set column widths
            uploaded_table.widths = {'Preview': 60, 'Delete': 60}
            uploaded_table.titles = {'Preview': 'Preview', 'Delete': 'Delete'}
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
        _update_summaries_card_title(len(data))
        if data:
            df = pd.DataFrame(data)
            # Add preview column
            df['preview'] = ''
            # Reorder with kind first, preview at end; retain IDs (hidden)
            desired_order = [c for c in ["kind","n_rows","n_cols","preview","summary_id","source_file_id"] if c in df.columns]
            df = df[desired_order]
            rename_map = {"kind":"Kind","n_rows":"Rows","n_cols":"Cols","preview":"Preview"}
            df = df.rename(columns=rename_map)
            summaries_table.value = df
            hidden_cols = [c for c in ["summary_id","source_file_id"] if c in df.columns]
            if hidden_cols:
                summaries_table.hidden_columns = hidden_cols
            # Set column widths
            summaries_table.widths = {'Preview': 60}
            summaries_table.titles = {'Preview': 'Preview'}
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

                # Show only error messages, success is indicated by table refresh
                if not rj.get("ok"):
                    msgs.append(f"❌ {name}: {rj.get('error')}")
            except Exception as e:  # pragma: no cover
                msgs.append(f"❌ {name}: {e}")
    upload_notice.object = "\n".join(msgs)
    _refresh_files()
    _refresh_summaries()

file_drop.param.watch(_handle_file_upload, "value")

def _initial_refresh():
    _refresh_files()
    _refresh_summaries()

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
    
    # Intelligently size based on column count
    cols = len(query_data.get("columns", []))
    rows = query_data.get("rows", 0)
    
    # For small tables (few columns), use compact width; for large tables, stretch
    if cols <= 3:
        # Compact table - don't stretch full width
        table_container = pn.Column(
            tabulator_widget,
            sizing_mode="fixed",
            width=min(400, cols * 150),  # Scale with columns, max 400px
            margin=(0, 0, 0, 0)
        )
    elif cols <= 6:
        # Medium table
        table_container = pn.Column(
            tabulator_widget,
            sizing_mode="fixed",
            width=600,
            margin=(0, 0, 0, 0)
        )
    else:
        # Large table - use full width
        table_container = pn.Column(
            tabulator_widget,
            sizing_mode="stretch_width",
            margin=(0, 0, 0, 0)
        )
    
    # Create collapsible card
    result_card = pn.Card(
        table_container,
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
    
    # Update Results tab title with counter (Results is now tab 2)
    if 'workspace_tabs' in globals():
        workspace_tabs[2] = (f"Results (📊 {len(workspace_results_list)})", workspace_body)


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
    
    # Update Results tab title with counter (Results is now tab 2)
    if 'workspace_tabs' in globals():
        workspace_tabs[2] = (f"Results (📊 {len(workspace_results_list)})", workspace_body)


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
    
    # Create a square-ish plot container (not stretched)
    # Clone the plot pane with fixed square sizing
    plot_container = pn.Column(
        plot_pane,
        sizing_mode="fixed",
        width=500,   # Fixed width for square appearance
        height=500,  # Fixed height to match
        margin=(0, 0, 0, 0)
    )
    
    # Create collapsible card
    result_card = pn.Card(
        plot_container,
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
    
    # Update Results tab title with counter (Results is now tab 2)
    if 'workspace_tabs' in globals():
        workspace_tabs[2] = (f"Results (📊 {len(workspace_results_list)})", workspace_body)


workspace_header = pn.pane.Markdown("### Query Results\n_Full tables and visualizations appear here._", margin=(0, 0, 10, 0))
workspace_results_container = pn.Column(sizing_mode="stretch_width")

# Height toggle button for workspace expansion
workspace_expanded = pn.widgets.Toggle(
    name="⬍ Expand Workspace ⬍",
    value=False,
    button_type="default",
    sizing_mode="fixed",
    width=180,
    margin=(0, 0, 10, 0)
)

def toggle_workspace_height(event):
    """Toggle workspace height between compact (600px) and expanded (800px)"""
    if event.new:
        workspace_tabs.styles = {"maxHeight": "800px", "overflow": "auto"}
        workspace_card.styles = {"maxHeight": "800px", "overflow": "auto"}
        workspace_expanded.name = "⬆ Compact Workspace ⬆"
        workspace_expanded.button_type = "primary"
    else:
        workspace_tabs.styles = {"maxHeight": "600px", "overflow": "auto"}
        workspace_card.styles = {"maxHeight": "600px", "overflow": "auto"}
        workspace_expanded.name = "⬍ Expand Workspace ⬍"
        workspace_expanded.button_type = "default"

workspace_expanded.param.watch(toggle_workspace_height, 'value')

workspace_body = pn.Column(
    workspace_expanded,
    workspace_results_container,
    sizing_mode="stretch_width",
    scroll=True,
)

# Data upload tab content with preview card side-by-side
data_upload_left = pn.Column(
    file_drop,
    upload_notice,
    uploaded_table,
    sizing_mode="stretch_width",
    margin=(10, 10, 10, 10),
    min_width=400,
)

# Use GridSpec for proper 2-column layout with percentage-based widths
data_upload_grid = pn.GridSpec(sizing_mode='stretch_width', margin=0)
data_upload_grid[0, 0:4] = data_upload_left           # Takes 30% (3 out of 10 columns)
data_upload_grid[0, 4:10] = data_upload_preview_card  # Takes 70% (7 out of 10 columns)
data_upload_content = data_upload_grid

# Summaries tab content with preview card side-by-side
summaries_left = pn.Column(
    summaries_table,
    sizing_mode="stretch_width",
    margin=(10, 10, 10, 10),
    min_width=400,
)

# Use GridSpec for proper 2-column layout
summaries_grid = pn.GridSpec(sizing_mode='stretch_width', margin=0)
summaries_grid[0, 0:4] = summaries_left           # Takes 30%
summaries_grid[0, 4:10] = summaries_preview_card  # Takes 70%
summaries_content = summaries_grid

# Create tabbed workspace panel
workspace_tabs = pn.Tabs(
    ("Data Upload (📁 0 files)", data_upload_content),
    ("Summaries (📋 0)", summaries_content),
    ("Results (📊 0)", workspace_body),
    dynamic=True,
    sizing_mode="stretch_width",
    styles={"maxHeight": "600px", "overflow": "auto"},
)

# Constrain height to 600px with scrolling inside (can be toggled to 800px)
workspace_card = pn.Card(
    workspace_tabs,
    title="Workspace",
    collapsed=False,  # Open at startup
    sizing_mode="stretch_width",
    styles={"maxHeight": "600px", "overflow": "auto"},
    margin=(0, 0, 10, 0)
)

app = pn.template.FastListTemplate(
    title=f"Neuroglanger Chat v{version}",
    sidebar=[agent_status_card, chat], #views_table (dont need below)
    right_sidebar=[reset_app_btn, viewer_settings_card, settings_card],
    collapsed_right_sidebar = True,
    main=[workspace_card, viewer],
    sidebar_width=500,
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