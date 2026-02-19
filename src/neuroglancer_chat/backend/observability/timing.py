"""
Timing instrumentation for agent loop performance analysis.

Captures detailed timing information at key steps in the agent execution flow:
- Request handling
- Prompt assembly
- LLM calls
- Tool executions
- Response assembly

Outputs JSONL format for easy analysis. Enable with TIMING_MODE=true env var.
"""

import asyncio
import json
import os
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

# Configuration from environment
TIMING_MODE = os.getenv("TIMING_MODE", "false").lower() == "true"
TIMING_OUTPUT_FILE = os.getenv("TIMING_OUTPUT_FILE", "./logs/agent_timing.jsonl")
TIMING_VERBOSE = os.getenv("TIMING_VERBOSE", "false").lower() == "true"

# In-memory store for recent timing records (for /debug/timing endpoint)
MAX_RECENT_RECORDS = 100
_recent_records: Deque[Dict[str, Any]] = deque(maxlen=MAX_RECENT_RECORDS)


@dataclass
class ToolTiming:
    """Timing for a single tool execution."""
    name: str
    start: float
    end: float
    duration: float
    args_size_bytes: int = 0
    result_size_bytes: int = 0


@dataclass
class LLMTiming:
    """Timing for a single LLM call."""
    start: float
    end: float
    duration: float
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class IterationTiming:
    """Timing for one iteration of the agent loop."""
    iteration: int
    llm_call: Optional[LLMTiming] = None
    tools: List[ToolTiming] = field(default_factory=list)


@dataclass
class ContextTiming:
    """Timing for context assembly operations."""
    state_summary: float = 0.0
    data_context: float = 0.0
    interaction_memory: float = 0.0
    total_chars: int = 0


@dataclass
class PhaseTiming:
    """Timing for a phase with start/end/duration."""
    start: float
    end: float
    duration: float


@dataclass
class TimingRecord:
    """Complete timing record for one request."""
    request_id: str
    timestamp: str
    user_prompt: str
    
    # Timings relative to request start
    request_received: float = 0.0
    prompt_assembly: Optional[PhaseTiming] = None
    context: Optional[ContextTiming] = None
    agent_loop_start: float = 0.0
    agent_loop_end: float = 0.0
    agent_loop_duration: float = 0.0
    iterations: List[IterationTiming] = field(default_factory=list)
    response_assembly: Optional[PhaseTiming] = None
    response_sent: float = 0.0
    total_duration: float = 0.0
    
    # Summary stats
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "user_prompt": self.user_prompt,
            "timings": {
                "request_received": self.request_received,
                "prompt_assembly": asdict(self.prompt_assembly) if self.prompt_assembly else None,
                "context": asdict(self.context) if self.context else None,
                "agent_loop": {
                    "start": self.agent_loop_start,
                    "end": self.agent_loop_end,
                    "duration": self.agent_loop_duration,
                    "iterations": [
                        {
                            "iteration": it.iteration,
                            "llm_call": asdict(it.llm_call) if it.llm_call else None,
                            "tools": [asdict(t) for t in it.tools]
                        }
                        for it in self.iterations
                    ]
                },
                "response_assembly": asdict(self.response_assembly) if self.response_assembly else None,
                "response_sent": self.response_sent,
                "total_duration": self.total_duration,
            },
            "summary": self.summary
        }
        return result

    def compute_summary(self):
        """Compute summary statistics."""
        llm_duration = sum(
            it.llm_call.duration for it in self.iterations if it.llm_call
        )
        tool_duration = sum(
            tool.duration for it in self.iterations for tool in it.tools
        )
        total_tokens = sum(
            (it.llm_call.prompt_tokens + it.llm_call.completion_tokens)
            for it in self.iterations if it.llm_call
        )
        
        overhead = self.total_duration - llm_duration - tool_duration
        
        self.summary = {
            "total_duration": round(self.total_duration, 3),
            "llm_duration": round(llm_duration, 3),
            "llm_percentage": round(100 * llm_duration / self.total_duration, 1) if self.total_duration > 0 else 0,
            "tool_duration": round(tool_duration, 3),
            "tool_percentage": round(100 * tool_duration / self.total_duration, 1) if self.total_duration > 0 else 0,
            "overhead_duration": round(overhead, 3),
            "overhead_percentage": round(100 * overhead / self.total_duration, 1) if self.total_duration > 0 else 0,
            "num_iterations": len(self.iterations),
            "num_tools_called": sum(len(it.tools) for it in self.iterations),
            "total_tokens": total_tokens,
        }


class TimingCollector:
    """
    Collects timing information for a single request.
    
    Usage:
        collector = TimingCollector(user_prompt="show me...")
        collector.mark("request_received")
        
        with collector.phase("prompt_assembly"):
            # ... build prompt
            pass
        
        collector.start_agent_loop()
        for i in range(3):
            iteration = collector.start_iteration(i)
            
            with collector.llm_call(iteration, model="gpt-4o") as llm:
                # ... call LLM
                llm.set_tokens(prompt=100, completion=50)
            
            with collector.tool_execution(iteration, "ng_set_view") as tool:
                # ... execute tool
                tool.set_sizes(args=256, result=128)
        
        collector.end_agent_loop()
        
        with collector.phase("response_assembly"):
            # ... assemble response
            pass
        
        collector.mark("response_sent")
        collector.finalize()
    """
    
    def __init__(self, user_prompt: str):
        self.request_id = str(uuid.uuid4())
        self.start_time = time.perf_counter()
        self.user_prompt = user_prompt[:100]  # Truncate for logging
        
        self.record = TimingRecord(
            request_id=self.request_id,
            timestamp=datetime.utcnow().isoformat(),
            user_prompt=self.user_prompt,
        )
        
        self._phase_starts: Dict[str, float] = {}
        self._current_iteration: Optional[IterationTiming] = None
    
    def _elapsed(self) -> float:
        """Get elapsed time since request start."""
        return time.perf_counter() - self.start_time
    
    def mark(self, event: str):
        """Mark a point in time event."""
        elapsed = self._elapsed()
        if event == "request_received":
            self.record.request_received = elapsed
        elif event == "response_sent":
            self.record.response_sent = elapsed
    
    @contextmanager
    def phase(self, phase_name: str):
        """Context manager for timing a phase."""
        start = self._elapsed()
        try:
            yield
        finally:
            end = self._elapsed()
            duration = end - start
            phase_timing = PhaseTiming(start=start, end=end, duration=duration)
            
            if phase_name == "prompt_assembly":
                self.record.prompt_assembly = phase_timing
            elif phase_name == "response_assembly":
                self.record.response_assembly = phase_timing
    
    def set_context_timing(self, state_summary: float, data_context: float, 
                          interaction_memory: float, total_chars: int):
        """Set timing for context assembly operations."""
        self.record.context = ContextTiming(
            state_summary=state_summary,
            data_context=data_context,
            interaction_memory=interaction_memory,
            total_chars=total_chars
        )
    
    def start_agent_loop(self):
        """Mark start of agent loop."""
        self.record.agent_loop_start = self._elapsed()
    
    def end_agent_loop(self):
        """Mark end of agent loop."""
        self.record.agent_loop_end = self._elapsed()
        self.record.agent_loop_duration = self.record.agent_loop_end - self.record.agent_loop_start
    
    def start_iteration(self, iteration_num: int) -> IterationTiming:
        """Start a new iteration."""
        iteration = IterationTiming(iteration=iteration_num)
        self.record.iterations.append(iteration)
        self._current_iteration = iteration
        return iteration
    
    @contextmanager
    def llm_call(self, iteration: IterationTiming, model: str = ""):
        """Context manager for timing an LLM call."""
        start = self._elapsed()
        
        class LLMContext:
            def __init__(self, timing_collector, iteration, start, model):
                self.collector = timing_collector
                self.iteration = iteration
                self.start = start
                self.model = model
                self.prompt_tokens = 0
                self.completion_tokens = 0
            
            def set_tokens(self, prompt: int, completion: int):
                self.prompt_tokens = prompt
                self.completion_tokens = completion
        
        ctx = LLMContext(self, iteration, start, model)
        
        try:
            yield ctx
        finally:
            end = self._elapsed()
            duration = end - start
            iteration.llm_call = LLMTiming(
                start=start,
                end=end,
                duration=duration,
                model=ctx.model,
                prompt_tokens=ctx.prompt_tokens,
                completion_tokens=ctx.completion_tokens
            )
    
    @contextmanager
    def tool_execution(self, iteration: IterationTiming, tool_name: str):
        """Context manager for timing a tool execution."""
        start = self._elapsed()
        
        class ToolContext:
            def __init__(self, timing_collector, iteration, start, tool_name):
                self.collector = timing_collector
                self.iteration = iteration
                self.start = start
                self.tool_name = tool_name
                self.args_size = 0
                self.result_size = 0
            
            def set_sizes(self, args: int, result: int):
                self.args_size = args
                self.result_size = result
        
        ctx = ToolContext(self, iteration, start, tool_name)
        
        try:
            yield ctx
        finally:
            end = self._elapsed()
            duration = end - start
            tool_timing = ToolTiming(
                name=tool_name,
                start=start,
                end=end,
                duration=duration,
                args_size_bytes=ctx.args_size,
                result_size_bytes=ctx.result_size
            )
            iteration.tools.append(tool_timing)
    
    def finalize(self):
        """Finalize the timing record and write to file."""
        self.record.total_duration = self._elapsed()
        self.record.compute_summary()
        
        # Store in memory
        record_dict = self.record.to_dict()
        _recent_records.append(record_dict)
        
        if TIMING_MODE:
            # Write to file
            _write_timing_record(record_dict)
            
            # Console logging
            if TIMING_VERBOSE:
                print(f"[TIMING] Request {self.request_id[:8]}: {self.record.total_duration:.3f}s")
                print(f"  LLM: {self.record.summary['llm_duration']:.3f}s ({self.record.summary['llm_percentage']:.1f}%)")
                print(f"  Tools: {self.record.summary['tool_duration']:.3f}s ({self.record.summary['tool_percentage']:.1f}%)")
                print(f"  Overhead: {self.record.summary['overhead_duration']:.3f}s ({self.record.summary['overhead_percentage']:.1f}%)")


def _write_timing_record(record: Dict[str, Any]):
    """Write a timing record to the JSONL file."""
    try:
        output_path = Path(TIMING_OUTPUT_FILE)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[TIMING] Error writing timing record: {e}")


def get_recent_records(n: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get the N most recent timing records. If n is None, return all."""
    if n is None:
        return list(_recent_records)
    return list(_recent_records)[-n:]


def get_timing_stats() -> Dict[str, Any]:
    """Get summary statistics from recent timing records."""
    if not _recent_records:
        return {
            "count": 0,
            "message": "No timing data available"
        }
    
    records = list(_recent_records)
    
    total_durations = [r["timings"]["total_duration"] for r in records]
    llm_durations = [r["summary"]["llm_duration"] for r in records]
    tool_durations = [r["summary"]["tool_duration"] for r in records]
    
    def percentile(data: List[float], p: int) -> float:
        """Calculate percentile."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100)
        f = int(k)
        c = min(f + 1, len(sorted_data) - 1)
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])
    
    return {
        "count": len(records),
        "timing_mode_enabled": TIMING_MODE,
        "total_duration": {
            "avg": round(sum(total_durations) / len(total_durations), 3),
            "p50": round(percentile(total_durations, 50), 3),
            "p95": round(percentile(total_durations, 95), 3),
            "p99": round(percentile(total_durations, 99), 3),
            "min": round(min(total_durations), 3),
            "max": round(max(total_durations), 3),
        },
        "llm_duration": {
            "avg": round(sum(llm_durations) / len(llm_durations), 3),
            "p50": round(percentile(llm_durations, 50), 3),
            "p95": round(percentile(llm_durations, 95), 3),
        },
        "tool_duration": {
            "avg": round(sum(tool_durations) / len(tool_durations), 3),
            "p50": round(percentile(tool_durations, 50), 3),
            "p95": round(percentile(tool_durations, 95), 3),
        },
        "recent_requests": [
            {
                "request_id": r["request_id"][:8],
                "timestamp": r["timestamp"],
                "user_prompt": r["user_prompt"],
                "total_duration": r["summary"]["total_duration"],
                "llm_duration": r["summary"]["llm_duration"],
                "tool_duration": r["summary"]["tool_duration"],
                "num_iterations": r["summary"]["num_iterations"],
                "num_tools": r["summary"]["num_tools_called"],
            }
            for r in records[-20:]  # Last 20 requests
        ]
    }
