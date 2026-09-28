from fastapi.testclient import TestClient

from app.main import app
from app.retrieval import chunks, retrieve, open_resources


def test_chunks_and_source_ids_are_stable():
    text = "堆排序每轮取出堆顶。" * 90
    parts = chunks(text)
    assert len(parts) > 1
    hits = retrieve("堆排序", [{"id": "teacher-1", "title": "排序讲义", "content": text}])
    assert hits[0]["source_id"] == "teacher-1#1"
    assert "堆排序" in hits[0]["content"]
    assert retrieve("红黑树", [{"id": "one", "title": "队列", "content": "先进先出"}]) == []
    resources = open_resources()
    assert len(resources) >= 5
    assert all(row["url"].startswith("https://") and row["license"] for row in resources)


def test_document_ingest_search_and_chat_context(tmp_path, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "DB_PATH", tmp_path / "course.db")
    monkeypatch.setattr(main, "get_embedding_provider", lambda: None)

    class Provider:
        async def chat(self, messages, **kwargs):
            assert "课程资料摘录" in messages[0]["content"]
            return "堆排序先建堆再反复取堆顶。"

        async def chat_with_tools(self, messages, tools, **kwargs):
            return {"tool_calls": []}

        async def structured_chat(self, messages, response_schema, **kwargs):
            return {}

    monkeypatch.setattr(main, "get_provider", lambda: Provider())
    client = TestClient(app)
    created = client.post("/api/documents", json={"title": "teacher-doc", "content": "堆排序先建堆再反复取堆顶。"})
    assert created.status_code == 200
    doc_id = created.json()["id"]
    assert created.json()["chunks"] == 1
    found = client.get("/api/course/search", params={"q": "堆排序"}).json()
    assert any(hit["source_id"] == doc_id + "#1" for hit in found)
    sid = client.post("/api/chat/session", json={"student_id": "student"}).json()["session_id"]
    # The provider above only checks that the source is included in the system context.
    provider = main.get_provider()
    async def answer(messages, **kwargs):
        assert doc_id + "#1" in messages[0]["content"]
        return "堆排序先建堆再反复取堆顶。"
    provider.chat = answer
    monkeypatch.setattr(main, "get_provider", lambda: provider)
    result = client.post(f"/api/chat/{sid}/message", json={"content": "堆排序如何工作？"})
    assert result.status_code == 200
    assert any(hit["source_id"] == doc_id + "#1" for hit in result.json()["retrieved_sources"])
