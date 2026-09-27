# CogniTutor-DS Project Status

## Current Milestone

以对话为主入口、采用分阶段动态诊断与确定性算法首错定位的原型；未达到执行文档的最终验收标准。逐项差距见 `docs/execution_gap_matrix.md`。

## Completed

比赛公开资料检索；两候选上游许可与运行依赖检查；独立仓库及分支；FastAPI/SQLite API；自由对话和主动核验；分阶段概念映射、证据抽取、已知与目录外假设、置信度门槛、核验及 Beta 证据状态；结构化 Diagnostic Trace、证据/假设关联、教师时间线；四题旧专项练习；栈和队列轨迹工具；编程求助完整代码输出限制及三级提示；两个 Python 练习的 Docker 隔离运行接口、测试反馈和代码排错记录；教师端提问与排错活动；学生及教师页面；GUI 模型设置、OpenAI-compatible/Anthropic/Gemini 三协议适配器、密钥保管库与连接测试；证据持久化；端到端测试；Windows 一键启动入口与桌面快捷方式脚本。

## In Progress

教师审核课程目录、扩展剩余算法工具、构建正式评测集及可信评估。

## Next

1. 由教师审核 52 个概念、46 个误区的工程草案，补齐来源和有区分力的诊断题。
2. 完成文档首版算法工具清单剩余 9 项，扩大首错定位与可视化覆盖。
3. 引入 LangGraph checkpointer/interrupt、Embedding 检索和独立 Judge 接口。
4. 收集至少 120 条教师审核案例，开展四组消融、权限控制和真实教学验证。

## Known Issues

首选上游 README 声明 MIT，但仓库没有 LICENSE 文件；不可据此复制其源码。第二候选的本地运行需要 Azure/Supabase。当前项目为独立实现，尚未做生产安全加固。本机没有 Docker，容器运行路径已做自动化模拟检查，尚未完成真实容器执行验收；无 Docker 时学生代码不会在本机运行。代码练习仅支持两个固定 Python 函数，教师端目前无正式身份认证。

## Test Status

`python -m pytest -q`：覆盖先回答普通提问、带错误前提的提问追问、不强制测验、错误说法后的主动核验、学生改问时中断核验、自述薄弱点与已证实错误的区分、跨轮薄弱点汇总、22 个确定性算法工具、首错比较、聊天工具调用、编程回答代码限制、代码测试与三级提示、教师排错记录、Docker 启动参数模拟、模型协议及密钥遮蔽。已使用本机配置的 DeepSeek V4 Pro 实测错误前提纠正与主动核验。`benchmark/demo_seed.jsonl` 仅含 4 条 DEMO 案例，不是正式评测集。真实容器测试与教师标注集验证尚未完成。

## Run Commands

`python -m pip install -r requirements.txt -i https://pypi.org/simple`；`python -m uvicorn app.main:app --reload`；`python -m pytest -q`。

## Architecture Decisions

首选仓库许可文件缺失，第二仓库外部依赖多，因此采用独立实现；教学决策先由确定性规则支撑，模型调用隔离在 Provider 层，学习证据和画像存于 SQLite。

## External Dependencies

FastAPI、Uvicorn、HTTPX、Pytest；模型 API 需要用户自行提供密钥；运行学生 Python 代码需要 Docker Linux 容器和预先准备的 `python:3.12-alpine` 镜像。

## Required Human Input

真实模型 API Key、教师课程资料及经授权的真实学生数据；后续教学实验还需学校或课程负责人安排。
