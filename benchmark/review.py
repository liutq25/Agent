"""Generate review candidates and validate a genuinely reviewed benchmark."""
import argparse
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def candidate_rows() -> list[dict]:
    catalog = yaml.safe_load((ROOT / "data/data_structures/misconceptions.yaml").read_text(encoding="utf-8"))
    return [{"case_id": "DRAFT-" + item["id"], "label": "REVIEW_REQUIRED",
             "question": "请判断下面的说法是否正确，并解释理由。",
             "student_answer": item["wrong_belief"], "student_explanation": "",
             "gold_concepts": item["concept_ids"], "gold_misconceptions": [item["id"]],
             "gold_answer_status": "", "reviewer": "", "reviewed_at": "",
             "review_notes": "请教师核对真实学生表达、概念标注、误区及无证据样本。"}
            for item in catalog]


def validate_formal(rows: list[dict], *, minimum: int = 120) -> list[str]:
    problems = []
    if len(rows) < minimum:
        problems.append(f"正式评测至少需要 {minimum} 条，当前 {len(rows)} 条")
    seen = set()
    for index, row in enumerate(rows, 1):
        cid = row.get("case_id")
        if not cid or cid in seen:
            problems.append(f"第 {index} 条缺少唯一 case_id")
        seen.add(cid)
        if row.get("label") != "TEACHER_REVIEWED":
            problems.append(f"第 {index} 条尚未标记 TEACHER_REVIEWED")
        if not row.get("reviewer") or not row.get("reviewed_at"):
            problems.append(f"第 {index} 条缺少审核人或审核日期")
        if not row.get("question") or not row.get("student_answer"):
            problems.append(f"第 {index} 条缺少题目或学生回答")
        if not isinstance(row.get("gold_concepts"), list) or not isinstance(row.get("gold_misconceptions"), list):
            problems.append(f"第 {index} 条金标准标签必须是列表")
        if row.get("gold_answer_status") not in {"CORRECT", "INCORRECT", "PARTIAL", "INSUFFICIENT_EVIDENCE"}:
            problems.append(f"第 {index} 条缺少有效答案状态")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["draft", "validate"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "draft":
        if args.path.exists():
            parser.error("草案文件已存在，拒绝覆盖教师修改")
        args.path.parent.mkdir(parents=True, exist_ok=True)
        rows = candidate_rows()
        args.path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
        print(f"已写入 {len(rows)} 条待审核候选：{args.path}")
    else:
        rows = [json.loads(line) for line in args.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        issues = validate_formal(rows)
        if issues:
            print("\n".join(issues[:30]))
            raise SystemExit(1)
        print(f"正式评测集校验通过：{len(rows)} 条")


if __name__ == "__main__":
    main()
