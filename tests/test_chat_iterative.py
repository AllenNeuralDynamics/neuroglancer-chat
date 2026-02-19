from fastapi.testclient import TestClient
from neuroglancer_chat.backend.main import app, DATA_MEMORY, CURRENT_STATE
from neuroglancer_chat.backend.tools.neuroglancer_state import NeuroglancerState

client = TestClient(app)


def _upload_small_csv():
    content = b"id,val\n1,10\n2,20\n3,30\n"
    r = client.post("/upload_file", files={"file": ("mini.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True, j
    return j["file"]["file_id"]


def test_data_info_non_mutating_no_link(monkeypatch):
    fid = _upload_small_csv()

    # Monkeypatch run_chat to simulate a single tool call then final answer.
    from neuroglancer_chat.backend import adapters

    calls = []

    def fake_run_chat(msgs):  # first call returns tool call, second returns answer
        iteration = len([m for m in msgs if m.get("role") == "assistant"])  # crude
        if iteration == 0:
            return {
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [
                        {"id": "tc1", "type": "function", "function": {"name": "data_info", "arguments": f"{{\"file_id\": \"{fid}\"}}"}}
                    ]}}
                ]
            }
        else:
            # Second pass: no tool calls, model summarizes
            return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "File has 3 rows."}}]}

    monkeypatch.setattr(adapters.llm, "run_chat", fake_run_chat)

    resp = client.post("/agent/chat", json={"messages": [{"role": "user", "content": f"How many rows in file {fid}?"}]})
    j = resp.json()
    assert j.get("mutated") is False
    assert j.get("state_link") is None or j.get("state_link") == {}  # no link
    assert "3" in (j["choices"][0]["message"]["content"])  # uses tool result


def test_mutating_tool_returns_link(monkeypatch):
    # Reset state (optional for clarity)
    from neuroglancer_chat.backend import main as backend_main
    backend_main.CURRENT_STATE = NeuroglancerState()

    def fake_run_chat(msgs):
        iteration = len([m for m in msgs if m.get("role") == "assistant"])  # same tactic
        if iteration == 0:
            return {"choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "ng_set_view", "arguments": "{\"center\": {\"x\":1,\"y\":2,\"z\":3}, \"zoom\": \"fit\", \"orientation\": \"xy\"}"}}
            ]}}]}
        else:
            return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "View updated."}}]}

    from neuroglancer_chat.backend import adapters
    monkeypatch.setattr(adapters.llm, "run_chat", fake_run_chat)

    resp = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "Center on 1 2 3."}]})
    j = resp.json()
    assert j.get("mutated") is True
    sl = j.get("state_link")
    assert sl and "url" in sl and sl["url"].startswith("http"), sl
    assert "Updated Neuroglancer view" in sl.get("masked_markdown", "")
