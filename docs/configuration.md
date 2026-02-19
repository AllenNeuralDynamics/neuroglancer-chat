# Configuration

All environment variables and runtime settings for neuroglancer-chat.

---

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key for LLM calls |

### Backend

| Variable | Default | Description |
|----------|---------|-------------|
| `TIMING_MODE` | `false` | Enable performance timing instrumentation. See [docs/timing.md](timing.md). |

### Frontend (Panel)

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND` | `http://127.0.0.1:8000` | Backend URL for Panel to connect to |
| `USE_STREAMING` | `true` | Enable streaming chat via Server-Sent Events |
| `NEUROGLANCER_CHAT_DEBUG` | unset | Set to `"1"` to enable debug logging |
| `NEUROGLANCER_BASE` | `neuroglancer-demo.appspot.com` | Base URL for Neuroglancer viewer |

### Example `.env` / launch

```bash
# Minimal
export OPENAI_API_KEY="sk-..."

# With timing
export TIMING_MODE="true"
export OPENAI_API_KEY="sk-..."

# Debug
export NEUROGLANCER_CHAT_DEBUG="1"
```

PowerShell equivalents:
```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:TIMING_MODE = "true"
$env:NEUROGLANCER_CHAT_DEBUG = "1"
```

---

## Code-Level Configuration

### `SEND_DATA_TO_LLM`

**Location:** `src/neuroglancer_chat/backend/main.py` (near top of file)

Controls whether `data_query_polars` sends full result rows to the LLM or only a minimal acknowledgment.

```python
SEND_DATA_TO_LLM = False  # Recommended
```

**`False` (recommended):** LLM receives only row count, column names, and the expression used. Full data goes directly to the frontend Tabulator table. LLM responses are faster and cleaner.

**`True`:** LLM receives complete result rows. Use when you want the LLM to analyze or reference specific data values in follow-up answers.

---

## UI Settings

These settings are available in the Panel Settings card at runtime:

| Setting | Default | Description |
|---------|---------|-------------|
| Auto-load view | ON | Auto-apply newly generated Neuroglancer state links |
| Update state interval | 5s | Debounce delay for user-driven Neuroglancer URL changes |
| NG links open internal | ON | Open Neuroglancer links in the embedded viewer (vs. external browser) |
| Show query tables in plots | ON | Display data tables alongside generated plots |
| Trace history | OFF | Enable tool execution trace logging |

---

## Port Defaults

| Service | Port |
|---------|------|
| FastAPI backend | 8000 |
| Panel frontend | 8006 |
