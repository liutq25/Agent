"""Text chat adapters for three model API protocols."""
import asyncio
import json
import os
from typing import Protocol
from urllib.parse import quote, urlsplit
import httpx
from .config import load_local_env
from .model_settings import ModelSettings, DEFAULT_URLS, get_key, load_settings


class ChatModelProvider(Protocol):
    async def chat(self, messages, *, temperature=None, max_tokens=None, stream=False): ...
    async def structured_chat(self, messages, response_schema, *, temperature=0): ...
    async def chat_with_tools(self, messages, tools, *, tool_choice="auto"): ...


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


class OpenAICompatibleEmbeddingProvider:
    """Standalone embedding adapter; configuration is independent of chat."""
    def __init__(self, model: str, url: str, key: str, timeout: int = 30):
        self.model, self.url, self.key, self.timeout = model, url.rstrip("/"), key, timeout

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.key:
            raise RuntimeError("Embedding API Key is missing")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url + "/embeddings",
                json={"model": self.model, "input": texts},
                headers={"Authorization": f"Bearer {self.key}"})
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            if len(rows) != len(texts):
                raise ValueError("Embedding response count mismatch")
            return [row["embedding"] for row in rows]

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def get_embedding_provider():
    """Return None when no embedding service is configured; lexical retrieval remains available."""
    load_local_env()
    if os.getenv("EMBEDDING_PROVIDER", "openai_compatible") != "openai_compatible":
        return None
    model, url, key = (os.getenv("EMBEDDING_MODEL", ""),
                       os.getenv("EMBEDDING_BASE_URL", ""), os.getenv("EMBEDDING_API_KEY", ""))
    if model and url and key:
        return OpenAICompatibleEmbeddingProvider(model, url, key)
    return None


class StructuredChatMixin:
    async def structured_chat(self, messages, response_schema, *, temperature=0):
        instruction = {"role": "system", "content": "只输出一个有效的 JSON 对象，不要 Markdown 代码围栏。"}
        for attempt in range(2):
            raw = await self.chat([instruction, *messages], temperature=temperature, max_tokens=900)
            try:
                clean = raw.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                data = json.loads(clean)
                return response_schema.model_validate(data).model_dump() if hasattr(response_schema, "model_validate") else data
            except (ValueError, TypeError, AttributeError):
                if attempt == 0:
                    instruction = {"role": "system", "content": "上次输出无法解析。请只返回符合字段要求的 JSON 对象。"}
        return {}


class MockProvider(StructuredChatMixin):
    capabilities = dict(tool_calling=False, structured_output=False, streaming=False, vision=False, reasoning=False)
    protocol = "mock"
    model = "knowledge-card-demo"

    async def chat(self, messages, *, temperature=None, max_tokens=None, stream=False):
        return "当前是演示模式。请配置模型 API 以进行开放式回答和诊断。"

    async def structured_chat(self, messages, response_schema, *, temperature=0):
        return {}

    async def chat_with_tools(self, messages, tools, *, tool_choice="auto"):
        return {"content": await self.chat(messages), "tool_calls": []}


class HTTPProvider(StructuredChatMixin):
    capabilities = dict(tool_calling=False, structured_output=True, streaming=False, vision=False, reasoning=False)

    def __init__(self, model: str, url: str, key: str, timeout: int = 60):
        self.model, self.url, self.key, self.timeout = model, url.rstrip("/"), key, timeout

    async def _post(self, path: str, payload: dict, headers: dict):
        if not self.key:
            raise RuntimeError("API Key is missing")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(4):
                try:
                    response = await client.post(f"{self.url}{path}", json=payload, headers=headers)
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    response.raise_for_status()
                    return response.json()
                except (httpx.TimeoutException, httpx.ConnectError):
                    if attempt == 3:
                        raise
                    await asyncio.sleep(min(2 ** attempt, 8))


class OpenAICompatibleProvider(HTTPProvider):
    protocol = "openai_compatible"
    capabilities = dict(tool_calling=True, structured_output=True, streaming=False, vision=False, reasoning=False)

    async def _request(self, messages, **kwargs):
        # DeepSeek V4 enables high-effort reasoning by default. With a short
        # output cap it can spend every token on reasoning_content and return
        # no user-visible answer. For this tutoring chat, use direct output.
        if urlsplit(self.url).hostname == "api.deepseek.com":
            kwargs.setdefault("thinking", {"type": "disabled"})
        return (await self._post("/chat/completions", {"model": self.model, "messages": messages, **kwargs},
            {"Authorization": f"Bearer {self.key}"}))["choices"][0]["message"]

    async def chat(self, messages, *, temperature=None, max_tokens=None, stream=False):
        args = {}
        if temperature is not None:
            args["temperature"] = temperature
        if max_tokens is not None:
            args["max_tokens"] = max_tokens
        return (await self._request(messages, **args))["content"]

    async def chat_with_tools(self, messages, tools, *, tool_choice="auto"):
        return await self._request(messages, tools=tools, tool_choice=tool_choice)


class AnthropicProvider(HTTPProvider):
    protocol = "anthropic"

    async def chat(self, messages, *, temperature=None, max_tokens=None, stream=False):
        system = "\n".join(str(m["content"]) for m in messages if m["role"] == "system")
        turns = [{"role": m["role"], "content": str(m["content"])} for m in messages if m["role"] in ("user", "assistant")]
        if not turns:
            turns = [{"role": "user", "content": "你好"}]
        payload = {"model": self.model, "max_tokens": max_tokens or 1024, "messages": turns}
        if system:
            payload["system"] = system
        response = await self._post("/messages", payload, {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        return "".join(block.get("text", "") for block in response.get("content", []) if block.get("type") == "text")

    async def chat_with_tools(self, messages, tools, *, tool_choice="auto"):
        raise NotImplementedError("Tool calling is not used by this adapter")


class GeminiProvider(HTTPProvider):
    protocol = "gemini"

    async def chat(self, messages, *, temperature=None, max_tokens=None, stream=False):
        system = "\n".join(str(m["content"]) for m in messages if m["role"] == "system")
        turns = [{"role": "model" if m["role"] == "assistant" else "user",
                  "parts": [{"text": str(m["content"])}]} for m in messages if m["role"] in ("user", "assistant")]
        if not turns:
            turns = [{"role": "user", "parts": [{"text": "你好"}]}]
        payload = {"contents": turns}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if max_tokens is not None:
            payload["generationConfig"] = {"maxOutputTokens": max_tokens}
        model = self.model.removeprefix("models/")
        response = await self._post(f"/models/{quote(model, safe='-._')}:generateContent", payload,
            {"x-goog-api-key": self.key})
        candidates = response.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidate")
        return "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []) if "text" in part)

    async def chat_with_tools(self, messages, tools, *, tool_choice="auto"):
        raise NotImplementedError("Tool calling is not used by this adapter")


def create_provider(settings: ModelSettings, key: str):
    if settings.protocol == "mock":
        return MockProvider()
    url = settings.base_url or DEFAULT_URLS[settings.protocol]
    cls = {"openai_compatible": OpenAICompatibleProvider,
           "anthropic": AnthropicProvider, "gemini": GeminiProvider}[settings.protocol]
    return cls(settings.model, url, key, settings.timeout)


def get_provider():
    load_local_env()
    saved = load_settings()
    if saved:
        return create_provider(saved, get_key(saved))
    if os.getenv("MOCK_LLM", "true").lower() == "true":
        return MockProvider()
    legacy = ModelSettings(protocol="openai_compatible", model=os.getenv("LLM_MODEL", "qwen-plus"),
        base_url=os.getenv("LLM_BASE_URL", DEFAULT_URLS["openai_compatible"]),
        timeout=int(os.getenv("LLM_TIMEOUT", "60")))
    return create_provider(legacy, os.getenv("LLM_API_KEY", ""))
