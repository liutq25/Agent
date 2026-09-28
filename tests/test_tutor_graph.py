from app.tutor_graph import begin_probe, finish_probe


def test_langgraph_probe_survives_reopening_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNITUTOR_GRAPH_DB", str(tmp_path / "checkpoints.db"))
    question = {"id": "q-1", "question": "最大堆是否全局有序？", "concept_ids": ["HEAP_PROPERTY"]}
    assert begin_probe("session-1", "student-1", question)["waiting"] is True
    result = finish_probe("session-1", answer="不是", outcome="MASTERED", confidence=.92)
    assert result["mode"] == "VERIFIED"
    assert result["student_answer"] == "不是"
    assert result["answer_status"] == "MASTERED"
    assert finish_probe("session-1", answer="再次提交") is None


def test_langgraph_probe_can_be_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("COGNITUTOR_GRAPH_DB", str(tmp_path / "checkpoints.db"))
    begin_probe("session-2", "student-2", {"id": "q-2", "question": "为什么？"})
    result = finish_probe("session-2", cancelled=True)
    assert result["mode"] == "CANCELLED"
