# 节点长期记忆

每个节点拥有独立的对话上下文和长期记忆空间。回答或错误落盘后，后台检查对话历史预算，超过预算时压缩较早内容；下次发送直接恢复有效续聊摘要和后续原文。长期记忆从该节点的完整任务历史提取，自动注入小摘要，引导模型按需读取来源。

## 主路径和数据契约

```text
节点 messages.jsonl + archive/*/messages.jsonl
    → Source（trace_id、消息 ID、时间、内容指纹、完成状态）
    → 阶段一：逐任务提取 rollout_summary / rollout_slug
    → 阶段二：合并有效摘要、显式更正和来源变化
    → memory_summary.md + 来源摘要 + 发布清单
    → 下次模型输入：对话续聊摘要 + 未压缩的后续消息 + 长期记忆小摘要
    → search_node_memory / read_node_memory 按需补充证据
```

源码边界：

| 模块 | 责任 |
|---|---|
| `src/long_term_memory/contracts.py` | Source、Extraction、Consolidation、MemoryModel；严格 JSON 字段、类型、预算、来源 ID 校验 |
| `sources.py` | 从活动与归档历史读取证据，以 trace_id 分组；没有 trace_id 的旧记录按用户消息分组 |
| `store.py` / `artifacts.py` | 节点 SQLite、来源指纹、笔记、遗忘排除、原子发布与旧产物清理 |
| `jobs.py` | 跨进程租约、心跳、失效回收 |
| `pipeline.py` | 提取、无产出记录、失败重试、来源选择、合成、版本检查 |
| `model.py` / `prompts/` | 使用配置的 AgentProfile 预设；隔离临时上下文；后台请求不装载节点工具、不写入节点历史 |
| `retrieval.py` / `tools.py` | 字面关键词搜索、分页读取摘要或原始记录、显式更正、按来源遗忘 |
| `service.py` | 输入时注入与调度，任务持久化后的后台调度；进程内最多两个工作线程 |
| `lifecycle.py` | 清空派生记忆、移动节点时验证与更新所有权 |

SQLite 位于 `<节点目录>/long_term_memory/state.sqlite3`，保存来源、摘要、使用计数、笔记、排除项、任务租约和执行状态。当前文件版本由 `owner.publication` 指向 `generations/<版本>/`，包含 `memory_summary.md`、`manifest.json` 和 `<source_id>.md`。模型不能决定这些路径。

摘要必须以 `v1` 开始，包含 User Profile、User preferences、General Tips、What's in Memory 四个部分，最多 10,000 个 UTF-8 字节。单任务提取最多 9,000 字节。来源指针格式为 `memory:<64位十六进制ID>`；读取工具只接收原始 64 位 ID，不含前缀。

## 注入和生命周期

### 当前对话上下文

入口为 **设置 → 默认设置 → 当前对话上下文**，保存在 `conversationContext`。旧的 `agentNode.historyMessageLimit` 已退出运行路径与设置表单。普通 Agent 节点以节点历史作为连续对话，不按一次触发切断；清空记忆开始新的空白历史。GUI Agent 的独立动作循环不使用这个普通聊天加载器。

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `input_tokens` | 24000 | 历史上下文预算，仅用于历史保留和摘要分段，不限制当前输入 |
| `retain_tokens` | 6000 | 压缩时保留的连续近期原文预算，尽量从用户消息开始 |
| `summary_tokens` | 2000 | 续聊摘要上限 |
| `profile_id` | `DouBao` | 对话压缩 AgentProfile 预设，读取其 Provider、模型、思考参数和指令 |

当前工作区将 `summary_tokens` 设为 4000、`profile_id` 设为 `GPT`；表中保留程序默认值。

历史预算沿用现有会话压缩的 UTF-8 字节数 / 4 估算，非实际 tokenizer 计数，不自动探测模型窗口。压缩时预留摘要输出空间；首次接入的长历史按预算分段合并，未静默丢弃超大记录的剩余内容。当前输入、附件、工具定义、指令及恢复上下文不计入历史预算，不会根据其大小拦截输入，也不参与旧历史压缩。供应商运行时继续负责实际请求的上下文管理。摘要模型返回不符合契约时明确报错并保留历史，不退回固定条数截断。

每轮普通 Agent 回答或错误落盘后，由 `nodes/agent_history_background.py` 调度后台预算检查；未超预算不调用模型，超预算则生成摘要。检查以刚落盘的消息 ID 为历史边界，不把后续新输入或工具记录卷入本次压缩。`src/conversation_context/jobs.py` 合并同一节点的待处理检查；后台最多使用两个工作线程。

`nodes/agent_history.py` 读取活动与归档历史；`src/conversation_context/window.py` 在后台选择待压缩前缀并生成严格 JSON 摘要。发送路径只恢复有效检查点及后续原文，不等待或调用压缩模型。后台尚未完成、摘要失效或后台失败时，原始历史仍会发送给 Provider；若超过实际模型窗口，Provider 可明确拒绝该请求。工具审计记录作为有标记的历史证据恢复，不伪造成缺少配对调用的工具协议消息；明确标记排除的运行时上下文不回放。历史图片仍按原加载器转为引用，当前输入的图片保持原发送协议。

节点目录中的 `conversation_checkpoint.json` 保存被摘要的前缀条数、内容指纹和续聊摘要。下次输入恢复摘要与后续原文，不依赖长期记忆的一小时门槛，也不重复整理同一前缀。历史被修改/删除后指纹不匹配，旧摘要失效。最终发布与历史编辑、ClearMemory 共用事务锁，阻止清空后的旧结果回写；清空时删除该文件。原始 `messages.jsonl` 与归档始终保留到用户清空或删除历史。

这对应 Codex 的持久化上下文与压缩方向，但使用 Provider 通用的摘要调用，不是 Responses `/compact` 或 Codex 的不透明压缩项。单次长工具执行继续使用已有 Provider 会话压缩机制；其启用状态和阈值仍由 Provider 配置控制。长期记忆的检索与整理独立运行。

实测：`python -m scripts.compare_conversation_context` 使用 54 条独立合成消息，真实 `GPT_Official` 调用中，旧最近六条方案 0/4，压缩并恢复后 4/4，覆盖原始标识、更正、失败状态和下一步。恢复后的窗口与首次压缩结果完全一致，估算 1,227 token；完整结果在 `artifacts/conversation-context-comparison/`。这是一次定向验收，不代表所有长对话均能无损压缩。本次相关自动测试共 222 项通过，前端构建通过，重启后已在实际设置页确认新字段和值。

### 长期记忆

- 普通 Agent 节点自动获得摘要与四个节点限定工具。摘要以 `persist=False` 注入，Responses 的历史重建会排除已持久化的旧摘要，避免重复累积。
- GUI Agent 保持固定动作协议，只注入小摘要，不安装其协议无法调用的检索工具。图片、视频等生成节点可积累自己的任务摘要，但不向其媒体生成协议添加自然语言检索工具。
- 输入时和任务持久化后尝试后台处理；没有额外的定时唤醒。新完成的任务达到空闲阈值后，在后续触发时进入提取。当前正在处理的 trace 不参与输入时启动的提取。
- 输入未变且已有成功摘要时不重复提取；无价值的历史标为 `no_output`；错误记入 sources/runs/jobs，带明确重试时间，不伪装为成功。
- 历史被更正或删除时撤销旧发布并清理旧派生产物。后台推理期间若历史或笔记版本变化，拒绝发布旧结果，下一次触发可以重试。
- `add_node_memory_note` 用于用户明确要求的记住或更正；笔记进入下一次合成。`forget_node_memory` 立即排除指定来源，并阻止相同 trace 重新进入记忆。原始聊天仍由历史管理功能保管。
- 清空节点历史同步清空其派生记忆和笔记。设置页的“Clear long-term memory”只清空所有节点的派生记忆和笔记，保留原始聊天，后续可重新提取；已明确遗忘的来源仍保持排除。
- 移动节点保留其记忆并更新所属图；后台合成持有租约时拒绝移动，防止目录移动破坏正在写入的数据。
- 记忆工具不接受 graph_id、node_id 或路径参数。这是记忆命名空间隔离；不会改变节点原本已有的通用文件工具权限。

## 与 Codex 的对应关系

参考本机 `C:/Project/codex`，提交 `82d4a989124d6786b1145f871a7ca610cdc220a4`：

| Codex 源码 | 对应实现 |
|---|---|
| `codex-rs/memories/write/src/start.rs`，`start_memories_startup_task` | 节点输入时启动符合条件的历史处理 |
| `codex-rs/memories/write/src/phase1.rs`，`run`、`prune`、逐来源工作任务 | 分任务提取、空闲/年龄筛选、无产出与重试 |
| `codex-rs/memories/write/src/phase1_output.rs`，`StageOneOutput::parse`、`SummaryOutput` | V2 的 rollout_summary / rollout_slug 契约 |
| `codex-rs/memories/write/src/phase2.rs`，`run`、claim/succeed/failed | 来源选择、增量合成、后台任务租约 |
| Memory V2 的提取与合成提示词 | 高价值信息、证据分级、更正优先、小摘要与来源导航 |

采用 V2，不保留 V1 的 raw_memory 分支。核心机制与 Codex 对齐，执行环境按 AgentPark 改造：Codex 的合成 Agent 可在记忆工作目录操作文件；这里用无工具的模型请求返回严格 JSON，由宿主校验、写文件并通过 SQLite 版本检查发布。没有引入 Git 工作区、跨节点检索或独立向量数据库。结构化输出采用提示词约束与宿主严格解析，未要求所有 Provider 支持同一种原生 JSON Schema API。

因此这是根据 Codex 开源机制实现的节点版本，不是 ChatGPT 服务端 Memory/Dreaming 的复刻。

## 配置与运行

界面入口为 **设置 → 默认设置 → 节点长期记忆**。常用配置直接显示，输入预算、租约和重试间隔位于可展开的高级选项。修改后使用页面顶部的“保存”；界面默认值由后台 `MemorySettings` 提供，保存接口按相同契约校验。

设置保存在 `config/config.json` 的 `longTermMemory` 中，供各节点共用处理策略；节点记忆仍各自隔离。当前已启用，`extract_profile_id` 和 `consolidation_profile_id` 均默认引用 `DouBao` AgentProfile。对话压缩的 `profile_id` 同样默认引用 `DouBao`。三项设置必须指向存在的 `agent_node` 预设，不接受旧 Provider 字段，也不回退到节点 Provider。每次模型调用读取预设最新的模型、思考参数和指令；内部任务保持无工具、无联网搜索和严格 JSON 输出契约。

保存后下一次后台检查读取新配置，无需重启；已启动的任务继续使用启动时的配置。空闲时间是提取门槛，没有到点自动整理的定时器。关闭长期记忆不会删除已有记忆，也不会取消已经启动的后台任务。

| 配置 | 默认值 | 含义 |
|---|---:|---|
| `min_idle_seconds` | 3600 | 完成任务至少空闲一小时后才提取 |
| `max_age_days` | 30 | 首次提取的历史年龄上限 |
| `max_unused_days` | 30 | 未使用来源的记忆保留窗口；读取刷新使用时间 |
| `max_extractions` | 8 | 每次最多提取的任务数 |
| `max_selected` | 64 | 每次合成最多选择的来源数 |
| `input_bytes` | 180000 | 单来源输入预算；超出时明确报错，不静默截断 |
| `consolidation_bytes` | 240000 | 合成输入预算 |
| `lease_seconds` | 180 | 自动续约的工作租约 |
| `retry_seconds` | 3600 | 模型/协议错误的重试间隔 |

后台模型请求计入配置 Provider 的用量，归属节点和 `memory:<phase>` 任务。失败可在节点 SQLite 的 runs、sources、jobs 以及后台日志中定位。摘要与搜索结果依赖历史记录，并不自动证明历史中的成功声明；精确信息可读取原始消息证据。

## 旧方案退出

删除 Note/Hobbit/Soul 三个整理器、operational memory 工具与实现、旧 SQLite 试验实现及旧清理脚本。Companion 保留审查职责，停止代写其他节点记忆。更新现有模板、事件规则、上下文诊断及设置页清理入口。

`python -m scripts.migrate_node_memory --apply` 是显式的一次性配置迁移命令，清理配置中的旧触发器、旧摘要注入和旧工具，不删除原始历史，也不把旧派生文件继续作为新的输入。已在本工作区执行；重复执行没有变化。新建节点直接走新主路径。

## 对比测试

复现命令：

```powershell
python -m scripts.compare_node_memory --provider GPT_Official --output artifacts/node-memory-comparison-new
```

测试使用合成历史，不导出真实用户历史。五个较早任务提供缓存前缀、备份桶及后续更正、失败迁移和明确偏好，再加入三十组无关对话，使最近六条消息不包含这些旧事实。两组使用同一个 Provider、相同问题、相同近期消息；实验组增加生成的摘要和最多六轮检索/回答。

`artifacts/node-memory-comparison/results.json` 保存答案、检索请求、返回证据、摘要和评分；`report.md` 为结果表。测试问题固定为远期事实、更正优先、失败/成功区分和项目范围。另验证删除来源后摘要、搜索、直接读取均失效。

问答驱动使用显式 JSON action 循环调用正式 MemoryReader，并将工具错误反馈给模型；不是浏览器端到端测试，也不是各 Provider 原生 function calling 的横向评测。评分是这些确定答案的验收检查，不是通用模型能力分数；字节统计不等同于计费 token。

自动测试另覆盖档案读取、节点隔离、来源变化、显式遗忘、竞态拒绝发布、错误重试、租约回收、保留期、摘要注入、节点移动和清空。普通单元测试禁用真实付费后台调用，记忆集成测试显式启用并替换模型边界。

### 本次实测结果（2026-09-09）

两次独立的合成历史运行均为：仅近期历史 1/4，加入长期记忆 4/4；删除检查均通过。最终运行提取五个任务，无提取失败，摘要 1,721 个 UTF-8 字节，整套模型调用耗时 269.8 秒。

| 检查 | 仅近期 6 条 | 节点长期记忆 |
|---|---|---|
| 较早任务的缓存前缀 | 不知道 | 正确找回 lm_orchid_739 |
| 采用更正后的备份桶 | 不知道 | archive-east-862 |
| 失败迁移是否完成 | 无记录 | 未完成，并指出 E_LOCK_47 |
| 不把 Lumen 约定移用到 Orion | 正确表示不知道 | 正确表示不知道 |

最终回归套件 322 项通过，其中节点长期记忆专项 22 项。覆盖记忆及其连接的历史、事件、Provider、GUI Agent 和设置接口；前端 vue-tsc 与 Vite 构建通过。AgentPark 已重启，页面 HTTP 200；新接口 /api/node-memory/clear-derived 已加载，旧接口已移除。测试结果与真实模型结果分别验证工程契约和这组历史问答表现。
