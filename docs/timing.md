# Agent Loop Timing & Performance Instrumentation

## Overview

The neuroglancer_chat agent loop now includes comprehensive timing instrumentation to help identify performance bottlenecks and optimize response times. This feature captures detailed metrics at key points in the request lifecycle and provides both file-based logging and real-time monitoring.

## Features

- **Detailed Timing Metrics**: Captures timing at multiple granularities:
  - Request-level (total duration)
  - Phase-level (prompt assembly, agent loop, response assembly)
  - LLM call-level (per iteration, with token counts)
  - Tool execution-level (per tool, with payload sizes)
  - Context assembly (state summary, data context, interaction memory)

- **JSONL Output**: Structured logging to `./logs/agent_timing.jsonl` for easy analysis
- **In-Memory Storage**: Recent records (last 100) kept in memory for real-time monitoring
- **Real-Time Monitoring**: `/debug/timing` endpoint provides live statistics and tabular data
- **Minimal Performance Impact**: Timing collection adds negligible overhead
- **Optional Mode**: Enable only when needed via environment variable

## Architecture

### Timing Flow

```
Request Received
    ↓
Prompt Assembly Phase
    ├─ State Summary Timing
    ├─ Data Context Timing
    └─ Interaction Memory Timing
    ↓
Agent Loop Start
    ↓
Iteration 1
    ├─ LLM Call (with token counts)
    └─ Tool Executions (with payload sizes)
    ↓
Iteration 2
    ├─ LLM Call
    └─ Tool Executions
    ↓
... (up to 3 iterations)
    ↓
Agent Loop End
    ↓
Response Assembly Phase
    ├─ State Link Generation
    ├─ Interaction Memory Update
    └─ Trace History Update
    ↓
Response Sent
    ↓
Finalize & Write Timing Record
```

### Data Structure

Each request produces a comprehensive timing record:

```json
{
  "request_id": "abc123...",
  "timestamp": "2025-10-17T14:30:45.123Z",
  "user_prompt": "show me the hemibrain...",
  "timings": {
    "request_received": 0.0,
    "prompt_assembly": {
      "start": 0.001,
      "end": 0.045,
      "duration": 0.044
    },
    "context": {
      "state_summary": 0.012,
      "data_context": 0.018,
      "interaction_memory": 0.003,
      "total_chars": 1500
    },
    "agent_loop": {
      "start": 0.045,
      "end": 2.567,
      "duration": 2.522,
      "iterations": [
        {
          "iteration": 0,
          "llm_call": {
            "start": 0.045,
            "end": 1.234,
            "duration": 1.189,
            "model": "gpt-4o",
            "prompt_tokens": 2500,
            "completion_tokens": 150
          },
          "tools": [
            {
              "name": "ng_set_view",
              "start": 1.234,
              "end": 1.245,
              "duration": 0.011,
              "args_size_bytes": 256,
              "result_size_bytes": 128
            }
          ]
        },
        {
          "iteration": 1,
          "llm_call": {
            "start": 1.245,
            "end": 2.550,
            "duration": 1.305,
            "model": "gpt-4o",
            "prompt_tokens": 2800,
            "completion_tokens": 80
          },
          "tools": []
        }
      ]
    },
    "response_assembly": {
      "start": 2.567,
      "end": 2.580,
      "duration": 0.013
    },
    "response_sent": 2.580,
    "total_duration": 2.580
  },
  "summary": {
    "total_duration": 2.580,
    "llm_duration": 2.494,
    "llm_percentage": 96.7,
    "tool_duration": 0.011,
    "tool_percentage": 0.4,
    "overhead_duration": 0.075,
    "overhead_percentage": 2.9,
    "num_iterations": 2,
    "num_tools_called": 1,
    "total_tokens": 5530
  }
}
```

## Usage

### Enable Timing Mode

#### Option 1: Using Launch Scripts

**Bash (Linux/macOS/WSL/Git Bash):**
```bash
./start.sh --timing
```

**PowerShell (Windows):**
```powershell
.\start.ps1 -Timing
```

#### Option 2: Environment Variable

Set the environment variable before starting the backend:

**Bash:**
```bash
export TIMING_MODE=true
uv run uvicorn backend.main:app --reload --port 8000
```

**PowerShell:**
```powershell
$env:TIMING_MODE = "true"
uv run uvicorn backend.main:app --reload --port 8000
```

#### Option 3: .env File

Add to your `.env` file in the project root:
```
TIMING_MODE=true
TIMING_OUTPUT_FILE=./logs/agent_timing.jsonl  # optional, this is the default
TIMING_VERBOSE=false  # optional, set to true for console logging
```

### View Real-Time Statistics

Access the real-time monitoring endpoint:

```bash
# Get statistics and last 20 requests
curl http://127.0.0.1:8000/debug/timing

# Get all available timing records (up to 100)
curl http://127.0.0.1:8000/debug/timing

# Get specific number of recent records
curl "http://127.0.0.1:8000/debug/timing?n=10"
```

Or visit in your browser:
```
http://127.0.0.1:8000/debug/timing
```

### Response Format

The `/debug/timing` endpoint returns:

```json
{
  "stats": {
    "count": 25,
    "timing_mode_enabled": true,
    "total_duration": {
      "avg": 2.450,
      "p50": 2.340,
      "p95": 4.120,
      "p99": 5.230,
      "min": 1.120,
      "max": 5.450
    },
    "llm_duration": {
      "avg": 2.100,
      "p50": 2.050,
      "p95": 3.800
    },
    "tool_duration": {
      "avg": 0.045,
      "p50": 0.030,
      "p95": 0.120
    },
    "recent_requests": [
      {
        "request_id": "abc12345",
        "timestamp": "2025-10-17T14:30:45.123Z",
        "user_prompt": "show me the hemibrain",
        "total_duration": 2.580,
        "llm_duration": 2.494,
        "tool_duration": 0.011,
        "num_iterations": 2,
        "num_tools": 1
      }
    ]
  },
  "records": [...],  // Full timing records
  "count": 25
}
```

## Analysis

### Analyzing JSONL Output

The timing data is saved to `./logs/agent_timing.jsonl` where each line is a complete JSON record.

#### Python Analysis Example

```python
import json
import pandas as pd
from pathlib import Path

# Load timing records
records = []
with open("./logs/agent_timing.jsonl") as f:
    for line in f:
        records.append(json.loads(line))

# Extract summary data
df = pd.DataFrame([r["summary"] for r in records])

# Basic statistics
print("Average total duration:", df["total_duration"].mean())
print("P95 LLM duration:", df["llm_duration"].quantile(0.95))
print("Average tools per request:", df["num_tools_called"].mean())

# Find slow requests
slow = df[df["total_duration"] > df["total_duration"].quantile(0.90)]
print(f"\nSlowest 10% of requests ({len(slow)} requests):")
print(slow[["total_duration", "llm_duration", "num_iterations", "num_tools_called"]])

# LLM vs Tool time breakdown
print("\nTime breakdown:")
print(f"  LLM: {df['llm_percentage'].mean():.1f}%")
print(f"  Tools: {df['tool_percentage'].mean():.1f}%")
print(f"  Overhead: {df['overhead_percentage'].mean():.1f}%")
```

#### Bash Analysis Example

```bash
# Count total requests
wc -l logs/agent_timing.jsonl

# Extract total durations
jq '.summary.total_duration' logs/agent_timing.jsonl

# Find requests that took > 3 seconds
jq 'select(.summary.total_duration > 3)' logs/agent_timing.jsonl

# Average LLM percentage
jq '.summary.llm_percentage' logs/agent_timing.jsonl | awk '{sum+=$1} END {print sum/NR}'

# Most used tools
jq -r '.timings.agent_loop.iterations[].tools[].name' logs/agent_timing.jsonl | sort | uniq -c | sort -rn
```

### Common Bottlenecks & Solutions

#### 1. High LLM Duration (>80% of total)
**Symptoms:** `llm_percentage` consistently above 80%

**Possible Causes:**
- Large context size (many uploaded files, long interaction history)
- Complex tool schemas
- Model latency

**Solutions:**
- Reduce context size via more aggressive truncation
- Simplify tool descriptions
- Consider faster model (e.g., gpt-4o-mini)
- Implement caching for repeated queries

#### 2. High Tool Duration
**Symptoms:** `tool_percentage` above 20%

**Possible Causes:**
- Slow data operations (large CSV processing)
- Multi-view generation with many rows
- Network calls in tools

**Solutions:**
- Optimize Polars operations (use lazy evaluation)
- Reduce `top_n` in multi-view generation
- Add caching for expensive computations
- Profile specific slow tools

#### 3. High Overhead
**Symptoms:** `overhead_percentage` above 15%

**Possible Causes:**
- Slow state serialization
- Interaction memory updates
- JSON encoding/decoding

**Solutions:**
- Optimize state serialization
- Reduce interaction memory size
- Use faster JSON library (orjson)

#### 4. Multiple Iterations
**Symptoms:** `num_iterations` consistently 3 (maximum)

**Possible Causes:**
- Model not converging
- Too many tool calls needed
- Ambiguous user requests

**Solutions:**
- Improve system prompt clarity
- Add examples to tool descriptions
- Implement early stopping for redundant calls

## Performance Targets

Based on typical usage patterns:

| Metric | Target | Acceptable | Needs Investigation |
|--------|--------|------------|---------------------|
| Total Duration | < 2s | 2-5s | > 5s |
| LLM Duration | < 1.5s | 1.5-4s | > 4s |
| Tool Duration | < 0.1s | 0.1-0.5s | > 0.5s |
| Overhead | < 0.2s | 0.2-0.5s | > 0.5s |
| Iterations | 1-2 | 3 | consistently 3 |
| Tools per Request | 1-3 | 4-6 | > 6 |

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TIMING_MODE` | `false` | Enable/disable timing collection |
| `TIMING_OUTPUT_FILE` | `./logs/agent_timing.jsonl` | Path to timing log file |
| `TIMING_VERBOSE` | `false` | Print timing to console |

### In-Memory Storage

- **Max Records**: 100 (hardcoded in `timing.py`)
- **Storage**: FIFO deque, automatically drops oldest when full
- **Persistence**: Records are always written to file (if `TIMING_MODE=true`), regardless of in-memory limit

## API Reference

### TimingCollector

Main class for collecting timing data within the agent loop.

```python
from neuroglancer_chat.backend.observability.timing import TimingCollector

# Initialize
timing = TimingCollector(user_prompt="your prompt here")
timing.mark("request_received")

# Time a phase
with timing.phase("prompt_assembly"):
    # ... your code
    pass

# Time LLM call
iteration = timing.start_iteration(0)
with timing.llm_call(iteration, model="gpt-4o") as llm:
    # ... call LLM
    llm.set_tokens(prompt=100, completion=50)

# Time tool execution
with timing.tool_execution(iteration, "tool_name") as tool:
    # ... execute tool
    tool.set_sizes(args=256, result=128)

# Finalize
timing.mark("response_sent")
timing.finalize()  # Writes to file and stores in memory
```

### Helper Functions

```python
from neuroglancer_chat.backend.observability.timing import (
    get_recent_records,
    get_timing_stats
)

# Get recent records
records = get_recent_records(n=10)  # Last 10 records
all_records = get_recent_records()  # All available records

# Get statistics
stats = get_timing_stats()
```

## Future Enhancements

Potential improvements for the timing system:

1. **Distributed Tracing Integration**
   - OpenTelemetry support for distributed systems
   - Span correlation across services
   - Integration with Jaeger/Zipkin

2. **Memory Profiling**
   - Track memory usage alongside timing
   - Identify memory leaks
   - Monitor garbage collection impact

3. **Automatic Alerts**
   - Threshold-based warnings
   - Slack/email notifications for slow requests
   - Automated performance regression detection

4. **Visualization Dashboard**
   - Real-time charts of timing metrics
   - Historical trends
   - Comparative analysis (before/after changes)

5. **Sampling Mode**
   - Record only a percentage of requests
   - Reduce overhead in production
   - Stratified sampling by request type

6. **Tool-Specific Metrics**
   - Per-tool percentile breakdowns
   - Tool dependency graphs
   - Cost attribution (by token count)

## Troubleshooting

### Timing File Not Created

**Problem:** `TIMING_MODE=true` but no file appears

**Solutions:**
- Check file permissions in `./logs/` directory
- Verify environment variable is actually set: `echo $TIMING_MODE`
- Check console for error messages
- Ensure `./logs/` directory exists (it's created automatically, but check permissions)

### High Memory Usage

**Problem:** Memory grows over time

**Solutions:**
- The in-memory store is bounded to 100 records
- Check if you have other memory leaks
- Recent records are small (~10KB each max)
- Total in-memory footprint: ~1MB max

### Missing Token Counts

**Problem:** `prompt_tokens` and `completion_tokens` are 0

**Solutions:**
- Ensure your LLM adapter returns usage information
- Check that `run_chat()` returns OpenAI-compatible response format
- Verify the LLM API is returning usage data

### Timing Overhead

**Problem:** Concerned about performance impact

**Solutions:**
- Timing overhead is typically <1ms per request
- Uses `time.perf_counter()` for high precision
- File writes are synchronous but fast (append-only)
- Context managers have negligible overhead
- Can disable by setting `TIMING_MODE=false`

## Support

For issues, questions, or feature requests related to timing:

1. Check this documentation
2. Review `backend/observability/timing.py` source code
3. Open a GitHub issue with timing data attached
4. Tag with `observability` or `performance` labels

---

Last updated: 2025-10-17

