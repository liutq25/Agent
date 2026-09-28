"""Evidence based, open-set cognitive diagnosis for conversational turns.

The curated catalogs define stable teaching concepts, not every possible student error.
Model outputs remain hypotheses until a separate verification turn supplies evidence.
"""
from __future__ import annotations
from pathlib import Path
import re
from pydantic import BaseModel, Field
import yaml
from .providers import MockProvider

CATALOG = Path(__file__).resolve().parent.parent / "data" / "data_structures"


def load_catalog(name: str) -> list[dict]:
    data = yaml.safe_load((CATALOG / name).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Invalid catalog: {name}")
    return data


CONCEPTS = load_catalog("concepts.yaml")
MISCONCEPTIONS = load_catalog("misconceptions.yaml")
QUESTIONS = load_catalog("diagnostic_questions.yaml")
CONCEPT_BY_ID = {item["id"]: item for item in CONCEPTS}
MISCONCEPTION_BY_ID = {item["id"]: item for item in MISCONCEPTIONS}
QUESTION_BY_ID = {item["id"]: item for item in QUESTIONS}


class ConceptCandidate(BaseModel):
    id: str
    relevance: float = Field(ge=0, le=1)


class ConceptMap(BaseModel):
    concepts: list[ConceptCandidate] = []


class EvidenceSpan(BaseModel):
    quote: str
    type: str = "reasoning_evidence"


class EvidenceResult(BaseModel):
    evidence: list[EvidenceSpan] = []
    is_question_only: bool = False


class Hypothesis(BaseModel):
    misconception_id: str | None = None
    issue_type: str = "knowledge_gap"
    candidate_name: str = ""
    related_concepts: list[str] = []
    evidence_quotes: list[str] = []
    confidence: float = Field(default=0, ge=0, le=1)


class HypothesisResult(BaseModel):
    hypotheses: list[Hypothesis] = []


class TurnAssessment(BaseModel):
    evidence: list[EvidenceSpan] = []
    hypotheses: list[Hypothesis] = []
    is_question_only: bool = False


class VerificationResult(BaseModel):
    outcome: str = "UNCERTAIN"
    evidence_quote: str = ""
    explanation: str = ""
    confidence: float = Field(default=0, ge=0, le=1)


class PremiseAssessment(BaseModel):
    has_false_premise: bool = False
    premise_quote: str = ""
    possible_confusion: str | list[str] = ""
    concept_ids: list[str] = []
    question: str = ""
    expected_answer: str = ""
    confidence: float = Field(default=0, ge=0, le=1)


def _ngrams(text: str, size=2) -> set[str]:
    text = "".join(text.lower().split())
    return {text[i:i + size] for i in range(max(0, len(text) - size + 1))}


def shortlist_concepts(text: str, limit: int = 15) -> list[dict]:
    tokens = _ngrams(text)
    ranked = sorted(CONCEPTS, key=lambda item: (
        len(tokens & _ngrams(item["name"] + item["summary"])),
        len(tokens & _ngrams(item["name"]))), reverse=True)
    return ranked[:limit]


def mock_concept_map(text: str) -> list[dict]:
    aliases = {
        "堆": "HEAP_PROPERTY", "顺序表": "ARRAY_INSERTION", "数组": "ARRAY_INSERTION", "链表": "LINKED_LIST_INSERTION",
        "栈": "STACK_LIFO", "队列": "QUEUE_FIFO", "二叉搜索树": "BST_SEARCH",
        "BST": "BST_SEARCH",
    }
    for phrase, concept_id in aliases.items():
        if phrase.lower() in text.lower():
            return [{"id": concept_id, "relevance": .9}]
    tokens = _ngrams(text)
    matches = []
    for item in CONCEPTS:
        names = _ngrams(item["name"] + item["summary"])
        overlap = len(tokens & names)
        if overlap >= 1:
            matches.append({"id": item["id"], "relevance": round(min(0.95, overlap / max(2, len(tokens)) + 0.35), 2)})
    return sorted(matches, key=lambda x: x["relevance"], reverse=True)[:3]


def _validated_quotes(text: str, spans: list[dict]) -> list[dict]:
    return [span for span in spans if span.get("quote") and span["quote"] in text]


def explicit_claim(text: str) -> bool:
    return bool(re.search(r"我(认为|觉得)|一定|总是|肯定|应该|因为|所以|就是", text)) and not bool(
        re.match(r"^\s*(为什么|怎么|如何|什么|请问|能否|是否)", text))


def self_reported_gap(text: str) -> bool:
    return bool(re.search(r"(我|自己).{0,8}(不会|不懂|不理解|没弄懂|弄不清|搞不清|总是弄混|总弄混|不确定|记不住)", text))


def known_hypothesis_fallback(text: str, concepts: list[dict]) -> list[dict]:
    concept_ids = {item["id"] for item in concepts}
    candidate = None
    if "ARRAY_INSERTION" in concept_ids and re.search(r"插入.{0,12}O\s*\(?1\)?", text, re.I) and not re.search(r"不.{0,4}O\s*\(?1\)?", text, re.I):
        candidate = "DS-ARRAY-01"
    elif "LINKED_LIST_INSERTION" in concept_ids and re.search(r"(任意|任何|总是|一定).{0,12}(插入|O\s*\(?1\)?)", text, re.I):
        candidate = "DS-LINK-02"
    elif "BST_SEARCH" in concept_ids and re.search(r"(一定|总是|永远|肯定).{0,15}(log|对数)", text, re.I):
        candidate = "DS-BST-02"
    elif "HEAP_PROPERTY" in concept_ids and re.search(r"(?:堆.{0,6}(?:建好|建完|建成)|(?:建好|建完|建立|建成).{0,6}堆).{0,16}(?:已经|就是|完全).{0,6}(?:排好序|有序|排序)", text):
        candidate = next((item["id"] for item in MISCONCEPTIONS
                          if "HEAP_PROPERTY" in item["concept_ids"] and "堆" in item["name"] and "有序" in item["name"]), None)
    if candidate:
        item = MISCONCEPTION_BY_ID[candidate]
        return [{"misconception_id": candidate, "issue_type": "misconception",
                 "candidate_name": item["name"], "related_concepts": item["concept_ids"],
                 "evidence_quotes": [text], "confidence": .65}]
    return []


async def assess_explicit_turn(provider, text: str, concepts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Assess a student's statement in one bounded model call."""
    evidence_type = "self_reported_gap" if self_reported_gap(text) else "reasoning_evidence"
    candidates = [item for item in MISCONCEPTIONS
                  if {entry["id"] for entry in concepts}.intersection(item["concept_ids"])]
    compact = [{"id": item["id"], "name": item["name"]} for item in candidates[:8]]
    prompt = ("判断学生当前原话中的明确主张或自述薄弱点，最多提出两个待核验假设。"
              "提问、引用别人的错误说法、假设情境不能当成学生已犯错的证据。"
              "每条 evidence.quote 必须是原话连续片段；hypotheses.evidence_quotes 必须引用 evidence.quote。"
              "自述不会只能是 knowledge_gap，不能推断具体误区；无法确定就返回空 hypotheses。"
              "可使用目录 ID，也可提出开放假设；不要硬套目录。"
              "输出 JSON: evidence:[{quote,type}], hypotheses:[{misconception_id,issue_type,candidate_name,"
              "related_concepts,evidence_quotes,confidence}],is_question_only。"
              f"\n相关概念：{[item['id'] for item in concepts]}\n可选误区：{compact}\n学生原话：{text}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], TurnAssessment)
    evidence = _validated_quotes(text, raw.get("evidence", []))
    if not evidence:
        evidence = [{"quote": text, "type": evidence_type}]
    only_self_report = evidence_type == "self_reported_gap"
    if only_self_report:
        evidence = [{**entry, "type": "self_reported_gap"} for entry in evidence]
    valid_quotes = {entry["quote"] for entry in evidence}
    known_ids = {entry["id"] for entry in concepts}
    hypotheses = []
    for item in raw.get("hypotheses", [])[:2]:
        quotes = [quote for quote in item.get("evidence_quotes", []) if quote in valid_quotes]
        if not quotes:
            continue
        mid = item.get("misconception_id")
        if only_self_report or mid not in MISCONCEPTION_BY_ID or not known_ids.intersection(MISCONCEPTION_BY_ID[mid]["concept_ids"]):
            mid = None
        confidence = min(1.0, max(0.0, float(item.get("confidence") or 0)))
        hypotheses.append({"misconception_id": mid,
                           "issue_type": "knowledge_gap" if only_self_report else item.get("issue_type", "knowledge_gap"),
                           "candidate_name": str(item.get("candidate_name") or ""),
                           "related_concepts": [cid for cid in item.get("related_concepts", []) if cid in CONCEPT_BY_ID],
                           "evidence_quotes": quotes, "confidence": confidence})
    if not hypotheses and not only_self_report:
        hypotheses = known_hypothesis_fallback(text, concepts)
    if not hypotheses and only_self_report:
        hypotheses = [{"misconception_id": None, "issue_type": "knowledge_gap",
                       "candidate_name": "学生自述该知识点理解不稳",
                       "related_concepts": [entry["id"] for entry in concepts],
                       "evidence_quotes": [evidence[0]["quote"]], "confidence": .55}]
    return evidence, hypotheses


async def map_concepts(provider, text: str, context: str = "") -> list[dict]:
    direct = mock_concept_map(text)
    if direct and direct[0]["relevance"] >= .9:
        return direct
    contextual = mock_concept_map(context)
    if contextual and contextual[0]["relevance"] >= .9:
        return contextual
    if isinstance(provider, MockProvider):
        return direct or contextual
    prompt = ("将学生原话映射到给定概念目录，最多返回 3 个高相关概念。"
              "不要判断对错，只输出 JSON 对象，字段 concepts: [{id,relevance}]。"
              f"\n相关概念候选：{[{k: item[k] for k in ('id','name','summary')} for item in shortlist_concepts(text + context[-300:])]}"
              f"\n最近对话背景（只用于消歧）：{context[-1500:]}\n学生当前原话：{text}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], ConceptMap)
    return [entry for entry in raw.get("concepts", []) if entry.get("id") in CONCEPT_BY_ID][:3]


async def extract_evidence(provider, text: str) -> dict:
    if not explicit_claim(text) and not self_reported_gap(text) and ("?" in text or "？" in text or re.match(r"^\s*(为什么|怎么|如何|什么|请问|能否|是否)", text)):
        return {"evidence": [], "is_question_only": True}
    if isinstance(provider, MockProvider):
        # Offline demo recognizes only explicit claims; it does not grade arbitrary language.
        statement = explicit_claim(text)
        return {"evidence": [{"quote": text, "type": "reasoning_evidence" if statement else "self_reported_gap"}]
                if statement or self_reported_gap(text) else [],
                "is_question_only": not (statement or self_reported_gap(text))}
    prompt = ("只从学生原话提取明确表达的主张、推理或操作步骤。"
              "单纯提问不是错误证据。学生主动说某点不会或总弄混，可标为 self_reported_gap，不能标成已犯错误。"
              "quote 必须是原文连续片段。"
              "输出 JSON: evidence:[{quote,type}], is_question_only:bool。"
              f"\n学生原话：{text}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], EvidenceResult)
    question_only = bool(raw.get("is_question_only", False))
    spans = [] if question_only else _validated_quotes(text, raw.get("evidence", []))
    if not spans and (explicit_claim(text) or self_reported_gap(text)):
        spans = [{"quote": text, "type": "reasoning_evidence" if explicit_claim(text) else "self_reported_gap"}]
        question_only = False
    return {"evidence": spans, "is_question_only": question_only}


async def generate_hypotheses(provider, text: str, concepts: list[dict], evidence: list[dict]) -> list[dict]:
    if not evidence:
        return []
    if isinstance(provider, MockProvider):
        return known_hypothesis_fallback(text, concepts)
    relevant_ids = {item["id"] for item in concepts}
    known = [item for item in MISCONCEPTIONS if relevant_ids.intersection(item["concept_ids"])]
    prompt = ("根据学生真实证据形成最多两个可推翻的认知假设。学生自述不懂只能支持 knowledge_gap，不能据此推断已犯某种具体错误。"
              "可匹配误区目录，也可产生 open-set 新问题，"
              "但绝不能把未列出的错误硬塞进目录。区分 knowledge_gap、misconception、procedural_error、reasoning_gap。"
              "所有 evidence_quotes 必须逐字来自所给证据；不确定则返回空 hypotheses。"
              "输出 JSON: hypotheses:[{misconception_id 或 null,issue_type,candidate_name,related_concepts,evidence_quotes,confidence}]。"
              f"\n相关概念：{concepts}\n目录候选：{known}\n证据：{evidence}\n学生原话：{text}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], HypothesisResult)
    valid_quotes = {item["quote"] for item in evidence}
    only_self_report = all(item.get("type") == "self_reported_gap" for item in evidence)
    result = []
    for item in raw.get("hypotheses", [])[:2]:
        quote_list = [quote for quote in item.get("evidence_quotes", []) if quote in valid_quotes]
        if not quote_list:
            continue
        mid = item.get("misconception_id")
        if only_self_report:
            mid = None
        if mid not in MISCONCEPTION_BY_ID or (mid and relevant_ids and not relevant_ids.intersection(MISCONCEPTION_BY_ID[mid]["concept_ids"])):
            mid = None
        related = [cid for cid in item.get("related_concepts", []) if cid in CONCEPT_BY_ID]
        result.append({"misconception_id": mid, "issue_type": "knowledge_gap" if only_self_report else item.get("issue_type", "knowledge_gap"),
                       "candidate_name": item.get("candidate_name", ""), "related_concepts": related,
                       "evidence_quotes": quote_list,
                       "confidence": min(1.0, max(0.0, float(item.get("confidence") or 0)))})
    return result or ([] if only_self_report else known_hypothesis_fallback(text, concepts))


def confidence_gate(hypotheses: list[dict]) -> str:
    if not hypotheses:
        return "COLLECT_MORE_EVIDENCE"
    peak = max(item["confidence"] for item in hypotheses)
    if peak < 0.5:
        return "COLLECT_MORE_EVIDENCE"
    return "VERIFY" if peak >= 0.8 else "PROBE"


def select_question(concepts: list[dict], hypotheses: list[dict], used_ids: set[str] | None = None,
                    approved_questions: list[dict] | None = None,
                    student_profile: dict | None = None) -> dict | None:
    used_ids = used_ids or set()
    mids = {item["misconception_id"] for item in hypotheses if item.get("misconception_id")}
    cids = {item["id"] for item in concepts}
    cids.update(cid for item in hypotheses for cid in item.get("related_concepts", []))
    ranked = []
    mastery = (student_profile or {}).get("mastery", {})
    risks = (student_profile or {}).get("misconception_risk", {})
    assistance = (student_profile or {}).get("support_dependency", {}).get("recent_mean_hint_level")
    for question in [*QUESTIONS, *(approved_questions or [])]:
        if question["id"] in used_ids:
            continue
        targets = set(question.get("diagnostic_targets", []))
        concepts_for_question = set(question.get("concept_ids", []))
        score = 3 * len(mids.intersection(targets)) + len(cids.intersection(concepts_for_question))
        if score:
            score += sum((1 - mastery.get(cid, .5)) * .2 for cid in concepts_for_question)
            score += sum(risks.get(mid, 0) * .2 for mid in targets)
            known = [mastery[cid] for cid in concepts_for_question if cid in mastery]
            target_difficulty = 1 + round((sum(known) / len(known) if known else .5) * 4)
            if assistance is not None and assistance >= 1:
                target_difficulty = max(1, target_difficulty - 1)
            score += .05 * (5 - abs(question.get("difficulty", 2) - target_difficulty))
        if score:
            ranked.append((score, question["id"], question))
    return max(ranked, default=(0, "", None))[2]


async def generate_open_question(provider, text: str, concepts: list[dict], hypotheses: list[dict]) -> dict | None:
    if isinstance(provider, MockProvider):
        return None
    prompt = ("设计一个短小、可核验的数据结构诊断题，区分学生可能的两个理解状态。"
              "只输出 JSON: question, expected_answer, mastered_pattern, misconception_pattern。"
              f"\n学生问题：{text}\n概念：{concepts}\n假设：{hypotheses}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], dict)
    if not raw.get("question") or not raw.get("expected_answer"):
        return None
    return {"id": "GENERATED", "question": str(raw["question"]),
            "expected_answer": str(raw["expected_answer"]), "concept_ids": [item["id"] for item in concepts],
            "diagnostic_targets": [], "discriminates": {"mastered": raw.get("mastered_pattern", ""),
            "misconception": raw.get("misconception_pattern", "")},
            "follow_up_if_unclear": "请写出关键一步的理由。"}


async def assess_question_premise(provider, text: str, concepts: list[dict]) -> dict | None:
    """A question can contain a false premise without proving student mastery."""
    if isinstance(provider, MockProvider) or not re.search(r"为什么.{2,}(?:是|都|一定|总是|必须)", text):
        return None
    prompt = ("检查数据结构问题中是否包含可以明确判错的前提。提问本身不是学生已掌握或已犯错的证据。"
              "若前提有争议、条件不明、或者问题本身正确，has_false_premise=false。"
              "若确有错误，premise_quote 必须逐字引用问题中的连续片段；possible_confusion 写最可能混淆的两个概念，"
              "只作为待核验线索。设计一道有确定输入或确定前提的简短题目，要求学生先说明原判断依据，"
              "再分别数出单次操作与重复操作的比较、移动或指针修改次数；不要让学生自行设计场景。"
              "expected_answer 给出简要核验标准。"
              "只输出 JSON: has_false_premise,premise_quote,possible_confusion,concept_ids,question,expected_answer,confidence。"
              f"\n概念目录：{[item['id'] for item in CONCEPTS]}\n已关联概念：{concepts}\n学生问题：{text}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], PremiseAssessment)
    quote = str(raw.get("premise_quote") or "")
    confidence = min(1.0, max(0.0, float(raw.get("confidence") or 0)))
    if not raw.get("has_false_premise") or confidence < .7:
        return None
    # The model often normalizes whitespace or O(n²) spelling inside a quote.
    # Preserve provenance by using the complete original question in that case.
    if not quote or quote not in text:
        quote = text
    question = str(raw.get("question") or "").strip()
    expected = str(raw.get("expected_answer") or "").strip()
    confusion_value = raw.get("possible_confusion") or ""
    confusion = "；".join(str(item) for item in confusion_value) if isinstance(confusion_value, list) else str(confusion_value)
    confusion = confusion.strip()
    if not question or not expected or not confusion:
        return None
    concept_ids = [cid for cid in raw.get("concept_ids", []) if cid in CONCEPT_BY_ID]
    if not concept_ids:
        concept_ids = [item["id"] for item in concepts]
    return {"evidence": {"quote": quote, "type": "premise_to_check"},
            "hypothesis": {"misconception_id": None, "issue_type": "knowledge_gap",
                           "candidate_name": confusion, "related_concepts": concept_ids,
                           "evidence_quotes": [quote], "confidence": min(confidence, .7)},
            "question": {"id": "GENERATED-PREMISE", "question": question,
                         "expected_answer": expected, "concept_ids": concept_ids,
                         "diagnostic_targets": [], "discriminates": {},
                         "follow_up_if_unclear": "请先说明你原来的判断依据，再分析一次操作的步骤。"}}


async def analyze_turn(provider, text: str, used_questions: set[str] | None = None,
                       context: str = "", approved_questions: list[dict] | None = None,
                       student_profile: dict | None = None) -> dict:
    concepts = await map_concepts(provider, text, context)
    if not isinstance(provider, MockProvider) and (explicit_claim(text) or self_reported_gap(text)):
        evidence, hypotheses = await assess_explicit_turn(provider, text, concepts)
        extracted = {"evidence": evidence, "is_question_only": False}
    else:
        extracted = await extract_evidence(provider, text)
        hypotheses = await generate_hypotheses(provider, text, concepts, extracted["evidence"])
    premise = None
    if extracted["is_question_only"] and not hypotheses:
        premise = await assess_question_premise(provider, text, concepts)
        if premise:
            extracted["evidence"] = [premise["evidence"]]
            hypotheses = [premise["hypothesis"]]
            for cid in premise["hypothesis"]["related_concepts"]:
                if cid not in {item["id"] for item in concepts}:
                    concepts.append({"id": cid, "relevance": .7})
    gate = confidence_gate(hypotheses)
    # Do not turn an ordinary question into a compulsory quiz. Probe only when
    # the student's own statement supplies a concrete, testable concern.
    question = premise["question"] if premise else None
    if question is None and gate in ("PROBE", "VERIFY"):
        question = select_question(concepts, hypotheses, used_questions,
                                   approved_questions, student_profile)
        if question is None:
            question = await generate_open_question(provider, text, concepts, hypotheses)
    return {"concepts": concepts, "evidence": extracted["evidence"], "hypotheses": hypotheses,
            "gate": gate, "question": question}


async def verify_answer(provider, question: dict, answer: str) -> dict:
    if isinstance(provider, MockProvider):
        text = answer.lower().replace(" ", "")
        qid = question["id"]
        outcome = "UNCERTAIN"
        if qid == "DIAG-ARRAY-001":
            if ("移动" in text or "后移" in text) and ("o(n)" in text or "线性" in text): outcome = "MASTERED"
            elif "o(1)" in text and not ("移动" in text or "后移" in text): outcome = "GAP"
        elif qid == "DIAG-LINK-004":
            rejects_search = any(phrase in text for phrase in ("不用遍历", "无需遍历", "不必查找", "不用查找", "不需要定位"))
            if ("遍历" in text or "查找" in text or "定位" in text) and "o(n)" in text and not rejects_search: outcome = "MASTERED"
            elif "o(1)" in text and (rejects_search or not ("遍历" in text or "查找" in text or "定位" in text)): outcome = "GAP"
        elif qid == "DIAG-BST-001":
            if ("链" in text or "退化" in text) and "o(n)" in text: outcome = "MASTERED"
            elif "o(log" in text or "平衡" in text: outcome = "GAP"
        elif qid == "DIAG-STACK-001":
            if "3、2" in text or "3,2" in text: outcome = "MASTERED"
            elif "1、2" in text or "1,2" in text: outcome = "GAP"
        elif qid == "DIAG-QUEUE-001":
            if "1、2" in text or "1,2" in text: outcome = "MASTERED"
            elif "3、2" in text or "3,2" in text: outcome = "GAP"
        elif qid == "DIAG-LINK-005":
            if ("不" in text or "未" in text) and "连续" in text: outcome = "MASTERED"
            elif "必须连续" in text: outcome = "GAP"
        elif qid == "DIAG-HEAP-001":
            if ("不" in text or "没" in text) and "排序" in text and ("调整" in text or "下沉" in text): outcome = "MASTERED"
            elif "已经排序" in text: outcome = "GAP"
        return {"outcome": outcome, "evidence_quote": answer if outcome != "UNCERTAIN" else "",
                "explanation": "演示规则只判断这道核验题的关键条件。" if outcome != "UNCERTAIN" else "请补充关键步骤和理由，我会继续核验。",
                "confidence": .85 if outcome != "UNCERTAIN" else .2}
    prompt = ("评估学生对诊断题的回答。只从回答原文引用 evidence_quote。"
              "outcome 只能是 MASTERED、GAP 或 UNCERTAIN。"
              "不能仅因与参考答案措辞不同就判 GAP；要看概念和推理。"
              "当回答含糊、证据不足或有多种合理解释时必须 UNCERTAIN。"
              "输出 JSON：outcome,evidence_quote,explanation,confidence。"
              f"\n题目：{question['question']}\n参考答案：{question['expected_answer']}"
              f"\n两种理解状态：{question.get('discriminates', {})}\n学生回答：{answer}")
    raw = await provider.structured_chat([{"role": "user", "content": prompt}], VerificationResult)
    quote = str(raw.get("evidence_quote") or "")
    outcome = raw.get("outcome")
    if quote not in answer or not quote or outcome not in ("MASTERED", "GAP"):
        outcome = "UNCERTAIN"
    confidence = min(1.0, max(0.0, float(raw.get("confidence") or 0)))
    if confidence < 0.8:
        outcome = "UNCERTAIN"
    return {"outcome": outcome, "evidence_quote": quote if quote in answer else "",
            "explanation": str(raw.get("explanation") or ""), "confidence": confidence}
