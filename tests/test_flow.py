import os
os.environ["MOCK_LLM"] = "true"
os.environ["COGNITUTOR_DB"] = ":memory:"
from fastapi.testclient import TestClient
from app.core import diagnose, simulate, first_divergence
from app.main import app
from app.diagnostic_pipeline import confidence_gate, select_question, verify_answer
import asyncio
import pytest


@pytest.fixture(autouse=True)
def isolate_model_settings(tmp_path, monkeypatch):
    import app.model_settings as settings
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "isolated-model-settings.json")


def test_diagnosis_and_trace():
    d = diagnose("array-insert", "中间插入是 O(1)")
    assert d["misconception_ids"] == ["M_ARRAY_INSERT_O1"]
    assert d["teaching_action"] == "PROBE"
    assert diagnose("linked-insert", "O(1)，因为节点在内存里连续")["answer_status"] == "INCORRECT"
    assert diagnose("array-insert", "移动后续元素，所以最坏 O(n)")["answer_status"] == "CORRECT"
    assert diagnose("array-insert", "我知道不是 O(1)，但不知道原因")["answer_status"] == "INSUFFICIENT_EVIDENCE"
    assert simulate("stack", [["push",1],["push",2],["pop"]])["outputs"] == [2]
    assert first_divergence([2,3], [1,3])["step"] == 1
    assert diagnose("stack-trace", "1, 3")["first_divergence"]["step"] == 1


def test_full_learning_loop(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/system/model-status").json()["mock_mode"] is True
    session = client.post("/api/tutor/session", json={"student_id":"s1", "question_id":"array-insert"}).json()["session_id"]
    first = client.post(f"/api/tutor/{session}/message", json={"answer":"插入是 O(1)"}).json()
    assert first["teaching_action"] == "PROBE"
    second = client.post(f"/api/tutor/{session}/resume", json={"answer":"需要移动后续元素，最坏 O(n)"}).json()
    assert second["answer_status"] == "CORRECT"
    evidence = client.get("/api/student/s1/evidence").json()
    assert len(evidence) == 2 and evidence[0]["diagnosis"]["answer_status"] == "CORRECT"
    assert client.get("/api/student/s1/profile").json()["mastery"]["array_insert"] > 0.5
    assert client.get("/api/class/demo-class/dashboard").json()["student_count"] == 1
    assert client.get("/api/class/demo-class/misconceptions").json()[0]["misconception_id"] == "M_ARRAY_INSERT_O1"


def test_conversation_answers_then_verifies_before_diagnosis(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "chat.db")
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "chat-student"}).json()["session_id"]
    first = client.post(f"/api/chat/{sid}/message", json={"content": "顺序表中间插入为什么不是 O(1)？"}).json()
    assert first["mode"] == "answer"
    assert "移动后续元素" in first["answer"]
    assert first["diagnosis"]["status"] == "OBSERVED"
    assert first["probe"] is None
    assert client.get("/api/student/chat-student/profile").json()["mastery"] == {}
    second = client.post(f"/api/chat/{sid}/message", json={"content": "顺序表中间插入一定是 O(1)，因为可以按下标找到位置"}).json()
    assert second["mode"] == "answer"
    assert second["diagnosis"]["status"] == "SUSPECTED"
    assert second["probe"]["id"] == "DIAG-ARRAY-001"
    third = client.post(f"/api/chat/{sid}/message", json={"content": "找到下标后直接放进去，所以是 O(1)"}).json()
    assert third["mode"] == "diagnosis"
    assert third["diagnosis"]["status"] == "CONFIRMED"
    assert "正确理解" in third["answer"]
    assert client.get("/api/student/chat-student/evidence").json()[0]["diagnosis"]["status"] == "CONFIRMED"
    assert len(client.get(f"/api/chat/{sid}/history").json()) == 6


def test_conversation_uses_provider_when_configured(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "model.db")
    calls = []
    class FakeProvider:
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            return "顺序表访问 O(1)，中间插入需要移动元素。"
        async def structured_chat(self, messages, response_schema, **kwargs):
            if response_schema.__name__ == "ConceptMap":
                return {"concepts": [{"id": "ARRAY_INSERTION", "relevance": 0.95}]}
            if response_schema.__name__ == "EvidenceResult":
                return {"evidence": [], "is_question_only": True}
            return {"hypotheses": []}
    monkeypatch.setattr(main, "get_provider", lambda: FakeProvider())
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "s2"}).json()["session_id"]
    result = client.post(f"/api/chat/{sid}/message", json={"content": "顺序表插入为什么慢？"}).json()
    assert result["model_mode"] == "api" and "需要移动元素" in result["answer"]
    assert len(calls) == 1 and calls[0][-1]["content"] == "顺序表插入为什么慢？"


def test_dynamic_hypothesis_verification_and_beta_update(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "dynamic.db")
    class FakeProvider:
        async def chat(self, messages, **kwargs):
            return "链表插入的复杂度取决于是否已找到前驱节点。"
        async def structured_chat(self, messages, response_schema, **kwargs):
            name = response_schema.__name__
            if name == "ConceptMap": return {"concepts": [{"id": "LINKED_LIST_INSERTION", "relevance": 0.95}]}
            if name == "EvidenceResult": return {"evidence": [{"quote": "链表任何位置插入都 O(1)", "type": "reasoning_evidence"}], "is_question_only": False}
            if name == "HypothesisResult": return {"hypotheses": [{"misconception_id": "DS-LINK-02", "issue_type": "misconception", "candidate_name": "忽略定位前驱的代价", "related_concepts": ["LINKED_LIST_INSERTION"], "evidence_quotes": ["链表任何位置插入都 O(1)"], "confidence": 0.72}]}
            if name == "VerificationResult": return {"outcome": "GAP", "evidence_quote": "直接改指针就是 O(1)", "explanation": "你遗漏了从头定位第 100 个节点的遍历。", "confidence": 0.93}
            raise AssertionError(name)
    monkeypatch.setattr(main, "get_provider", lambda: FakeProvider())
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "s3"}).json()["session_id"]
    first = client.post(f"/api/chat/{sid}/message", json={"content": "链表任何位置插入都 O(1)"}).json()
    assert first["diagnosis"]["status"] == "SUSPECTED"
    assert first["diagnosis"]["gate"] == "PROBE"
    assert first["probe"]["id"] == "DIAG-LINK-004"
    assert client.get("/api/student/s3/profile").json()["concept_state"] == {}
    second = client.post(f"/api/chat/{sid}/message", json={"content": "直接改指针就是 O(1)"}).json()
    assert second["diagnosis"]["status"] == "CONFIRMED"
    profile = client.get("/api/student/s3/profile").json()
    assert profile["concept_state"]["LINKED_LIST_INSERTION"]["mastery"] < 0.5
    assert profile["concept_state"]["LINKED_LIST_INSERTION"]["evidence_count"] == 1
    assert profile["diagnoses"][0]["status"] == "CONFIRMED"
    assert client.get("/api/student/s3/evidence").json()[1]["diagnosis"]["status"] == "SUSPECTED"


def test_open_set_and_quote_guard():
    assert confidence_gate([{"confidence": 0.3}]) == "COLLECT_MORE_EVIDENCE"
    assert select_question([{"id": "BST_SEARCH"}], [{"misconception_id": "DS-BST-02"}])["id"] == "DIAG-BST-001"
    class FakeProvider:
        async def structured_chat(self, messages, response_schema, **kwargs):
            return {"outcome": "GAP", "evidence_quote": "学生没说的话", "explanation": "错误", "confidence": 0.99}
    question = select_question([{"id": "BST_SEARCH"}], [{"misconception_id": "DS-BST-02"}])
    result = asyncio.run(verify_answer(FakeProvider(), question, "我还不知道"))
    assert result["outcome"] == "UNCERTAIN"


def test_open_set_issue_is_kept_outside_known_catalog(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "open.db")
    class FakeProvider:
        async def chat(self, messages, **kwargs): return "我们先核验你的推理。"
        async def structured_chat(self, messages, response_schema, **kwargs):
            name = response_schema.__name__
            if name == "ConceptMap": return {"concepts": []}
            if name == "EvidenceResult": return {"evidence": [{"quote": "我认为索引总会变快", "type": "reasoning_evidence"}]}
            if name == "HypothesisResult": return {"hypotheses": [{"misconception_id": None, "issue_type": "reasoning_gap", "candidate_name": "混淆索引构建与查询成本", "related_concepts": [], "evidence_quotes": ["我认为索引总会变快"], "confidence": 0.66}]}
            if name == "dict": return {"question": "建立索引的成本要计算吗？", "expected_answer": "需要", "mastered_pattern": "考虑构建成本", "misconception_pattern": "忽略构建成本"}
            if name == "VerificationResult": return {"outcome": "GAP", "evidence_quote": "不用计算构建成本", "explanation": "构建也有成本。", "confidence": 0.9}
            raise AssertionError(name)
    monkeypatch.setattr(main, "get_provider", lambda: FakeProvider())
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "s4"}).json()["session_id"]
    first = client.post(f"/api/chat/{sid}/message", json={"content": "我认为索引总会变快"}).json()
    assert first["probe"]["id"] == "GENERATED"
    assert first["diagnosis"]["hypotheses"][0]["misconception_id"] is None
    second = client.post(f"/api/chat/{sid}/message", json={"content": "不用计算构建成本"}).json()
    assert second["diagnosis"]["status"] == "CONFIRMED"
    issues = client.get("/api/class/demo-class/emerging-issues").json()
    assert issues[0]["issue_key"] == "OPEN:混淆索引构建与查询成本"
