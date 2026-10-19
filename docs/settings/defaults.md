# 默认设置：存储、上下文、记忆与运行参数

[Settings 索引](README.md) · [节点预设](presets-companion.md)

入口：**Settings → 默认设置 / Default settings**。大部分配置保存到 `config/config.json`，Memories Directory 单独保存在本机 `.cache/memoryLocalConfig.json`。普通字段用页顶保存；Paste Agent 区有自己的保存按钮。

## 1. Storage

| 控件 | 如何使用 |
| --- | --- |
| Memories Directory | 输入后端设备的绝对目录。保存后重启；Active 显示本次进程使用的目录，After restart 显示待生效目录 |
| Clear Logs | 清理运行事件、响应 payload、备份及 HTTP 调试日志；先保存排错需要的证据，再确认清理 |

不填写目录时使用项目 `memories/`；无效值按当前路径解析规则回到默认目录，不能把相对路径当成自定义目录。修改配置不迁移旧数据。迁移应先停止相关执行、备份并复制完整记忆目录，再设置目标绝对路径并重启，核对 Graph、节点与历史是否齐全。

Clear Logs 使用后端维护脚本，不等于清空对话或清空长期记忆。在没有相应维护脚本/执行环境的平台上，以返回错误为准，不能假定 Windows 批处理在所有系统通用。

## 2. Paste Agent

1. 先准备一个可用的 `agent_node` 预设。
2. 在 Paste Agent 的 Profile 下拉中选择它。
3. 点击该区 **Save**；它使用独立接口，不依赖页面其他草稿一起保存。
4. 返回画板粘贴剪贴板文本或图片创建 Agent，核对生成节点的 Provider、指令和能力。

该选择保存在 `config/pastagent.json`。若显示 Missing Profile，先在节点预设中恢复或选择有效预设。预设管理模型、提示词、工具、运行字段和事件规则；仅修改这里的选择不会重配已有节点。

## 3. Agent 弹窗

| 字段 | 单位/范围 | 效果 |
| --- | --- | --- |
| Width | px，360–7680 | 点击 Agent 打开的聊天弹窗宽度 |
| Height | px，320–7680 | 弹窗高度 |

保存后生效，超出可用屏幕时缩小。留空使用程序默认值；这是网页 Agent 弹窗设置，不是 Electron 所有窗口的统一尺寸。

## 4. 当前对话上下文

用于普通 Agent 连续聊天的历史预算和后台摘要，配置键为 `conversationContext`。

| 字段 | 程序默认 | 含义 |
| --- | --- | --- |
| `input_tokens` | 24000 | 历史上下文预算，至少 4096；不限制当前用户输入 |
| `retain_tokens` | 6000 | 压缩时尽量保留的近期原文预算 |
| `summary_tokens` | 2000 | 续聊摘要输出预算 |
| `profile_id` | `DouBao` | 执行摘要的 `agent_node` 推理预设 |

这些是程序默认，已有工作区的实际值可能不同。需满足 `retain_tokens + summary_tokens + 1024 < input_tokens`。估算使用 UTF-8 字节/4，不是真实 tokenizer，也不自动识别模型最大窗口。

操作建议：先选一个已验证可用的摘要预设，保留默认预算完成连续对话；确认后台摘要能成功生成，再按任务调整预算。提高 `summary_tokens` 时要同时留足总预算余量。

每轮回答或错误落盘后后台检查；未超预算不请求摘要。下次输入恢复有效摘要与后续原文。原始历史保留，摘要不是对原文的删除。后台尚未完成或失败时仍发送原历史，因此可能继续触及实际模型窗口；出现摘要错误应修复预设或服务问题。

保存后的后续检查读取新配置，已开始任务使用原配置。该加载器不等同于每种 Harness 的原生上下文机制。

## 5. 节点长期记忆

配置键为 `longTermMemory`，策略由工作区共享，各节点记忆分别保存。它从完成的任务中提取来源摘要，再合成小摘要；与上一节的续聊摘要独立。

| 字段 | 程序默认 | 如何理解与调整 |
| --- | --- | --- |
| Enabled | true | 开关；关闭不删除已有数据，也不取消已启动任务 |
| `extract_profile_id` | `DouBao` | 单任务提取预设，必须是有效 `agent_node` 预设 |
| `consolidation_profile_id` | `DouBao` | 多来源合成预设，也必须单独可用 |
| `min_idle_seconds` | 3600 秒 | 完成任务进入提取前的空闲门槛，可设 0；不是到点唤醒计时器 |
| `max_age_days` | 30 天 | 首次提取允许的历史年龄窗口 |
| `max_unused_days` | 30 天 | 未使用来源保留窗口，读取会刷新使用时间 |
| `max_extractions` | 8 | 一次处理最多提取任务数 |
| `max_selected` | 64 | 一次合成最多选择来源数 |

展开高级选项：

| 字段 | 程序默认 | 含义 |
| --- | --- | --- |
| `input_bytes` | 180000 | 单来源输入字节预算；超出报错，不静默截掉余下内容 |
| `consolidation_bytes` | 240000 | 合成输入字节预算 |
| `lease_seconds` | 180 秒 | 后台任务自动续约租约；不同于模型响应超时 |
| `retry_seconds` | 3600 秒 | 失败后重试等待间隔 |

所有数值为整数，除空闲秒数可为 0 外都至少为 1。选择预设时要检查它的模型、授权和指令；内部摘要调用不装载该预设的普通工具，不依赖节点原 Provider 自动补位。

输入时及任务持久化后触发后台处理；空闲门槛达到后仍需后续触发。可以让 Agent 记住明确偏好、修正旧事实或按来源遗忘，再在后续问题中检查结果。摘要中的历史声明仍需来源核对，不能自动证明某个工作已经完成。

### 三种“清理”的区别

| 操作 | 影响 |
| --- | --- |
| Clear Logs | 删除诊断日志，不是清聊天 |
| 统计页 Clear long-term memory | 清所有节点的派生记忆和笔记，保留原聊天；后续可重新提取，显式遗忘排除仍保留 |
| 节点清空历史/记忆 | 影响该节点聊天、续聊检查点和派生记忆；Harness 会话按各自清理合同处理 |

长期记忆存于节点目录 `long_term_memory/`，不是集中对所有节点开放的知识库。机制与工具见 [节点长期记忆](../node-long-term-memory.md)。

## 6. 看板布局

| 字段 | 表单默认/范围 | 作用 |
| --- | --- | --- |
| Grid Cell Width | 300，230–2000 | 网格单元宽度 |
| Grid Cell Height | 320，250–2000 | 网格单元高度 |
| Node Width | 230，230–720 | 新节点默认宽度 |
| Node Height | 250，250–760 | 新节点默认高度 |

已有节点保存过的自定义尺寸仍保留。修改后用新建节点或布局操作验证，不要只观察旧节点推断设置失效。

## 7. 服务器

`server.host` 指监听网卡，`server.port` 是 1–65535 的端口。程序默认 `0.0.0.0:8766`；已有配置可能不同。只在本机使用可设 `127.0.0.1`；其他设备直接访问需要对应网卡可达。

保存后重启，再按实际地址访问。端口占用时程序可选用后续可用端口，以日志和 PID 文件记录为准；浏览器不能通过 `0.0.0.0` 代替实际访问地址。

## 8. 网络

| 字段 | 示例 | 生效方式 |
| --- | --- | --- |
| HTTP Proxy / `network.httpProxy` | `http://127.0.0.1:7890`（替换实际端口） | 启动时写入 HTTP(S) 代理环境并由子进程继承 |
| No Proxy / `network.noProxy` | `localhost,127.0.0.1,::1` | 指定绕过代理的目标 |

代理必须是绝对 HTTP/HTTPS URL。配置代理且未填 No Proxy 时程序使用回环地址默认列表。清空字段不保证删除启动进程原本继承的代理环境；需要同时核对启动终端环境。保存后重启，安装器下载与模型请求都应检查实际错误，而不是反复切换随机代理端口。

## 9. Agent 节点与运行时默认值

| 字段 | 实际用途 |
| --- | --- |
| Min Send Delay / `agentNode.minSendDelayMs` | 普通 Agent 最小发送延迟，毫秒；0 表示不增加该延迟 |
| Console Timeout / `consoleCommand.timeoutSec` | 控制台命令默认超时，秒；命令会话还可能有自己的显式超时 |
| Memory Entries / 表单 `nodeMemory.maxEntries` | 当前存在字段不一致：表单写 `maxEntries`，活动历史归档读取 `maxActiveEntries`，因此此控件不能控制实际归档条数 |

如果需要配置活动历史归档，在高级 JSON 的 `nodeMemory.maxActiveEntries` 设置正整数，当前程序默认 20；归档按完整轮次边界处理。这不是模型历史预算，也不删除 Archive。上述表单差异仅记录现状，避免误认为调小控件即可减少模型上下文。

## 10. 撤销

`undo.maxSteps` 为 0–100，默认 5。控制画板编辑撤销记录的保留步数，0 关闭保留。它不是对已经执行的模型请求、命令或外部文件修改的事务回滚。

## 11. MCP 服务器

1. 在 MCP Servers 输入唯一名称并添加，选中该服务。
2. 设置 Label；选择 `streamable-http` 或 `stdio`。
3. HTTP 服务填写真实 MCP URL；按服务需求设置读取超时（秒）。
4. stdio 服务需要在高级 JSON 中补齐 `command`、`args` 及所需环境等完整定义，普通表单没有展示全部子进程字段。
5. 保存默认设置，在目标 Agent 节点选择对应 `mcp_servers` 项，再发起新任务验证工具发现与调用。

最小结构示意（地址和命令需替换为已经安装的服务）：

```json
{
  "mcpServers": {
    "local-service": {
      "label": "本地 MCP",
      "transport": "stdio",
      "command": "实际可执行程序",
      "args": ["实际入口参数"]
    }
  }
}
```

这是要合并进现有配置的局部结构，不能用它覆盖整个 `config.json`。HTTP 授权和附加字段按 MCP 配置合同填写。登记不等于全体节点自动启用；启动失败时到能力诊断查看原始错误。

## 排查顺序

保存错误先看字段名与类型；摘要失败先看推理预设；目录未变化看 Active 与 After restart；网络修改未生效看是否重启以及继承环境；MCP 不出现看是否已登记、是否被节点选择及发现状态。离线可运行 `python -m src.cli doctor --json`。

源码依据：`DefaultSettingsForm.vue`、`StorageSettingsGroup.vue`、`src/workspace_settings.py`、`src/conversation_context/settings.py`、`src/long_term_memory/settings.py`、`src/web_backend/node_memory_limits.py`。
