import asyncio
import json
from pathlib import Path

from app.diagnostic_pipeline import CONCEPTS, MISCONCEPTIONS
from benchmark.evaluate import evaluate, score


def test_curriculum_catalog_integrity():
    concept_ids = [item["id"] for item in CONCEPTS]
    issue_ids = [item["id"] for item in MISCONCEPTIONS]
    assert len(concept_ids) >= 50 and len(set(concept_ids)) == len(concept_ids)
    assert len(issue_ids) >= 40 and len(set(issue_ids)) == len(issue_ids)
    assert all(set(item["concept_ids"]) <= set(concept_ids) for item in MISCONCEPTIONS)
    assert all(item.get("summary") for item in CONCEPTS)
    assert all(item.get("wrong_belief") and item.get("correct_model") for item in MISCONCEPTIONS)


def test_demo_benchmark_stays_labeled_and_saves_real_predictions():
    path = Path(__file__).resolve().parent.parent / "benchmark" / "demo_seed.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    report = asyncio.run(evaluate(cases, "mock"))
    assert report["dataset_label"] == "DEMO"
    assert report["metrics"]["case_count"] == 4
    assert all("prediction" in row and "case" in row for row in report["rows"])
    assert 0 <= report["metrics"]["evidence_grounding_rate"] <= 1
    assert score(report["rows"])["case_count"] == 4
