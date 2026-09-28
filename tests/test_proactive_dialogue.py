import pytest
from fastapi.testclient import TestClient
from app.main import app
import asyncio
from app.diagnostic_pipeline import analyze_turn


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    import app.main as main
    import app.model_settings as settings
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "dialogue.db")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "model-settings.json")


def post(client, session_id, content):
    response = client.post(f"/api/chat/{session_id}/message", json={"content": content})
    assert response.status_code == 200, response.text
    return response.json()


def test_wrong_claim_is_addressed_and_verified_then_summarized():
    import app.main as main
    from app.tutor_graph import finish_probe
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "learner"}).json()["session_id"]
    first = post(client, sid, "我认为链表任何位置插入都 O(1)，因为只需改指针。")
    assert first["diagnosis"]["status"] == "SUSPECTED"
    assert "可能存在这个问题" in first["answer"]
    assert "定位前驱" in first["answer"]
    assert first["probe"]["id"] == "DIAG-LINK-004"
    graph_path = main.DB_PATH.with_name(main.DB_PATH.stem + "_graph.db")
    assert graph_path.exists()
    second = post(client, sid, "直接改指针就是 O(1)，不用遍历。")
    assert second["diagnosis"]["status"] == "CONFIRMED"
    assert "正确理解" in second["answer"]
    assert finish_probe(sid, answer="重复回答", path=graph_path) is None
    summary = post(client, sid, "我现在有哪些薄弱点？")
    assert summary["mode"] == "summary"
    assert "链表任意位置插入" in summary["answer"]
    assert "已由核验题支持" in summary["answer"]
    assert client.get("/api/student/learner/evidence").json()[0]["diagnosis"]["status"] == "SUMMARY"


def test_ordinary_question_is_answered_without_compulsory_quiz():
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "learner"}).json()["session_id"]
    first = post(client, sid, "为什么 BST 查找不一定是 O(log n)？")
    assert first["probe"] is None
    assert first["diagnosis"]["status"] == "OBSERVED"
    assert "O(n)" in first["answer"]
    second = post(client, sid, "我认为普通 BST 查找一定是 O(log n)。")
    assert second["probe"]["id"] == "DIAG-BST-001"
    third = post(client, sid, "它退化成链，最坏 O(n)。")
    assert third["diagnosis"]["status"] == "RESOLVED"


def test_question_then_wrong_claim_creates_specific_diagnosis():
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "learner"}).json()["session_id"]
    first = post(client, sid, "顺序表中间插入为什么慢？")
    assert first["diagnosis"]["status"] == "OBSERVED"
    assert first["probe"] is None
    second = post(client, sid, "找到下标后直接插入就行，应该是 O(1)。")
    assert second["diagnosis"]["status"] == "SUSPECTED"
    assert second["probe"]["id"] == "DIAG-ARRAY-001"
    third = post(client, sid, "找到下标就直接插入，应该是 O(1)。")
    assert third["diagnosis"]["status"] == "CONFIRMED"
    assert "将随机访问复杂度误用于中间插入" in third["answer"]
    assert "移动元素" in third["answer"]
    trace = client.get(f"/api/trace/{second['trace_id']}").json()
    assert trace["hypotheses"][0]["misconception_id"] == "DS-ARRAY-01"
    assert trace["hypotheses"][0]["status"] == "CONFIRMED"
    summary = post(client, sid, "总结我的薄弱点")
    assert "将随机访问复杂度误用于中间插入" in summary["answer"]


def test_model_misses_explicit_claim_but_pipeline_keeps_evidence():
    class IncompleteModel:
        async def structured_chat(self, messages, response_schema, **kwargs):
            if response_schema.__name__ == "ConceptMap":
                return {"concepts": [{"id": "BST_SEARCH", "relevance": .9}]}
            if response_schema.__name__ == "EvidenceResult":
                return {"evidence": [], "is_question_only": True}
            return {"hypotheses": []}
    result = asyncio.run(analyze_turn(IncompleteModel(),
        "我认为普通BST查找一定是O(log n)，因为每一步排除一半节点。"))
    assert result["evidence"][0]["quote"].startswith("我认为")
    assert result["hypotheses"][0]["misconception_id"] == "DS-BST-02"
    assert result["question"]["id"] == "DIAG-BST-001"


def test_new_question_interrupts_pending_probe():
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "learner"}).json()["session_id"]
    first = post(client, sid, "我认为普通 BST 查找一定是 O(log n)。")
    assert first["probe"]["id"] == "DIAG-BST-001"
    second = post(client, sid, "什么是栈？请详细解释。")
    assert second["mode"] == "answer"
    assert second["probe"] is None
    assert "最后入栈" in second["answer"]
    assert client.get(f"/api/trace/{first['trace_id']}").json()["status"] == "ABORTED"


def test_self_reported_weakness_is_not_treated_as_proven_error():
    class Model:
        async def structured_chat(self, messages, response_schema, **kwargs):
            if response_schema.__name__ == "EvidenceResult":
                return {"evidence": [{"quote": "我总是弄混", "type": "self_reported_gap"}],
                        "is_question_only": False}
            if response_schema.__name__ == "HypothesisResult":
                return {"hypotheses": [{"misconception_id": "DS-STACK-01",
                    "issue_type": "misconception", "candidate_name": "栈和队列概念不牢",
                    "related_concepts": ["STACK_LIFO"], "evidence_quotes": ["我总是弄混"],
                    "confidence": .65}]}
            return {}
    result = asyncio.run(analyze_turn(Model(), "我总是弄混栈和队列，能讲讲区别吗？"))
    assert result["evidence"][0]["type"] == "self_reported_gap"
    assert result["hypotheses"][0]["issue_type"] == "knowledge_gap"
    assert result["hypotheses"][0]["misconception_id"] is None


def test_false_premise_question_gets_answer_and_targeted_probe(monkeypatch):
    import app.main as main
    class Model:
        async def chat(self, messages, **kwargs):
            return "单次线性查找最多比较 n 次，是 O(n)；顺序表删除后最多移动 n-1 个元素，也是 O(n)。重复 n 次才可能达到 O(n²)。"
        async def structured_chat(self, messages, response_schema, **kwargs):
            if response_schema.__name__ == "ConceptMap":
                return {"concepts": []}
            if response_schema.__name__ == "PremiseAssessment":
                return {"has_false_premise": True, "premise_quote": "查找和删除都是O(n^2)",
                        "possible_confusion": "把单次操作与重复 n 次操作的总复杂度混为一谈",
                        "concept_ids": ["TIME_COMPLEXITY"],
                        "question": "你为什么判断是 O(n²)？在长度 n 的顺序表中，查找末尾元素和删除第一个元素分别执行多少次比较或移动？",
                        "expected_answer": "单次查找最多 n 次比较，单次删除最多 n-1 次移动，均为 O(n)。",
                        "confidence": .9}
            if response_schema.__name__ == "VerificationResult":
                return {"outcome": "GAP", "evidence_quote": "每次都要遍历 n 次，一共执行 n 次",
                        "explanation": "你分析的是 n 次重复操作，而题目问单次操作。", "confidence": .92}
            return {}
    monkeypatch.setattr(main, "get_provider", lambda: Model())
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "linear-learner"}).json()["session_id"]
    first = post(client, sid, "为什么线性表的查找和删除都是O(n^2)？")
    assert "O(n)" in first["answer"]
    assert "你为什么会这样判断" in first["answer"]
    assert "查找末尾元素" in first["answer"]
    assert first["probe"]["id"] == "GENERATED-PREMISE"
    assert first["diagnosis"]["status"] == "SUSPECTED"
    assert client.get("/api/student/linear-learner/profile").json()["diagnoses"] == []
    second = post(client, sid, "每次都要遍历 n 次，一共执行 n 次")
    assert second["diagnosis"]["status"] == "CONFIRMED"
    assert "单次操作" in second["answer"]


def test_correct_premise_question_does_not_force_probe():
    class Model:
        async def structured_chat(self, messages, response_schema, **kwargs):
            if response_schema.__name__ == "PremiseAssessment":
                return {"has_false_premise": False}
            return {}
    result = asyncio.run(analyze_turn(Model(), "为什么顺序表按下标访问是 O(1)？"))
    assert result["question"] is None
    assert result["hypotheses"] == []


def test_premise_assessment_accepts_list_confusion_and_normalized_quote():
    class Model:
        async def structured_chat(self, messages, response_schema, **kwargs):
            if response_schema.__name__ == "PremiseAssessment":
                return {"has_false_premise": True,
                        "premise_quote": "查找和删除都是 O(n²)",
                        "possible_confusion": ["单次与重复操作", "顺序表与链表"],
                        "concept_ids": ["TIME_COMPLEXITY"],
                        "question": "你为什么这样判断？长度为 4 的顺序表查找末尾元素和删除首元素分别做多少次比较与移动？",
                        "expected_answer": "最多 4 次比较、3 次移动；均为 O(n)。", "confidence": .9}
            return {}
    text = "为什么线性表的查找和删除都是O(n^2)？"
    result = asyncio.run(analyze_turn(Model(), text))
    assert result["evidence"][0]["quote"] == text
    assert result["question"]["id"] == "GENERATED-PREMISE"
    assert "顺序表与链表" in result["hypotheses"][0]["candidate_name"]


def test_heap_explanation_followup_stays_on_heap_and_does_not_probe(monkeypatch):
    import app.main as main

    class CountingModel:
        def __init__(self):
            self.chat_calls = 0
            self.structured_calls = 0

        async def chat(self, messages, **kwargs):
            self.chat_calls += 1
            return "堆排序先用 O(n) 建堆，再反复交换堆顶和末尾、缩小堆范围并下沉，整体 O(n log n)。"

        async def structured_chat(self, messages, response_schema, **kwargs):
            self.structured_calls += 1
            if response_schema.__name__ == "VerificationResult":
                return {"outcome": "GAP", "evidence_quote": "我觉得在堆建好之后数组就是排序的",
                        "explanation": "堆只保证父子偏序。", "confidence": .95}
            return {}

    model = CountingModel()
    monkeypatch.setattr(main, "get_provider", lambda: model)
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "heap-learner"}).json()["session_id"]
    first = post(client, sid, "为什么堆排序的时间复杂度是O(n^2)？")
    assert "O(n log n)" in first["answer"]
    assert first["probe"] is None
    assert model.chat_calls == 1
    assert model.structured_calls == 1  # premise check found no validated hypothesis
    second = post(client, sid, "我觉得在堆建好之后数组就是排序的，我们需要遍历数组才能把需要的数据找出来")
    assert second["diagnosis"]["status"] == "OBSERVED"
    before = model.structured_calls
    third = post(client, sid, "那真正的实现是什么样子的")
    assert third["mode"] == "answer"
    assert third["probe"] is None
    assert "建堆" in third["answer"]
    assert "链表" not in third["answer"]
    assert model.structured_calls == before
