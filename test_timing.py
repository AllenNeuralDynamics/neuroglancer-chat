#!/usr/bin/env python3
"""Quick test of timing instrumentation."""

import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from neuroglancer_chat.backend.observability.timing import TimingCollector
import time

def test_timing():
    """Test basic timing collection."""
    print("Testing timing collector...")
    
    # Create a collector
    timing = TimingCollector(user_prompt="test query: show me the data")
    timing.mark("request_received")
    
    # Simulate prompt assembly
    with timing.phase("prompt_assembly"):
        time.sleep(0.01)
        timing.set_context_timing(0.005, 0.003, 0.002, 1500)
    
    # Simulate agent loop
    timing.start_agent_loop()
    
    # Iteration 1
    iter1 = timing.start_iteration(0)
    with timing.llm_call(iter1, model="gpt-4o") as llm:
        time.sleep(0.05)
        llm.set_tokens(prompt=2500, completion=150)
    
    with timing.tool_execution(iter1, "ng_set_view") as tool:
        time.sleep(0.01)
        tool.set_sizes(args=256, result=128)
    
    # Iteration 2
    iter2 = timing.start_iteration(1)
    with timing.llm_call(iter2, model="gpt-4o") as llm:
        time.sleep(0.03)
        llm.set_tokens(prompt=2700, completion=80)
    
    timing.end_agent_loop()
    
    # Response assembly
    with timing.phase("response_assembly"):
        time.sleep(0.005)
    
    timing.mark("response_sent")
    timing.finalize()
    
    # Check summary
    summary = timing.record.summary
    print(f"\n✓ Timing collected successfully!")
    print(f"  Request ID: {timing.request_id[:8]}")
    print(f"  Total duration: {summary['total_duration']:.3f}s")
    print(f"  LLM duration: {summary['llm_duration']:.3f}s ({summary['llm_percentage']:.1f}%)")
    print(f"  Tool duration: {summary['tool_duration']:.3f}s ({summary['tool_percentage']:.1f}%)")
    print(f"  Overhead: {summary['overhead_duration']:.3f}s ({summary['overhead_percentage']:.1f}%)")
    print(f"  Iterations: {summary['num_iterations']}")
    print(f"  Tools called: {summary['num_tools_called']}")
    print(f"  Total tokens: {summary['total_tokens']}")
    
    print("\n✓ All tests passed!")
    return True

if __name__ == "__main__":
    try:
        test_timing()
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
