"""Tests for TimingCollector observability infrastructure."""

import time

from neuroglancer_chat.backend.observability.timing import TimingCollector


def test_timing_collector_basic_lifecycle():
    """TimingCollector records phases, iterations, LLM calls, and tool executions."""
    timing = TimingCollector(user_prompt="test query: show me the data")
    timing.mark("request_received")

    with timing.phase("prompt_assembly"):
        time.sleep(0.001)
        timing.set_context_timing(0.005, 0.003, 0.002, 1500)

    timing.start_agent_loop()

    iter1 = timing.start_iteration(0)
    with timing.llm_call(iter1, model="gpt-4o") as llm:
        time.sleep(0.001)
        llm.set_tokens(prompt=2500, completion=150)

    with timing.tool_execution(iter1, "ng_set_view") as tool:
        time.sleep(0.001)
        tool.set_sizes(args=256, result=128)

    iter2 = timing.start_iteration(1)
    with timing.llm_call(iter2, model="gpt-4o") as llm:
        time.sleep(0.001)
        llm.set_tokens(prompt=2700, completion=80)

    timing.end_agent_loop()

    with timing.phase("response_assembly"):
        time.sleep(0.001)

    timing.mark("response_sent")
    timing.finalize()

    summary = timing.record.summary
    assert summary["num_iterations"] == 2
    assert summary["num_tools_called"] == 1
    assert summary["total_tokens"] == 2500 + 150 + 2700 + 80
    assert summary["total_duration"] > 0
    assert summary["llm_duration"] > 0
    assert summary["tool_duration"] > 0
    assert timing.request_id


def test_timing_collector_request_id_is_unique():
    """Each TimingCollector gets a unique request_id."""
    t1 = TimingCollector(user_prompt="q1")
    t2 = TimingCollector(user_prompt="q2")
    assert t1.request_id != t2.request_id


def test_timing_collector_no_iterations():
    """TimingCollector with no iterations produces zero counts."""
    timing = TimingCollector(user_prompt="empty")
    timing.start_agent_loop()
    timing.end_agent_loop()
    timing.finalize()

    summary = timing.record.summary
    assert summary["num_iterations"] == 0
    assert summary["num_tools_called"] == 0
    assert summary["total_tokens"] == 0
