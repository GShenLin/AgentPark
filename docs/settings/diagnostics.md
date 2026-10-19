# 测试、压力监控、统计与维护

[Settings 索引](README.md) · [模型配置](models.md)

<a id="provider-test"></a>
## 1. 提供商测试 / Test

入口：**Settings → 提供商测试**。结果位于 `config/ProviderLimit.json`，用于展示能力/模型探测证据；它不是服务商额度账单。

### 按钮与流程

| 按钮 | 作用 |
| --- | --- |
| Test all | 对已配置 Provider 执行能力测试作业 |
| Models | 发起模型目录发现作业 |
| Reload | 重读结果，不发起同等测试 |

1. 先保存 Provider，确保账号和模型 ID 有效。
2. 需要查模型时点击 Models；需要探测协议参数时点击 Test all。
3. 等待进度条的当前 Provider 和总数完成，避免同时重复发起。
4. 左侧选择 Provider，逐个查看测试通道、Endpoint、Access error、Unsupported 和 Inconclusive。
5. 按证据修复设置，再对实际节点执行最小任务。

测试会进行真实网络/模型请求，可能耗时和产生费用。对不支持探测的 Provider，查看具体原因，不能将没有测试项当作全部通过。

### 如何读结果

| 结果 | 含义 |
| --- | --- |
| 成功/可访问 | 本次测试的连接和请求完成，不等于所有模型与功能均可用 |
| Access error | 先排查认证、网络和实际 Endpoint |
| Unsupported | 已发现对应字段/能力不被该测试路径接受 |
| Inconclusive / not tested | 无法确认或未覆盖；不能视为支持，也不能简单视为永久不支持 |
| Model discovery | 查看查询时间、地址、成功状态、失败原因和模型清单 |

旧结果可能不反映账号、模型或协议变更后的实际能力。新增模型应在 Provider 中明确登记并保存，测试页显示目录不等于所有模型已被节点选用。

<a id="pressure"></a>
## 2. 压力测试 / Pressure

入口中文名是“压力测试”，当前面板实际为 **Provider Pressure 运行监控**。它读取后端限流器状态，不会因打开页面或 Refresh 自动发起压力请求。

| 列 | 如何理解 |
| --- | --- |
| Provider / Type / Model | 当前统计连接标识与模型信息 |
| Concurrency | 当前在途请求 / 本地并发上限 |
| Queue | 当前排队及峰值 |
| RPM Limit | 本地配置的请求频率上限 |
| Interval / Next | 请求间隔与下次允许时间 |
| Total TPM / left | 当前 Token 窗口用量、配置上限与余量 |
| Input / Output TPM | 输入、输出分别占用 |
| TPM Next | Token 限制预计允许的等待时间 |
| Peak | 并发、队列、请求频率和 Token 的峰值 |

刷新后用以下顺序判断：是否队列增长 → 并发是否满 → RPM/TPM 是否触限 → 上游是否还在处理。需要调整上限时回到 Provider 额度设置保存，再观察新请求。显示“未配置限制”不表示服务商无限额；这是当前进程本地调度状态，不是全账号跨设备总用量。

<a id="statistics"></a>
## 3. 统计 / Statistics

入口：**Settings → 统计**，内部部分名称为 Static。包含 **Full Chain Audit** 和 **Tool Statistics** 两个标签页。

### Full Chain Audit：检查一次完整运行

1. 选择 From / To 日期范围。
2. 按需选择 Graph 和 Node，点击 Reload。
3. 从左侧选择目标运行，核对 `trace_id` 和完整性标记。
4. 右侧查看状态、耗时、模型轮数、工具数和文件变更。
5. 沿 Timeline 展开 Raw details 和可读取的 artifact 内容，定位第一次出现异常的步骤。

| 区域 | 能回答的问题 |
| --- | --- |
| Status / Duration | 运行如何结束、用了多久 |
| Model rounds | 模型实际往返次数 |
| Tool calls | 本地与服务端工具记录 |
| Persisted file changes | 已记录的文件操作和路径 |
| Timeline | 输入、模型、工具和落盘之间的先后关系 |
| Completeness | 证据是否完整；部分记录不能当作完整执行链 |

文件变更列表只覆盖运行记录能够提供的证据，不代表自动扫描了所有外部工具修改。过大的 artifact 会显示路径与超限提示，不在页面截成“完整内容”。

### Tool Statistics：按 Provider 诊断

1. 选 Graph 与时间范围（全部、24 小时、7 天、30 天）。
2. 选择 Provider，查看总调用、成功、失败和成功率。
3. 展开失败模式/历史，选 Recent Calls 中的具体调用。
4. 阅读参数、失败原因、完整结果和 Diagnostics，再判断问题属于模型参数、工具合同还是执行环境。
5. 在 Model Turn Statistics 中选择任务，查看模型请求和用量。

| 数据 | 用法 |
| --- | --- |
| Tools | 按工具的调用计数和最近状态 |
| Recent Calls | 当前范围的近期调用，不是无限完整历史 |
| Call / Failure Review | 调用参数、完整结果、错误与诊断 |
| Model Turn Statistics | 一次节点执行中每个完成的模型响应及请求统计 |
| Input / Output | 切换累计和单请求 Token 视图 |
| Time scale | 缩放时间线；标号点表示完成响应，虚线表示节点运行结束 |

`model turns` 是完整模型响应数，不等于用户消息数。一轮用户任务可包含多次模型请求与工具调用。usage 标为 missing / partial 时，缺失部分不算零；计数与时长也不自动证明任务结果正确。

<a id="maintenance"></a>
## 4. 清理与维护

| 入口 | 实际影响 |
| --- | --- |
| Tool Statistics → Reload | 重新读取统计 |
| Tool Statistics → Clear | 清除全部工具统计并建立统计重置点，不只清当前筛选的一个 Provider |
| Tool Statistics → Clear long-term memory | 清所有节点派生记忆与笔记，原始对话保留，可后续重新提取 |
| 默认设置 → Storage → Clear Logs | 删除维护脚本所列运行/响应/调试日志，不等于删聊天 |

清理前先保留需要的诊断证据。原始聊天、工具统计、审计日志和派生长期记忆的用途不同，不要用其中一个清理按钮代替另一个。

### 离线诊断与配置检查

使用安装依赖的 Python；示例中的节点 ID 替换为实际 ID：

```powershell
python -m src.cli doctor --json
python -m src.cli config validate --graph default --node YOUR_NODE --json
python -m src.cli capabilities list --graph default --node YOUR_NODE --refresh --json
```

Doctor 检查工具链、Provider、MCP、Skill、插件、Graph 和节点配置。它不等于真实模型调用或完整外部依赖验收。查看 `checks[].name/status/detail/path`，按具体文件修复。

### 日志位置

| 位置 | 适用问题 |
| --- | --- |
| `.runtime/startup-*.log` / `restart-worker-*.log` | Windows 构建、启动与重启交接 |
| `.runtime/agentpark-server.log` / `.err.log` | 标准脚本启动的后端输出 |
| `.runtime/startup-repair/` | 启动修复上下文与会话 |
| `.runtime/node-windows/host.log` | Windows 节点小窗 |
| `.runtime/public-gateway-access.log` | 公共网关外部请求 |
| 节点/Graph 目录的运行记录 | 具体节点任务和图调度 |
| `.cache/tool_stats/` | 工具统计及重置数据 |

自定义 Memories Directory 后，Graph/节点记录位于新的活动根目录。手动前台启动的服务输出在终端，不保证自动写入脚本日志文件。

<a id="exit"></a>
## 5. 退出 / Exit

入口：**Settings → 退出 → Exit backend**。它请求结束当前后端，不只是关闭 Settings 或浏览器；其他连接到同一实例的页面会失去服务。

执行前完成或停止需要保留结果的任务，再按界面确认退出。后端停止后浏览器无法自行恢复模型执行；重新运行原启动入口。返回 Board、关闭节点小窗与 Exit backend 是三个不同操作。

### 重启

用标准启动器管理的实例可使用界面重启或 `Restart.bat` / `Restart.sh`。Windows 重启命令返回只说明请求被接受，必须等待新后端就绪；构建、修复与实际 PID 检查结果在日志中。手动运行时用同一解释器重新启动更便于排错。

启动修复不替代外部工具/模型的真实验收。详细状态和恢复边界见 [启动修复](../startup-repair.md)、[运行状态机](../runtime-state-machine.md)与 [Troubleshooting](../troubleshooting.md)。
