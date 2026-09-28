"""Descriptive paired pre/post summary; requires actual collected scores."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def analyze(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    groups = {}
    for row in rows:
        if not row.get("anonymous_student_id") or not row.get("pre_score") or not row.get("post_score"):
            continue
        pre, post = float(row["pre_score"]), float(row["post_score"])
        if not 0 <= pre <= 100 or not 0 <= post <= 100:
            raise ValueError("分数必须介于 0 与 100")
        groups.setdefault(row.get("group") or "unassigned", []).append((pre, post))
    return {name: {"paired_count": len(pairs),
                   "pre_mean": round(mean(pre for pre, _ in pairs), 2),
                   "post_mean": round(mean(post for _, post in pairs), 2),
                   "mean_change": round(mean(post - pre for pre, post in pairs), 2)}
            for name, pairs in groups.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    result = analyze(args.csv_path)
    print(json.dumps(result if result else {"status": "NO_REAL_DATA"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
