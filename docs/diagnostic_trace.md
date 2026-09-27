# Diagnostic Trace 设计与当前实现

`diagnostic_trace` 保存**可观察的学习证据和系统决策**。它不保存模型隐藏思维链、完整系统提示词或 API Key。每个 Trace 对应一轮“观察 → 可选追问 → 核验 → 状态更新”的诊断周期；完整记录在 SQLite 中，当前会话状态只保存 `trace_id` 与待核验题。

## 数据结构

- `diagnostic_traces`：学生、会话、状态、结果、当前置信度、版本信息。
- `diagnostic_events`：按序号记录知识点映射、证据抽取、假设、置信度门槛、教学动作、追问、复诊和状态更新。
- `diagnostic_evidence`：学生原文片段、来源轮次、关联概念，以及支持或反驳的误区 ID。
- `diagnostic_hypotheses`：已知或目录外假设、状态、置信度及支持/反驳证据 ID。

所有写入经 `DiagnosticTraceRecorder` 完成，避免在各诊断步骤散落 SQL。`GET /api/trace/{trace_id}` 返回完整轨迹；`GET /api/class/{class_id}/traces` 列出班级轨迹。教师页面提供证据、假设和决策时间线；学生页面只展示高层诊断反馈。

## 当前边界

每次新发言若没有足够证据，会形成 `COMPLETED + UNRESOLVED` 轨迹。若发出诊断题，轨迹进入 `WAITING_STUDENT`；学生作答后完成同一轨迹。已有专项练习的确定性算法工具也记录 `TOOL_REQUESTED`、`TOOL_RESULT`、`TRACE_COMPARISON` 和首次偏差。

Trace 置信度沿用诊断模型给出的**工程分数**，尚未按教师标注数据校准，不能当成统计概率。当前教师端尚无身份认证，项目只能用于本机演示；正式部署前必须加入权限隔离，否则不能展示真实学生数据。已有历史记录不会自动回填完整 Trace。

`trace_schema=1.0`，并记录诊断提示、教学策略和误区目录版本，以便未来评测。当前还没有 LangGraph；若后续接入，节点应调用同一个 Recorder 写事件，不能把完整历史塞进 Graph State。
