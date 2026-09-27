import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.diagnostic_trace import DiagnosticTraceRecorder, EventType


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    import app.main as main
    import app.model_settings as settings
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "trace.db")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "model_settings.json")


def test_conversation_trace_lifecycle_and_no_private_reasoning(monkeypatch):
    import app.main as main
    class FakeProvider:
        protocol = "openai_compatible"
        model = "test"
        capabilities = {"tool_calling": False}
        async def chat(self, messages, **kwargs): return "先区分定位节点和改指针。"
        async def structured_chat(self, messages, response_schema, **kwargs):
            name = response_schema.__name__
            if name == "ConceptMap": return {"concepts": [{"id": "LINKED_LIST_INSERTION", "relevance": .95}]}
            if name == "EvidenceResult": return {"evidence": [{"quote": "链表任何位置插入都 O(1)", "type": "reasoning_evidence"}]}
            if name == "HypothesisResult": return {"hypotheses": [{"misconception_id": "DS-LINK-02", "issue_type": "misconception", "candidate_name": "忽略定位前驱的代价", "related_concepts": ["LINKED_LIST_INSERTION"], "evidence_quotes": ["链表任何位置插入都 O(1)"], "confidence": .7}]}
            if name == "VerificationResult": return {"outcome": "GAP", "evidence_quote": "直接改指针就是 O(1)", "explanation": "还需定位前驱。", "confidence": .93}
            raise AssertionError(name)
    monkeypatch.setattr(main, "get_provider", lambda: FakeProvider())
    client = TestClient(app)
    session_id = client.post("/api/chat/session", json={"student_id": "trace-student"}).json()["session_id"]
    first = client.post(f"/api/chat/{session_id}/message", json={"content": "链表任何位置插入都 O(1)"}).json()
    trace_id = first["trace_id"]
    waiting = client.get(f"/api/trace/{trace_id}").json()
    assert waiting["status"] == "WAITING_STUDENT"
    assert waiting["hypotheses"][0]["status"] == "SUSPECTED"
    assert waiting["evidence"][0]["quote"] == "链表任何位置插入都 O(1)"
    second = client.post(f"/api/chat/{session_id}/message", json={"content": "直接改指针就是 O(1)"}).json()
    assert second["trace_id"] == trace_id
    trace = client.get(f"/api/trace/{trace_id}").json()
    assert trace["status"] == "COMPLETED"
    assert trace["outcome"] == "MISCONCEPTION_CONFIRMED"
    assert trace["hypotheses"][0]["status"] == "CONFIRMED"
    assert trace["hypotheses"][0]["confidence"] == .93
    assert len(trace["evidence"]) == 2
    assert trace["evidence"][1]["supports"] == ["DS-LINK-02"]
    event_types = [event["event_type"] for event in trace["events"]]
    assert event_types[:3] == ["STUDENT_INPUT", "CONCEPT_MAPPING", "EVIDENCE_EXTRACTED"]
    assert "PROBE_SENT" in event_types and "RE_DIAGNOSIS" in event_types
    assert event_types[-2:] == ["STUDENT_STATE_UPDATED", "TRACE_COMPLETED"]
    assert [event["sequence"] for event in trace["events"]] == list(range(1, len(trace["events"]) + 1))
    assert "system_prompt" not in str(trace).lower()
    assert client.get("/api/class/demo-class/traces").json()[0]["trace_id"] == trace_id


def test_trace_rejects_private_fields_and_records_tool_result():
    import app.main as main
    with main.db() as connection:
        recorder = DiagnosticTraceRecorder(connection)
        trace_id = recorder.create_trace("s", "session")
        with pytest.raises(ValueError):
            recorder.append_event(trace_id, EventType.ERROR, output_summary={"api_key": "secret"})
    client = TestClient(app)
    sid = client.post("/api/tutor/session", json={"student_id": "s", "question_id": "stack-trace"}).json()["session_id"]
    result = client.post(f"/api/tutor/{sid}/message", json={"answer": "1,3"}).json()
    trace = client.get(f"/api/trace/{result['trace_id']}").json()
    types = [event["event_type"] for event in trace["events"]]
    assert "TOOL_REQUESTED" in types and "TOOL_RESULT" in types and "TRACE_COMPARISON" in types
    comparison = next(event for event in trace["events"] if event["event_type"] == "TRACE_COMPARISON")
    assert comparison["output_summary"]["first_divergence"]["step"] == 1
