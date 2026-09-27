# 模型 API 协议

本地“模型设置”支持：

| 协议 | 默认基础地址 | 文本请求 |
|---|---|---|
| OpenAI Chat Completions 兼容 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `POST /chat/completions`，Bearer Key |
| Anthropic Messages | `https://api.anthropic.com/v1` | `POST /messages`，`x-api-key` 与 `anthropic-version` |
| Gemini generateContent | `https://generativelanguage.googleapis.com/v1beta` | `POST /models/{model}:generateContent`，`x-goog-api-key` |

依据：[OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create)、[阿里云 Qwen 兼容接口及地址](https://help.aliyun.com/en/model-studio/base-url)、[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)、[Gemini generateContent API](https://ai.google.dev/api/generate-content)。模型名称会随服务更新，应填写服务商当前可用的模型 ID。

当前适配器面向文本对话和 JSON 诊断输出。Anthropic/Gemini 的工具调用与流式输出尚未接入；核心诊断流程不依赖模型的原生工具调用。Gemini 官方还提供较新的 Interactions API，本项目此处实现的是 widely supported 的 `generateContent` REST 接口。

远程基础地址必须使用 HTTPS；`http://localhost` 和回环 IP 可用于本机兼容服务。API Key 保存在操作系统凭据保管库，普通配置写入 `data/model_settings.json`。服务仅监听 `127.0.0.1`，设置接口不向页面返回 Key。若要迁移到另一台电脑，需要重新输入密钥。
