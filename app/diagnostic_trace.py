"""Structured and auditable diagnostic events, without model private reasoning."""
from datetime import datetime, timezone
from enum import Enum
import json
import uuid
from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
POLICY_VERSION = "evidence-gate-v1"
PROMPT_VERSION = "diagnosis-v1"
TAXONOMY_VERSION = "2026-09-27"


class EventType(str, Enum):
    STUDENT_INPUT = "STUDENT_INPUT"
    CONCEPT_MAPPING = "CONCEPT_MAPPING"
    EVIDENCE_EXTRACTED = "EVIDENCE_EXTRACTED"
    HYPOTHESIS_CREATED = "HYPOTHESIS_CREATED"
    OPEN_SET_ISSUE_FOUND = "OPEN_SET_ISSUE_FOUND"
    TOOL_REQUESTED = "TOOL_REQUESTED"
    TOOL_RESULT = "TOOL_RESULT"
    TRACE_COMPARISON = "TRACE_COMPARISON"
    CONFIDENCE_EVALUATED = "CONFIDENCE_EVALUATED"
    TEACHING_ACTION_SELECTED = "TEACHING_ACTION_SELECTED"
    PROBE_SENT = "PROBE_SENT"
    STUDENT_RESPONSE_RECEIVED = "STUDENT_RESPONSE_RECEIVED"
    RE_DIAGNOSIS = "RE_DIAGNOSIS"
    DIAGNOSIS_CONFIRMED = "DIAGNOSIS_CONFIRMED"
    DIAGNOSIS_REJECTED = "DIAGNOSIS_REJECTED"
    STUDENT_STATE_UPDATED = "STUDENT_STATE_UPDATED"
    TRACE_COMPLETED = "TRACE_COMPLETED"
    ERROR = "ERROR"


class DiagnosticTrace(BaseModel):
    trace_id: str
    student_id: str
    session_id: str
    question_id: str | None = None
    status: str = "ACTIVE"
    outcome: str = "UNRESOLVED"
    current_confidence: float = Field(default=0, ge=0, le=1)
    current_teaching_action: str | None = None
    started_at: str
    completed_at: str | None = None
    versions: dict[str, str]


class DiagnosticTraceEvent(BaseModel):
    event_id: str
    trace_id: str
    sequence: int
    timestamp: str
    event_type: EventType
    input_summary: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    hypothesis_updates: list[dict] = Field(default_factory=list)
    action: str | None = None
    confidence_before: float | None = None
    confidence_after: float | None = None


class DiagnosticEvidence(BaseModel):
    evidence_id: str
    trace_id: str
    source_type: str
    source_turn: int
    quote: str
    concept_ids: list[str] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    strength: float = Field(ge=0, le=1)
    created_at: str


class DiagnosticHypothesis(BaseModel):
    hypothesis_id: str
    trace_id: str
    misconception_id: str | None = None
    candidate_name: str
    hypothesis_type: str
    status: str
    concept_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False)
    if len(data) > 12000:
        raise ValueError("Trace event summary exceeds limit")
    for forbidden in ("api_key", "authorization", "system_prompt", "chain_of_thought"):
        if forbidden in data.lower():
            raise ValueError("Trace summary contains a forbidden field")
    return data


class DiagnosticTraceRecorder:
    """All methods participate in the caller's SQLite transaction."""

    def __init__(self, connection):
        self.db = connection

    def create_trace(self, student_id: str, session_id: str, question_id: str | None = None) -> str:
        trace_id = str(uuid.uuid4())
        versions = {"trace_schema": SCHEMA_VERSION, "policy": POLICY_VERSION,
                    "diagnostician_prompt": PROMPT_VERSION, "taxonomy": TAXONOMY_VERSION}
        self.db.execute("INSERT INTO diagnostic_traces VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (trace_id, student_id, session_id, question_id, "ACTIVE", "UNRESOLVED", 0.0, None,
             now(), None, _json(versions)))
        return trace_id

    def append_event(self, trace_id: str, event_type: EventType, *, input_summary=None,
                     output_summary=None, evidence_ids=None, hypothesis_updates=None, action=None,
                     confidence_before=None, confidence_after=None) -> str:
        if not self.db.execute("SELECT 1 FROM diagnostic_traces WHERE id=?", (trace_id,)).fetchone():
            raise ValueError("Unknown diagnostic trace")
        sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM diagnostic_events WHERE trace_id=?",
            (trace_id,)).fetchone()[0]
        event_id = str(uuid.uuid4())
        self.db.execute("INSERT INTO diagnostic_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, trace_id, sequence, event_type.value, now(), _json(input_summary or {}),
             _json(output_summary or {}), _json(evidence_ids or []), _json(hypothesis_updates or []),
             action, confidence_before, confidence_after))
        return event_id

    def add_evidence(self, trace_id: str, *, source_type: str, source_turn: int, quote: str,
                     concept_ids=None, supports=None, contradicts=None, strength=0.5) -> str:
        evidence_id = str(uuid.uuid4())
        self.db.execute("INSERT INTO diagnostic_evidence VALUES(?,?,?,?,?,?,?,?,?,?)",
            (evidence_id, trace_id, source_type, source_turn, quote[:2000], _json(concept_ids or []),
             _json(supports or []), _json(contradicts or []), float(strength), now()))
        return evidence_id

    def create_hypothesis(self, trace_id: str, *, misconception_id: str | None, candidate_name: str,
                          hypothesis_type: str, concept_ids: list[str], confidence: float,
                          evidence_ids: list[str]) -> str:
        hypothesis_id = str(uuid.uuid4())
        stamp = now()
        self.db.execute("INSERT INTO diagnostic_hypotheses VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (hypothesis_id, trace_id, misconception_id, candidate_name[:200], hypothesis_type,
             "SUSPECTED", _json(concept_ids), float(confidence), _json(evidence_ids), "[]", stamp, stamp))
        return hypothesis_id

    def update_hypothesis(self, hypothesis_id: str, *, status: str, confidence: float,
                          added_evidence_id: str | None, supports: bool):
        row = self.db.execute("SELECT * FROM diagnostic_hypotheses WHERE id=?", (hypothesis_id,)).fetchone()
        if not row:
            raise ValueError("Unknown diagnostic hypothesis")
        field = "supporting_evidence_ids_json" if supports else "contradicting_evidence_ids_json"
        ids = json.loads(row[field])
        if added_evidence_id:
            ids.append(added_evidence_id)
        self.db.execute(f"UPDATE diagnostic_hypotheses SET status=?,confidence=?,{field}=?,updated_at=? WHERE id=?",
            (status, float(confidence), _json(ids), now(), hypothesis_id))

    def set_status(self, trace_id: str, *, status: str, confidence: float, action: str | None = None,
                   outcome: str | None = None):
        completed_at = now() if status in ("COMPLETED", "ABORTED", "ERROR") else None
        self.db.execute("UPDATE diagnostic_traces SET status=?,current_confidence=?,current_action=?,"
                        "outcome=COALESCE(?,outcome),completed_at=? WHERE id=?",
                        (status, float(confidence), action, outcome, completed_at, trace_id))

    def get_trace(self, trace_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM diagnostic_traces WHERE id=?", (trace_id,)).fetchone()
        if not row:
            return None
        trace = dict(row)
        trace["versions"] = json.loads(trace.pop("versions_json"))
        trace["trace_id"] = trace.pop("id")
        trace["current_teaching_action"] = trace.pop("current_action")
        events = []
        for item in self.db.execute("SELECT * FROM diagnostic_events WHERE trace_id=? ORDER BY sequence", (trace_id,)):
            event = dict(item)
            event["input_summary"] = json.loads(event.pop("input_json"))
            event["output_summary"] = json.loads(event.pop("output_json"))
            event["evidence_ids"] = json.loads(event.pop("evidence_ids_json"))
            event["hypothesis_updates"] = json.loads(event.pop("hypothesis_updates_json"))
            event["event_id"] = event.pop("id")
            events.append(event)
        trace["events"] = events
        trace["evidence"] = []
        for item in self.db.execute("SELECT * FROM diagnostic_evidence WHERE trace_id=?", (trace_id,)):
            evidence = dict(item)
            evidence["evidence_id"] = evidence.pop("id")
            evidence["concept_ids"] = json.loads(evidence.pop("concept_ids_json"))
            evidence["supports"] = json.loads(evidence.pop("supports_json"))
            evidence["contradicts"] = json.loads(evidence.pop("contradicts_json"))
            trace["evidence"].append(evidence)
        trace["hypotheses"] = []
        for item in self.db.execute("SELECT * FROM diagnostic_hypotheses WHERE trace_id=?", (trace_id,)):
            hypothesis = dict(item)
            hypothesis["hypothesis_id"] = hypothesis.pop("id")
            hypothesis["concept_ids"] = json.loads(hypothesis.pop("concept_ids_json"))
            hypothesis["supporting_evidence_ids"] = json.loads(hypothesis.pop("supporting_evidence_ids_json"))
            hypothesis["contradicting_evidence_ids"] = json.loads(hypothesis.pop("contradicting_evidence_ids_json"))
            trace["hypotheses"].append(hypothesis)
        return trace


def record_initial(recorder: DiagnosticTraceRecorder, *, student_id: str, session_id: str,
                   student_text: str, analysis: dict) -> tuple[str, list[str]]:
    """Record only validated quotes and structured decisions from the first turn."""
    trace_id = recorder.create_trace(student_id, session_id,
        analysis["question"]["id"] if analysis.get("question") else None)
    recorder.append_event(trace_id, EventType.STUDENT_INPUT,
        input_summary={"turn": 1, "character_count": len(student_text)})
    concepts = analysis["concepts"]
    recorder.append_event(trace_id, EventType.CONCEPT_MAPPING,
        output_summary={"concepts": concepts})
    evidence_ids = []
    for item in analysis["evidence"]:
        quote = item.get("quote", "")
        if quote and quote in student_text:
            supporting = [h["misconception_id"] for h in analysis["hypotheses"]
                          if h.get("misconception_id") and quote in h.get("evidence_quotes", [])]
            evidence_ids.append(recorder.add_evidence(trace_id, source_type="STUDENT_ANSWER",
                source_turn=1, quote=quote, concept_ids=[c["id"] for c in concepts],
                supports=supporting, strength=0.6))
    recorder.append_event(trace_id, EventType.EVIDENCE_EXTRACTED,
        output_summary={"count": len(evidence_ids)}, evidence_ids=evidence_ids)
    hypothesis_ids = []
    for item in analysis["hypotheses"]:
        own_evidence = [eid for eid, evidence in zip(evidence_ids, analysis["evidence"])
                        if evidence.get("quote") in item.get("evidence_quotes", [])]
        hypothesis_ids.append(recorder.create_hypothesis(trace_id,
            misconception_id=item.get("misconception_id"), candidate_name=item.get("candidate_name", ""),
            hypothesis_type=item.get("issue_type", "UNKNOWN").upper(),
            concept_ids=item.get("related_concepts", []), confidence=item["confidence"],
            evidence_ids=own_evidence))
        if not item.get("misconception_id"):
            recorder.append_event(trace_id, EventType.OPEN_SET_ISSUE_FOUND,
                output_summary={"candidate_name": item.get("candidate_name", "")},
                hypothesis_updates=[{"hypothesis_id": hypothesis_ids[-1], "status": "SUSPECTED"}])
    recorder.append_event(trace_id, EventType.HYPOTHESIS_CREATED,
        hypothesis_updates=[{"hypothesis_id": hid, "confidence": h["confidence"]}
                            for hid, h in zip(hypothesis_ids, analysis["hypotheses"])])
    confidence = max((item["confidence"] for item in analysis["hypotheses"]), default=0)
    recorder.append_event(trace_id, EventType.CONFIDENCE_EVALUATED,
        output_summary={"confidence": confidence, "gate": analysis["gate"],
                        "probe_threshold": 0.5, "verify_threshold": 0.8})
    question = analysis.get("question")
    action = "PROBE" if question else "COLLECT_MORE_EVIDENCE"
    recorder.append_event(trace_id, EventType.TEACHING_ACTION_SELECTED, action=action,
        output_summary={"selected_by": "HYBRID", "evidence_count": len(evidence_ids),
                        "question_id": question["id"] if question else None})
    if question:
        recorder.append_event(trace_id, EventType.PROBE_SENT, action="PROBE",
            output_summary={"question_id": question["id"], "question": question["question"]})
        recorder.set_status(trace_id, status="WAITING_STUDENT", confidence=confidence, action="PROBE")
    else:
        recorder.append_event(trace_id, EventType.TRACE_COMPLETED,
            output_summary={"outcome": "UNRESOLVED", "reason_code": "INSUFFICIENT_EVIDENCE"})
        recorder.set_status(trace_id, status="COMPLETED", confidence=confidence,
                            action=action, outcome="UNRESOLVED")
    return trace_id, hypothesis_ids


def record_verification(recorder: DiagnosticTraceRecorder, *, trace_id: str, student_text: str,
                        question: dict, verification: dict, hypotheses: list[dict],
                        hypothesis_ids: list[str]) -> tuple[str, float]:
    recorder.append_event(trace_id, EventType.STUDENT_RESPONSE_RECEIVED,
        input_summary={"turn": 2, "character_count": len(student_text), "question_id": question["id"]})
    quote = verification.get("evidence_quote", "")
    evidence_id = None
    if quote and quote in student_text:
        targets = [item["misconception_id"] for item in hypotheses if item.get("misconception_id")]
        evidence_id = recorder.add_evidence(trace_id, source_type="VERIFY_RESPONSE", source_turn=2,
            quote=quote, concept_ids=question.get("concept_ids", []),
            supports=targets if verification["outcome"] == "GAP" else [],
            contradicts=targets if verification["outcome"] == "MASTERED" else [],
            strength=verification.get("confidence", 0))
    recorder.append_event(trace_id, EventType.RE_DIAGNOSIS,
        output_summary={"outcome": verification["outcome"], "confidence": verification["confidence"],
                        "reason_code": "PROBE_CONFIRMED" if verification["outcome"] == "GAP" else
                                       "PROBE_CONTRADICTED" if verification["outcome"] == "MASTERED" else "INSUFFICIENT_EVIDENCE"},
        evidence_ids=[evidence_id] if evidence_id else [])
    targets = set(question.get("diagnostic_targets", []))
    target_indices = [index for index, item in enumerate(hypotheses)
                      if item.get("misconception_id") in targets] if targets else ([0] if hypotheses else [])
    if verification["outcome"] in ("GAP", "MASTERED"):
        for index in target_indices:
            item = hypotheses[index]
            before = item["confidence"]
            after = max(before, verification["confidence"]) if verification["outcome"] == "GAP" else min(before, 1-verification["confidence"])
            status = "CONFIRMED" if verification["outcome"] == "GAP" else "REJECTED"
            recorder.update_hypothesis(hypothesis_ids[index], status=status, confidence=after,
                                       added_evidence_id=evidence_id, supports=verification["outcome"] == "GAP")
            recorder.append_event(trace_id, EventType.DIAGNOSIS_CONFIRMED if status == "CONFIRMED" else EventType.DIAGNOSIS_REJECTED,
                hypothesis_updates=[{"hypothesis_id": hypothesis_ids[index], "status": status,
                                     "reason_code": "PROBE_CONFIRMED" if status == "CONFIRMED" else "PROBE_CONTRADICTED"}],
                confidence_before=before, confidence_after=after,
                evidence_ids=[evidence_id] if evidence_id else [])
    outcome = ("MISCONCEPTION_CONFIRMED" if target_indices else "KNOWLEDGE_GAP") if verification["outcome"] == "GAP" else (
        "MISCONCEPTION_REJECTED" if target_indices else "CORRECT_UNDERSTANDING") if verification["outcome"] == "MASTERED" else "UNRESOLVED"
    confidence = max((row[0] for row in recorder.db.execute(
        "SELECT confidence FROM diagnostic_hypotheses WHERE trace_id=?", (trace_id,))), default=0)
    return outcome, confidence
