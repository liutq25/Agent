import asyncio
import httpx

from app.providers import OpenAICompatibleEmbeddingProvider
from app.retrieval import retrieve


def test_embedding_adapter_orders_vectors_by_input_index(monkeypatch):
    import app.providers as providers
    original_client = httpx.AsyncClient
    seen = {}

    def reply(request):
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]}]})

    monkeypatch.setattr(providers.httpx, "AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(reply), **kwargs))
    adapter = OpenAICompatibleEmbeddingProvider("embedding-model", "https://example.org/v1", "test-key")
    vectors = asyncio.run(adapter.embed_documents(["堆", "栈"]))
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert seen["authorization"] == "Bearer test-key"
    assert '"model":"embedding-model"' in seen["body"]


def test_semantic_vector_can_retrieve_without_lexical_overlap():
    docs = [{"id": "d", "title": "优先队列", "content": "父节点满足堆序性质"}]
    hits = retrieve("priority scheduling", docs, query_vector=[1.0, 0.0],
                    vectors={"d#1": [0.9, 0.1]})
    assert hits[0]["source_id"] == "d#1"
