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

- `openai`: OpenAI Responses API 兼容实现。当前 `OpenAIAgent` 固定走 `/responses`。
- `claude`: Claude 原生 Anthropic Messages API 实现，走 `/messages`，支持 Claude tools、web search tool、thinking 与 `output_config.effort`；不使用 OpenAI Responses API 字段。
- `doubao`: Ark Responses implementation. When `responsesApi: true`, chat/Agent uses `/responses`; otherwise it uses `/chat/completions`.
- `gemini`: Gemini chat / image generation 实现。
- `zhipu`: 智谱 GLM chat 实现。
- `hyper3d`: Hyper3D Rodin 3D 模型和贴图生成实现。

要求：

- 必须是字符串。
- 配置加载时会转成小写。
- 新增 Provider 类型时，必须同步 `src/providers/__init__.py` 的创建逻辑和本文档。

### `apiKey`

Provider 认证密钥在 `.env/apiKey.json` 中的引用名称。例如，
`modelProvider.json` 使用 `"apiKey": "Ark"`，本机密钥文件使用
`{"Ark": "实际密钥"}`。

要求：

- 必须是非空字符串，且首尾不能有空白字符。
- 引用名称必须存在于 `.env/apiKey.json`，对应值必须是非空字符串。
- `ConfigLoader.get_provider_config()` 只在运行时解析真实密钥。
- `modelProvider.json` 不允许保存真实密钥。

注意：

- `apiKeyEnv` 不属于当前配置合同。
- `.env/apiKey.json` 是本机文件并由 Git 忽略；每台机器需要单独配置。

### `xApiKey`

豆包语音数据面接口使用的独立鉴权引用名称。真实值同样从
`.env/apiKey.json` 解析；运行时仅在接口协议要求 `X-Api-Key` 请求头时读取，
不会回退到通用的 `apiKey`。

要求：

- 配置该字段时必须引用 `.env/apiKey.json` 中存在的非空条目。
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

Provider 支持的能力列表。WebUI 和专用节点用它筛选可选 Provider。

当前常用取值：

- `chat`: 普通文本对话。
- `imagechat`: 多模态图片对话。
- `image_generation`: 图片生成节点可选。
- `vision_understand`: 视觉理解节点可选。
- `GUIAgent`: GUI Agent 相关工具可选。
- `video_generation`: 视频生成节点可选。
- `video_change_person`: 换人视频节点可选。
- `model_generation`: 3D 模型生成节点可选。
- `model_texture_generation`: 3D 模型贴图生成节点可选。

要求：

- 必须是数组。
- 加载器会去掉空值和重复值。
- 大小写不会被统一改写；新增能力名时应保持全项目一致。

### `timeoutMs`

单次 HTTP 请求超时时间，单位毫秒。

用途：

- `openai` / `doubao` / `gemini` / `zhipu` / `hyper3d` 的 HTTP transport 都会读取它。
- 部分长任务还有独立的轮询总等待时间，例如 Hyper3D 的 `maxWaitSec`。

要求：

- 必须能转换为大于 0 的整数。
- 配置加载器会在读取时校验。

建议：

- 普通 chat Provider 通常使用 `60000`。
- 生成类或长上下文 Provider 可以使用 `180000` 或更高。
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

- `false`: 不回放 `reasoning` item。当前推荐值。
- `true`: 回放 `reasoning` item。只适用于 Provider 明确支持引用这些 item，且 response item 会被服务端持久保存的场景。

当前配置均为 `false`。

原因：

- 当 Provider 使用 `store=false` 或不持久化 reasoning item 时，回放带 `rs_...` id 的 reasoning item 可能触发错误：`Item with id ... not found. Items are not persisted when store is set to false.`
- 因此 Krill 这类兼容服务应保持 `false`。

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
- 必须是大于 0 的整数。

### `responsesApi`

Declares that the provider supports the project Responses API contract.

Rules:

- Must be a boolean.
- `true` enables the Responses runtime path.
- The Responses runtime uses item-level function-call handling: a complete `function_call` output item can start tool execution during streaming, and tool outputs are submitted on the next Responses request after `response.completed`.
- Providers that do not declare `responsesApi: true` are treated as not supporting Responses features.
- Item-level handling is the normal Responses path; there is no separate runtime-mode switch.

## 工具上下文压缩字段

工具上下文压缩是 Provider 运行时的内部机制。达到明确阈值后，运行时会把已经完成的工具调用历史替换为有版本、可校验的结构化 replacement history；模型不会看到或调用专用压缩工具。

当前这组字段已经从全局 `config/config.json` 移到每个 Provider 上。运行时只读取 Provider 配置，不再读取全局默认。

### `toolContextCompactionEnabled`

是否启用运行时内部的工具上下文压缩。

取值：

- `true`: 启用。达到任一已配置阈值后，由 Provider 运行时直接安装 replacement history。
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
- `0` 表示每次有普通工具执行时都达到阈值；通常不建议这样配置。

要求：

- 当 `toolContextCompactionEnabled` 为 `true` 时必填。
- 必须能转换为大于等于 0 的整数。
- 当前也建议在 `toolContextCompactionEnabled: false` 的 Provider 上显式写出，便于以后打开时知道预期阈值。

不计入阈值的内部工具：

- `edit_operational_memory`

### `toolContextCompactionReplacementMaxChars`

单次结构化 replacement history 的最大字符数。缺省值为 `50000`，显式配置时必须是大于等于 `4000` 的整数。超出预算的明细会按契约降为带摘要哈希的元数据，运行时不会把非结构化截断文本伪装成完整结果。

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
