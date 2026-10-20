# AgentPark

[English](./README.md) | [中文](./README.zh.md)

AgentPark 是一个可在本机运行、通过浏览器使用的可视化 Agent 工作台。你可以先和一个 Agent 对话，再把多个 Agent、工具和触发器组织成工作流或协作组，让它们使用各自的模型、工作目录、能力和历史完成任务。

**项目最大的亮点：把不同模型和不同 Agent 运行时，放进同一张可观察、可协作、可跨设备使用的画板。** 普通 Agent、Codex、Claude Code 等节点可以共同参与任务；你可以查看过程、调整分工、检查工具调用，并保留每个节点的独立对话。

本文按入门到高级介绍现有代码提供的功能。首次使用请继续阅读 **[GettingStart：安装、配置和第一次对话](docs/GettingStart.md)**；全部设置说明见 **[Settings 使用手册](docs/settings/README.md)**。

## 为什么使用 AgentPark

| 亮点 | 实际用法 |
| --- | --- |
| 可视化组织工作 | 在 Graph / Board 中创建节点、连线、分组，直接打开节点聊天和查看运行状态 |
| 多种 Agent 运行时 | 使用项目自有 Agent，或接入九种 Harness；不同运行时保留自身的工具、会话和权限规则 |
| 真正的成员分工 | 协作组共享目标、任务、依赖和交接动态，成员继续使用自己的模型与历史 |
| 可持续的节点上下文 | 普通 Agent 支持历史压缩和节点长期记忆；摘要附带来源，能进一步检索原始依据 |
| 本地资料可查证 | 文件夹知识库支持 PDF、文本、Word 和 Excel，检索与表格计算返回可核对的出处 |
| 从电脑延伸到其他设备 | 浏览器移动视图、Windows 节点小窗、设备中心、远程执行和节点同步各有明确入口 |
| 过程可追溯 | 全链路审计、工具成功率、失败详情、Provider 队列与用量帮助定位问题 |

## 启动项目

从源码目录启动。准备 Git、带 pip 的 Python（建议先使用 3.12）以及 Node.js/npm（建议使用满足要求的 LTS，WebUI 与 Windows 小窗使用 Node.js 22.12 或更高版本；部分 Harness 要求更高版本）。模型服务的账号或 API Key 需要自行配置。

Windows，在项目根目录的 PowerShell 执行：

```powershell
.\build_and_run.bat
```

Linux / macOS，在项目根目录执行：

```sh
sh ./build_and_run.sh server
```

打开 [本机工作台](http://127.0.0.1:8766)。程序默认监听 `0.0.0.0:8766`；配置或端口占用可能改变实际端口，以启动日志为准。首次配置建议从本机回环地址访问 Settings。

启动脚本会安装依赖、构建 WebUI 并启动后端。Windows 入口还会准备节点小窗、检查仓库更新和私有 CA 信任，并尝试发布云端前端；具体行为、手动分步启动及无账号时的配置顺序见 [GettingStart](docs/GettingStart.md)。启动成功只代表服务可用，发起模型任务还需要有效的 Provider、模型和授权。

首次运行的最短路线：

1. 打开 **Settings → 模型提供商**，配置连接地址、密钥或官方授权，以及模型列表。
2. 在画板空白处右键创建 **Agent**，选择 Provider 和明确的模型，先发送一个简单问题。
3. 在 **节点预设** 中配置需要复用的模型、指令和能力，再到 **伴侣 / 默认设置** 选择相关预设。
4. 需要读取资料时添加知识库；需要编程运行时再到 Harness 安装对应 CLI。

## 第一阶段：单节点入门

### 1. 画板与节点管理

Graph 是一组节点、连线和分组的工作空间，Board 是它的可视化界面。可创建与切换 Graph、拖动节点、调整布局、编辑节点名称和注释，打开节点配置与聊天。不同任务可放在不同 Graph 中管理。

节点有自己的运行状态和任务队列。通过输入框发送消息，通过节点控件触发、暂停或停止工作；查看最终答复时也可以展开过程，检查模型输出与工具执行。暂停与停止的含义以节点当前状态和控件反馈为准。

### 2. 普通 Agent 对话

`Agent` 节点使用 AgentPark 的运行时，可按所选 Provider 的实际能力进行文本对话、图片理解、调用工具和处理资源。输入框支持文字及附件，聊天与过程记录持久化在节点目录中。

模型选择是 **Provider + Model** 两部分：前者决定连接、授权及协议，后者决定具体请求模型。不要把 Provider ID 当成模型名。配置说明见 [模型与 Harness](docs/settings/models.md)。

### 3. 文件与附件

支持通过文件面板查看工作区资源，在节点或组的输入框选择、拖放或粘贴浏览器可读取的附件。图片可以预览，文件可以作为资源交给模型；模型能否直接理解具体格式，取决于节点和 Provider。浏览器文件面板的工作区边界，与 Agent 获得的文件工具权限是两套不同边界。

### 4. 复用节点预设

Agent Profile / Preset 保存节点类型、模型、指令、能力和事件规则，适合重复创建研究、编程、审查等角色。创建并调试一个节点后可保存为预设，再在 **Settings → 节点预设** 中编辑。

普通节点从预设创建时复制配置；Companion 和后台推理配置则通过预设 ID 读取。修改预设对这些场景的影响不同，见 [节点预设与 Companion](docs/settings/presets-companion.md)。

### 5. Companion 与命令行

Companion 是工作台的伴侣 Agent。设置页选择它使用的预设和本地工作目录；预设决定模型、指令与能力。Windows 启动修复也使用该预设。

命令行还可用于对话和离线诊断：

```powershell
python -m src.cli chat
python -m src.cli doctor --json
```

这两条命令需使用已经安装项目依赖的 Python；`chat` 还需要可用的 Companion 配置。

## 第二阶段：让 Agent 具备知识与工具

### 6. 多提供商与账号管理

设置表单提供 OpenAI、Claude、DeepSeek、Doubao、Gemini、Grok、Kimi、智谱、Hyper3D、Agnes 和本地 alpha matting 等类型入口。不同适配器的能力不同，不能仅靠勾选能力就让服务支持某种协议。

可管理 API Key 引用、命名账号、多 OAuth 账号及固定账号。密钥存放在 `.auth/`；Provider 配置引用密钥名或账号 ID。官方 OAuth 入口只对已经实现该协议的类型开放。详见 [模型连接与授权](docs/settings/models.md)。

### 7. Tools、Skills、MCP 与插件

| 能力 | 用途 | 如何启用 |
| --- | --- | --- |
| Tool | 文件、命令、节点操作等可调用功能 | 在节点配置中选择工具 |
| Skill | 带使用说明、脚本和资源的任务流程 | 在节点选择 Skill，运行时按需激活 |
| MCP | 接入本地子进程或远程 MCP 服务 | 默认设置登记服务，再在节点选择 |
| Plugin | 以插件清单组织扩展能力 | 安装对应资源并在节点选择插件 |

Skill 管理汇总项目、系统用户和自定义来源，可搜索、阅读说明、查看依赖和引用，整理文件夹、移入回收区及恢复。能力变更通常在下一次 Agent 执行时装载，已经运行的任务不会因此自动重启。见 [Skills 与扩展](docs/settings/skills.md)。

### 8. 本地文件夹知识库

支持递归扫描 PDF、Markdown、TXT、DOCX/DOC、XLSX/XLS，使用 OpenAI 兼容文本 Embedding 服务建立磁盘索引，提供关键词、语义和混合检索。可增量扫描、暂停、继续、重试失败文件，并在管理页检验检索结果。

Agent 选择 `knowledge` Skill 后，可以在获准的库中列文档、检索、读取原文并对 Excel 指定工作表和行范围进行统计。结果标注 PDF 页码、文本行、Word 段落或 Excel 行列。当前不执行 OCR；DOC 需要 LibreOffice；公式使用文件中保存的计算结果。见 [知识库使用指南](docs/settings/knowledge.md)。

### 9. 对话压缩与节点长期记忆

普通 Agent 的连续对话超过历史预算后，可在后台压缩较早内容，并保留近期原文。长期记忆则从节点完成的任务历史提取与合成小摘要，在后续输入中注入，再按需检索来源。

两者分别配置推理预设、预算和处理门槛；节点之间保持独立记忆。显式记住、更正和按来源遗忘也有对应工具。历史压缩、长期记忆、清空聊天的区别见 [默认设置](docs/settings/defaults.md)。

### 10. 命令与进程会话

自有 Agent 的 `system_tools` 支持同步短命令，以及启动、读取、等待、停止异步进程会话。构建或测试可以逐步读取输出并取消。命令使用后端所声明的平台与 shell；Windows 使用 PowerShell，POSIX 使用检测到的 shell。会话属于当前 Agent 执行，不提供跨轮次或重启恢复。见 [命令会话](docs/console-sessions.md)。

### 11. 浏览器与 Windows 桌面操作

通过对应 Skill 和依赖接入浏览器自动化；Windows `computer-use` 支持窗口发现、截图、UI Automation、鼠标和键盘操作。需选择支持图片输入和工具调用的模型，并按 Skill 要求完成依赖准备。桌面能力依赖 Windows 图形会话，不能在 Linux 后端上直接使用。见 [Computer Use](docs/computer-use.md)。

### 12. 本地服务管理

**Settings → 本地服务** 可登记任意本地服务，配置启动程序、工作目录、参数、服务地址和健康检查，并手动启动、停止和检测。Strata、ComfyUI 管理预设额外提供模型发现及相应操作。

登记服务不等于将其接入模型 Provider，也不会自动下载或加载权重。普通服务与两种管理预设的具体用法见 [本地服务](docs/settings/local-services.md)。

## 第三阶段：工作流、多 Agent 与多模态

### 13. 节点连线工作流

连接输出端口和输入端口，让上游结果进入下游节点。适合把输入整理、模型处理和文件输出拆成可单独检查的步骤。

| 节点 | 代码提供的行为 |
| --- | --- |
| BasicTrigger | 手动触发并发送配置的文本 |
| TimerTrigger / Clock | 到指定时间触发 / 按固定间隔输出 |
| Append / Response / Echo | 追加固定文本 / 返回配置文本 / 回显输入 |
| MultiInput | 等待所有输入端口到齐，按端口顺序合并 |
| Loop | 执行指定次数的循环分支，再进入出口 |
| Event | 按 EventKey 分发输入 |
| ConsoleCommand / SaveFile | 执行配置命令 / 将输入写入文件 |

先用触发器、一个 Agent 和输出节点验证小流程，再增加分支与循环。定时触发依赖后端运行；它不等同于操作系统级常驻服务。

### 14. 多 Agent 协作组

框选多个 Agent 按 **G** 建组，编辑共同目标、成员职责和任务。任务可以指定负责人、前置依赖、状态和验证证据；成员可定向交接，只有相关成员被唤醒。共享动态、任务回复和归档任务用于追踪进展。

组本身不占用一个模型，各节点保留自己的模型、工具和历史。适合“研究 → 实现 → 验证”等可明确分工的任务。完整操作见 [协作组指南](docs/agent-groups-guide.md)。

### 15. 九种 Harness

当前注册了 **Codex、Claude Code、OpenClaw、DeepSeek Harness、MiniMax Code、OpenCode CLI、Antigravity CLI、Pi、Hermes Agent**。在设置中检查、安装、升级或卸载，再创建对应类型的节点。

其中 OpenCode 与 Antigravity 使用原生模型目录；其他节点的 Provider 绑定、登录、工具与权限依各自适配器实现。Harness 不会自动获得普通 Agent 的全部技能和后台记忆能力，也不保证每种原生交互式审批都能在无界面执行时处理。见 [Harness 使用步骤](docs/settings/models.md#harness)。

### 16. 图片、视频、3D 与音频

Agent 的可用字段按 Provider 的 `supportmode` 动态显示，支持图片生成与编辑、视觉理解、视频生成和音频生成；抠图、视频换人、3D 生成与贴图使用对应专用节点。图片附件也可作为聊天的多模态输入。

语音相关代码还包含转写、TTS、实时交互和同传等按服务配置的能力；豆包音频与 RTC 需要对应的语音密钥、AK/SK 或应用配置。是否能运行取决于具体服务、模型、账号额度及本地依赖。配置入口见 [模型手册](docs/settings/models.md)，图片接口细节见 [OpenAI Images](docs/openai-image-provider.md)。

### 17. 消息通道与定时唤醒

通道接收/发送节点支持将微信通道消息接入 Graph，并从节点输出回复；需完成所用通道登录与接收节点配置。节点定时唤醒通过项目 cron 能力管理，和 TimerTrigger / Clock 的图内触发分开。后端、通道账号和目标节点均需可用。

## 第四阶段：跨端与跨设备

### 18. 手机与独立节点小窗

浏览器根据屏幕尺寸提供移动工作区，可浏览节点、聊天、附件和协作组。Windows 本机可右键节点选择“弹出节点”，用置顶小窗继续聊天，关闭主网页后仍能使用运行中的后端；关闭小窗不删除节点或停止任务。见 [独立节点小窗](docs/node-windows.md)。

### 19. 设备互联与云端设备中心

经鉴权中心批准的设备可通过 WebRTC 连接，优先直连，必要时使用 TURN 中继，业务数据端到端加密。管理员可从云端设备中心打开某台设备的 Board。

两台后端之间还可明确授予公开 Graph 的查看、控制与 Agent 协作权限，并通过 `peer_network_tools` 定向发消息。设备获准上线，与双方授予业务权限是不同步骤。见 [设备与同步](docs/settings/connectivity.md)。

### 20. 远程执行与跨设备工作区

已登记的 Remote 或 AgentPark 可作为执行设备。节点右键 **LinkToRemote** 选择设备后，按远程工作区协议执行支持的文件和命令操作。远端的工作目录、平台、shell 和工具能力决定实际执行环境；它不同于打开远程 Board。Linux 工作机部署见 [Remote Worker](deploy/remote-worker/README-linux.md)。

### 21. 节点及整图增量同步

选择来源和目标节点可同步用户消息、最终回答、附件及 Archive；两边都不选节点则同步 Graph 结构与各节点对话。预览会展示消息、附件、结构变更和冲突，确认后提交。

同步保留目标已有额外内容，不同步删除，不传输 Process、不复制模型账号和插件安装，也不自动执行任务。见 [节点同步步骤](docs/settings/connectivity.md#node-sync)。

## 第五阶段：高级配置与维护

### 22. 运行事件

对输入、工具失败、运行提示、网络错误、结果落盘和工作失败配置处理规则：生成上下文、追加文件、写通知或交给 Agent。可调整上下文 TTL、片段长度和去重窗口，查看编译诊断。见 [运行事件与主题](docs/settings/events-theme.md)。

### 23. 公共模型网关

将本机 Provider 中选定的模型通过网关开放，管理独立网关 Key、固定账号和允许协议，内置请求测试及按日期/IP/模型的用量统计。支持的入口包含 Models、Responses、Chat Completions、Messages 和 JSON 图片生成/编辑；协议须同时被上游与网关允许。见 [权限与网关](docs/settings/access-gateway.md)。

### 24. 权限与可见性

管理远程用户名、客户端/IP 记录、Developer 身份和非 Developer 工具过滤。Provider 可设为私有，设备共享有独立授权，云端管理员 Board 又有独立拥有者身份。设置权限前应先明确使用的是哪一种访问入口。见 [权限说明](docs/settings/access-gateway.md#authorization)。

### 25. Provider 测试与压力监控

**提供商测试** 查询模型并探测实际接口能力，区分不支持与无法判定。**压力测试 / Pressure** 页面展示运行时并发、排队、RPM/TPM 使用及峰值，是监控页面；打开它不会自动发起压测。见 [诊断手册](docs/settings/diagnostics.md)。

### 26. 全链路审计与工具统计

按日期、Graph、节点选择一次运行，查看输入、模型轮次、工具结果、文件变更与时间线；按 Provider 查看成功率、失败原因和 Token 用量。服务端未返回 usage 时显示缺失，不把缺失计作零。见 [统计与审计](docs/settings/diagnostics.md#statistics)。

### 27. 外观、存储与生命周期

可调整主题预设、面板颜色与背景图片、Agent 弹窗和看板尺寸、撤销步数、代理、服务监听地址及记忆目录。提供日志清理、派生长期记忆清理和退出后端入口。启动与重启保留日志，并按实现执行状态恢复；它们不保证恢复所有外部进程或原生 CLI 会话。见 [默认设置](docs/settings/defaults.md)与[维护](docs/settings/diagnostics.md#maintenance)。

### 28. 执行记录与整会话检查点

自有 Responses 运行路径可开启节点级 step ledger，记录请求、工具开始/结束及回答；进程中断后，将没有完成记录的工具结果标为未知，引导先核对外部状态。还可按模型窗口压力生成整会话检查点，保留近期对话与原始记录，继续长任务。

这些功能需在 Provider 高级 JSON 中明确启用，与后台历史摘要和长期记忆分别工作。字段、默认值和恢复边界见 [模型高级设置](docs/settings/models.md#高级-json执行记录与整会话压缩)。

## 文档与开发

| 你的目标 | 阅读入口 |
| --- | --- |
| 安装并完成第一次对话 | [GettingStart](docs/GettingStart.md) |
| 按 Settings 菜单查字段和步骤 | [Settings 使用手册](docs/settings/README.md) |
| 查找专题与技术文档 | [Docs 索引](docs/README.md) |
| 扩展 Skill / 插件 | [能力系统](docs/capability-system.md)、[编写指南](docs/skill-plugin-authoring.md) |
| 理解代码边界 | [架构概览](docs/architecture/agentpark-architecture-overview.md)、[配置合同](docs/config-contract.md) |
| 排查启动与配置问题 | [Troubleshooting](docs/troubleshooting.md)、[启动修复](docs/startup-repair.md) |

后端为 Python / FastAPI，前端为 Vue 3 / TypeScript / Vite。开发约束见 [AGENTS.md](AGENTS.md)，许可证为 [MIT](LICENSE)。功能说明以仓库当前实现为依据；服务商的可用模型、额度及外部软件支持范围以实际查询和运行结果为准。

