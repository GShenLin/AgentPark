# Settings 使用手册

[项目介绍](../../README.md) · [GettingStart](../GettingStart.md) · [Docs 索引](../README.md)

本手册按当前 Settings 实际注册的 **18 个入口** 编写。桌面显示侧栏；窄屏按“模型与 Agent、工具与知识、连接与权限、运行与诊断、外观与系统”分组，可搜索设置名称。中英文界面的标签不同，下表同时列出入口 ID，便于准确定位。

## 完整入口对照

| Settings 入口 | ID | 用途与详细说明 |
| --- | --- | --- |
| 权限 / Authorization | `authorization` | [远程用户、Developer 与工具过滤](access-gateway.md#authorization) |
| 网关 / Gateway | `gateway` | [公开模型、网关 Key、协议、请求测试与用量](access-gateway.md#gateway) |
| 模型提供商 / Model Provider | `model-provider` | [连接、账号、模型、协议、额度与多模态](models.md#model-provider) |
| 本地服务 / LocalModel | `local-model` | [服务登记、进程控制、Strata 与 ComfyUI](local-services.md) |
| 默认设置 / Default settings | `defaults` | [存储、粘贴预设、上下文、记忆、布局、网络、MCP 等](defaults.md) |
| 伴侣 / Companion | `companion` | [伴侣预设、工作路径与启动修复](presets-companion.md#companion) |
| 运行事件 / Runtime Events | `events` | [事件处理规则、上下文策略与接收者](events-theme.md#runtime-events) |
| 主题 / Theme | `theme` | [主题预设、颜色、透明度及图片](events-theme.md#theme) |
| Harness | `harness` | [九种原生 Agent 运行时的检查、安装、升级与模型目录](models.md#harness) |
| Knowledge | `knowledge` | [文件夹知识库、Embedding、扫描、检索和 Agent 接入](knowledge.md) |
| Skill 管理 | `skills` | [加载来源、说明、依赖、整理、删除与恢复](skills.md) |
| 设备互联 | `peer-network` | [设备中心、共享授权、远程工作区与执行设备](connectivity.md#peer-network) |
| 节点同步 | `node-sync` | [节点或整图同步、预览、提交与续传](connectivity.md#node-sync) |
| 提供商测试 / Test | `provider-test` | [模型发现、能力探测和结果解释](diagnostics.md#provider-test) |
| 压力测试 / Pressure | `pressure` | [并发、队列、RPM/TPM 与峰值监控](diagnostics.md#pressure) |
| 统计 / Statistics（部分内部名称为 Static） | `tool-stats` | [全链路审计、工具调用、模型轮次和清理](diagnostics.md#statistics) |
| 节点预设 / Node Presets | `node-preset-editor` | [预设字段、模型、指令、能力与事件元数据](presets-companion.md#node-presets) |
| 退出 / Exit | `exit` | [退出后端与重新启动](diagnostics.md#exit) |

语音字段在模型与节点配置中按能力显示；独立的 豆包音色管理嵌在 Provider 表单中。源码目录中存在某个组件或翻译名称，并不代表它已经作为独立 Settings 菜单开放。

## 先掌握保存方式

| 面板 | 保存/执行入口 | 生效方式 |
| --- | --- | --- |
| 模型、默认设置、伴侣 | 页顶保存 | 新请求/下次读取使用新配置；监听地址、代理、记忆目录需重启 |
| 运行事件 | 页顶应用 | 校验并应用规则；失败时查看应用错误与诊断 |
| 主题 | 页顶保存，或预设 Load / Save | 保存或加载后更新页面主题 |
| 节点预设 | Save Profile | 保存预设；普通已创建节点不自动批量改写 |
| 网关 | 保存选项；Key 的添加/删除另有按钮 | 网关选项与公开模型先保存，账号密钥操作单独提交 |
| 本地服务、知识库、技能、连接、权限 | 面板自己的保存/操作按钮 | 以对应作业状态和返回结果为准 |
| 提供商测试与 Harness | 测试/安装/升级按钮 | 实际发起后台作业，需等待完成并查看错误输出 |
| Pressure、统计 | 刷新/筛选 | 读取诊断数据；清理为单独操作 |

“高级 JSON”编辑的是当前配置草稿，“格式化”只整理 JSON 文本，仍需保存或应用。重新加载会读取磁盘内容，未保存的修改可能被丢弃。切换菜单时如出现未保存提示，先保存要保留的内容。

## 推荐配置顺序

1. 模型提供商：确保有一个可用 Provider、明确模型与授权。
2. 创建普通 Agent 并验证对话，保存为可复用预设。
3. 节点预设、伴侣、默认设置：配置对话压缩和记忆任务的推理预设。
4. 根据任务添加 Skill、MCP 或知识库；需要原生 CLI 时再配置 Harness。
5. 根据设备布局配置远程连接与同步。
6. 最后配置事件、网关和精细限流，并使用统计审计验证结果。

首次管理本机设置建议使用 `http://127.0.0.1:<实际端口>` 或 `localhost`。普通远程用户、已授权设备与云端管理员的权限不同；无法操作时先核对访问身份，而不是重复修改配置文件。

## 文档依据与维护范围

入口来自 `SettingsPage.vue`、`settingsSections.ts` 与后端 `SETTINGS_SECTIONS`，字段来自各面板及相应后端配置合同。下列手册也明确标注发现的“表单已显示但运行路径未读取”字段，避免把控件存在误写成能力已生效。

维护功能时应同步更新对应专题及本表。实现说明、历史测试数据与用户操作步骤分别保留；需要底层细节可沿每篇末尾的专题链接继续阅读。
