from experiments.analyze import analyze


def test_empty_template_does_not_create_fake_results():
    from pathlib import Path
    template = Path(__file__).resolve().parent.parent / "experiments/pre_post_template.csv"
    assert analyze(template) == {}


def test_paired_scores_are_descriptive_only(tmp_path):
    path = tmp_path / "actual.csv"
    path.write_text("anonymous_student_id,group,pre_score,post_score,assessment_version,date\n"
                    "p1,Agent,40,60,v1,2026-09-28\n"
                    "p2,Agent,50,70,v1,2026-09-28\n", encoding="utf-8")
    assert analyze(path)["Agent"] == {"paired_count": 2, "pre_mean": 45,
                                      "post_mean": 65, "mean_change": 20}
