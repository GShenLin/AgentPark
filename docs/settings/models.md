# 模型提供商与 Harness

[Settings 索引](README.md) · [第一次配置](../GettingStart.md#4-配置第一个-provider)

<a id="model-provider"></a>
## 模型提供商 / Model Provider

入口：**Settings → 模型提供商**。配置主要保存在 `config/modelProvider.json`；设置 `AGENTPARK_CONFIG_PATH` 时以后端报告的实际路径为准。真实密钥与授权文件位于 `.auth/`。

### 添加、复制、重命名与删除

1. 在左侧搜索已有连接，或输入唯一 Provider ID 并点击添加。
2. 在“连接、授权与模型”中选择 Type、Base URL、授权和模型。
3. 展开其他字段组，只配置服务确实支持的参数。
4. 点击页顶保存，再到实际节点选择此 Provider 与一个明确模型，完成最小请求验证。

Duplicate 复制配置草稿，并在保存时处理对应的 ProviderLimit 复制；它不创建新的服务账号。Provider ID 是其他配置使用的引用键；重命名或删除前，检查节点、预设和网关对它的引用，不应假定已有引用会自动改名。所有这类草稿变更都要保存。

### 连接字段

| 字段 | 如何填写 | 如何判断正确 |
| --- | --- | --- |
| Provider ID | 工作区内唯一的连接标识，如 `my-chat` | 节点能找到同一个 ID |
| Type | 对应已实现的适配器类型 | 与上游协议一致，不能仅按品牌猜测 |
| Base URL | API 根地址，保留服务要求的版本前缀 | 没有重复拼接业务 endpoint；以测试返回的 Endpoint 核对 |
| API Key Name | 选择本机密钥别名 | 下拉无 `(missing)`，授权请求成功 |
| Models | 一行一个模型项目，通过添加按钮新增 | 模型 ID 与服务目录一致；节点明确选中其中一个 |
| Description | 连接用途说明 | 便于区分生产、测试和不同账号 |

Type 选项包括 `alpha_matting`、`agnes`、`openai`、`workbuddy`、`claude`、`deepseek`、`doubao`、`gemini`、`grok`、`kimi`、`zhipu`、`hyper3d`。各自支持范围由代码适配器与服务共同决定。

OpenAI 兼容服务通常填写到 `/v1` 或服务指定的兼容根路径；Claude 使用 Messages 协议；Gemini、Hyper3D 等按各自适配器处理。不能为所有 Type 套用同一地址格式。

### 密钥别名、账号与 OAuth

| 方式 | 操作步骤 | 适用情况 |
| --- | --- | --- |
| 密钥别名 | API Key Name → Add → 输入名称与真实 Key → 保存 → 选择别名 → 保存 Provider | 复用 `.auth/api-keys/aliases.json` 中的 Key |
| 命名 API Key 账号 | Accounts 区输入账号名称、唯一标识和 Key → 添加 → 选择账号 → 保存 Provider | 同一授权 Provider 下管理多个账号 |
| 官方 OAuth | 点 OAuth 开启 → 登录 → 完成浏览器/设备授权 → 选择账号 → 保存 Provider | 仅用于已实现官方授权协议的类型 |
| 同步本机 Codex 凭据 | OpenAI OAuth 区点击同名按钮 → 查看同步结果 → 选择账号 | 明确从运行后端的设备、同一系统用户的本机 Codex 登录文件导入 |

账号列表显示 kind、当前 Provider 绑定和全局活动账号。选中账号会设置 `authAccountId`；修改后仍需保存当前 Provider 草稿。移除账号会影响使用该账号的连接，不能以“列表中还有别的账号”判断原绑定仍可用。

官方授权实现包含 OpenAI、Anthropic、Kimi 和 xAI 协议；仅在当前类型支持时显示可用操作。授权回调、过期和刷新错误以界面原始错误为准。通用密钥字段填写的是引用名，不能填真实 Key；Provider 配置不使用 `apiKeyEnv`。

`alpha_matting` 是受限的无认证特例：`authMode: "none"`、HTTP loopback 根地址，不允许配置认证字段。它不表示其他任意远程接口都可以无认证使用。更完整的合同见 [Provider 字段](../../config/modelProvider.README.md)。

### 额度与推理参数

| 字段 | 含义与调节方式 |
| --- | --- |
| Timeout / `timeoutMs` | 毫秒；非流式请求的单次总超时，SSE 的空闲超时。慢任务需区分 HTTP 等待与服务端生成总时长 |
| Concurrency / `concurrencyLimit` | 同时在途请求数上限；排队明显时结合 Pressure 检查，不盲目提高 |
| RPM / `rpmLimit` | 每分钟请求限制；留空表示未配置该项本地限制，仍受服务端额度限制 |
| TPM / `tpmLimit` | 每分钟 Token 限制；结合输入、输出使用量与等待时间设置 |
| Max Tokens / `maxTokens` | 模型输出预算，不能当作输入上下文窗口 |
| Reasoning Effort / `reasoningEffort` | 推理强度；表单选项不代表每个模型都接受，按功能矩阵与实际服务校验 |
| Reasoning Summary / `reasoningSummary` | 推理摘要选项，依协议支持情况发送 |
| Thinking / `thinking` | 思考模式，按所选适配器支持情况设置 |

保存 Provider 后，后续请求读取新配置；正在执行的请求不因此改写。节点层可能另有思考/搜索字段，需同时核对实际节点选择。

### 协议与功能开关

| 字段 | 用法与当前边界 |
| --- | --- |
| Private / `private` | 对非本机客户端隐藏该 Provider 的节点配置选项；不是撤销账号或停止任务 |
| Responses API / `responsesApi` | 声明服务支持项目 Responses 合同；开启后走对应协议并校验必需字段 |
| Responses WebSocket / `responsesWebSocket` | Responses 流式传输的可选 WebSocket 路径；先确认服务支持，不能当作通用网络修复开关 |
| Fast Mode / `fastMode` | 仅 OpenAI 类型且启用 Responses 时可用，映射到请求 `service_tier: priority`；返回成功不保证上游实际采用该层级 |
| Replay Reasoning / `responsesReplayReasoningItems` | 是否回放 Responses reasoning 协议项；仅在服务验证支持时开启，不等于增大思考强度 |
| Tool Compaction / `toolContextCompactionEnabled` | 启用工具上下文压缩触发机制，配合下表阈值使用 |
| Item-level Streaming / `responsesItemLevelStreaming` | 当前表单仍显示此字段，但 Responses 主路径固定按 item 处理，代码没有读取它作为运行模式开关；不要靠切换它排查流式行为 |

Responses HTTP 续聊从本地显式重建逻辑上下文；不要添加已经退出合同的 `responsesContinuationMode`。协议选项的准确校验见 `src/responses_provider_config.py`。

### 工具、搜索与上下文

| 字段 | 用途 |
| --- | --- |
| Support Modes / `supportmode` | 能力声明，影响创建菜单与节点字段；多选不等于服务自动获得该能力 |
| Web Search Sources / `webSearchSources` | 服务支持的搜索来源列表 |
| Web Search Max Keyword / `webSearchMaxKeyword` | 对应搜索接口的关键词数量上限 |
| Web Search Limit / `webSearchLimit` | 对应搜索接口的结果数量上限 |
| Compaction Calls / `toolContextCompactionEveryToolCalls` | 达到工具调用次数时尝试压缩；0 关闭该次数触发条件 |
| Compaction Input / `toolContextCompactionInputTokens` | 压缩窗口内累计输入 Token 触发阈值；0 关闭该条件 |
| Compaction Output / `toolContextCompactionOutputTokens` | 压缩窗口内累计输出 Token 触发阈值；0 关闭该条件 |
| Tool Result Max Chars / `toolResultSubmissionMaxChars` | 单次工具结果提交模型前的字符硬上限；不是工具实际输出文件的大小上限 |

这些压缩项管理一次运行中的工具上下文，与默认设置里的“历史对话压缩”和“节点长期记忆”分别配置。高级 JSON 还可配置当前输入阈值、模型窗口与会话压缩等后端字段，具体以配置校验为准；表单未展示的字段不应凭名称猜值。

### 高级 JSON：执行记录与整会话压缩

这组字段作用于自有 Responses 运行路径，不会改变原生 Harness 的会话实现。在对应 Provider 对象中编辑，保留其他字段并保存，再用新任务验证。

| 字段 | 默认/约束 | 用途 |
| --- | --- | --- |
| `agentStepLedgerEnabled` | false，布尔值 | 开启节点 `agent_steps.jsonl`，记录模型请求、重试、工具开始/结束及最终回答 |
| `modelContextWindowTokens` | 正整数，按实际模型窗口设置 | 提供压缩判断的上下文窗口，不会自动探测服务商上限 |
| `sessionContextCompactionEnabled` | false，布尔值 | 开启请求前整会话 checkpoint；开启时必须配置模型窗口 |
| `sessionContextCompactionThresholdPercent` | 80，1–100 | 达到窗口压力阈值时尝试整理较早完整前缀 |
| `sessionContextCompactionRetainPercent` | 16，1–100 | 整理后期望保留的近期会话比例，边界保留工具调用配对 |
| `sessionContextCompactionMaxAttempts` | 3，1–5 | checkpoint 不符合严格结构时的最大提交次数，耗尽后明确失败 |
| `toolContextCompactionCurrentInputTokens` | 0，非负整数 | 按最近请求输入 Token 数触发工具上下文压缩；0 关闭此固定条件 |
| `toolContextCompactionContextPercent` | 1–100 | 与模型窗口配合按当前输入占比触发；配置时固定当前输入阈值须为 0 |
| `toolContextCompactionReplacementMaxChars` | 50000，至少 4000 | 工具 replacement history 的字符预算 |

Step ledger 记录工具副作用边界。如果工具开始后进程退出且没有结果记录，恢复会把结果标为未知，要求先核验外部状态；不能据此重放所有命令。整会话压缩临时使用 `compact_session_context` 提交结构化检查点，原始历史与 ledger 保留。工具压缩则使用 `compact_tool_context`，主要替换已完成工具历史。

这两种运行内压缩、默认设置的跨轮历史摘要、长期记忆是不同机制。先验证基本对话和工具任务，再逐个启用；遇到协议校验错误应修正字段，不添加其他客户端的同名配置来绕过。

### 多模态和语音

`supportmode` 表单提供 `chat`、`image_generation`、`image_matting`、`vision_understand`、`video_generation`、`video_change_person`、`model_generation`、`model_texture_generation`、`audio_generation`。节点会按 Provider 能力显示相应的尺寸、参考图、音色等字段。聊天图片作为多模态输入，不需要另造一个图片聊天模式。

普通 Agent 的主模式为 chat、图片生成、视频生成、音频生成、视觉理解；抠图、视频换人、3D 与贴图另有专用节点。按创建菜单选择对应节点，不能仅勾选一个 supportmode 就期待普通聊天节点完成所有媒体协议。

豆包音频相关配置可能额外显示：

| 字段 | 作用 |
| --- | --- |
| X-Api-Key Name | 豆包语音数据面的独立 Key 别名，不能用通用 API Key 自动替代 |
| Speech Access Key ID Name | 语音控制面签名 AK 的引用名 |
| Speech Secret Access Key Name | 语音控制面签名 SK 的引用名 |
| AI 音视频应用 AppId | RTC 应用 ID；AppKey 由后端查询，不在浏览器填写 |

在 **Doubao Speech Management** 中，选择操作后核对 JSON payload，再点击 Run operation。当前有内置音色列表、训练克隆音色、查询、升级和设计音色五种操作。克隆时选择音频文件，前端上限 10 MB；根据服务要求补齐 speaker ID、文本与参数。Reset payload 恢复该操作模板。操作会调用真实服务，结果与错误显示在面板，成功读取音色后可写入 `config/audio_speaker.json`。先保存 Provider 的授权与连接，再执行管理请求。

节点的聊天语音选择也使用节点自己的 Provider、Model、Voice 字段；当前 OpenAI 语音支持条件由 `src/voice_settings.py` 校验。没有独立全局语音菜单时，在节点配置中检查，不要修改过时的全局语音项。

### WorkBuddy 连接

选择 WorkBuddy 类型后显示本机服务与账号面板，不使用通用 API Key 表单：

1. 先保存 Provider，再安装服务依赖，等待作业成功。
2. 核对本机端口，使用“保存服务设置”保存；需要时勾选随 AgentPark 启动。
3. 点击启动服务，再点击“使用本机服务地址”，保存更新后的 Provider。
4. 登录 WorkBuddy，打开返回的授权页，在五分钟有效期内完成授权；面板会自动检测结果。
5. 点击刷新账号与模型，可搜索模型 ID、筛选明确标为免费者，单独加入模型或加入全部模型。
6. 保存 Provider 后在节点选择 Model，再验证请求。停止服务会中断使用它的请求；退出此服务账号和停止进程是两个动作。

卡片显示模型的上下文、输出上限、图片支持、思考强度及服务返回的计费/活动说明。费用未知不会被标成免费，活动说明不保证长期有效。安装与运行日志路径直接显示在面板，排错见 [WorkBuddy](../workbuddy.md)。

### 常见问题

| 问题 | 检查顺序 |
| --- | --- |
| 保存成功但推理 401 | Key/账号存在 → 当前账号绑定 → OAuth 状态 → 服务端权限 |
| 模型不出现在节点选项 | Provider 已保存 → Models 非空 → supportmode 匹配 → 私有/远程可见性 |
| 参数被拒绝 | Type 和协议 → 提供商测试的 unsupported / inconclusive → 当前模型支持范围 |
| Responses 工具续聊出错 | reasoning 回放支持 → 工具结果限制 → 原始请求错误与审计 |
| 等待很久 | Pressure 的排队与限流 → 请求空闲超时 → 上游生成状态 |

<a id="harness"></a>
## Harness

入口：**Settings → Harness**。这里管理原生 Agent 软件，区别于配置一个模型 HTTP 连接。

### 安装与验证流程

1. 找到目标运行时卡片，点击 **Check**，核对版本、来源、包名、可执行路径与错误。
2. 未安装时点击 **Install**；已由项目管理的安装可重装。等待作业完成，展开输出查看真实安装结果。
3. 完成该运行时要求的原生登录；OpenCode/Antigravity 的账号不由 AgentPark Provider 表单代管。
4. 返回画板创建对应类型节点，填写该类型要求的模型、工作目录和执行选项。
5. 先验证简单对话，再验证一次明确的文件读取；命令执行还需匹配权限模式。

| 卡片 | 节点类型 | 模型与会话方式 |
| --- | --- | --- |
| Codex | `codex_node` | 现有 app-server 适配，保留原生会话与权限映射 |
| Claude Code | `claude_node` | 现有 SDK 适配，保留其会话与权限规则 |
| OpenClaw | `openclaw_node` | 选择 AgentPark Provider/Model；本地 CLI 最终 JSON 输出，不提供同等细度的实时 delta |
| DeepSeek Harness | `deepseek_harness_node` | Provider/Model 绑定，ACP 会话 |
| MiniMax Code | `minimax_code_node` | Provider/Model 绑定，ACP 会话与原生 permission mode |
| Pi | `pi_node` | Provider/Model 绑定，原生 JSON stream 和节点历史 |
| Hermes Agent | `hermes_agent_node` | 独立 Python 环境中运行真实 SDK，使用当前 Provider/Model 绑定 |
| OpenCode CLI | `opencode_node` | 原生 `provider/model` 目录、原生 agent 与 effort，不选择 AgentPark Provider |
| Antigravity CLI | `antigravity_node` | 原生 Google 登录与模型目录，不经过 AgentPark Provider 网关 |

OpenCode 与 Antigravity 卡片可刷新原生模型列表，节点必须选择实际可用的 ID。原生模型免费或付费状态由运行时提供方决定，不承诺某个内置默认一直可用。

### 升级、卸载和工作目录

- **Check** 可报告新版本；升级按钮仅在支持且有可用升级时开放。运行中的节点与安装作业互斥，先结束相关执行。
- 来源显示 managed 时由项目管理；external 表示外部安装。卸载仅对允许由项目删除的安装开放，不能通过卡片随意删除外部环境。
- 失败时检查作业输出、实际 Python/Node 版本和安装路径，不把“已创建进程”当作已可用。
- 普通新 Harness 的空工作路径会使用节点所属的隔离工作区；显式工作目录应已存在。原生工具与 Skill 发现由该运行时负责，不自动复制 AgentPark 的项目能力。
- 节点会话保存在节点 `.harness/` 及相应原生运行时存储中。卸载软件不等于清空会话；清空节点历史对各类型的具体影响见专题。
- 部分 Harness 需要 Developer 身份，且无法在 headless 协议中完成交互审批或问卷。出现明确拒绝时，按运行时文档配置可支持的执行模式。

进一步阅读：[通用 Harness](../harness.md)、[OpenCode](../opencode-harness.md)、[Antigravity](../antigravity-harness.md)、[提供商测试](diagnostics.md#provider-test)。
