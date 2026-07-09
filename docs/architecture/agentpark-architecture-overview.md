# AgentPark 项目架构梳理(已更新)

> 范围: 仓库 `C:\Project\AgentPark` 顶层 + 后端 `src/` + 节点 `nodes/` + 前端 `webui/` + 公共资源/脚本
> 资料: 关键入口源码(`src/fast_api.py`、`src/cli.py`、`src/web_backend/__init__.py`、`src/web_backend/facade.py`、`src/web_backend/core.py`、`src/web_backend/route_registry.py`、`src/web_backend/agent_domain.py`、`src/capabilities/registry.py`、`src/capabilities/types.py`、`src/channels/service.py`、`src/provider_feature_matrix.py`、`src/config_loader.py`、`nodes/base_node.py`、`nodes/agent_node.py`、`webui/src/api.ts`、`README.md`、`AGENTS.md`)均已通读
> 验证: 8 份 `docs/*.md` 契约文档(架构总览/config-contract/runtime-state-machine/provider-feature-matrix/capability-system/skill-plugin-authoring/long-term-architecture/troubleshooting)对齐一致

---

## 1. 项目定位

Agent / Tool / Graph **可视化构建 + 运行 + 分享平台**,理念是 "local-first → 生态化"。
工程约束写在 `AGENTS.md`: 优先清晰架构与长期扩展性、禁止 heuristic 兜底、禁止静默降级、>400 行文件按职责拆分、UTF-8、PowerShell/Windows 主环境。

主要运行环境: Windows + Python 3.11+ + Node.js + ripgrep(`build_and_run.bat` / `Restart.bat` / `package.bat` / `uninstall.bat` / `sync_public_repo.bat` 在根目录)。

---

## 2. 顶层目录速览

```
AgentPark/
├─ config/          服务/Provider/Events/PastAgent/ProviderLimit/Remote/ModuleProvider 配置(config.json 默认 port=8788)
├─ nodes/           32+ 可视化节点实现(BaseNode + Agent / GUI Agent / 图像·视频·模型生成 / trigger / loop / multi_input / channel / save_file / console_command / …)
├─ functions/       20+ Agent 工具模块(file / code / shell / network / memory / curl / capability_management / gui_agent / parallel / user_interaction / skill_resource / operational_memory / console / rg / multi_tool_use / …)
├─ src/             FastAPI 后端 + Provider + Tool + Runtime Event + CLI + Channels + MCP
├─ webui/           Vue 3 + Vite 前端(desktop + mobile + pet + settings)
├─ memories/        图/节点持久化 memory(Companion 为默认保护图)
├─ skills/, plugins/  节点级可插拔能力资源
├─ tests/, docs/, scripts/, logs/, resource/, graph/, prompt/, agent/, petAvatars/
└─ *.bat            启动/重启/打包/卸载/同步脚本
```

---

## 3. 后端架构(Python · FastAPI)

### 3.1 启动链路
1. `python -m src.fast_api`(`build_and_run.bat` 入口)→ `src/fast_api.py::main`
2. 子命令分流: 首参数是 `doctor/capabilities/config/chat` 时转交 `src.cli`;否则进入服务器模式
3. 读取 `workspace_settings` 决定 host/port、`find_available_server_port` 找可用端口、写入 PID 文件
4. 调用 `src.web_backend.create_app()` 构造 FastAPI 实例
5. 启动 uvicorn 并装配: `Ignore200OKFilter`、desktop pet 进程退出监听、5s 强制退出兜底、`start_frozen_parent_exit_monitor` / `start_env_parent_exit_monitor`

### 3.2 应用工厂与路由注册
- `src/web_backend/__init__.py::create_app(tool_names)` → `WebBackendFacade(tool_names).build()`
- `WebBackendFacade` 持有 `BackendCore`(全部子系统聚合器)、FastAPI 实例、Companion MCP、CORS / Private-Network 中间件
- 启动 lifespan: `_recover_node_runtime_state_on_startup` → `runtime_events.startup` → `_ensure_timer_trigger_scheduler` → `channel_service.start_autostart_receivers` → 可选的 desktop pet 延迟恢复
- **路由集中表** `src/web_backend/route_registry.py::ApiRouteRegistry.ROUTES`: 95+ 条 `(method, path, resolver)` 元组,`register()` 一行 `getattr(app, method_name)(path)(handler)` 批量挂载;channel 路由通过 `channel_http_endpoint` 包装
- handler 通过 `core.<子域>.<方法>` 引用,例如 `core.node_ops.run_node` / `core.graph_api.start_graph_runner` / `core.settings_api.get_provider_pressure`

### 3.3 BackendCore 聚合的子域(`src/web_backend/core.py`,71 行)
| 字段 | 类型/职责 |
|---|---|
| `tool_names` | 工具白名单(透传给 MCP companion) |
| `node_runs` | 节点异步 run 跟踪表 |
| `mp_ctx` | `multiprocessing.get_context("spawn")` |
| `graph_runners` + `graph_runners_lock` | 图运行线程/状态注册表 |
| `timer_scheduler_thread/stop/lock` + `timer_trigger_last_fired` | 定时触发器调度 |
| `node_cancellations` | `NodeCancellationRegistry` 取消令牌池 |
| `node_live_outputs` | `NodeLiveOutputStore` 节点实时输出流 |
| `graph_events` | `GraphEventStreamStore` 图事件 SSE |
| `provider_limit_jobs` | `ProviderLimitJobStore` Provider 探测 job 池 |
| `reserved_node_fields` | 节点 config 中保留的字段集合(含所有 `RUNTIME_STATE_FIELDS`) |
| `graph_runtime` | `GraphRuntimeDomain` 图调度域 |
| `channel_service` | `ChannelService`(IM 接收器编排) |
| `agent_domain` | `AgentDomain`(agent 子智能体、paste-agent、prompts 库) |
| `node_ops` | `NodeOpsDomain` 节点 CRUD/run/config |
| `graph_api` | `GraphApiDomain` 图 CRUD/runner/UE |
| `profile_api` | `ProfileApi` agent/graph profile 持久化 |
| `mobile_api` | `MobileApiDomain` 移动端 API |
| `node_desktop_views` | `NodeDesktopViewDomain` 桌面宠物视图 |
| `pet_avatars` | `PetAvatarDomain` 宠物形象资源 |
| `remote_api` | `RemoteApiDomain` 远端实例 |
| `settings_api` | `SettingsApiDomain` settings + provider 压力/限额 |
| `user_interaction_api` | `UserInteractionApiDomain` 用户交互请求 |
| `runtime_events` | `RuntimeEventDomain` 事件引擎 |
| `system_api` | `SystemApiDomain` 文件/Provider/重启 |

### 3.4 关键子包结构(已实测)

**`src/web_backend/`(83 文件,按职责细粒度拆分)**
- 核心装配:`__init__` `core` `facade` `core_graph_api` `core_graph_runtime` `core_node_ops` `core_system_api` `service_host` `shared` `domain_base` `route_parser`
- 节点域:`node_catalog` `node_config_service` `node_config_errors` `node_runtime` `node_runtime_event_sink` `node_runtime_fields` `node_state_machine` `node_async_runs` `node_cancellation` `node_request_tracking` `node_live_output` `node_tool_history` `node_event_sequence` `node_metadata_reader`
- 节点实例:`node_instance_runtime` `node_instance_registry` `node_instance_queue` `node_instance_artifacts` `node_instance_deletion` `node_deletion` `node_goal_runtime`
- 记忆:`node_memory_store` `node_memory_records` `node_memory_paths` `node_memory_archive` `node_memory_markdown` `node_memory_limits` `node_memory_errors` `runtime_state_memory_store`
- 图运行:`graph_runner_runtime` `graph_runner_state` `graph_runtime_registry` `graph_node_execution` `graph_node_store` `graph_message_dispatch` `graph_event_stream` `graph_output_routes` `graph_schedule_registration` `graph_timer_scheduler` `graph_api_storage`
- Agent 域:`agent_domain`(28 行,已拆,内含 `PasteAgentSettings` + `PromptLibrary` 两个 service target)
- 移动/桌面/MCP/Profile/Pet:`mobile_api` `node_desktop_view` `node_desktop_pet_launcher` `pet_avatar` `pet_avatar_schema` `profile_api` `profile_storage` `companion_mcp*`(8 个 MCP 编排文件) `companion_capabilities` `companion_node_summary` `paste_agent_settings` `user_interaction_api` `remote_api` `prompt_library` `clock_runtime`
- 调度:`scheduled_node_registry` `scheduled_node_index` `scheduled_node_config_cache`
- 运行时/事件:`runtime_event_store` `runtime_paths` `state_store`
- 频道:`channel_api`(HTTP 端点)+ `src/channels/service.py` 业务服务

**`src/providers/`(65 文件,LLM 适配层)**
- 公共:`instructions` `provider_errors` `provider_pressure` `provider_runtime_events` `provider_stream_emit` `sse_debug` `tool_call_execution` `tool_call_runtime` `tool_feedback` `tool_loop_guard`
- 上下文与协作:`agent_collaboration_mode` `agent_context_history` `agent_environment_context` `agent_permissions_context` `agent_project_instructions` `agent_runtime_context` `agent_turn_context` `mid_turn_user_inputs`
- OpenAI Responses 协议栈(单独 16 文件):`responses_*` (mapping/payload_analysis/payload_log/request_summary/empty_message/followup/image_input/input_items/item_runtime/runtime/runtime_context/runtime_loop/runtime_methods/runtime_mode/runtime_protocol/stream_events) + `openai_responses_stream_normalizer` + `responses_websocket_transport`
- 各 Provider 实现:
  - OpenAI:`openai_agent` `openai_chat_runtime` `openai_curl_transport` `openai_mapping` `openai_responses_runtime` `openai_transport` `openai_transport_errors`
  - Doubao:`doubao_agent` `doubao_agent_common` `doubao_curl_stream_transport` `doubao_http_transport` `doubao_image_generation` `doubao_responses_mapping` `doubao_responses_runtime` `doubao_stream_runtime` `doubao_tool_runtime` `doubao_video_generation`
  - Gemini:`gemini_agent` `gemini_function_runtime` `gemini_image_generation` `gemini_stream_runtime`
  - Claude:`claude_agent` `claude_chat_runtime` `claude_message_ordering` `claude_stream_runtime`
  - Zhipu:`zhipu_agent` `zhipu_chat_runtime` `zhipu_http_transport`
  - Hyper3D:`hyper3d_agent` `hyper3d_common` `hyper3d_rodin_runtime` `hyper3d_runtime_base` `hyper3d_texture_runtime` `hyper3d_transport`
  - 其它:`wan_animate_mix_runtime` `curl_transport`

**`src/runtime_events/`(event_engine/event_registry/event_models/metrics/node_dispatch/context_store/event_config_store)**
- 事件引擎 + context 注入 + 编译诊断

**`src/cli_commands/`(17 文件)**
- 4 主命令:`chat.py` `doctor.py` `capabilities.py` `config.py`(`src.cli` 派发)
- 通用:`common.py` `__init__.py`
- Companion 系列 12 个:`companion_console` `companion_debug` `companion_inbox_watcher` `companion_markdown_render` `companion_prompt` `companion_restart` `companion_style` `companion_terminal` `companion_tool_render` `companion_tui` `companion_tui_render`

**`src/capabilities/`(4 文件)**
- `registry.py` 283 行 `CapabilityRegistry.discover/discover_payload/validate_requested` + `_options/_mcp_descriptors/_skill_descriptors/_plugin_descriptors`
- `types.py` 43 行 `CapabilityDescriptor` + `CapabilityRef` dataclass
- `discovery_cache.py` 短 TTL 缓存 + 显式 invalidate
- `__init__.py` 导出

**`src/channels/`**
- `service.py` 468 行 `ChannelService`(线程池+账号 poll+receiver 路由)
- `receiver_models.py` `ReceiverConfigRef/Key/RuntimeConfig/RoutedEnvelope` dataclass
- `receiver_routing.py` `envelope_receiver_command/normalize_receiver_name/route_receiver_envelope`
- `errors.py` `ChannelConfigError`
- `weixin/`(driver/media/storage) — OpenClaw Weixin 通道实现

**`src/mcp/`** `lifecycle.py` — MCP 生命周期快照

**`src/tool/`** `base_tool.py` `tool_call_protocol.py` `tool_event_protocol.py` `tool_module_loader.py` `tool_stats_store.py`

**顶层设施** `base_agent.py` `base_planner.py` `base_memory.py` `base_agent_manager.py` `message_protocol.py` `node_stream_protocol.py` `node_capabilities.py` `node_config_overlay.py` `node_run_companion.py` `runtime_cancellation.py` `service_host.py` `provider_feature_matrix.py` `provider_model_discovery.py` `provider_limit_*`(schema/probe/jobs/static_contract) `provider_limit_doubao/claude/hyper3d`

### 3.5 节点层(`nodes/`,32 顶层 + `agent_support/`)
- **`nodes/base_node.py`** 197 行 `BaseNode`: 单一基类
  - `common_config_defaults/schema = {plugins, skills, working_path}`(全节点通用)
  - 子类 `config_defaults/config_schema` 自由扩展
  - `_resolve_memory_path/_resolve_messages_path` → `memories/<graph>/<node>/memory.md` & `messages.jsonl`
  - `_persist_input_default` 自动落盘 user 输入
  - `on_input` 默认实现(子类基本都覆盖)
  - `get_capabilities()` → `NODE_CAPABILITY_LIST.parse(input_capabilities/output_capabilities)`
  - `get_config_schema(context)` 动态注入 `skills/plugins` 的 `options`(调用 `CapabilityRegistry().discover_payload(context)`)
- **`nodes/agent_node.py`** 440 行 `Node`: 只做编排,所有能力委托给独立模块
  - 编排管线:`load_agent_node_run_request` → `resolve_agent_capabilities` → `create_agent` → `bind_agent_runtime_context` → 注入 instruction / operational memory / MCP context / skills / goal / runtime events / history → `stream_runtime.send` → `build_agent_output_message` → 写回
  - 子模块:agent_node_config / agent_node_settings / agent_stream_runtime / agent_tool_loader / agent_mcp_loader / agent_mcp_runtime / agent_plugin_loader / agent_plugin_tool_loader / agent_plugin_mcp_loader / agent_plugin_manifest / agent_skill_loader / agent_skill_scripts / agent_skill_dependencies / agent_message_adapter / agent_assistant_memory / agent_working_path_context / agent_support.capability_setup
  - 关键模型:`input_capabilities = [text, resource:{image,video,audio,doc,file,url}, structured, meta]`,`output_capabilities = [text, resource:{image,video}, structured, tool_call, meta]`
  - 配置:`provider_id` `instruction` `system_prompt` `mode` `collaboration_mode` `plugins` `tools` `mcp_servers` `web_search` `thinking` `reasoning_effort`
  - `get_config_schema(context)` 从 `ConfigLoader().get_all_providers()[provider_id]["features"]` 取 provider 能力,`provider_feature` 字段直接暴露给前端表单
- GUI Agent 拆为 `gui_agent_node + actions/capture/executor/markers/observation/output/prompts/run/runtime/verifier`
- 其他节点:trigger/basic_trigger_node/timer_trigger_node/clock_node/loop_node/event_node/multi_input_node/input_output_test/channel_receiver_node/channel_sender_node/echo_node/append_node/response_node/save_file_node/console_command_node/image_generation_node/video_generation_node/video_change_person_node/model_generation_node/model_texture_generation_node/...
- 节点注册:`type_id = filename` 规则;`nodes/__init__.py` 暴露 `Node` 类列表

### 3.6 Provider 能力矩阵(`src/provider_feature_matrix.py`,114 行)
- 中心函数 `build_provider_feature_matrix(provider_config)` → 每家 provider 返回带 `schema_version: 1` 的 features dict
- 5 维特性:`responses_api` `web_search` `tools` `thinking` `reasoning_effort` — 每项含 `supported/values/requires/transport`
- 表驱动(openai/doubao/zhipu/claude/gemini/其它),前端 `getNodeTemplate` / `get_provider_pressure` 走相同 shape
- `ConfigLoader` 强制 `moduleProvider.json` 不允许的字段(48 个白名单外),`responsesApi=true` 必填 `toolResultSubmissionMaxChars` + `toolContextCompactionEnabled` + `toolContextCompactionEveryToolCalls`,openai 额外要求 `responsesReplayReasoningItems`

### 3.7 数据 / 资源
- `config/config.json`(`server.port=8788`, `agentNode.minSendDelayMs=200 / historyMessageLimit=40`, `nodeMemory.maxEntries=20`, `mcpServers` 内置 4 个: ark-docs-mcp / unreal-engine-skills / asset-to-json / agentpark-companion, `consoleCommand.timeoutSec=300`)
- `config/moduleProvider.json`(provider 注册 `type: doubao/gemini/openai/zhipu/hyper3d/...` + `supportmode` + `timeoutMs`)
- `config/remote.json`、`config/events.json`(`events.json.lock` 并发锁)
- `memories/Companion/Companion/{config.json,memory.md,messages.jsonl,agent_turn_context.json,agent_context_history.json}` — Companion 默认保护图
- `agent/*.json` 预置 Agent 配置:GPT / Doubao / Doubao_CodingPlan / XYJProgrammer / Companion

---

## 4. 前端架构(Vue 3 + Vite · TypeScript)

### 4.1 入口与视图分发(`webui/src/App.vue`)
```
URL: pathname='/pet'              → <PetDesktopView />
URL: ?pet=1                       → <PetDesktopView />
URL: ?ask_here=1                  → <PetPickerView />
matchMedia('(max-width: 760px)')  → <MobileWorkspace />
其他                              → <DesktopWorkspace />
```
启动时 `syncDocumentTitle()` 通过 `listMobilePcs()` 拉取本机 PC 名作为 title。

### 4.2 API 集中层
- `webui/src/api.ts` 1035 行:**后端所有路由的 1:1 镜像**,统一 `apiFetch(path, init) = requestApiJson(readActiveApiBase(), path, init)`
- 远端覆盖: `setActiveApiBase(base)` 写入 `localStorage['agentpark.activeRemoteBaseUrl']`,后续 `readActiveApiBase()` 优先使用
- `apiTypes.ts` 定义全部请求/响应类型(GraphConfig、NodeInstanceConfig、MessageEnvelope、MobileNode、NodeDesktopView、PetAvatarFrame、RuntimeEvent…);`uploadApi.ts` / `settingsApi.ts` 为大文件/设置专用
- SSE / WebSocket URL 工厂:`graphEventsStreamUrl(graphId)`、`nodeInstanceLiveStreamUrl(nodeId, graphId)` 直接拼到 `readActiveApiBase()`

### 4.3 桌面视图
- `DesktopWorkspace.vue` + `DesktopTopbar.vue` + `AgentBoard.vue`
- `AgentBoard.vue` 把画布相关全部下沉到 `agent-board/`(40+ 文件):
  - 视图: `BoardCanvas / NodeCardItem / NodePalette / NodeSideEditor / NodePorts / NodeConfigFields / NodeConfigSection / NodeContextMenu / NodeRuntimeDiagnostics / NodeRuntimeEventsSection / WorkingPathField / ToolActivityBadge / FieldMultiSelect / NodeAgentMeta / NodeEditorInputSection / NodeOutputRoutesPanel / NodeOutputRoutesSection / AgentProfileDropdown`
  - composables: `useAgentBoard / useNodeSideEditorPanel`
  - 状态/模型: `boardLayout / Links / Model / Selection / Runtime / Clipboard / Files / DragState / NodeIdentity / NodeConfigRefresh / NodeRuntime / RuntimeRefresh / GraphPersistence / Context` + `toolRuntimeEvents / capabilitySchemaState / nodeApplySummary / CanvasContextMenu`
- 共享组件 `MemoryPanel/*`(MemoryContentView / MessageFeed / MessageActions / PanelHeader / ResourcePart / ToolCallPart / SaveDialog + memoryFeedTools / memoryMessageText / memoryMarkdown / markdownCodeCopy)

### 4.4 移动视图
- `mobile/MobileWorkspace.vue` + composable `useMobileWorkspace.ts`
- 子组件: `MobileNodeListItem / MobileNodeConfigDialog / MobileNodeCreateDialog / MobileMessageText / MobileLiveMessage / mobileMessageRender`

### 4.5 桌面宠物(Pet)
- `PetDesktopView.vue` / `PetPickerView.vue` + `pet-avatar/PetAvatarRenderer.vue` / `PetContextMenu.vue`
- composables: `usePetAvatarWindow / usePetPanelResize`

### 4.6 设置页
- `SettingsPage.vue` + `settings/` 子目录 12+ 子组件:
  Provider / Companion / Default / Pressure / ProviderTest / RuntimeEvents / ToolStats / SystemExit / AnimEditor / AnimTrackEditor / SupportModeMultiSelect / CompanionCapabilitySelect / ModuleProviderSettingsForm / CompanionSettingsForm / DefaultSettingsForm / RuntimeEventsSettingsForm

### 4.7 其他关键组件 / composables
- `FileExplorer.vue` / `FileNode.vue` / `NodeInspector.vue` / `UserInteractionDialog.vue` / `UserInteractionCustomFrame.vue`
- composables: `droppedPaths` / `nodeSchemaFields` / `useAgentNodeCreateSchema` / `useGlobalState` / `useMemory` / `useMemoryMessageExport`
- `liveActivity.ts` / `runtimeEventsConfig.ts` 实时事件总线

---

## 5. CLI 与 Channels 子系统

### 5.1 CLI(`src/cli.py` + `src/cli_commands/`)
- 主入口 `argparse` 子命令:
  - `doctor [--json]`:运行 `run_doctor`,输出 `checks[].name/status/detail/path`
  - `chat [--config/--message/--json/--plain/--backend/--debug-terminal]`:运行 `run_chat`,默认自动选 backend(prompt → win32/msvcrt → 不可用就报错)
  - `capabilities list|enable|disable [--kind tool/mcp/skill/plugin --name <id>...] [--refresh] [--json]`
  - `config validate|diff --fields <json path>`
- Companion CLI 的 `_StreamPrinter` 处理 `NODE_MESSAGE_DELTA` / `NODE_MESSAGE_DONE` / `tool_call_start/end` 事件,工具调用前后注入 `tool_call_start/end` → `messages.jsonl`
- Companion 重启:`companion_restart.RESTART_EXIT_CODE` → 触发 `Restart.bat`(不破坏 canonical startup path)
- 跨平台兼容:Windows console input echo 强制恢复(`_restore_windows_console_input_echo`)

### 5.2 Channels(`src/channels/service.py` + `weixin/`)
- `ChannelService` 是唯一一个 channel 后端,目前内置 `WeixinChannelDriver`(`CHANNEL_ID = openclaw-weixin`)
- 线程模型:`_account_pollers` 按 account_id 共享轮询线程;`stop_event` + `threading.Thread(daemon=True)`
- 接收器路由:
  - 命令路由:`envelope_receiver_command(envelope)` 提取 `@receiver_name` 前缀,找到目标 receiver 并把 `active` 标志位推过去
  - 非命令路由:同一个 account 下所有 receiver 按 `Name` 匹配分发
- 状态持久化:`state_store._set_node_config_last_message` 把最后一次消息写入 `memories/<graph>/<node>/config.json` 的 last_message 字段
- 启动: `start_autostart_receivers()` 扫描 `memories/` 找到所有 `channel_receiver_node`,按 `AutoStart` 启动
- API:`/api/channels`、`/api/channels/receivers`、`/api/channels/receivers/{graph}/{node}/control|login/start|login/wait`

---

## 6. 跨端分层关系(概览)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  webui (Vue 3)              api.ts  ──HTTP/JSON──▶  FastAPI ROUTES       │
│  App.vue → Desktop / Mobile / Pet                                          │
│       │                                                                   │
│       ▼                                                                   │
│  ApiRouteRegistry.register(app, BackendCore)                              │
│       │                                                                   │
│       ▼                                                                   │
│  BackendCore:                                                             │
│    node_ops / graph_api / settings_api / system_api / remote_api /         │
│    mobile_api / node_desktop_views / pet_avatars /                        │
│    user_interaction_api / profile_api / runtime_events /                  │
│    channel_service / graph_runtime / agent_domain                         │
│       │                                                                   │
│       ▼                                                                   │
│  Provider 适配 (src/providers)  +  Tool 协议 (src/tool)  +                │
│  Runtime 事件 (src/runtime_events) +  MCP (src/mcp)                       │
│       │                                                                   │
│       ▼                                                                   │
│  节点实现 (nodes/base_node → nodes/agent_node → 20+ 子模块)                │
│       │                                                                   │
│       ▼                                                                   │
│  资源: config/*, memories/<graph>/<node>/*, agent/*.json, skills, plugins │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 7. 关键设计要点(代码级事实)

1. **路由不再散落**:`ApiRouteRegistry.ROUTES` 用一张大表替代零散 `@app.get/@app.post`,新增/调整 API 只改这一处
2. **节点能力声明驱动 UI**:`BaseNode.common_config_schema.skills/plugins` 的 `options` 在 `get_config_schema(context)` 中由 `CapabilityRegistry().discover_payload(context)` 动态填充,前端 `useAgentNodeCreateSchema` 据此生成表单
3. **能力描述符单一来源**:`CapabilityRegistry` 返回 `{kind, id, label, version, source, enabled, dependencies, config_schema, status, diagnostics}`,webui/AI/CLI 都消费同一形状(含 `schema_version: 1`)
4. **provider 能力矩阵**:`build_provider_feature_matrix` 单点决定 webui 控件是否禁用;`ConfigLoader.PROVIDER_UNSUPPORTED_CONFIG_KEYS` 强制白名单
5. **记忆落盘路径统一**:`memories/<graph_id>/<node_id>/memory.md` + `messages.jsonl`,`agent_turn_context.json` + `agent_context_history.json` 为 Companion 专属
6. **运行时保护**:lifespan 中 `_recover_node_runtime_state_on_startup` 恢复 graphs/nodes 状态,desktop pet 走 1s 延迟线程恢复
7. **远端访问支持**:后端 `config/remote.json` + `/api/remotes/*`;前端 `setActiveApiBase` 写入 localStorage,后续请求自动切到远端 base
8. **CLI 与服务器同入口**:`src.fast_api.main` 在收到 `doctor/capabilities/config/chat` 时直接转交 `src.cli`,保持单一入口
9. **AGENTS.md 约束落地**:Agent 节点被拆为 10+ 独立模块,GUI Agent 拆为 10 个子包,`agent_node.py` 主体 440 行做编排(`BaseNode.common_config_schema` 三字段 + `config_schema` + `get_config_schema` 动态注入)
10. **schema_version 显式化**:provider feature matrix / capability registry / runtime config 都带 schema_version,迁移可见
11. **OpenAI Responses 协议独立成栈**:`src/providers/responses_*.py` 16 个文件 + `responses_websocket_transport` + `responses_stream_events`,把 `responsesApi=true` 的所有 openai/doubao 适配共享
12. **能力修改 take effect: next_agent_run**:UI/CLI 显式标注,不假装 hot reload
13. **P3 侧车预留**:`docs/long-term-architecture.md` 明确"不重写,Rust 侧车只用于 process supervision / file watching / capability indexer",协议 JSON over stdio / JSON-RPC

---

## 8. 模块级"行数"快查(已确认)

| 模块 | 行数 | 备注 |
|---|---|---|
| `nodes/agent_node.py` | 440 | 编排文件,**已超过 400 红线**,可考虑进一步拆解为 capability_setup / instruction_inject / output_assemble 三个模块 |
| `src/channels/service.py` | 468 | 已拆分 `_iter_receiver_configs` / `_route_receiver_envelope*` 工具方法,主体只负责线程生命周期 |
| `src/capabilities/registry.py` | 283 | 4 类(kind) × 多方法,合理 |
| `src/cli_commands/chat.py` | 308 | `_StreamPrinter` 抽离为 inner class,边界清晰 |
| `src/web_backend/route_registry.py` | 119 | 一张路由表,无膨胀 |
| `src/web_backend/facade.py` | 166 | 启动生命周期 + static mount,边界清晰 |
| `src/web_backend/agent_domain.py` | 28 | 内含 `_service_targets_cache` 委托,已拆薄 |
| `src/web_backend/core.py` | 71 | 纯聚合,无业务逻辑 |
| `src/provider_feature_matrix.py` | 114 | 表驱动,合理 |
| `src/fast_api.py` | 159 | CLI/Server 双模式 dispatcher |
| `src/cli.py` | 143 | argparse 装配 + 异常统一处理 |
| `webui/src/api.ts` | 1035 | 后端路由的 1:1 镜像,**已超 400 行**,可考虑按子域(节点/图/Provider/Channel/Mobile)拆分 |

---

## 9. 仍可继续深入的方向

- 跟踪一条 `run_node` 完整调用链:API → `node_ops.run_node` → `agent_node.on_input` → `AgentStreamRuntime` → Provider → 事件 sink
- 跟踪一条 `emit_graph` 链路:移动端 / 桌面 / 通道 → `graph_runtime` → 节点 routing → memory 持久化
- 跟踪桌面宠物启动:`launch_node_desktop_pet` → `node_desktop_pet_launcher` → 子进程
- 对比 `src/providers/*` 中各家的 transport / tool_call / loop_guard 实现差异
- 跟踪一条 `channel_receiver_node` 链路:Weixin 消息 → `ChannelService._receiver_loop` → `route_receiver_envelope` → `graph_api.emit_graph` → 节点 on_input
- 读 `src/providers/responses_runtime*.py` 摸清 OpenAI Responses 协议栈

(以上内容基于已读源码与目录扫描,所有 API 路径、模块名、类名均与 `route_registry.py` / `nodes/agent_node.py` / `webui/src/api.ts` 对齐)
