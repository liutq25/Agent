# 教学试用资料模板

本目录只有空白模板，不含真实学生、教师或实验结果。正式试用前应由课程负责人确定知情同意、分组方式、题目难度、数据保留周期和审核流程。记录使用匿名编号，身份对应表不得放入项目仓库。

- `pre_post_template.csv`：同一学生的前测与后测分数。
- `teacher_review_template.csv`：教师对诊断证据、首错和干预建议的审核。
- `student_survey_template.csv`：学生对回答清晰度和提示帮助程度的反馈。
- `analyze.py`：只对实际填写且配对的前后测行计算描述性变化；不产生因果结论。

运行：`python -m experiments.analyze experiments/pre_post_template.csv`。空模板会明确报告无数据。
