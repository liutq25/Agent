"""Small, auditable course retriever with optional provider embeddings."""
import math
import re
from collections import Counter
from pathlib import Path
import yaml


def open_resources() -> list[dict]:
    path = Path(__file__).resolve().parent.parent / "data" / "data_structures" / "open_resources.yaml"
    rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [{**row, "kind": "open_resource"} for row in rows]


def chunks(text: str, size: int = 650, overlap: int = 100) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    result = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = max(text.rfind("。", start + size // 2, end), text.rfind("；", start + size // 2, end))
            if cut > start:
                end = cut + 1
        result.append(text[start:end])
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return result


def _terms(text: str) -> Counter:
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.lower())
    terms = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            terms.extend(word[i:i+2] for i in range(len(word)-1))
        else:
            terms.append(word)
    return Counter(terms)


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    den = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / den if den else 0.0


def retrieve(query: str, documents: list[dict], *, limit: int = 4,
             query_vector: list[float] | None = None,
             vectors: dict[str, list[float]] | None = None) -> list[dict]:
    """Return only positively matching chunks, with stable source IDs."""
    q = _terms(query)
    if not q:
        return []
    scored = []
    for doc in documents:
        for index, chunk in enumerate(chunks(doc["content"])):
            source_id = f"{doc['id']}#{index+1}"
            terms = _terms(doc["title"] + " " + chunk)
            lexical = sum(min(count, terms[term]) for term, count in q.items()) / max(1, sum(q.values()))
            semantic = _cosine(query_vector, (vectors or {}).get(source_id, [])) if query_vector is not None else 0
            score = max(lexical, semantic)
            if score > 0:
                scored.append({"source_id": source_id, "title": doc["title"],
                               "content": chunk, "score": round(score, 4), "kind": doc.get("kind", "document"),
                               "url": doc.get("url")})
    return sorted(scored, key=lambda item: (-item["score"], item["source_id"]))[:limit]


def format_context(hits: list[dict]) -> str:
    if not hits:
        return ""
    return "课程资料摘录。仅在摘录支持时引用 [资料ID]，不要编造来源：\n" + "\n".join(
        f"[{hit['source_id']}] {hit['title']}：{hit['content']}" +
        (f" 来源：{hit['url']}" if hit.get("url") else "") for hit in hits)
