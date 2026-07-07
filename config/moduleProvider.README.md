# moduleProvider.json 配置说明

运行时会按以下顺序定位 Provider 配置：

1. 如果设置了环境变量 `AGENTPARK_CONFIG_PATH`，读取该路径指向的 JSON 文件。
2. 否则读取工作区 `config/moduleProvider.json`。
3. 如果工作区路径不可用，再尝试当前进程目录下的 `config/moduleProvider.json`。

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
- `doubao`: 火山方舟 Ark Responses 实现，chat/Agent 主路径走 `/responses`；同时包含图片、视频、换人视频等生成能力。旧的 OpenAI-compatible `/chat/completions` 只作为未声明 `responsesApi: true` 的兼容路径。
- `gemini`: Gemini chat / image generation 实现。
- `zhipu`: 智谱 GLM chat 实现。
- `hyper3d`: Hyper3D Rodin 3D 模型和贴图生成实现。

要求：

- 必须是字符串。
- 配置加载时会转成小写。
- 新增 Provider 类型时，必须同步 `src/providers/__init__.py` 的创建逻辑和本文档。

### `apiKey`

Provider 的认证密钥。

要求：

- 必须是字符串。
- `ConfigLoader.get_provider_config()` 会要求最终 `apiKey` 非空。
- 不要把真实生产密钥提交到公开仓库。

注意：

- 当前加载器会删除 `apiKeyEnv`，也就是说不要依赖 `apiKeyEnv` 在运行时注入密钥。
- 如果要改成环境变量注入，应先改加载器合同，再同步本文档。

### `baseUrl`

Provider API 根地址。

用途：

- `openai`: runtime 会在去掉末尾 `/` 后请求 `{baseUrl}/responses`。
- `claude`: runtime 会在去掉末尾 `/` 后请求 `{baseUrl}/messages`；如果 `baseUrl` 已经以 `/messages` 结尾则直接使用。
- `doubao`: 声明 `responsesApi: true` 时 chat/Agent 路径会请求 `{baseUrl}/responses`；如果 `baseUrl` 已经以 `/responses` 结尾则直接使用。未声明 `responsesApi: true` 的旧兼容路径才会请求 `{baseUrl}/chat/completions`。
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
- `video_changePerson`: 换人视频节点可选。
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

- `openai` 和 `zhipu` runtime 也兼容旧字段名 `reasoning_effort`，但 `moduleProvider.json` 应统一使用 `reasoningEffort`。
- Krill 相关问题排查时，`reasoningEffort` 是重点字段之一，不要把它隐藏到默认值里。

### Responses continuation

OpenAI Responses 工具调用后的逻辑上下文延续固定采用显式回放：每一轮都从本地消息、工具调用、工具结果与运行时上下文构造完整 input，再发送到 HTTP `/responses`。

要求：

- Provider 配置中不再出现 `responsesContinuationMode`。
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
- 不接受 `responses_replay_reasoning_items` 别名。

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

工具上下文压缩用于 Agent 多轮工具调用后，让模型调用 `compact_tool_context` 压缩可回放的工具结果窗口，降低上下文膨胀。

当前这组字段已经从全局 `config/config.json` 移到每个 Provider 上。运行时只读取 Provider 配置，不再读取全局默认。

### `toolContextCompactionEnabled`

是否启用工具上下文压缩 gate。

取值：

- `true`: 启用。达到 `toolContextCompactionEveryToolCalls` 阈值后触发压缩 gate。
- `false`: 关闭。工具调用计数不会触发压缩 gate。

要求：

- 必须是布尔值。
- 必须写在每个 Provider 配置上。
- 缺失会报错。

当前特殊配置：

- `krill_gpt55` 为 `false`。原因是当前 Krill Responses continuation 重点是验证显式上下文回放和工具连续调用，不希望压缩 gate 介入改变上下文形态。
- 其他 Provider 当前为 `true`。

### `toolContextCompactionEveryToolCalls`

触发工具上下文压缩 gate 的工具调用次数阈值。

取值：

- 非负整数。
- `10` 表示累计 10 次普通工具执行后触发一次压缩 gate。
- `0` 表示每次有普通工具执行时都达到阈值；通常不建议这样配置。

要求：

- 当 `toolContextCompactionEnabled` 为 `true` 时必填。
- 必须能转换为大于等于 0 的整数。
- 当前也建议在 `toolContextCompactionEnabled: false` 的 Provider 上显式写出，便于以后打开时知道预期阈值。

不计入阈值的内部工具：

- `edit_operational_memory`
- `compact_tool_context`

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

Claude web search server tool 类型，缺省为 `web_search_20260318`。兼容旧配置名 `claudeWebSearchToolType`。

可选相关字段：

- `webSearchLimit` / `claudeWebSearchMaxUses` -> `max_uses`
- `webSearchAllowedDomains` / `claudeWebSearchAllowedDomains` -> `allowed_domains`
- `webSearchBlockedDomains` / `claudeWebSearchBlockedDomains` -> `blocked_domains`
- `webSearchAllowedCallers` / `claudeWebSearchAllowedCallers` -> `allowed_callers`
- `webSearchUserLocation` / `claudeWebSearchUserLocation` -> `user_location`
- `webSearchResponseInclusion` / `claudeWebSearchResponseInclusion` -> `response_inclusion`

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

- runtime 仍兼容 `web_search_max_keyword`，但 `moduleProvider.json` 应统一使用 `webSearchMaxKeyword`。

### `webSearchLimit`

Doubao Responses web search 的结果数量限制。

要求：

- 整数。
- 当前配置为 `10`。

注意：

- runtime 仍兼容 `web_search_limit`，但 `moduleProvider.json` 应统一使用 `webSearchLimit`。

### `webSearchSources`

Doubao Responses web search 的来源列表。

要求：

- 字符串数组。
- 当前配置为 `["toutiao"]`。

注意：

- runtime 仍兼容 `web_search_sources`，但 `moduleProvider.json` 应统一使用 `webSearchSources`。

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

- runtime 仍兼容 `max_tokens`，但 `moduleProvider.json` 应统一使用 `maxTokens`。

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
