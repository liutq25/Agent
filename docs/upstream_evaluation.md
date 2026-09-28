# 上游评估

2026-09-27 克隆并检查：

| 项目 | 许可 | 架构与依赖 | 决定 |
|---|---|---|---|
| `dglabsxyz/adaptive-genai-learning-tutor` | README 声称 MIT，但检出的主分支缺少 LICENSE、COPYING、NOTICE | FastAPI、React、LangGraph、教育学习工具和测试；课程内容为 GenAI | 只借鉴公开设计思路，不复制源码；许可待作者确认 |
| `StudentTraineeCenter/edu-agent` | 有 MIT LICENSE | 功能丰富，但 Azure OpenAI、Content Understanding、Blob、Key Vault 与 Supabase 是主要运行依赖 | 保留作架构参考，不直接搬用代码或运行栈 |

上游研究仓库位于工作区兄弟目录 `cognitutor-ds` 和 `edu-agent-reference`，不属于本项目代码。当前项目所有代码均独立编写。母体项目的运行与测试没有完成，因为首选许可文件缺失、第二候选需要外部服务；不能据此称上游测试通过。

首选母体可复用的公开思想：诊断、学习路径、练习、确定性评分、学习进度、前后端分离。重写部分：数据结构概念与误区、证据诊断、教学策略、算法轨迹、学生状态。当前已在核验题生命周期使用 LangGraph，课程检索支持可选向量接口；完整教学图和生产级状态存储仍未完成。
