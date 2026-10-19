# AgentPark 文档

这里是项目的 `docs/` 目录（文中统称 Docs）。如果你刚拿到代码，请从 **[GettingStart](GettingStart.md)** 开始；如果已经打开设置页，请使用 **[Settings 逐项手册](settings/README.md)**。

## 建议阅读顺序

| 阶段 | 先完成什么 | 文档 |
| --- | --- | --- |
| 入门 | 启动后端与 WebUI，配置一个模型，完成第一轮对话 | [GettingStart](GettingStart.md) |
| 配置 | 理解 Provider、Preset、Node，设置 Companion | [模型与 Harness](settings/models.md)、[预设与伴侣](settings/presets-companion.md) |
| 工具与知识 | 添加资料目录，启用 Skill、工具和 MCP | [知识库](settings/knowledge.md)、[Skills](settings/skills.md)、[默认设置](settings/defaults.md) |
| 协作 | 给多个 Agent 分工、创建依赖任务、检查交接 | [协作组指南](agent-groups-guide.md) |
| 跨设备 | 打开远程 Board、授权协作、切换执行设备、同步节点 | [连接与同步](settings/connectivity.md) |
| 高级 | 编排事件、发布模型网关、审计运行 | [运行事件](settings/events-theme.md)、[网关](settings/access-gateway.md)、[诊断](settings/diagnostics.md) |

## 用户指南

新手指南与 Settings 手册依据实际界面和源码编写。下列专题包含更深入的实现、适用条件和验证记录；其中的日期、模型名和测试成绩属于当时记录。

| 专题 | 文档 |
| --- | --- |
| 本地服务与模型 | [操作手册](settings/local-services.md)、[实现与边界](local-model.md) |
| 节点长期记忆与对话压缩 | [设置方法](settings/defaults.md)、[机制与来源](node-long-term-memory.md) |
| Word / Excel 知识 | [使用流程](settings/knowledge.md)、[解析与计算合同](knowledge-office.md) |
| Skill 管理与扩展 | [操作指南](settings/skills.md)、[来源与整理](skill-management.md)、[编写 Skill / 插件](skill-plugin-authoring.md) |
| Harness | [配置步骤](settings/models.md#harness)、[通用实现](harness.md)、[OpenCode](opencode-harness.md)、[Antigravity](antigravity-harness.md) |
| Provider | [字段合同](../config/modelProvider.README.md)、[授权存储](provider-authorization.md)、[功能矩阵](provider-feature-matrix.md) |
| 图片与媒体 | [OpenAI Images](openai-image-provider.md)、[网关图片](public-gateway-images.md)、[语音截图工具](voice-screenshot-tools.md)、[语音错误隔离](voice-error-isolation.md) |
| WorkBuddy | [连接说明](workbuddy.md) |
| 桌面与命令执行 | [Computer Use](computer-use.md)、[命令会话](console-sessions.md)、[节点小窗](node-windows.md) |
| 移动与协作组 | [协作组](agent-groups-guide.md)、[移动组聊](mobile-group-chat.md)、[定向协作](group-directed-collaboration.md) |
| 设备互联 | [用户操作](settings/connectivity.md)、[P2P 与鉴权中心部署](peer-network.md)、[云端前端](../deploy/peer-network/README-frontend.md) |
| 远程执行 | [Linux Worker 部署](../deploy/remote-worker/README-linux.md) |
| 节点同步 | [预览与提交](settings/connectivity.md#node-sync)、[同步协议](node-sync.md) |
| 启动与排错 | [启动修复](startup-repair.md)、[排错](troubleshooting.md)、[节点打开诊断](node-open-diagnostics.md) |

## 开发与架构

- [架构概览](architecture/agentpark-architecture-overview.md)：前后端、节点、Provider、工具与运行事件的职责。
- [配置合同](config-contract.md)：配置校验与错误处理。
- [能力系统](capability-system.md)：Tool、Skill、MCP、Plugin 的发现与装载。
- [HTTP 传输](http-transport.md)：项目统一网络传输边界。
- [运行状态机](runtime-state-machine.md)：节点状态与恢复规则。
- [长期架构](long-term-architecture.md)：后续演进设计；不应当作全部已实现功能。

测试报告、事故记录及历史验收文档保留在本目录及 `benchmarks/` 下，供追溯使用。查看当前使用方法时优先从本索引和 Settings 手册进入。
