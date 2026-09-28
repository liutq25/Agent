"""Run diagnostic cases and save raw predictions plus limited factual metrics."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from app.diagnostic_pipeline import analyze_turn
from app.providers import MockProvider, get_provider
from benchmark.review import validate_formal


def _f1(predicted: set[str], expected: set[str]) -> float:
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    overlap = len(predicted & expected)
    return 2 * overlap / (len(predicted) + len(expected))


def score(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("没有可评测案例")
    concept_scores, issue_scores, grounded, false_diagnoses, insufficient = [], [], [], 0, []
    for row in rows:
        case, prediction = row["case"], row["prediction"]
        predicted_concepts = {item["id"] for item in prediction["concepts"]}
        expected_concepts = set(case.get("gold_concepts", []))
        concept_scores.append(_f1(predicted_concepts, expected_concepts))
        predicted_issues = {item["misconception_id"] for item in prediction["hypotheses"]
                            if item.get("misconception_id")}
        expected_issues = set(case.get("gold_misconceptions", []))
        issue_scores.append(_f1(predicted_issues, expected_issues))
        if predicted_issues and not expected_issues:
            false_diagnoses += 1
        text = case.get("student_answer", "") or case.get("question", "")
        grounded.extend(span.get("quote", "") in text for span in prediction["evidence"])
        if case.get("gold_answer_status") == "INSUFFICIENT_EVIDENCE":
            insufficient.append(not bool(prediction["hypotheses"]))
    return {"case_count": len(rows),
            "concept_identification_f1_mean": round(sum(concept_scores) / len(rows), 3),
            "misconception_f1_mean": round(sum(issue_scores) / len(rows), 3),
            "false_diagnosis_rate": round(false_diagnoses / len(rows), 3),
            "evidence_grounding_rate": round(sum(grounded) / len(grounded), 3) if grounded else None,
            "insufficient_evidence_accuracy": round(sum(insufficient) / len(insufficient), 3) if insufficient else None,
            "unmeasured": ["answer_status_macro_f1", "first_divergence_accuracy", "hint_leakage_rate",
                           "tool_selection_accuracy", "teaching_action_agreement"]}


async def evaluate(cases: list[dict], mode: str) -> dict:
    if not cases:
        raise ValueError("没有可评测案例")
    if not all(case.get("label") == "DEMO" for case in cases):
        problems = validate_formal(cases)
        if problems:
            raise ValueError("正式评测集未通过审核校验：" + problems[0])
    provider = MockProvider() if mode == "mock" else get_provider()
    rows = []
    for case in cases:
        text = case.get("student_answer") or case.get("question", "")
        result = await analyze_turn(provider, text)
        rows.append({"case": case, "prediction": result})
    return {"timestamp": datetime.now(timezone.utc).isoformat(),
            "model": getattr(provider, "model", "unknown"), "mode": mode,
            "dataset_label": "DEMO" if all(case.get("label") == "DEMO" for case in cases) else "TEACHER_REVIEWED",
            "metrics": score(rows), "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--mode", choices=["mock", "api"], default="mock")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[:args.limit]
    report = asyncio.run(evaluate(cases, args.mode))
    output_dir = Path(__file__).resolve().parent / "results"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + args.mode + ".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"file": str(path), "dataset_label": report["dataset_label"],
                      "metrics": report["metrics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
