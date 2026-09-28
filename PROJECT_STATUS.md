# CogniTutor-DS Project Status

## Current Milestone

以对话为主入口、采用分阶段动态诊断与确定性算法首错定位的原型；未达到执行文档的最终验收标准。逐项差距见 `docs/execution_gap_matrix.md`。

## Completed

比赛公开资料检索；两候选上游许可与运行依赖检查；FastAPI/SQLite API；自由对话和主动核验；分阶段概念映射、证据抽取、已知与目录外假设、置信度门槛、核验及 Beta 证据状态；结构化 Diagnostic Trace、证据/假设关联、教师时间线；22 个确定性算法工具；编程求助完整代码输出限制及三级提示；两个 Python 练习的 Docker 隔离运行接口；教师端活动、资料上传、诊断题草稿审核和可选管理口令；课程资料分片检索、5 条带来源的公开资源摘要、独立可选 Embedding 接口；核验题 LangGraph interrupt/SQLite 检查点；待审核 Benchmark 候选与正式审核门槛；GUI 模型设置、OpenAI-compatible/Anthropic/Gemini 三协议适配器；Windows 一键启动入口。

## In Progress

将剩余教学节点迁入 LangGraph；扩大可视化算法输入和练习覆盖；准备教师审核数据与真实课堂试用。

## Next

1. 由教师审核 52 个概念、46 个误区的工程草案，补齐来源和有区分力的诊断题。
2. 将回答、工具、检索、诊断及持久化的完整教学流程迁入 LangGraph；扩展所有工具的网页输入表单。
3. 用真实 Embedding API 验收向量检索，完成独立 Judge 接口及严格的来源评价。
4. 收集至少 120 条教师审核案例，开展四组消融、学生身份和班级权限控制及真实教学验证。

## Known Issues

首选上游 README 声明 MIT，但仓库没有 LICENSE 文件；不可据此复制其源码。当前项目为独立实现，尚未做生产安全加固。本机没有 Docker，容器运行路径已做自动化模拟检查，尚未完成真实容器执行验收；无 Docker 时学生代码不会在本机运行。代码练习仅支持两个固定 Python 函数。教师口令只保护管理接口，学生身份及班级权限尚未建立，不可直接公开部署存储真实学生数据。

## Test Status

`python -m pytest -q`：覆盖原有对话、诊断、工具、沙箱模拟与设置，以及课程资料检索、管理口令、LangGraph 检查点恢复、评测审核门槛。已使用本机配置的 DeepSeek V4 Pro 实测错误前提纠正与主动核验；本轮新增 Embedding 路径尚未使用真实服务验收。`benchmark/demo_seed.jsonl` 仅含 4 条 DEMO 案例，不是正式评测集。真实容器测试与教师标注集验证尚未完成。

## Run Commands

`python -m pip install -r requirements.txt -i https://pypi.org/simple`；`python -m uvicorn app.main:app --reload`；`python -m pytest -q`。

## Architecture Decisions

首选仓库许可文件缺失，第二仓库外部依赖多，因此采用独立实现；教学决策先由确定性规则支撑，模型调用隔离在 Provider 层，学习证据和画像存于 SQLite。

## External Dependencies

FastAPI、Uvicorn、HTTPX、Pytest、LangGraph 与 SQLite checkpointer；模型 API 需要用户自行提供密钥；运行学生 Python 代码需要 Docker Linux 容器和预先准备的 `python:3.12-alpine` 镜像。

## Required Human Input

真实模型 API Key、教师课程资料及经授权的真实学生数据；后续教学实验还需学校或课程负责人安排。
