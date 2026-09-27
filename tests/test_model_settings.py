import asyncio
import json
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.model_settings import ModelSettings
from app.providers import create_provider


def test_settings_save_mask_and_switch(tmp_path, monkeypatch):
    import app.model_settings as settings
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "model_settings.json")
    vault = {}
    monkeypatch.setattr(settings.keyring, "get_password", lambda service, user: vault.get((service, user)))
    monkeypatch.setattr(settings.keyring, "set_password", lambda service, user, key: vault.__setitem__((service, user), key))
    monkeypatch.setattr(settings.keyring, "delete_password", lambda service, user: vault.pop((service, user)))
    client = TestClient(app)
    saved = client.put("/api/system/model-settings", json={"protocol": "openai_compatible",
        "model": "qwen-plus", "base_url": "https://example.com/v1", "api_key": "secret-123"}).json()
    assert saved["has_key"] is True and "api_key" not in saved
    assert "secret-123" not in settings.SETTINGS_PATH.read_text(encoding="utf-8")
    public = client.get("/api/system/model-settings").json()["settings"]
    assert public["has_key"] and "api_key" not in public
    assert client.get("/api/system/model-status").json()["provider"] == "openai_compatible"
    import app.main as main
    observed = []
    class WorkingProvider:
        async def chat(self, messages, **kwargs): return "OK"
    monkeypatch.setattr(main, "create_provider", lambda config, key: (observed.append(key), WorkingProvider())[1])
    tested = client.post("/api/system/model-settings/test", json={"protocol": "openai_compatible",
        "model": "qwen-plus", "base_url": "https://example.com/v1"}).json()
    assert tested["ok"] and observed == ["secret-123"]
    rejected = client.put("/api/system/model-settings", json={"protocol": "anthropic",
        "model": "claude-test", "base_url": "https://api.anthropic.com/v1"})
    assert rejected.status_code == 400  # key for another address cannot be silently reused
    assert client.put("/api/system/model-settings", json={"protocol": "openai_compatible",
        "model": "qwen-plus", "base_url": "http://example.com/v1", "api_key": "x"}).status_code == 422
    assert client.delete("/api/system/model-settings/key").json()["has_key"] is False
    assert client.get("/api/system/model-status").json()["has_key"] is False


def test_protocol_wire_formats(monkeypatch):
    captured = []
    def handler(request):
        captured.append(request)
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "openai-ok"}}]})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"content": [{"type": "text", "text": "anthropic-ok"}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "gemini-ok"}]}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    messages = [{"role": "system", "content": "be concise"}, {"role": "user", "content": "hi"}]
    async def run():
        results = []
        for protocol in ("openai_compatible", "anthropic", "gemini"):
            provider = create_provider(ModelSettings(protocol=protocol, model="test-model",
                base_url="https://example.com/v1"), "secret")
            results.append(await provider.chat(messages))
        return results
    assert asyncio.run(run()) == ["openai-ok", "anthropic-ok", "gemini-ok"]
    assert captured[0].headers["authorization"] == "Bearer secret"
    assert captured[1].headers["x-api-key"] == "secret"
    assert captured[1].headers["anthropic-version"] == "2023-06-01"
    assert json.loads(captured[1].content)["system"] == "be concise"
    assert captured[2].headers["x-goog-api-key"] == "secret"
    assert captured[2].url.path.endswith("/models/test-model:generateContent")
    assert json.loads(captured[2].content)["systemInstruction"]["parts"][0]["text"] == "be concise"


def test_deepseek_short_answers_disable_default_reasoning(monkeypatch):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "回答"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    provider = create_provider(ModelSettings(protocol="openai_compatible", model="deepseek-v4-pro",
        base_url="https://api.deepseek.com"), "secret")
    assert asyncio.run(provider.chat([{"role": "user", "content": "你好"}], max_tokens=1600)) == "回答"
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["max_tokens"] == 1600
