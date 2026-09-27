import pytest
from fastapi.testclient import TestClient

from app.algorithm_tools import TOOLS, execute_tool, compare_student_trace
from app.main import app


CASES = [
    ("simulate_stack", {"operations": [["push", 1], ["push", 2], ["pop"]]}, {"outputs": [2]}),
    ("validate_stack_pop_sequence", {"pushes": [1, 2, 3], "pops": [2, 3, 1]}, {"valid": True}),
    ("simulate_queue", {"operations": [["enqueue", 1], ["enqueue", 2], ["dequeue"]]}, {"outputs": [1]}),
    ("simulate_circular_queue", {"capacity": 2, "operations": [["enqueue", 1], ["enqueue", 2], ["dequeue"], ["enqueue", 3]]}, {"outputs": [1]}),
    ("linked_list_insert_trace", {"values": [1, 3], "index": 1, "value": 2}, {"values": [1, 2, 3]}),
    ("linked_list_delete_trace", {"values": [1, 2, 3], "index": 1}, {"values": [1, 3], "removed": 2}),
    ("binary_search_trace", {"values": [1, 3, 5, 7], "target": 5}, {"index": 2}),
    ("bst_search", {"values": [5, 3, 7, 6], "target": 6}, {"found": True}),
    ("heapify", {"values": [1, 5, 3, 2]}, {"heap": [5, 2, 3, 1]}),
    ("bfs_trace", {"graph": {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}, "start": "A"}, {"order": ["A", "B", "C", "D"]}),
    ("dfs_trace", {"graph": {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}, "start": "A"}, {"order": ["A", "B", "D", "C"]}),
    ("insertion_sort_trace", {"values": [4, 1, 3]}, {"values": [1, 3, 4]}),
    ("bubble_sort_trace", {"values": [4, 1, 3]}, {"values": [1, 3, 4]}),
    ("binary_tree_traversal", {"tree": {"value": 2, "left": {"value": 1}, "right": {"value": 3}}, "order": "inorder"}, {"order": [1, 2, 3]}),
    ("reconstruct_binary_tree", {"preorder": [2, 1, 3], "inorder": [1, 2, 3]}, {"tree": {"value": 2, "left": {"value": 1, "left": None, "right": None}, "right": {"value": 3, "left": None, "right": None}}}),
    ("bst_insert", {"values": [2, 1, 3]}, {"tree": {"value": 2, "left": {"value": 1}, "right": {"value": 3}}}),
    ("heap_insert", {"values": [5, 2, 3], "value": 7}, {"heap": [7, 5, 3, 2]}),
    ("topological_sort_trace", {"graph": {"A": ["C"], "B": ["C"], "C": []}}, {"order": ["A", "B", "C"], "acyclic": True}),
    ("hash_insert_trace", {"values": [1, 4], "capacity": 3}, {"slots": [None, 1, 4]}),
    ("quick_sort_trace", {"values": [4, 1, 3]}, {"values": [1, 3, 4]}),
    ("merge_sort_trace", {"values": [4, 1, 3]}, {"values": [1, 3, 4]}),
    ("heap_sort_trace", {"values": [4, 1, 3]}, {"values": [1, 3, 4]}),
]


@pytest.mark.parametrize("name,params,expected", CASES)
def test_deterministic_tool(name, params, expected):
    result = execute_tool(name, params)
    assert len(TOOLS) == 22
    assert all(result["final_result"][key] == value for key, value in expected.items())
    assert result["metadata"]["deterministic"] is True
    assert result == execute_tool(name, params)


def test_new_tool_invalid_inputs_and_cycle():
    with pytest.raises(ValueError):
        execute_tool("heap_insert", {"values": [1, 5], "value": 3})
    with pytest.raises(ValueError):
        execute_tool("reconstruct_binary_tree", {"preorder": [1, 2], "inorder": [1, 3]})
    cycle = execute_tool("topological_sort_trace", {"graph": {"A": ["B"], "B": ["A"]}})
    assert cycle["final_result"]["acyclic"] is False


def test_first_divergence_reports_exact_state():
    reference = execute_tool("bubble_sort_trace", {"values": [3, 1, 2]})["steps"]
    actual = [reference[0]["state"], [1, 3, 2]]
    result = compare_student_trace(actual, reference)
    assert result["matched_steps"] == 1
    assert result["first_divergence_index"] == 1
    assert result["expected_state"] == reference[1]["state"]


def test_algorithm_api_records_comparison(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "trace.db")
    client = TestClient(app)
    response = client.post("/api/algorithm/trace", json={"student_id": "learner",
        "tool_name": "bubble_sort_trace", "params": {"values": [3, 1, 2]},
        "student_trace": [[1, 3, 2], [1, 3, 2]]})
    assert response.status_code == 200
    assert response.json()["comparison"]["first_divergence_index"] == 1
    rows = client.get("/api/class/demo-class/algorithm-runs").json()
    assert rows[0]["comparison"]["first_divergence_index"] == 1
    assert client.post("/api/algorithm/trace", json={"student_id": "learner",
        "tool_name": "binary_search_trace", "params": {"values": [3, 1], "target": 3}}).status_code == 400


def test_chat_calls_real_algorithm_tool_and_records_event(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "tool-chat.db")
    class Provider:
        async def chat_with_tools(self, messages, tools, **kwargs):
            assert any(tool["function"]["name"] == "bubble_sort_trace" for tool in tools)
            return {"tool_calls": [{"function": {"name": "bubble_sort_trace",
                "arguments": '{"params":{"values":[3,1,2]}}'}}]}
        async def chat(self, messages, **kwargs):
            assert "确定性算法工具结果" in messages[0]["content"]
            return "从 [3,1,2] 开始，先交换 3 和 1，再交换 3 和 2，得到 [1,2,3]。"
        async def structured_chat(self, messages, response_schema, **kwargs):
            return {}
    monkeypatch.setattr(main, "get_provider", lambda: Provider())
    client = TestClient(app)
    sid = client.post("/api/chat/session", json={"student_id": "learner"}).json()["session_id"]
    result = client.post(f"/api/chat/{sid}/message", json={"content": "请模拟冒泡排序 [3,1,2] 的每一步"}).json()
    assert result["tool_result"]["final_result"]["values"] == [1, 2, 3]
    trace = client.get(f"/api/trace/{result['trace_id']}").json()
    assert "TOOL_REQUESTED" in [event["event_type"] for event in trace["events"]]
    assert "TOOL_RESULT" in [event["event_type"] for event in trace["events"]]
