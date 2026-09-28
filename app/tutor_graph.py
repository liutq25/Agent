"""Persistent LangGraph lifecycle for a diagnostic probe.

The conversational answer and diagnosis remain in the tutor service; this
graph owns the explicit wait/resume boundary for a student verification turn.
"""
import os
from pathlib import Path
from typing import TypedDict, Any

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt


class TutorState(TypedDict, total=False):
    thread_id: str
    session_id: str
    student_id: str
    mode: str
    question_id: str | None
    question_text: str | None
    task_type: str | None
    reference_answer: str | None
    student_answer: str | None
    student_explanation: str | None
    student_trace: list | None
    conversation_history: list
    retrieved_concepts: list
    retrieved_materials: list
    answer_status: str | None
    concept_ids: list[str]
    misconception_candidates: list
    confirmed_misconceptions: list
    prerequisite_gaps: list
    evidence_spans: list
    first_divergence_step: dict | None
    diagnosis_confidence: float
    teaching_action: str | None
    hint_level: int
    attempt_count: int
    student_profile: dict
    tool_requests: list
    tool_results: list
    recommended_next_concepts: list
    final_response: str | None
    errors: list


def _await_student(state: TutorState) -> dict[str, Any]:
    reply = interrupt({"question_id": state.get("question_id"),
                       "question": state.get("question_text"),
                       "concept_ids": state.get("concept_ids", [])})
    if not isinstance(reply, dict):
        raise ValueError("恢复诊断时必须提交结构化回答")
    if reply.get("cancelled"):
        return {"mode": "CANCELLED", "teaching_action": "STUDENT_CHANGED_TOPIC"}
    return {"mode": "VERIFIED", "student_answer": str(reply.get("answer", "")),
            "answer_status": reply.get("outcome"), "diagnosis_confidence": float(reply.get("confidence", 0)),
            "teaching_action": "EXPLAIN" if reply.get("outcome") == "GAP" else "VERIFY"}


def _compiled(checkpointer):
    graph = StateGraph(TutorState)
    graph.add_node("await_student", _await_student)
    graph.add_edge(START, "await_student")
    graph.add_edge("await_student", END)
    return graph.compile(checkpointer=checkpointer)


def _path() -> Path:
    return Path(os.getenv("COGNITUTOR_GRAPH_DB", str(Path(__file__).resolve().parent.parent / "data" / "tutor_graph.db")))


def begin_probe(session_id: str, student_id: str, question: dict, *, path: Path | None = None) -> dict:
    path = path or _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(path)) as saver:
        graph = _compiled(saver)
        result = graph.invoke({"thread_id": session_id, "session_id": session_id,
            "student_id": student_id, "mode": "WAITING_STUDENT", "question_id": question.get("id"),
            "question_text": question["question"], "concept_ids": question.get("concept_ids", []),
            "teaching_action": "PROBE", "attempt_count": 0},
            {"configurable": {"thread_id": session_id}})
        return {"waiting": bool(result.get("__interrupt__")), "question_id": question.get("id")}


def finish_probe(session_id: str, *, answer: str = "", outcome: str | None = None,
                 confidence: float = 0, cancelled: bool = False,
                 path: Path | None = None) -> TutorState | None:
    path = path or _path()
    if not path.exists():
        return None
    with SqliteSaver.from_conn_string(str(path)) as saver:
        graph = _compiled(saver)
        config = {"configurable": {"thread_id": session_id}}
        state = graph.get_state(config)
        if not state.next:
            return None
        return graph.invoke(Command(resume={"answer": answer, "outcome": outcome,
            "confidence": confidence, "cancelled": cancelled}), config)
