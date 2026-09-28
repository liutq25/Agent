import json
import hmac
import os
import re
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header, Depends, Request
import httpx
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ValidationError
from .core import CONCEPTS, MISCONCEPTIONS, QUESTIONS, diagnose, recommend, simulate
from .providers import get_provider, create_provider, get_embedding_provider
from .config import load_local_env
from .retrieval import chunks, retrieve, format_context, open_resources
from .tutor_graph import begin_probe, finish_probe
from .model_settings import ModelSettings, DEFAULT_URLS, load_settings, save_settings, public_settings, get_key, delete_key
from .conversation import answer_question, is_coding_request
from .code_lab import EXERCISES as CODE_EXERCISES, sandbox_ready, run_tests, feedback as code_feedback
from .algorithm_tools import TOOLS as ALGORITHM_TOOLS, execute_tool, compare_student_trace
from .tool_routing import select_and_run_tool
from .diagnostic_pipeline import analyze_turn, verify_answer, mock_concept_map, CONCEPT_BY_ID, MISCONCEPTION_BY_ID
from .diagnostic_trace import DiagnosticTraceRecorder, EventType, record_initial, record_verification

DB_PATH = Path(os.getenv("COGNITUTOR_DB", str(Path(__file__).resolve().parent.parent / "data" / "cognitutor.db")))
app = FastAPI(title="知学 CogniTutor-DS", version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


def require_admin(request: Request, x_admin_token: str | None = Header(default=None)):
    """Opt-in token for teacher data and local model configuration."""
    load_local_env()
    expected = os.getenv("COGNITUTOR_ADMIN_TOKEN", "")
    if expected and not hmac.compare_digest(x_admin_token or "", expected):
        raise HTTPException(403, "需要有效的教师访问口令")
    if not expected and request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "远程访问教师数据前必须配置 COGNITUTOR_ADMIN_TOKEN")


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, student_id TEXT NOT NULL, class_id TEXT NOT NULL, question_id TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS learning_evidence(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, student_id TEXT NOT NULL, question_id TEXT NOT NULL, raw_student_answer TEXT NOT NULL, student_explanation TEXT NOT NULL, diagnosis_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS student_concept_state(student_id TEXT NOT NULL, concept_id TEXT NOT NULL, mastery REAL NOT NULL, PRIMARY KEY(student_id, concept_id));
    CREATE TABLE IF NOT EXISTS student_misconception_state(student_id TEXT NOT NULL, misconception_id TEXT NOT NULL, risk REAL NOT NULL, PRIMARY KEY(student_id, misconception_id));
    CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS document_vectors(source_id TEXT PRIMARY KEY, vector_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_sessions(id TEXT PRIMARY KEY, student_id TEXT NOT NULL, class_id TEXT NOT NULL, pending_json TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS chat_messages(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, meta_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS code_submissions(id TEXT PRIMARY KEY, student_id TEXT NOT NULL, class_id TEXT NOT NULL, exercise_id TEXT NOT NULL, source TEXT NOT NULL, result_json TEXT NOT NULL, feedback TEXT NOT NULL, hint_stage INTEGER NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_code_submissions_class ON code_submissions(class_id,created_at);
    CREATE TABLE IF NOT EXISTS algorithm_runs(id TEXT PRIMARY KEY, student_id TEXT NOT NULL, class_id TEXT NOT NULL, tool_name TEXT NOT NULL, params_json TEXT NOT NULL, trace_json TEXT NOT NULL, comparison_json TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS student_concept_evidence(student_id TEXT NOT NULL, concept_id TEXT NOT NULL, alpha REAL NOT NULL DEFAULT 1, beta REAL NOT NULL DEFAULT 1, evidence_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(student_id,concept_id));
    CREATE TABLE IF NOT EXISTS student_misconception_diagnosis(student_id TEXT NOT NULL, issue_key TEXT NOT NULL, issue_name TEXT NOT NULL, status TEXT NOT NULL, risk REAL NOT NULL, evidence_count INTEGER NOT NULL, positive_count INTEGER NOT NULL, PRIMARY KEY(student_id,issue_key));
    CREATE TABLE IF NOT EXISTS diagnostic_traces(id TEXT PRIMARY KEY, student_id TEXT NOT NULL, session_id TEXT NOT NULL, question_id TEXT, status TEXT NOT NULL, outcome TEXT NOT NULL, current_confidence REAL NOT NULL, current_action TEXT, started_at TEXT NOT NULL, completed_at TEXT, versions_json TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_diagnostic_traces_session ON diagnostic_traces(session_id);
    CREATE TABLE IF NOT EXISTS diagnostic_events(id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_type TEXT NOT NULL, timestamp TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, hypothesis_updates_json TEXT NOT NULL, action TEXT, confidence_before REAL, confidence_after REAL, UNIQUE(trace_id,sequence));
    CREATE INDEX IF NOT EXISTS idx_diagnostic_events_trace ON diagnostic_events(trace_id);
    CREATE TABLE IF NOT EXISTS diagnostic_evidence(id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, source_type TEXT NOT NULL, source_turn INTEGER NOT NULL, quote TEXT NOT NULL, concept_ids_json TEXT NOT NULL, supports_json TEXT NOT NULL, contradicts_json TEXT NOT NULL, strength REAL NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS diagnostic_hypotheses(id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, misconception_id TEXT, candidate_name TEXT NOT NULL, hypothesis_type TEXT NOT NULL, status TEXT NOT NULL, concept_ids_json TEXT NOT NULL, confidence REAL NOT NULL, supporting_evidence_ids_json TEXT NOT NULL, contradicting_evidence_ids_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
    return connection


class SessionInput(BaseModel):
    student_id: str = Field(min_length=1)
    class_id: str = "demo-class"
    question_id: str = "array-insert"


class MessageInput(BaseModel):
    answer: str = ""
    explanation: str = ""
    student_trace: list[int] | None = None


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100000)


async def course_context(connection, query: str) -> list[dict]:
    documents = [{"id": row["id"], "title": row["title"], "content": row["content"]}
                 for row in connection.execute("SELECT * FROM documents")]
    embedder = get_embedding_provider()
    vector = None
    vectors = {}
    if embedder:
        rows = connection.execute("SELECT source_id,vector_json FROM document_vectors").fetchall()
        if rows:
            try:
                vector = await embedder.embed_query(query)
                vectors = {row["source_id"]: json.loads(row["vector_json"]) for row in rows}
            except (httpx.HTTPError, ValueError, RuntimeError):
                vector = None
    return retrieve(query, documents + open_resources(), query_vector=vector, vectors=vectors)


class ChatSessionInput(BaseModel):
    student_id: str = Field(min_length=1)
    class_id: str = "demo-class"


class ChatMessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class CodeSubmissionInput(BaseModel):
    student_id: str = Field(min_length=1, max_length=100)
    class_id: str = "demo-class"
    exercise_id: str
    source: str = Field(min_length=1, max_length=12000)


class AlgorithmRunInput(BaseModel):
    student_id: str = Field(min_length=1, max_length=100)
    class_id: str = "demo-class"
    tool_name: str
    params: dict
    student_trace: list | None = None


class ModelSettingsInput(BaseModel):
    protocol: str = "mock"
    model: str = ""
    base_url: str = ""
    timeout: int = 60
    api_key: str | None = None

    def settings(self):
        return ModelSettings(protocol=self.protocol, model=self.model.strip(),
                             base_url=self.base_url.strip(), timeout=self.timeout)


@app.post("/api/chat/session")
def create_chat_session(body: ChatSessionInput):
    session_id = str(uuid.uuid4())
    with db() as connection:
        connection.execute("INSERT INTO chat_sessions VALUES(?,?,?,?,?)", (session_id, body.student_id,
            body.class_id, None, datetime.now(timezone.utc).isoformat()))
    return {"session_id": session_id, "student_id": body.student_id}


@app.get("/api/chat/{session_id}/history")
def chat_history(session_id: str):
    with db() as connection:
        if not connection.execute("SELECT 1 FROM chat_sessions WHERE id=?", (session_id,)).fetchone():
            raise HTTPException(404, "Unknown chat session")
        rows = connection.execute("SELECT role, content, meta_json, created_at FROM chat_messages WHERE session_id=? ORDER BY rowid", (session_id,))
        return [{"role": row["role"], "content": row["content"], "meta": json.loads(row["meta_json"]),
                 "created_at": row["created_at"]} for row in rows]


def weakness_summary(connection, student_id: str) -> str:
    rows = connection.execute("SELECT issue_name,status,evidence_count FROM student_misconception_diagnosis "
        "WHERE student_id=? ORDER BY CASE status WHEN 'CONFIRMED' THEN 0 WHEN 'IMPROVING' THEN 1 ELSE 2 END, evidence_count DESC LIMIT 5",
        (student_id,)).fetchall()
    if not rows:
        return "目前还没有足够的核验记录来判断你的薄弱点。你可以讲一道题的解法，我会先观察再追问。"
    lines = []
    for row in rows:
        state = {"CONFIRMED": "已由核验题支持", "IMPROVING": "正在改善", "RESOLVED": "最近核验已通过",
                 "SUSPECTED": "仍待核验"}.get(row["status"], "证据不足")
        lines.append(f"- {row['issue_name']}：{state}，已有 {row['evidence_count']} 条相关记录")
    return "结合此前对话与核验记录，目前的学习画像是：\n" + "\n".join(lines) + "\n这些结论会随你后续回答而更新。"


def asks_for_explanation(text: str) -> bool:
    """Recognize an explicit request to explain the current topic further."""
    return bool(re.search(r"(真正|具体|详细|实际).{0,8}(实现|过程|步骤|怎么)|"
                          r"(怎么|如何).{0,8}(实现|写|做|操作)|"
                          r"(讲|解释|说明|展开).{0,8}(一下|清楚|详细|具体)|"
                          r"(代码|伪代码|例子|示例)", text))


def coding_hint_stage(connection, session_id: str, topic: str) -> int:
    rows = connection.execute("SELECT meta_json FROM chat_messages WHERE session_id=? AND role='assistant'",
                              (session_id,)).fetchall()
    count = sum(json.loads(row[0]).get("teaching_topic") == topic for row in rows)
    return min(count, 2)


@app.post("/api/chat/{session_id}/message")
async def chat_message(session_id: str, body: ChatMessageInput):
    provider = get_provider()
    with db() as connection:
        session = connection.execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Unknown chat session")
        recorder = DiagnosticTraceRecorder(connection)
        pending = json.loads(session["pending_json"]) if session["pending_json"] else None
        history = [dict(row) for row in connection.execute(
            "SELECT role,content FROM chat_messages WHERE session_id=? ORDER BY rowid DESC LIMIT 8", (session_id,))]
        history.reverse()
        wants_summary = bool(re.search(r"(哪里|哪些|什么).{0,8}(薄弱|不会|问题|错误)|总结.{0,8}(学习|薄弱|问题)|学习画像", body.content))
        last_assistant = next((row for row in reversed(history) if row["role"] == "assistant"), None)
        recent_user = next((row for row in reversed(history) if row["role"] == "user"), None)
        new_question = bool(re.search(r"[?？]", body.content) or
                            re.match(r"^\s*(为什么|怎么|如何|什么|请问|能否|是否)", body.content))
        stated_topic = mock_concept_map(body.content)
        explicit_topic = bool(re.search(r"顺序表|数组|链表|二叉搜索树|BST|堆|栈|队列", body.content, re.I))
        changed_topic = bool(pending and explicit_topic and stated_topic and stated_topic[0]["relevance"] >= .9 and
                             stated_topic[0]["id"] not in pending["question"].get("concept_ids", []))
        if pending and (wants_summary or asks_for_explanation(body.content) or new_question or changed_topic):
            # The student is steering the conversation. A pending quiz must not
            # swallow a fresh question or a request for explanation.
            if pending.get("trace_id"):
                recorder.set_status(pending["trace_id"], status="ABORTED", confidence=0,
                                    action="STUDENT_CHANGED_TOPIC", outcome="INTERRUPTED")
            finish_probe(session_id, cancelled=True, path=DB_PATH.with_name(DB_PATH.stem + "_graph.db"))
            pending = None
        followup = bool(last_assistant and asks_for_explanation(body.content))
        try:
            if wants_summary and not pending:
                analysis = {"concepts": [], "evidence": [], "hypotheses": [],
                            "gate": "COLLECT_MORE_EVIDENCE", "question": None}
                reply = weakness_summary(connection, session["student_id"])
                diagnosis = {"status": "SUMMARY", "concepts": [], "evidence": [], "hypotheses": [],
                             "gate": "COLLECT_MORE_EVIDENCE"}
                next_pending = None
                response = {"mode": "summary", "answer": reply, "probe": None, "diagnosis": diagnosis,
                            "model_mode": "local-record"}
            elif pending:
                question = pending["question"]
                verification = await verify_answer(provider, question, body.content)
                prior = pending["analysis"]
                if verification["outcome"] == "GAP" and not prior["hypotheses"] and question.get("diagnostic_targets"):
                    mid = question["diagnostic_targets"][0]
                    known = MISCONCEPTION_BY_ID.get(mid)
                    if known:
                        prior["hypotheses"] = [{"misconception_id": mid, "issue_type": "misconception",
                            "candidate_name": known["name"], "related_concepts": known["concept_ids"],
                            "evidence_quotes": [verification["evidence_quote"]],
                            "confidence": verification["confidence"]}]
                hypothesis = prior["hypotheses"][0] if prior["hypotheses"] else None
                if verification["outcome"] == "GAP":
                    label = hypothesis["candidate_name"] if hypothesis else "当前知识点的理解偏差"
                    correction = MISCONCEPTION_BY_ID.get(hypothesis.get("misconception_id"), {}).get("correct_model", "") if hypothesis else ""
                    reply = (f"根据你在核验题中的回答“{verification['evidence_quote']}”，可以定位到：{label}。"
                             f"{verification['explanation']}\n正确理解：{correction or question['expected_answer']}")
                    previous = [item["issue_name"] for item in profile(connection, session["student_id"])["diagnoses"]
                                if item["status"] == "CONFIRMED" and item["issue_name"] != label]
                    if previous:
                        reply += "\n结合此前记录，你还需要留意：" + "、".join(previous[:2]) + "。"
                elif verification["outcome"] == "MASTERED":
                    reply = "这道核验题表明你理解了当前关键点。" + verification["explanation"]
                else:
                    reply = "我还不能可靠判断你是否掌握了这一步。请再回答一个更具体的问题：" + question["follow_up_if_unclear"]
                diagnosis = {"status": "CONFIRMED" if verification["outcome"] == "GAP" else
                             "RESOLVED" if verification["outcome"] == "MASTERED" else "UNCERTAIN",
                             "verification": verification, "hypotheses": prior["hypotheses"],
                             "concepts": prior["concepts"], "evidence": prior["evidence"]}
                response = {"mode": "diagnosis", "answer": reply, "probe": None, "diagnosis": diagnosis,
                            "model_mode": "mock" if provider.__class__.__name__ == "MockProvider" else "api"}
                next_pending = None if verification["outcome"] != "UNCERTAIN" else {
                    **pending, "attempts": pending.get("attempts", 0) + 1}
            elif followup:
                prior_meta_row = connection.execute(
                    "SELECT meta_json FROM chat_messages WHERE session_id=? AND role='assistant' ORDER BY rowid DESC LIMIT 1",
                    (session_id,)).fetchone()
                prior_meta = json.loads(prior_meta_row[0]) if prior_meta_row else {}
                prior_concepts = prior_meta.get("diagnosis", {}).get("concepts", [])
                cards = [CONCEPT_BY_ID[item["id"]]["summary"] for item in prior_concepts
                         if item.get("id") in CONCEPT_BY_ID]
                topic = recent_user["content"] if recent_user else ""
                teaching_topic = prior_concepts[0]["id"] if prior_concepts else "GENERAL"
                code_stage = coding_hint_stage(connection, session_id, teaching_topic)
                coding_context = is_coding_request(body.content) or is_coding_request(topic)
                course_hits = await course_context(connection, topic + " " + body.content)
                reply = await answer_question(provider, body.content, history, cards,
                    context_hint=f"当前追问延续上一主题。上一轮学生原话：{topic}。"
                                 "请解释原理、关键步骤和复杂度；不要转到其他数据结构，也不要出新题。\n"
                                 + format_context(course_hits),
                    code_stage=code_stage, coding_context=coding_context)
                analysis = {"concepts": prior_concepts, "evidence": [], "hypotheses": [],
                            "gate": "EXPLAIN", "question": None}
                diagnosis = {"status": "EXPLAINED", **analysis}
                next_pending = None
                response = {"mode": "answer", "answer": reply, "probe": None,
                            "diagnosis": diagnosis, "sources": cards, "retrieved_sources": course_hits,
                            "model_mode": "mock" if provider.__class__.__name__ == "MockProvider" else "api"}
                if coding_context:
                    response.update({"teaching_topic": teaching_topic,
                                     "teaching_stage": ["反问", "反例", "线索"][code_stage]})
            else:
                used = {json.loads(row[0]).get("probe", {}).get("id") for row in connection.execute(
                    "SELECT meta_json FROM chat_messages WHERE session_id=? AND role='assistant'", (session_id,))
                    if json.loads(row[0]).get("probe")}
                context = "\n".join(row["content"] for row in history[-6:] if row["role"] == "user")
                # The student's request gets its own complete answer. The
                # diagnostic layer may then add one evidence-based probe.
                preliminary = mock_concept_map(body.content) or mock_concept_map(context)
                cards = [CONCEPT_BY_ID[item["id"]]["summary"] for item in preliminary]
                teaching_topic = preliminary[0]["id"] if preliminary else "GENERAL"
                code_stage = coding_hint_stage(connection, session_id, teaching_topic)
                tool_run = await select_and_run_tool(provider, body.content)
                tool_context = ("确定性算法工具结果（须优先用此结果说明步骤）：" +
                                json.dumps({"algorithm": tool_run["tool_name"],
                                            "steps": tool_run["trace"]["steps"][:15],
                                            "final_result": tool_run["trace"]["final_result"]}, ensure_ascii=False)
                                if tool_run else "")
                course_hits = await course_context(connection, body.content + " " + context[-500:])
                explanation = await answer_question(provider, body.content, history, cards,
                                                    context_hint=tool_context + "\n" + format_context(course_hits),
                                                    code_stage=code_stage)
                analysis = await analyze_turn(provider, body.content, used, context=context)
                analysis["tool_run"] = tool_run
                question = analysis["question"]
                if question:
                    next_pending = {"question": question, "analysis": analysis}
                    if analysis["hypotheses"]:
                        top = analysis["hypotheses"][0]
                        correction = MISCONCEPTION_BY_ID.get(top.get("misconception_id"), {}).get("correct_model", "")
                        if analysis["evidence"] and analysis["evidence"][0].get("type") == "premise_to_check":
                            reply = (explanation + "\n\n你问题中的前提“" + top["evidence_quotes"][0] +
                                     "”值得进一步核验，可能混淆了：" + top["candidate_name"] + "。"
                                     "你为什么会这样判断？请结合下面的小题说明：" + question["question"])
                        else:
                            reply = (explanation + "\n\n你刚才的说法“" + top["evidence_quotes"][0] +
                                     "”可能存在这个问题：" + top["candidate_name"] + "。" +
                                     ("关键区别是：" + correction + "。" if correction else "") +
                                     "为了确认你是否已理解，请回答：" + question["question"])
                    else:
                        reply = explanation + "\n\n针对这个知识点，我想确认一个关键区别：" + question["question"]
                else:
                    next_pending = None
                    reply = explanation
                diagnosis = {"status": "SUSPECTED" if analysis["hypotheses"] else "OBSERVED",
                             "concepts": analysis["concepts"], "evidence": analysis["evidence"],
                             "hypotheses": analysis["hypotheses"], "gate": analysis["gate"]}
                response = {"mode": "answer", "answer": reply, "probe": question, "diagnosis": diagnosis,
                            "sources": cards, "retrieved_sources": course_hits,
                            "model_mode": "mock" if provider.__class__.__name__ == "MockProvider" else "api"}
                if tool_run:
                    response["tool_result"] = {"algorithm": tool_run["tool_name"],
                                               "steps": tool_run["trace"]["steps"],
                                               "final_result": tool_run["trace"]["final_result"]}
                if is_coding_request(body.content):
                    response.update({"teaching_topic": teaching_topic,
                                     "teaching_stage": ["反问", "反例", "线索"][code_stage]})
        except RuntimeError as error:
            if str(error) == "Model returned an empty answer":
                raise HTTPException(502, "模型已连接，但没有生成可显示的回答。请重试或调整模型输出设置。") from error
            raise HTTPException(503, "模型调用失败；请检查 API 配置并重试。") from error
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise HTTPException(503, f"模型服务暂不可用：{type(error).__name__}。请检查 API 配置或启用 Mock 模式。") from error
        if pending:
            trace_id = pending.get("trace_id")
            hypothesis_ids = pending.get("hypothesis_ids")
            if not trace_id:
                previous = connection.execute("SELECT content FROM chat_messages WHERE session_id=? AND role='user' ORDER BY rowid DESC LIMIT 1", (session_id,)).fetchone()
                trace_id, hypothesis_ids = record_initial(recorder, student_id=session["student_id"],
                    session_id=session_id, student_text=previous[0] if previous else "",
                    analysis=pending["analysis"])
            if len(hypothesis_ids or []) < len(pending["analysis"]["hypotheses"]):
                hypothesis_ids = list(hypothesis_ids or [])
                for item in pending["analysis"]["hypotheses"][len(hypothesis_ids):]:
                    hid = recorder.create_hypothesis(trace_id, misconception_id=item.get("misconception_id"),
                        candidate_name=item["candidate_name"], hypothesis_type=item["issue_type"].upper(),
                        concept_ids=item["related_concepts"], confidence=item["confidence"], evidence_ids=[])
                    hypothesis_ids.append(hid)
                    recorder.append_event(trace_id, EventType.HYPOTHESIS_CREATED,
                        hypothesis_updates=[{"hypothesis_id": hid, "confidence": item["confidence"],
                                             "reason_code": "PROBE_REVEALED"}])
            state_before = profile(connection, session["student_id"])
            trace_outcome, trace_confidence = record_verification(recorder, trace_id=trace_id,
                student_text=body.content, question=question, verification=verification,
                hypotheses=pending["analysis"]["hypotheses"], hypothesis_ids=hypothesis_ids or [])
        else:
            trace_id, hypothesis_ids = record_initial(recorder, student_id=session["student_id"],
                session_id=session_id, student_text=body.content, analysis=analysis)
            if analysis.get("tool_run"):
                tool_run = analysis["tool_run"]
                recorder.append_event(trace_id, EventType.TOOL_REQUESTED,
                    output_summary={"tool_name": tool_run["tool_name"], "params": tool_run["params"]})
                recorder.append_event(trace_id, EventType.TOOL_RESULT,
                    output_summary={"tool_name": tool_run["tool_name"],
                                    "step_count": len(tool_run["trace"]["steps"]),
                                    "final_result": tool_run["trace"]["final_result"]})
            if next_pending:
                next_pending["trace_id"] = trace_id
                next_pending["hypothesis_ids"] = hypothesis_ids
        response["trace_id"] = trace_id
        now = datetime.now(timezone.utc).isoformat()
        connection.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), session_id,
            "user", body.content, "{}", now))
        connection.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), session_id,
            "assistant", response["answer"], json.dumps(response, ensure_ascii=False), now))
        connection.execute("UPDATE chat_sessions SET pending_json=? WHERE id=?",
            (json.dumps(next_pending, ensure_ascii=False) if next_pending else None, session_id))
        if not pending:
            connection.execute("INSERT INTO learning_evidence VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), session_id,
                session["student_id"], "conversation-observation", body.content, "",
                json.dumps(diagnosis, ensure_ascii=False), now))
            for item in analysis["hypotheses"]:
                if any(span.get("type") == "premise_to_check" for span in analysis["evidence"]):
                    continue
                key = item["misconception_id"] or "OPEN:" + item["candidate_name"][:100]
                if not key or key == "OPEN:":
                    continue
                old = connection.execute("SELECT 1 FROM student_misconception_diagnosis WHERE student_id=? AND issue_key=?",
                    (session["student_id"], key)).fetchone()
                if not old:
                    connection.execute("INSERT INTO student_misconception_diagnosis VALUES(?,?,?,?,?,?,?)",
                        (session["student_id"], key, item["candidate_name"], "SUSPECTED",
                         round(item["confidence"] * 0.5, 3), 1, 0))
        if pending:
            connection.execute("INSERT INTO learning_evidence VALUES(?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), session_id,
                session["student_id"], question["id"], body.content, "",
                json.dumps(diagnosis, ensure_ascii=False), now))
            if verification["outcome"] in ("GAP", "MASTERED"):
                positive = verification["outcome"] == "MASTERED"
                target_concepts = (pending["analysis"]["hypotheses"][0].get("related_concepts")
                    if not positive and pending["analysis"]["hypotheses"] else None)
                for concept_id in (target_concepts or question["concept_ids"]):
                    connection.execute("INSERT INTO student_concept_evidence VALUES(?,?,?,?,?) "
                        "ON CONFLICT(student_id,concept_id) DO UPDATE SET alpha=alpha+excluded.alpha-1, "
                        "beta=beta+excluded.beta-1, evidence_count=evidence_count+1",
                        (session["student_id"], concept_id, 2 if positive else 1,
                         1 if positive else 2, 1))
                for item in pending["analysis"]["hypotheses"]:
                    key = item["misconception_id"] or "OPEN:" + item["candidate_name"][:100]
                    if not key or key == "OPEN:":
                        continue
                    old = connection.execute("SELECT * FROM student_misconception_diagnosis WHERE student_id=? AND issue_key=?",
                        (session["student_id"], key)).fetchone()
                    count = (old["evidence_count"] if old else 0) + 1
                    pos_count = (old["positive_count"] if old else 0) + int(positive)
                    if positive:
                        status = ("RESOLVED" if pos_count >= 2 else "IMPROVING") if old and old["status"] in ("CONFIRMED", "IMPROVING") else "RESOLVED"
                    else:
                        status = "CONFIRMED"
                    risk = round(max(0, min(1, (old["risk"] if old else 0.5) + (-0.2 if positive else 0.25))), 3)
                    connection.execute("INSERT INTO student_misconception_diagnosis VALUES(?,?,?,?,?,?,?) "
                        "ON CONFLICT(student_id,issue_key) DO UPDATE SET status=excluded.status,risk=excluded.risk, "
                        "evidence_count=excluded.evidence_count,positive_count=excluded.positive_count",
                        (session["student_id"], key, item["candidate_name"], status, risk, count, pos_count))
            state_after = profile(connection, session["student_id"])
            changed = {}
            for concept_id in question.get("concept_ids", []):
                before = state_before["concept_state"].get(concept_id)
                after = state_after["concept_state"].get(concept_id)
                if before != after:
                    changed[concept_id] = {"before": before, "after": after}
            recorder.append_event(trace_id, EventType.STUDENT_STATE_UPDATED,
                output_summary={"concept_changes": changed,
                                "diagnosis_status": diagnosis["status"],
                                "state_changed": bool(changed)})
            if verification["outcome"] == "UNCERTAIN" and next_pending and next_pending["attempts"] <= 2:
                recorder.append_event(trace_id, EventType.PROBE_SENT, action="PROBE",
                    output_summary={"question_id": question["id"], "question": question["follow_up_if_unclear"],
                                    "reason_code": "INSUFFICIENT_EVIDENCE"})
                recorder.set_status(trace_id, status="WAITING_STUDENT", confidence=trace_confidence,
                                    action="PROBE")
            else:
                if verification["outcome"] == "UNCERTAIN":
                    next_pending = None
                    connection.execute("UPDATE chat_sessions SET pending_json=NULL WHERE id=?", (session_id,))
                    response["answer"] = "经过几轮追问，我仍缺少足够证据，暂不把这个点判为错误。已记录你的回答；你可以换一种方式说明思路，或询问另一个问题。"
                    connection.execute("UPDATE chat_messages SET content=? WHERE session_id=? AND role='assistant' AND rowid=(SELECT MAX(rowid) FROM chat_messages WHERE session_id=? AND role='assistant')",
                        (response["answer"], session_id, session_id))
                recorder.append_event(trace_id, EventType.TRACE_COMPLETED,
                    output_summary={"outcome": trace_outcome})
                recorder.set_status(trace_id, status="COMPLETED", confidence=trace_confidence,
                                    action="EXPLAIN" if verification["outcome"] == "GAP" else "VERIFY",
                                    outcome=trace_outcome)
        graph_path = DB_PATH.with_name(DB_PATH.stem + "_graph.db")
        if pending:
            finish_probe(session_id, answer=body.content, outcome=verification["outcome"],
                         confidence=verification["confidence"], path=graph_path)
            if next_pending:
                followup_question = {**next_pending["question"],
                                     "question": next_pending["question"]["follow_up_if_unclear"]}
                begin_probe(session_id, session["student_id"], followup_question, path=graph_path)
        elif next_pending:
            begin_probe(session_id, session["student_id"], next_pending["question"], path=graph_path)
        return response


def profile(connection, student_id):
    mastery = {r["concept_id"]: r["mastery"] for r in connection.execute("SELECT * FROM student_concept_state WHERE student_id=?", (student_id,))}
    risks = {r["misconception_id"]: r["risk"] for r in connection.execute("SELECT * FROM student_misconception_state WHERE student_id=?", (student_id,))}
    concept_state = {}
    for row in connection.execute("SELECT * FROM student_concept_evidence WHERE student_id=?", (student_id,)):
        value = round(row["alpha"] / (row["alpha"] + row["beta"]), 3)
        mastery[row["concept_id"]] = value
        concept_state[row["concept_id"]] = {"mastery": value,
            "confidence": round(row["evidence_count"] / (row["evidence_count"] + 2), 3),
            "evidence_count": row["evidence_count"]}
    diagnoses = [dict(row) for row in connection.execute("SELECT issue_key,issue_name,status,risk,evidence_count,positive_count FROM student_misconception_diagnosis WHERE student_id=?", (student_id,))]
    for item in diagnoses:
        if item["issue_key"] in MISCONCEPTION_BY_ID:
            risks[item["issue_key"]] = item["risk"]
    stages = [row[0] for row in connection.execute(
        "SELECT hint_stage FROM code_submissions WHERE student_id=? ORDER BY created_at,rowid", (student_id,))]
    # Descriptive assistance signal, not a calibrated psychological trait.
    support = {"sample_count": len(stages),
               "mean_hint_level": round(sum(stages) / len(stages), 3) if stages else None,
               "recent_mean_hint_level": round(sum(stages[-5:]) / len(stages[-5:]), 3) if stages else None}
    return {"student_id": student_id, "mastery": mastery, "concept_state": concept_state,
            "misconception_risk": risks, "diagnoses": diagnoses, "support_dependency": support}


@app.get("/api/health")
def health():
    with db() as connection: connection.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/system/model-status")
def model_status():
    provider = get_provider()
    return {"provider": provider.protocol,
            "model": getattr(provider, "model", "deterministic-demo"),
            "tool_calling": provider.capabilities["tool_calling"],
            "embedding_ready": os.getenv("EMBEDDING_PROVIDER", "local") == "local" or bool(os.getenv("EMBEDDING_API_KEY")),
            "mock_mode": provider.__class__.__name__ == "MockProvider",
            "has_key": bool(getattr(provider, "key", ""))}


@app.get("/api/system/model-settings", dependencies=[Depends(require_admin)])
def model_settings_get():
    return {"settings": public_settings(load_settings() or ModelSettings()), "defaults": DEFAULT_URLS}


@app.put("/api/system/model-settings", dependencies=[Depends(require_admin)])
def model_settings_put(body: ModelSettingsInput):
    try:
        settings = body.settings()
    except ValidationError as error:
        raise HTTPException(422, "协议、地址或超时设置无效；远程服务须使用 HTTPS") from error
    try:
        save_settings(settings, body.api_key)
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error
    return public_settings(settings)


@app.delete("/api/system/model-settings/key", dependencies=[Depends(require_admin)])
def model_settings_delete_key():
    settings = load_settings()
    if not settings or settings.protocol == "mock":
        raise HTTPException(400, "No active model API key")
    delete_key(settings)
    return public_settings(settings)


@app.post("/api/system/model-settings/test", dependencies=[Depends(require_admin)])
async def model_settings_test(body: ModelSettingsInput):
    try:
        settings = body.settings()
    except ValidationError as error:
        raise HTTPException(422, "协议、地址或超时设置无效；远程服务须使用 HTTPS") from error
    if settings.protocol == "mock":
        return {"ok": True, "message": "演示模式无需远程连接"}
    key = body.api_key.strip() if body.api_key else get_key(settings)
    if not key:
        raise HTTPException(400, "请先填写 API Key")
    try:
        answer = await create_provider(settings, key).chat(
            [{"role": "user", "content": "请只回复 OK"}], max_tokens=32)
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as error:
        raise HTTPException(502, f"连接失败：{type(error).__name__}。请检查协议、地址、模型和密钥。") from error
    return {"ok": True, "message": "连接成功", "preview": answer[:120]}


@app.get("/api/code/status")
def code_status():
    ready = sandbox_ready()
    return {"sandbox_ready": ready, "language": "python",
            "message": "Docker 隔离运行环境已就绪" if ready else
                       "尚未安装 Docker 或缺少 python:3.12-alpine 镜像；代码不会在本机直接运行"}


@app.get("/api/algorithm/tools")
def algorithm_tools():
    return {"tools": list(ALGORITHM_TOOLS)}


@app.post("/api/algorithm/trace")
def algorithm_trace(body: AlgorithmRunInput):
    try:
        trace = execute_tool(body.tool_name, body.params)
        comparison = compare_student_trace(body.student_trace, trace["steps"]) if body.student_trace is not None else None
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    run_id = str(uuid.uuid4())
    with db() as connection:
        connection.execute("INSERT INTO algorithm_runs VALUES(?,?,?,?,?,?,?,?)",
            (run_id, body.student_id, body.class_id, body.tool_name,
             json.dumps(body.params, ensure_ascii=False), json.dumps(trace, ensure_ascii=False),
             json.dumps(comparison, ensure_ascii=False) if comparison else None,
             datetime.now(timezone.utc).isoformat()))
    return {"run_id": run_id, "trace": trace, "comparison": comparison}


@app.get("/api/class/{class_id}/algorithm-runs", dependencies=[Depends(require_admin)])
def class_algorithm_runs(class_id: str, limit: int = 30):
    with db() as connection:
        rows = connection.execute("SELECT id,student_id,tool_name,comparison_json,created_at "
            "FROM algorithm_runs WHERE class_id=? ORDER BY created_at DESC LIMIT ?",
            (class_id, min(max(limit, 1), 100))).fetchall()
        return [{"run_id": row["id"], "student_id": row["student_id"],
                 "tool_name": row["tool_name"],
                 "comparison": json.loads(row["comparison_json"]) if row["comparison_json"] else None,
                 "created_at": row["created_at"]} for row in rows]


@app.get("/api/code/exercises")
def code_exercises():
    return [{"id": key, "title": item["title"], "task": item["task"], "function": item["function"]}
            for key, item in CODE_EXERCISES.items()]


@app.post("/api/code/submit")
def code_submit(body: CodeSubmissionInput):
    exercise = CODE_EXERCISES.get(body.exercise_id)
    if not exercise:
        raise HTTPException(404, "未知编程练习")
    with db() as connection:
        previous = connection.execute("SELECT COUNT(*) FROM code_submissions WHERE student_id=? AND exercise_id=? "
            "AND result_json NOT LIKE '%SANDBOX_UNAVAILABLE%'", (body.student_id, body.exercise_id)).fetchone()[0]
        stage = min(previous, 2)
        result = run_tests(body.exercise_id, body.source)
        message = code_feedback(exercise, result, stage)
        if result["status"] == "SANDBOX_UNAVAILABLE":
            return {"result": result, "feedback": message, "hint_stage": None, "recorded": False}
        submission_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        connection.execute("INSERT INTO code_submissions VALUES(?,?,?,?,?,?,?,?,?)",
            (submission_id, body.student_id, body.class_id, body.exercise_id, body.source,
             json.dumps(result, ensure_ascii=False), message, stage, now))
        if result["status"] == "TESTED":
            all_passed = all(case["passed"] for case in result["cases"])
            connection.execute("INSERT INTO student_concept_evidence VALUES(?,?,?,?,?) "
                "ON CONFLICT(student_id,concept_id) DO UPDATE SET alpha=alpha+excluded.alpha-1, "
                "beta=beta+excluded.beta-1, evidence_count=evidence_count+1",
                (body.student_id, exercise["concept_id"], 2 if all_passed else 1,
                 1 if all_passed else 2, 1))
        return {"submission_id": submission_id, "result": result, "feedback": message,
                "hint_stage": stage + 1, "recorded": True}


@app.get("/api/class/{class_id}/code-activity", dependencies=[Depends(require_admin)])
def class_code_activity(class_id: str, limit: int = 30):
    with db() as connection:
        rows = connection.execute("SELECT id,student_id,exercise_id,source,result_json,feedback,hint_stage,created_at "
            "FROM code_submissions WHERE class_id=? ORDER BY created_at DESC LIMIT ?",
            (class_id, min(max(limit, 1), 100))).fetchall()
        return [{"id": row["id"], "student_id": row["student_id"],
                 "exercise_id": row["exercise_id"], "source": row["source"],
                 "result": json.loads(row["result_json"]),
                 "feedback": row["feedback"], "hint_stage": row["hint_stage"],
                 "created_at": row["created_at"]} for row in rows]


@app.get("/api/class/{class_id}/learning-activity", dependencies=[Depends(require_admin)])
def class_learning_activity(class_id: str, limit: int = 30):
    with db() as connection:
        rows = connection.execute(
            "SELECT s.student_id,m.content,m.created_at FROM chat_messages m "
            "JOIN chat_sessions s ON s.id=m.session_id WHERE s.class_id=? AND m.role='user' "
            "ORDER BY m.rowid DESC LIMIT ?", (class_id, min(max(limit, 1), 100))).fetchall()
        return [dict(row) for row in rows]


@app.post("/api/tutor/session")
def create_session(body: SessionInput):
    if body.question_id not in QUESTIONS: raise HTTPException(404, "Unknown question")
    session_id = str(uuid.uuid4())
    with db() as connection:
        connection.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)", (session_id, body.student_id, body.class_id,
            body.question_id, 0, datetime.now(timezone.utc).isoformat()))
    return {"session_id": session_id, "question": QUESTIONS[body.question_id]}


def answer_session(session_id: str, body: MessageInput):
    with db() as connection:
        session = connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session: raise HTTPException(404, "Unknown session")
        recorder = DiagnosticTraceRecorder(connection)
        active = connection.execute("SELECT id FROM diagnostic_traces WHERE session_id=? AND status='WAITING_STUDENT' ORDER BY started_at DESC LIMIT 1", (session_id,)).fetchone()
        trace_id = active[0] if active else recorder.create_trace(session["student_id"], session_id, session["question_id"])
        before_state = profile(connection, session["student_id"])
        attempt = session["attempts"] + 1
        result = diagnose(session["question_id"], body.answer, body.explanation, body.student_trace, attempt)
        recorder.append_event(trace_id, EventType.STUDENT_INPUT if attempt == 1 else EventType.STUDENT_RESPONSE_RECEIVED,
            input_summary={"attempt": attempt, "answer_length": len(body.answer),
                           "explanation_length": len(body.explanation)})
        recorder.append_event(trace_id, EventType.CONCEPT_MAPPING,
            output_summary={"concept_ids": result["concept_ids"]})
        trace_evidence_ids = []
        if body.answer:
            trace_evidence_ids.append(recorder.add_evidence(trace_id, source_type="STUDENT_ANSWER",
                source_turn=attempt, quote=body.answer, concept_ids=result["concept_ids"],
                supports=result["misconception_ids"], strength=result["confidence"]))
        recorder.append_event(trace_id, EventType.EVIDENCE_EXTRACTED,
            output_summary={"count": len(trace_evidence_ids)}, evidence_ids=trace_evidence_ids)
        question = QUESTIONS[session["question_id"]]
        if question.get("tool"):
            recorder.append_event(trace_id, EventType.TOOL_REQUESTED,
                output_summary={"tool_name": question["tool"], "operations": question["operations"]})
            tool_result = simulate(question["tool"], question["operations"])
            recorder.append_event(trace_id, EventType.TOOL_RESULT,
                output_summary={"tool_name": question["tool"], "outputs": tool_result["outputs"],
                                "step_count": len(tool_result["trace"])})
            recorder.append_event(trace_id, EventType.TRACE_COMPARISON,
                output_summary={"first_divergence": result["first_divergence"]})
        recorder.append_event(trace_id, EventType.CONFIDENCE_EVALUATED,
            output_summary={"answer_status": result["answer_status"], "confidence": result["confidence"]})
        recorder.append_event(trace_id, EventType.TEACHING_ACTION_SELECTED,
            action=result["teaching_action"], output_summary={"selected_by": "RULE",
            "attempt": attempt, "answer_status": result["answer_status"]})
        evidence_id = str(uuid.uuid4())
        connection.execute("INSERT INTO learning_evidence VALUES(?,?,?,?,?,?,?,?)", (evidence_id, session_id,
            session["student_id"], session["question_id"], body.answer, body.explanation, json.dumps(result, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat()))
        connection.execute("UPDATE sessions SET attempts=? WHERE id=?", (attempt, session_id))
        if result["answer_status"] in ("CORRECT", "INCORRECT"):
            concept_id = result["concept_ids"][0]
            old = connection.execute("SELECT mastery FROM student_concept_state WHERE student_id=? AND concept_id=?",
                (session["student_id"], concept_id)).fetchone()
            value = old[0] if old else 0.5
            updated = round(min(1.0, max(0.0, value + (0.18 if result["answer_status"] == "CORRECT" else -0.12))), 3)
            connection.execute("INSERT INTO student_concept_state VALUES(?,?,?) ON CONFLICT(student_id,concept_id) DO UPDATE SET mastery=excluded.mastery",
                (session["student_id"], concept_id, updated))
        for mid in result["misconception_ids"]:
            old = connection.execute("SELECT risk FROM student_misconception_state WHERE student_id=? AND misconception_id=?",
                (session["student_id"], mid)).fetchone()
            risk = round(min(1.0, (old[0] if old else 0.0) + 0.25), 3)
            connection.execute("INSERT INTO student_misconception_state VALUES(?,?,?) ON CONFLICT(student_id,misconception_id) DO UPDATE SET risk=excluded.risk",
                (session["student_id"], mid, risk))
        after_state = profile(connection, session["student_id"])
        concept_id = result["concept_ids"][0]
        recorder.append_event(trace_id, EventType.STUDENT_STATE_UPDATED,
            output_summary={"concept_id": concept_id,
                            "mastery_before": before_state["mastery"].get(concept_id),
                            "mastery_after": after_state["mastery"].get(concept_id)})
        if result["answer_status"] == "CORRECT" or result["teaching_action"] == "EXPLAIN":
            outcome = "CORRECT_UNDERSTANDING" if result["answer_status"] == "CORRECT" else "UNRESOLVED"
            recorder.append_event(trace_id, EventType.TRACE_COMPLETED,
                output_summary={"outcome": outcome})
            recorder.set_status(trace_id, status="COMPLETED", confidence=result["confidence"],
                                action=result["teaching_action"], outcome=outcome)
        else:
            recorder.set_status(trace_id, status="WAITING_STUDENT", confidence=result["confidence"],
                                action=result["teaching_action"])
        return {"evidence_id": evidence_id, "trace_id": trace_id, "attempt": attempt,
                **result, "profile": after_state}


@app.post("/api/tutor/{session_id}/message")
def message(session_id: str, body: MessageInput): return answer_session(session_id, body)


@app.post("/api/tutor/{session_id}/resume")
def resume(session_id: str, body: MessageInput): return answer_session(session_id, body)


@app.get("/api/student/{student_id}/profile")
def get_profile(student_id: str):
    with db() as connection: return profile(connection, student_id)


@app.get("/api/student/{student_id}/concepts")
def get_concepts(student_id: str):
    with db() as connection: mastery = profile(connection, student_id)["mastery"]
    return [{"id": key, **value, "mastery": mastery.get(key, 0.5)} for key, value in CONCEPTS.items()]


@app.get("/api/student/{student_id}/misconceptions")
def get_misconceptions(student_id: str):
    with db() as connection: p = profile(connection, student_id)
    known = [{"id": key, **value, "risk": p["misconception_risk"].get(key, 0)} for key, value in MISCONCEPTIONS.items()]
    return {"known": known, "diagnoses": p["diagnoses"]}


@app.get("/api/student/{student_id}/evidence")
def get_evidence(student_id: str):
    with db() as connection:
        rows = connection.execute("SELECT * FROM learning_evidence WHERE student_id=? ORDER BY created_at DESC", (student_id,)).fetchall()
        return [{**dict(row), "diagnosis": json.loads(row["diagnosis_json"])} for row in rows]


@app.get("/api/questions/recommend")
def questions_recommend(student_id: str = "demo-student"):
    with db() as connection: return recommend(profile(connection, student_id))


@app.post("/api/documents", dependencies=[Depends(require_admin)])
async def add_document(body: DocumentInput):
    doc_id = str(uuid.uuid4())
    parts = chunks(body.content)
    embedder = get_embedding_provider()
    vectors = None
    if embedder:
        try:
            vectors = await embedder.embed_documents(parts)
        except (httpx.HTTPError, ValueError, RuntimeError) as error:
            raise HTTPException(503, "Embedding 服务不可用，资料未保存") from error
    with db() as connection:
        connection.execute("INSERT INTO documents VALUES(?,?,?)", (doc_id, body.title, body.content))
        for i, vector in enumerate(vectors or []):
            connection.execute("INSERT INTO document_vectors VALUES(?,?)",
                               (f"{doc_id}#{i+1}", json.dumps(vector)))
    return {"id": doc_id, "chunks": len(parts), "embedded": bool(vectors)}


@app.get("/api/course/search")
def search_course(q: str):
    cards = [{"id": key, "title": value["name"], "content": value["summary"], "kind": "concept"}
             for key, value in CONCEPT_BY_ID.items()]
    with db() as connection:
        docs = [{"id": row["id"], "title": row["title"], "content": row["content"]}
                for row in connection.execute("SELECT * FROM documents")]
    return retrieve(q, cards + docs + open_resources(), limit=5)


@app.get("/api/class/{class_id}/dashboard", dependencies=[Depends(require_admin)])
def class_dashboard(class_id: str):
    with db() as connection:
        students = [r[0] for r in connection.execute(
            "SELECT student_id FROM sessions WHERE class_id=? UNION "
            "SELECT student_id FROM chat_sessions WHERE class_id=? UNION "
            "SELECT student_id FROM code_submissions WHERE class_id=?", (class_id, class_id, class_id))]
        return {"class_id": class_id, "student_count": len(students), "students": [profile(connection, s) for s in students]}


@app.get("/api/class/{class_id}/misconceptions", dependencies=[Depends(require_admin)])
def class_misconceptions(class_id: str):
    with db() as connection:
        rows = connection.execute("SELECT d.issue_key AS misconception_id, d.issue_name, d.status, COUNT(*) AS student_count, AVG(d.risk) AS average_risk FROM student_misconception_diagnosis d JOIN (SELECT student_id FROM sessions WHERE class_id=? UNION SELECT student_id FROM chat_sessions WHERE class_id=?) s USING(student_id) GROUP BY d.issue_key,d.issue_name,d.status ORDER BY average_risk DESC", (class_id, class_id)).fetchall()
        old = connection.execute("SELECT m.misconception_id, COUNT(*) AS student_count, AVG(m.risk) AS average_risk FROM student_misconception_state m JOIN (SELECT student_id FROM sessions WHERE class_id=? UNION SELECT student_id FROM chat_sessions WHERE class_id=?) s USING(student_id) GROUP BY m.misconception_id", (class_id, class_id)).fetchall()
        return [dict(row) for row in rows] + [{**dict(row), "issue_name": row["misconception_id"], "status": "LEGACY"} for row in old]


@app.get("/api/class/{class_id}/emerging-issues", dependencies=[Depends(require_admin)])
def emerging_issues(class_id: str):
    with db() as connection:
        rows = connection.execute("SELECT d.issue_key,d.issue_name,COUNT(*) AS student_count,AVG(d.risk) AS average_risk FROM student_misconception_diagnosis d JOIN (SELECT student_id FROM sessions WHERE class_id=? UNION SELECT student_id FROM chat_sessions WHERE class_id=?) s USING(student_id) WHERE d.issue_key LIKE 'OPEN:%' GROUP BY d.issue_key,d.issue_name ORDER BY student_count DESC,average_risk DESC", (class_id, class_id)).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/class/{class_id}/traces", dependencies=[Depends(require_admin)])
def class_traces(class_id: str, limit: int = 30):
    limit = max(1, min(limit, 100))
    with db() as connection:
        rows = connection.execute("SELECT id AS trace_id,student_id,session_id,question_id,status,outcome,"
            "current_confidence,current_action,started_at,completed_at FROM diagnostic_traces WHERE session_id IN "
            "(SELECT id FROM chat_sessions WHERE class_id=? UNION SELECT id FROM sessions WHERE class_id=?) "
            "ORDER BY started_at DESC LIMIT ?", (class_id, class_id, limit)).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/trace/{trace_id}", dependencies=[Depends(require_admin)])
def diagnostic_trace_detail(trace_id: str):
    with db() as connection:
        trace = DiagnosticTraceRecorder(connection).get_trace(trace_id)
        if not trace:
            raise HTTPException(404, "Unknown diagnostic trace")
        return trace


STATIC = Path(__file__).resolve().parent.parent / "web"
if STATIC.exists(): app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
