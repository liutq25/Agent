# 知学 CogniTutor-DS

面向《数据结构》课程的对话式教学智能体原型。学生可以像使用通用聊天助手一样直接提问或追问；配置模型 API 后，系统先充分回答概念和原理问题，再评估学生原话中是否存在可核验的错误或薄弱线索。普通提问不会自动触发测验；若问题含明显错误前提，系统会纠正事实，并把该前提作为待核验线索，追问判断依据和一题具体情境题。对编程任务，系统解释原理与错误原因，但限制直接输出完整可提交代码，并按“反问—反例—线索”递进提示。学生可以在“代码排错”页提交自己的 Python 函数；隔离运行环境就绪时，系统执行固定测试用例，展示首个失败点并保存排错过程供教师查看。学生随时可以改问新问题。分层诊断设计见 `docs/diagnosis_architecture.md`。

## 本地运行

要求 Python 3.11+。在项目根目录运行：

```powershell
python -m pip install -r requirements.txt -i https://pypi.org/simple
python -m uvicorn app.main:app --reload
```

访问 http://127.0.0.1:8000/。API 文档在 http://127.0.0.1:8000/docs。默认 Mock 模式，无需 API Key；SQLite 自动建表，数据保存到 `data/cognitutor.db`。

Windows 简便入口：双击项目中的 `启动知学.cmd`，或运行 `powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1` 生成桌面快捷方式后双击图标。入口会复用已启动的服务，并自动打开浏览器；服务日志在 `data/server.log`。首次使用仍需安装上面的 Python 依赖。

运行测试：`python -m pytest -q`。

## 模型配置

打开桌面入口后进入“模型设置”，选择协议、填写模型名称、接口地址及 API Key，先点“测试连接”，再点“保存设置”。OpenAI 兼容协议提供 Qwen、DeepSeek、OpenAI 地址预设，也允许自定义。保存后下一条对话立即生效，无须重启。另支持 Anthropic Messages 和 Gemini `generateContent`。API Key 保存在 Windows 凭据保管库；`data/model_settings.json` 只保存协议、模型与地址，页面不会回显密钥。测试连接会向服务发送一个短请求，可能产生少量模型费用。接口细节见 `docs/model_protocols.md`。

旧的 `.env` 方式仍可使用；一旦在 GUI 保存设置，GUI 设置优先。`.env` 已被 Git 忽略，请勿分享给他人。本机已用所配置的 DeepSeek V4 Pro 验证普通问答与错误说法诊断；模型质量仍需教师标注评估。

## 代码排错的运行环境

“代码排错”目前提供两个 Python 练习：二分查找和括号匹配。运行学生代码需要 Docker Linux 容器以及预先下载的 `python:3.12-alpine` 镜像，可在 Docker 可用后执行 `docker pull python:3.12-alpine`。服务使用无网络、只读文件系统、资源限制和 8 秒超时运行测试。若 Docker 或镜像缺失，页面会明确提示未运行，不会在本机 Python 进程执行学生代码。此电脑目前尚未安装 Docker，因此真实容器运行仍待现场验收。代码提交、测试结果和提示阶段会写入本地 SQLite；教师端可查看排错活动。当前只支持这两个固定练习，不支持任意代码自由执行或多语言编译。

## 已实现范围

- FastAPI、SQLite、学生端与教师端页面。
- 以自由对话为主的首页；多轮会话、课程知识卡辅助回答、主动核验及证据反馈。
- 人工维护概念、常见误区、诊断题目录；模型动态进行概念映射、证据抽取、开放集假设、追问与复诊。
- GUI 模型设置、连接测试、三种协议适配器和本机凭据保管库密钥存储。
- 核验后按 Beta 证据计数更新长期概念状态；目录外候选单列供教师查看。
- 结构化诊断轨迹：记录证据、假设、置信度变化、教学动作和工具结果；教师端可查看时间线，详见 `docs/diagnostic_trace.md`。
- 顺序表插入、链表插入、栈与队列的固定核验题；栈和队列轨迹的确定性工具与首次偏差比较。
- 追问、两级提示、解释、挑战策略；按学生保存回答、诊断 JSON、掌握度、误区风险。
- 编程对话的完整代码输出限制与“反问—反例—线索”提示阶梯；两个固定 Python 练习的隔离测试入口、失败用例反馈及教师端排错记录。
- 22 个确定性数据结构与算法轨迹工具、学生步骤的首错比较、聊天中的模型工具调用和“算法轨迹”页面。
- 52 个概念与 46 个误区的工程草案目录，以及可运行的评测程序和与正式评测分离的 4 条演示种子。
- 课程知识卡检索、练习推荐、模型状态与文档上传接口。
- 可重复的 Mock 模式及端到端 API 测试。

## 明确未完成

本项目处于可运行原型阶段。目录数量已达 52 个概念、46 个误区，但新扩展内容是**工程草案，尚未由教师审定**；现有固定诊断题仍只有 7 道，目录外问题依靠模型动态生成。22 个首版确定性算法工具已实现。核验题已接入 LangGraph interrupt/SQLite checkpointer；课程资料可分片检索并显示来源，另有可选的 OpenAI 兼容 Embedding 服务（`EMBEDDING_MODEL`、`EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`）。未设置 Embedding 时使用文本检索。公开课程摘要的源链接见 `data/data_structures/open_resources.yaml`。

教师可在“教师概览”录入诊断题 JSON 草稿并审核；只有状态为 `APPROVED` 的题目进入对话选题。自动选题会参考误区、概念掌握证据、已用题和难度。这里的审核人字段是本地操作记录，不能自行证明真实教师审核；正式评测仍要使用独立的人工标注数据。

教师页面、课程资料上传和模型设置接口可使用 `COGNITUTOR_ADMIN_TOKEN` 设置访问口令；未设置时仅适合本机演示。学生 ID 仍不是正式身份认证，不能直接对公网开放或存放真实学生隐私数据。至少 120 条人工审核的正式 Benchmark、完整 LangGraph 教学流程、真实 Embedding 服务验收和课堂实验仍需完成。`benchmark/review_candidates.jsonl` 有 46 条自动生成、明确标为 `REVIEW_REQUIRED` 的候选；`python -m benchmark.review validate benchmark/review_candidates.jsonl` 会拒绝它作为正式评测。`experiments/` 是空白教学试用模板；公开资源不能代替教师审核。

架构与上游选择见 `docs/upstream_evaluation.md`。许可说明见 `THIRD_PARTY_NOTICES.md`。当前状态见 `PROJECT_STATUS.md`。
三项创新点的当前实现与验证边界见 `docs/innovation_alignment.md`。
逐项对照执行文档的差距见 `docs/execution_gap_matrix.md`。演示种子可用 `python -m benchmark.evaluate benchmark/demo_seed.jsonl --mode mock` 运行；输出标记为 DEMO，不可用于对外宣称诊断准确率。
