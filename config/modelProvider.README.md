# modelProvider.json 配置说明

运行时会按以下顺序定位 Provider 配置：

1. 如果设置了环境变量 `AGENTPARK_CONFIG_PATH`，读取该路径指向的 JSON 文件。
2. 否则读取工作区 `config/modelProvider.json`。
3. 如果工作区路径不可用，再尝试当前进程目录下的 `config/modelProvider.json`。

顶层结构固定为：

```json
{
  "providers": {
    "provider_id": {
      "type": "openai",
      "apiKey": "...",
      "baseUrl": "...",
      "model": "..."
    }
  }
}
```

`providers` 下面的每个 key 是 Provider ID。节点、Agent、测试和 WebUI 选择模型时使用的是这个 ID，而不是 `model` 字段。

## 基础字段

### `type`

Provider 实现类型。运行时根据它选择具体 Agent / runtime。

当前常用取值：

- `openai`: 支持对话及 Images API。`image_generation` 模式走 `/images/generations`，带参考图时走 `/images/edits`。
- `claude`: Claude 原生 Anthropic Messages API 实现，走 `/messages`，支持 Claude tools、web search tool、thinking 与 `output_config.effort`；不使用 OpenAI Responses API 字段。
- `doubao`: Ark Responses implementation. When `responsesApi: true`, chat/Agent uses `/responses`; otherwise it uses `/chat/completions`.
- `gemini`: Gemini chat / image generation 实现。
- `zhipu`: 智谱 GLM chat 实现。
- `hyper3d`: Hyper3D Rodin 3D 模型和贴图生成实现。
- `alpha_matting`: 本机透明通道抠图 endpoint；只允许 `authMode: "none"` 与 loopback HTTP。

要求：

- 必须是字符串。
- 配置加载时会转成小写。
- 新增 Provider 类型时，必须同步 `src/providers/registry.py` 的注册表和本文档。

### `apiKey`

Provider 认证密钥在 `.auth/api-keys/aliases.json` 中的引用名称。例如，
`modelProvider.json` 使用 `"apiKey": "Ark"`，本机密钥文件使用
`{"Ark": "实际密钥"}`。

要求：

- 必须是非空字符串，且首尾不能有空白字符。
- 引用名称必须存在于 `.auth/api-keys/aliases.json`，对应值必须是非空字符串。
- `ConfigLoader.get_provider_config()` 只在运行时解析真实密钥。
- `modelProvider.json` 不允许保存真实密钥。

注意：

- `apiKeyEnv` 不属于当前配置合同。
- `.auth/api-keys/aliases.json` 是本机文件并由 Git 忽略；每台机器需要单独配置。

### `authMode`

认证模式。通用 Provider 使用 `api_key`、`oauth` 或 `codex`。
`none` 只允许用于 `type: "alpha_matting"`，且该 Provider 不得配置
`apiKey`、`authProvider` 或 `authAccountId`。

### `codexClientVersion`

仅用于 `authMode: "codex"` 的 Models 查询。Codex 模型目录会根据请求中的
`client_version` 返回模型。默认读取本机 `codex --version`；也可以用此字段或
`CODEX_CLIENT_VERSION` 环境变量指定版本。无法确定版本时查询会报告错误，
不会使用伪造的 `0.0.0` 版本继续请求。若服务进程找不到 Codex CLI，配置此字段；
升级 Codex CLI 后需同步更新此字段。

### `xApiKey`

豆包语音数据面接口使用的独立鉴权引用名称。真实值同样从
`.auth/api-keys/aliases.json` 解析；运行时仅在接口协议要求 `X-Api-Key` 请求头时读取，
不会回退到通用的 `apiKey`。

要求：

- 配置该字段时必须引用 `.auth/api-keys/aliases.json` 中存在的非空条目。
- 使用 `X-Api-Key` 的语音能力在字段缺失时会明确报错。
- `apiKey` 仍用于 Provider 的通用鉴权；两者不要互相替代。
- 密钥文件中的对应值必须来自“豆包语音控制台 > API Key 管理”的单一语音
  API Key；账号级“API 密钥管理”中的 API Key ID/Secret 和 AccessKey 均不适用。
- 音色列表等控制台 OpenAPI 使用 HMAC AK/SK 签名，不使用此字段。

### `baseUrl`

Provider API 根地址。

用途：

- `openai`: runtime 会在去掉末尾 `/` 后请求 `{baseUrl}/responses`。
- `claude`: runtime 会在去掉末尾 `/` 后请求 `{baseUrl}/messages`；如果 `baseUrl` 已经以 `/messages` 结尾则直接使用。
- `doubao`: When `responsesApi: true`, chat/Agent requests `{baseUrl}/responses`; otherwise it requests `{baseUrl}/chat/completions`.
- `zhipu`: HTTP transport 会基于该地址构造 chat 请求；缺失时使用 Zhipu transport 内部默认地址。
- `gemini`: 用于 Gemini API 请求。
- `hyper3d`: 用于 Hyper3D API 请求；缺失时 Hyper3D runtime 有内部默认值 `https://api.hyper3d.com/api/v2`，但实际配置仍建议显式写出。
- `alpha_matting`: 必须是无路径的 HTTP loopback 根地址；运行时固定调用 `/health` 和 `/v1/matting`。

要求：

- 必须是字符串。
- 建议不要以业务 endpoint 结尾，除非对应 runtime 明确要求。例如 OpenAI 兼容 Provider 应写到 `/v1` 或兼容服务根路径，不要直接写 `/responses`。

### `model`

Provider 请求时使用的模型名。

用途：

- chat / responses / image / video 等 runtime 会把它作为请求模型。
- 对于部分生成类 Provider，节点输入可能覆盖模型；没有覆盖时使用这里的值。

要求：

- 必须是字符串。
- 模型名必须与 Provider 服务端实际支持的名称一致。

### `supportmode`

图片附件属于 `chat` 的多模态输入能力，不单独划分聊天模式。需要生成图片时使用 `image_generation`。

Provider 支持的能力列表。WebUI 和专用节点用它筛选可选 Provider。

当前常用取值：

- `chat`: 普通文本对话。
- `image_generation`: 图片生成节点可选。
- `image_matting`: 单图抠图节点可选。
- `vision_understand`: 视觉理解节点可选。
- `video_generation`: 视频生成节点可选。
- `video_change_person`: 换人视频节点可选。
- `model_generation`: 3D 模型生成节点可选。
- `model_texture_generation`: 3D 模型贴图生成节点可选。

要求：

- 必须是数组。
- 加载器会去掉空值和重复值。
- 大小写不会被统一改写；新增能力名时应保持全项目一致。

### `timeoutMs`

HTTP 传输超时时间，单位毫秒。

用途：

- `openai` / `doubao` / `gemini` / `zhipu` / `hyper3d` 的 HTTP transport 都会读取它。
- 非流式 HTTP 请求将其作为单次请求总超时。
- SSE 流式请求将其作为空闲超时；每收到一行流数据都会重新计时，持续活跃的流不受请求总时长限制。
- `alpha_matting` 的健康检查与抠图请求都会读取它。
- 部分长任务还有独立的轮询总等待时间，例如 Hyper3D 的 `maxWaitSec`。

要求：

- 必须能转换为大于 0 的整数。
- 配置加载器会在读取时校验。

建议：

- 当前 Provider 统一使用 `120000`。
- 不要把 `timeoutMs` 当成长任务总等待时间；轮询类任务应配置对应的 `maxWaitSec`。

### `streamEnabled`

该 Provider 的节点执行是否请求 SSE 流式响应。

用途：

- `nodes/agent_node.py` 构造 `stream_runtime.send(...)` 请求时会读取它，作为传给 `agent.Send(..., stream=...)` 的值。
- 关闭后该 Provider 的节点执行会走非流式请求；`stream_handler` 回调仍会在响应到达后一次性收到完整文本（而不是逐个 delta）。

要求：

- 必须是布尔值；不是布尔值会报错。
- 缺失时默认为 `true`，与当前所有 Provider 的既有行为一致。

注意：

- 这是唯一一个"缺失时不报错，而是自动补默认值"的开关字段；这是有意为之，目的是让新增/未显式配置的 Provider 保持现状（一直走流式），不需要逐个补写这个字段。

## Responses API 字段

这些字段用于声明了 `responsesApi: true` 的 Provider。当前 runtime 对这些字段采用显式合同，缺失会报错，不会读取全局默认。

### `reasoningEffort`

发送到 OpenAI Responses 兼容接口的 reasoning effort。

常见取值：

- `low`
- `medium`
- `high`
- `xhigh`
- `max`

实际可用值取决于 Provider。比如某些兼容服务可能只接受自己的扩展值。

要求：

- 字符串。
- 空字符串或缺失表示不发送 `reasoning` 字段。

注意：

- `modelProvider.json` only accepts `reasoningEffort`; `reasoning_effort` is rejected.
- Krill 相关问题排查时，`reasoningEffort` 是重点字段之一，不要把它隐藏到默认值里。

### `fastMode`

是否为 OpenAI Responses 兼容请求启用快速服务层。

取值：

- `true`: 请求体发送 `service_tier: "priority"`。
- `false` 或缺失：不发送 `service_tier`，由 Provider 使用默认服务层。

要求：

- 必须是布尔值。
- `true` 只允许用于 `type: "openai"` 且 `responsesApi: true` 的 Provider。
- 不限制 `authMode`；Codex OAuth 与明确支持 priority tier 的 API Key 兼容 Provider 都可配置。

注意：

- Codex 配置中的 legacy tier 名称是 `fast`，当前协议请求值是 `priority`；`fastMode` 会直接映射为后者。
- Provider 接受请求但在响应中返回 `service_tier: "default"`，表示 Provider 没有确认本次请求实际使用 priority tier，不能仅凭 HTTP 200 判断加速已经生效。

### Responses continuation

OpenAI Responses 工具调用后的逻辑上下文延续固定采用显式回放：每一轮都从本地消息、工具调用、工具结果与运行时上下文构造完整 input，再发送到 HTTP `/responses`。

要求：

- Provider config must not contain `responsesContinuationMode`.
- HTTP `/responses` 请求不使用 `previous_response_id` 作为上下文主机制。
- `previous_response_id` 只允许作为 Responses WebSocket 传输层的内部增量优化：必须先构造完整逻辑请求，并在确认当前 input 是上一轮逻辑请求加服务端 output 的严格延续后，才可以在 WebSocket payload 中发送 delta。

### `responsesReplayReasoningItems`

显式上下文回放时，是否把 Responses 返回的 `reasoning` output item 放回下一轮 input。

必填于 `type: "openai"` Provider。

取值：

- `false`: 不回放 `reasoning` item。第三方兼容 Provider 的默认推荐值。
- `true`: 回放 `reasoning` item。只适用于已验证支持加密 reasoning 上下文回放的 Provider。

当前仅官方 Codex Provider `GPT_Official` 使用 `true`；其余 Provider 使用 `false`。这个字段只控制 Responses 显式上下文中的协议项回放，不是推理强度或任务完成质量开关；非 Responses Provider 不使用它。

原因：

- 当 Provider 使用 `store=false` 或不持久化 reasoning item 时，回放带 `rs_...` id 的 reasoning item 可能触发错误：`Item with id ... not found. Items are not persisted when store is set to false.`
- 因此 Krill 这类兼容服务应保持 `false`。
- `include: ["reasoning.encrypted_content"]` 负责请求服务端返回可续接的加密 reasoning 内容，与是否在下一次显式 input 中回放该 item 是两个独立动作。

要求：

- 必须是布尔值。
- 必须写在 Provider 配置上。
- 缺失或非布尔值会报错。
- `modelProvider.json` only accepts `responsesReplayReasoningItems`; `responses_replay_reasoning_items` is rejected.

### `toolResultSubmissionMaxChars`

工具结果提交给 Responses 模型前的硬上限。

要求：

- 必填于 `responsesApi: true` Provider。
- 必须是大于 0 的整数。
- 超限工具结果会被替换为结构化压缩结果；原始结果只应作为运行时 artifact 保留。

### `toolContextCompactionEnabled`

是否启用工具上下文压缩门。

要求：

- 必填于 `responsesApi: true` Provider。
- 必须是布尔值。

### `toolContextCompactionEveryToolCalls`

每累计多少次工具调用后尝试压缩工具上下文。

要求：

- 必填于 `responsesApi: true` Provider。
- 必须是大于等于 0 的整数；`0` 关闭按工具调用次数触发的阈值。

### `responsesApi`

Declares that the provider supports the project Responses API contract.

Rules:

- Must be a boolean.
- `true` enables the Responses runtime path.
- The Responses runtime uses item-level function-call handling: a complete `function_call` output item can start tool execution during streaming, and tool outputs are submitted on the next Responses request after `response.completed`.
- Providers that do not declare `responsesApi: true` are treated as not supporting Responses features.
- Item-level handling is the normal Responses path; there is no separate runtime-mode switch.

### `responsesWebSocket`

控制流式 Responses 请求是否优先使用可选的 WebSocket transport。

规则：

- 必须是布尔值。
- `false` 固定使用 HTTP SSE，适用于 DeepSeek 等只支持 HTTP `/responses` 的 Provider。
- `true` 允许流式请求优先尝试 WebSocket；非流式请求仍使用 HTTP。
- 缺失时按 `false` 处理；WebSocket 必须由 Provider 显式选择加入。
- 设置页新启用 Responses API 时默认写入 `false`，需要 WebSocket 的 Provider 必须显式开启。
- WebSocket 握手返回 404、405 或 426 时，当前 Provider 会在本次会话内自动降级为 HTTP SSE。

## 工具上下文压缩字段

工具上下文压缩由 Provider 运行时的 checkpoint gate 管理。达到明确阈值后，运行时会暂时只向模型提供 `compact_tool_context`；模型通过该工具提交结构化 continuation checkpoint，运行时再把符合条件的已完成工具调用历史替换为可校验的摘要，并恢复普通工具。

当前这组字段已经从全局 `config/config.json` 移到每个 Provider 上。运行时只读取 Provider 配置，不再读取全局默认。

### `toolContextCompactionEnabled`

是否启用运行时内部的工具上下文压缩。

取值：

- `true`: 启用。达到任一已配置阈值后，进入只提供 `compact_tool_context` 的 checkpoint；压缩成功后安装 replacement history 并恢复普通工具。
- `false`: 关闭。运行时保留完整工具调用历史。

要求：

- 必须是布尔值。
- 必须写在每个 Provider 配置上。
- 缺失会报错。

### `toolContextCompactionEveryToolCalls`

触发内部 replacement history 的普通工具执行次数阈值。

取值：

- 非负整数。
- `10` 表示累计 10 次普通工具执行后触发一次内部压缩。
- `0` 表示关闭按普通工具执行次数触发；其他已配置的 token 阈值仍可独立触发。

要求：

- 当 `toolContextCompactionEnabled` 为 `true` 时必填。
- 必须能转换为大于等于 0 的整数。
- 当前也建议在 `toolContextCompactionEnabled: false` 的 Provider 上显式写出，便于以后打开时知道预期阈值。

不计入阈值的内部工具：

- `add_node_memory_note`
- `compact_tool_context`

### `toolContextCompactionReplacementMaxChars`

单次结构化 replacement history 的最大字符数。缺省值为 `50000`，显式配置时必须是大于等于 `4000` 的整数。超出预算的明细会按契约降为带摘要哈希的元数据，运行时不会把非结构化截断文本伪装成完整结果。

### `modelContextWindowTokens` / `toolContextCompactionContextPercent`

按当前请求输入占模型上下文窗口的比例触发压缩。两个字段必须成对使用：上下文窗口必须是正整数，比例必须是 `1` 到 `100` 的整数，同时 `toolContextCompactionCurrentInputTokens` 必须为 `0`。例如 `1000000` 与 `80` 会在最新请求输入达到约 800,000 token 时触发。

## 会话持久化与整会话压缩字段

这组字段管理 Agent harness 自己的可恢复执行状态，不改变 Provider 的 API 类型，也不会把 Responses 请求退回 Chat Completions。

运行时在节点目录写入 append-only `agent_steps.jsonl`。每次模型请求形成一个独立 step；Provider 请求、重试、工具开始、工具结束、最终回答和整会话压缩 checkpoint 都形成带序号的持久化事件。若进程在有副作用的工具开始后、结果持久化前退出，下一次启动会持久化并注入一组配对的历史 tool call 与 `TOOL_OUTCOME_UNKNOWN` tool result，要求模型先核验外部状态，不能直接重放有副作用的工具。

### `agentStepLedgerEnabled`

- 必须是布尔值；缺省为 `false`。
- `true` 启用持久化 step ledger。
- 工具执行遵守 write-ahead 语义：`tool_call_started` 必须落盘成功后才进入工具主体；落盘失败会明确中止，不会以未记录状态继续执行。

### `sessionContextCompactionEnabled`

- 必须是布尔值；缺省为 `false`。
- `true` 启用 provider request 前的整会话 checkpoint gate。
- 启用时必须配置正整数 `modelContextWindowTokens`。

整会话压缩与 `compact_tool_context` 不同：后者只替换已完成的工具调用历史；前者会选择会话中最旧的完整前缀，临时只提供 `compact_session_context`，让模型提交严格结构化 checkpoint，再保留最近对话继续执行。原始消息和 ledger 不会被删除，checkpoint 还会在新 Agent 实例恢复时注入上下文。

### `sessionContextCompactionThresholdPercent`

整会话压缩的上下文压力阈值，必须是 `1` 到 `100` 的整数，缺省为 `80`。运行时优先使用完整 Provider 请求 envelope 的 token 估算，确保 instructions、tools 和历史输入都计入判断。

### `sessionContextCompactionRetainPercent`

压缩后希望保留的最近会话比例，必须是 `1` 到 `100` 的整数，缺省为 `16`。运行时始终保留最新用户消息，并调整边界以避免切断 assistant tool call 与对应 tool result。

### `sessionContextCompactionMaxAttempts`

结构化 checkpoint 的最大提交次数，必须是 `1` 到 `5` 的整数，缺省为 `3`。模型提交不符合严格 schema 的结果时，运行时会把确切工具错误带入同一个压缩 gate 继续重试；达到上限仍失败则明确终止，不会放宽 schema 或跳过压缩。

## DeepSeek 字段与运行时合同

`type: "deepseek"` 同时拥有 Responses 主路径和 Chat Completions 兼容路径。内置 `deepseek_v4_pro`、`deepseek_v4_flash` 已通过 `/responses` 实际请求验证，因此都配置为 `responsesApi: true`、`responsesWebSocket: false`；需要排查兼容网关时仍可显式配置 `responsesApi: false` 使用 `/chat/completions`。

内置 V4 配置采用以下明确默认值：

- `thinking: "enabled"` 与 `reasoningEffort: "high"`。DeepSeek 只接受 `enabled` / `disabled`，启用时 reasoning effort 只接受 `high` / `max`。
- `maxTokens: 256000`。Chat 路径映射为 `max_tokens`，Responses 路径映射为 `max_output_tokens`。
- `modelContextWindowTokens: 1000000` 与 `toolContextCompactionContextPercent: 80`。按上下文压力触发，不再额外按固定工具调用次数触发。
- `agentStepLedgerEnabled: true`。Provider 请求和工具副作用边界会写入节点级持久化 ledger，重启后可识别结果未知的工具调用。
- `sessionContextCompactionEnabled: true`、`sessionContextCompactionThresholdPercent: 80`、`sessionContextCompactionRetainPercent: 16` 与 `sessionContextCompactionMaxAttempts: 3`。达到阈值时仍沿用 Responses 主路径，先完成整会话 checkpoint，再继续正常请求。
- `responsesReplayReasoningItems: false`。Responses 历史不回放提供方 reasoning item；Chat 工具调用轮次仍会按 DeepSeek 协议回传 `reasoning_content`。

Chat 兼容路径还执行以下严格协议规则：纯工具调用 assistant 消息的 `content` 固定序列化为 `""`，不会发送 `null`；SSE 必须以 `[DONE]` 结束；畸形 JSON、截断流和空响应分别以稳定的 `MALFORMED_RESPONSE`、`STREAM_CLOSED`、`EMPTY_RESPONSE` code 失败。HTTP 与传输失败也会分类为 `AUTH`、`QUOTA`、`RATE_LIMIT`、`CONTEXT_WINDOW_EXCEEDED`、`INVALID_REQUEST`、`SERVER` 或 `TRANSPORT`，不会静默降级。

## Claude Messages 字段

这些字段用于 `type: "claude"`，会映射到 Anthropic Messages API。

### `thinking`

- `disabled`: 不发送 `thinking` 字段。
- `enabled`: 发送 `{"type": "enabled", "budget_tokens": thinkingBudgetTokens}`。
- `auto`: 发送 `{"type": "adaptive"}`。

`thinkingBudgetTokens` 必须大于 0 且小于 `maxTokens`。

### `reasoningEffort`

Claude 原生实现会映射为 `output_config.effort`，当前允许：

- `low`
- `medium`
- `high`
- `xhigh`
- `max`

### `webSearchToolType`

Claude web search server tool type. `modelProvider.json` only accepts `webSearchToolType`; `claudeWebSearchToolType` is rejected.

可选相关字段：


`allowed_domains` 和 `blocked_domains` 不能同时配置。

## Doubao / Ark Responses 字段

这些字段用于 `type: "doubao"` 且 `responsesApi: true` 的火山方舟 Responses 路径。

### `thinking`

Doubao Ark Responses 会把该值映射到请求体的 `thinking.type`。

常见取值：

- `enabled`
- `disabled`
- `auto`

实际可用值取决于模型。当前 live probe 显示 `doubao-seed-2-1-pro-260628` 接受 `enabled` / `disabled`，但拒绝 `auto`；以 ProviderLimit probe 的结果为准。

### `reasoningEffort`

Doubao Ark Responses 会映射为 `reasoning.effort`。

当前允许：

- `low`
- `medium`
- `high`

`xhigh` / `max` 是 AgentPark/OpenAI-compatible 扩展值，不属于当前 Doubao Ark Responses 合同；runtime 会在本地拒绝，避免发出已知会 400 的请求。

### `webSearchMaxKeyword`

Doubao Ark Responses web search 的最大关键词数量。

用途：

- 构造 Doubao `web_search` 工具参数。

要求：

- 整数。
- 当前配置为 `5`。

注意：

- `modelProvider.json` only accepts `webSearchMaxKeyword`; `web_search_max_keyword` is rejected.

### `webSearchLimit`

Doubao Responses web search 的结果数量限制。

要求：

- 整数。
- 当前配置为 `10`。

注意：

- `modelProvider.json` only accepts `webSearchLimit`; `web_search_limit` is rejected.

### `webSearchSources`

Doubao Responses web search 的来源列表。

要求：

- 字符串数组。
- 当前配置为 `["toutiao"]`。

注意：

- `modelProvider.json` only accepts `webSearchSources`; `web_search_sources` is rejected.

## Zhipu 字段

### `thinking`

Zhipu Provider 的 thinking 模式。

当前配置：

- `GLM_5.2_HuoShan`: `enabled`

常见取值：

- `enabled`
- `disabled`
- `auto`

实际取值由 Zhipu / 火山兼容接口决定。运行时会把它转成请求中的 thinking 配置。

### `maxTokens`

Zhipu chat 请求的最大输出 token 数。

当前配置：

- `GLM_5.2_HuoShan`: `65536`

要求：

- 整数。
- 具体上限取决于模型和 Provider。

注意：

- `modelProvider.json` only accepts `maxTokens`; `max_tokens` is rejected.

## Alpha Matting 字段

`type: "alpha_matting"` 使用专用 Image Matting 节点，要求：

- `supportmode` 必须严格等于 `["image_matting"]`。
- `model` 必须与 `/health` 返回的 `model_id` 一致。
- `modelRevision` 必须与 `/health` 返回的 `model_revision` 一致。
- `/v1/matting` 必须返回 `image/png`、RGBA 像素和匹配的尺寸/alpha 响应头。
- 输出 alpha 必须具有非平凡范围；全透明或全不透明结果会被拒绝。

### `localRuntime`

本地 endpoint 的托管启动契约：

- `managed`: 是否允许 Provider 在健康检查连接失败时启动服务。
- `startupCommand`: `managed: true` 时必需；非空参数数组，使用 `shell=false` 原样执行。
- `workingDirectory`: `managed: true` 时必需；绝对路径。
- `healthUrl`: 必须严格等于 `{baseUrl}/health`。
- `startupTimeoutMs`: 启动健康检查的正整数超时。

服务可连接但健康协议、模型或输出不匹配时会直接报错，不会尝试重启或静默降级。

## Hyper3D 字段

这些字段用于 `type: "hyper3d"`。

### `tier`

Hyper3D Rodin 生成档位。

当前配置：

- `hyper3d-rodin-gen2`: `Gen-2`

用途：

- 3D 模型生成请求会把它作为 `tier` 字段提交。

### `pollIntervalSec`

Hyper3D 3D 模型生成轮询间隔，单位秒。

当前配置：

- `hyper3d-rodin-gen2`: `5`

要求：

- 数字。
- 必须大于 0。

### `maxWaitSec`

Hyper3D 3D 模型生成最大等待时间，单位秒。

当前配置：

- `hyper3d-rodin-gen2`: `1800`

取值：

- 数字表示最多等待多少秒。
- 空值表示不设置总等待上限，但不建议这么做。

### `texturePollIntervalSec`

Hyper3D 贴图生成轮询间隔，单位秒。

当前配置：

- `hyper3d-rodin-gen2`: `5`

要求：

- 数字。
- 必须大于 0。

回退关系：

- 如果缺失，贴图 runtime 会回退到 `pollIntervalSec`。
- 为了配置可见性，当前文件显式写出，不依赖回退。

### `textureMaxWaitSec`

Hyper3D 贴图生成最大等待时间，单位秒。

当前配置：

- `hyper3d-rodin-gen2`: `1800`

回退关系：

- 如果缺失，贴图 runtime 会回退到 `maxWaitSec`。
- 为了配置可见性，当前文件显式写出，不依赖回退。



## 修改规则

1. 不要把行为依赖藏到全局默认值里；影响 Provider runtime 的开关应写在对应 Provider 下。
2. 如果代码新增了 Provider 字段，必须同步更新本文档。
