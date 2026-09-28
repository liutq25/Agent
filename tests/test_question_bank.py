from fastapi.testclient import TestClient

from app.main import app


QUESTION = {
    "id": "Q-ARRAY-EXTRA",
    "question": "在顺序表下标 2 插入新元素时，原下标 2 到末尾的元素如何处理？",
    "expected_answer": "需要依次后移，最坏 O(n)。",
    "concept_ids": ["ARRAY_ACCESS", "ARRAY_INSERTION", "TIME_COMPLEXITY"],
    "diagnostic_targets": ["DS-ARRAY-01"],
    "discriminates": {"mastered": "说明元素移动", "misconception": "只计算定位下标"},
    "follow_up_if_unclear": "原位置已有元素会去哪里？",
    "difficulty": 2,
    "task_type": "COMPLEXITY",
}


def test_only_reviewed_teacher_question_enters_live_diagnosis(tmp_path, monkeypatch):
    import app.main as main
    from app.providers import MockProvider
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "questions.db")
    monkeypatch.setattr(main, "get_provider", lambda: MockProvider())
    client = TestClient(app)
    created = client.post("/api/questions/bank", json=QUESTION)
    assert created.status_code == 200
    assert created.json()["status"] == "DRAFT"
    sid = client.post("/api/chat/session", json={"student_id": "one"}).json()["session_id"]
    before = client.post(f"/api/chat/{sid}/message",
                         json={"content": "我认为顺序表可以下标 O(1) 访问，所以插入也是 O(1)。"}).json()
    assert before["probe"]["id"] == "DIAG-ARRAY-001"
    reviewed = client.put("/api/questions/bank/Q-ARRAY-EXTRA/review",
                          json={"reviewer": "课程教师", "approved": True, "notes": "已核对步骤与诊断目标"})
    assert reviewed.status_code == 200
    sid2 = client.post("/api/chat/session", json={"student_id": "two"}).json()["session_id"]
    after = client.post(f"/api/chat/{sid2}/message",
                        json={"content": "我认为顺序表可以下标 O(1) 访问，所以插入也是 O(1)。"}).json()
    assert after["probe"]["id"] == QUESTION["id"]
    assert client.get("/api/questions/bank").json()[0]["reviewer"] == "课程教师"
    changed = {**QUESTION, "question": "在顺序表下标 3 插入新元素时，后续元素如何移动？"}
    edited = client.put("/api/questions/bank/Q-ARRAY-EXTRA",
                        json={"question": changed, "editor": "课程教师"})
    assert edited.json()["status"] == "DRAFT"
    assert edited.json()["version"] == 2
    revisions = client.get("/api/questions/bank/Q-ARRAY-EXTRA/revisions").json()
    assert len(revisions) == 2
    assert revisions[0]["question"]["question"] != revisions[1]["question"]["question"]


def test_question_bank_rejects_unknown_catalog_ids(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "questions.db")
    client = TestClient(app)
    bad = {**QUESTION, "concept_ids": ["NOT_IN_CATALOG"]}
    assert client.post("/api/questions/bank", json=bad).status_code == 400


def test_selector_uses_mastery_to_adjust_difficulty():
    from app.diagnostic_pipeline import select_question
    questions = [
        {"id": "Q-EASY", "question": "easy", "concept_ids": ["BFS_TRAVERSAL"],
         "diagnostic_targets": [], "difficulty": 1},
        {"id": "Q-HARD", "question": "hard", "concept_ids": ["BFS_TRAVERSAL"],
         "diagnostic_targets": [], "difficulty": 5},
    ]
    concept = [{"id": "BFS_TRAVERSAL", "relevance": 1}]
    low = select_question(concept, [], approved_questions=questions,
                          student_profile={"mastery": {"BFS_TRAVERSAL": 0}})
    high = select_question(concept, [], approved_questions=questions,
                           student_profile={"mastery": {"BFS_TRAVERSAL": 1}})
    assert low["id"] == "Q-EASY"
    assert high["id"] == "Q-HARD"
