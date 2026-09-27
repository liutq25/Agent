import asyncio
import json
from fastapi.testclient import TestClient

from app.main import app
from app.conversation import answer_question


def test_code_feedback_progression_and_teacher_record(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "code.db")
    results = iter([
        {"status": "TESTED", "cases": [{"name": "空数组", "args": [[], 4],
            "expected": -1, "actual": 0, "passed": False}]},
        {"status": "TESTED", "cases": [{"name": "空数组", "args": [[], 4],
            "expected": -1, "actual": 0, "passed": False}]},
        {"status": "TESTED", "cases": [{"name": "空数组", "args": [[], 4],
            "expected": -1, "actual": 0, "passed": False}]},
        {"status": "TESTED", "cases": [{"name": "空数组", "args": [[], 4],
            "expected": -1, "actual": -1, "passed": True}]},
    ])
    monkeypatch.setattr(main, "run_tests", lambda exercise_id, source: next(results))
    client = TestClient(app)
    payload = {"student_id": "student-a", "class_id": "demo-class", "exercise_id": "binary-search",
               "source": "def binary_search(nums, target):\n    return 0"}
    responses = [client.post("/api/code/submit", json=payload).json() for _ in range(4)]
    assert [r["hint_stage"] for r in responses] == [1, 2, 3, 3]
    assert "反问" in responses[0]["feedback"]
    assert "反例" in responses[1]["feedback"]
    assert "线索" in responses[2]["feedback"]
    assert "全部测试通过" in responses[3]["feedback"]
    activity = client.get("/api/class/demo-class/code-activity").json()
    assert len(activity) == 4
    assert activity[0]["source"] == payload["source"]
    assert activity[1]["result"]["cases"][0]["actual"] == 0
    assert client.get("/api/class/demo-class/dashboard").json()["student_count"] == 1
    assert client.get("/api/student/student-a/profile").json()["concept_state"]["BINARY_SEARCH"]["evidence_count"] == 4


def test_unavailable_sandbox_never_executes_or_records(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "code.db")
    monkeypatch.setattr(main, "run_tests", lambda exercise_id, source: {
        "status": "SANDBOX_UNAVAILABLE", "cases": [], "message": "代码未执行"})
    client = TestClient(app)
    result = client.post("/api/code/submit", json={"student_id": "student-a",
        "exercise_id": "binary-search", "source": "print('hello')"}).json()
    assert result["recorded"] is False
    assert "代码未执行" in result["feedback"]
    assert client.get("/api/class/demo-class/code-activity").json() == []


def test_programming_answer_guard_removes_complete_code():
    class Provider:
        async def chat(self, messages, **kwargs):
            return "先维护左右边界。\n```python\ndef binary_search(nums, target):\n    return 0\n```\n再检查空数组。"
    answer = asyncio.run(answer_question(Provider(), "请给我二分查找的完整代码", [], []))
    assert "左右边界" in answer and "空数组" in answer
    assert "def binary_search" not in answer
    assert "return 0" not in answer


def test_docker_runner_uses_isolated_container(monkeypatch):
    import app.code_lab as lab
    from types import SimpleNamespace
    commands = []
    monkeypatch.setattr(lab, "sandbox_ready", lambda: True)
    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:2] == ["docker", "run"]:
            cases = [{"name": case["name"], "args": case["args"], "expected": case["expected"],
                      "actual": -1, "passed": False} for case in lab.EXERCISES["binary-search"]["tests"]]
            return SimpleNamespace(stdout='RESULT_JSON:'+json.dumps({"status": "TESTED", "cases": cases}),
                                   stderr="", returncode=0)
        raise AssertionError(command)
    monkeypatch.setattr(lab.subprocess, "run", fake_run)
    result = lab.run_tests("binary-search", "def binary_search(nums, target): return -1")
    assert result["status"] == "TESTED"
    command = commands[0]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--memory=128m" in command
    assert "--pids-limit=32" in command
    assert "--pull=never" in command
    assert "python:3.12-alpine" in command
