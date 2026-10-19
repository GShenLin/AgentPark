# 运行事件与主题

[Settings 索引](README.md) · [节点预设](presets-companion.md)

<a id="runtime-events"></a>
## 1. 运行事件 / Runtime Events

入口：**Settings → 运行事件**。全局配置在 `config/events.json`，节点/预设还可保存相应规则。表单修改后点击页顶 **应用**，而不是只切换 Enabled 就离开页面。

### 全局上下文策略

| 字段 | 作用 | 使用建议 |
| --- | --- | --- |
| Enabled | 启用运行事件系统 | 排错时先查看是否关闭 |
| Default TTL | 未覆盖时上下文片段的有效期 | 按信息应影响的执行范围选择 |
| Max Fragment Chars | 单个上下文片段长度上限 | 控制注入体积，不是用户输入总字数限制 |
| Dedupe Window Ms | 事件上下文去重窗口，毫秒 | 避免短时间重复片段；0 与具体规则按校验处理 |
| Refresh | 刷新编译/路由诊断 | 应用后查看规则是否正确编译 |

TTL 选项：`current_run` 用于当前执行，`next_turn` 用于下一轮消费，`persistent` 持续保留直到对应生命周期清理。它们管理运行时上下文片段，不是定时任务的时间表达式。

### 支持事件

| 事件 | 何时使用 |
| --- | --- |
| OnInput | 新输入到达时注入或处理上下文 |
| ToolFailure | 工具失败后提供补充指引或通知 |
| RuntimeNotice | 运行时产生提示时处理 |
| NetError | 网络相关错误时通知或交给 Agent 处理 |
| WorkPersisted | 结果已落盘后的通知与后处理 |
| WorkFailed | 一次工作失败后的处理 |

WorkPersisted 证明记录已保存，不自动证明业务目标已完成；它不应被当作独立测试通过信号。

### 规则动作

| 动作 | 作用 |
| --- | --- |
| `context.produce` | 由配置的 producer 生成上下文 |
| `context.append_file` | 读取指定文件并以配置角色附加上下文 |
| `notice.write` | 调用 notice writer 写通知 |
| `node.dispatch` | 使用指定推理预设或接收组派发 Agent 处理 |

推荐先从一个节点的一条规则开始。打开节点的事件配置，为实际事件选择动作、有效目标和参数并保存；需要复用时通过 SaveToProfile 保存。全局页的 Node Event Handlers 用于查看已存在的路由和删除条目，不提供对所有复杂动作的完整表单创建功能。

需要高级编辑时使用 JSON，依据当前动作合同填写 `target` 和 `params`；不要把附加文件路径、接收者和预设名混放。规则错误会在应用结果/诊断中显示，先修复再测试，不通过重复触发掩盖失败。

### Explicit Receivers

1. 点击 Add Receiver。
2. 填接收 Graph ID 和 Node ID，确保实际存在且可处理消息。
3. 删除无效接收者，应用配置。
4. 在小任务中触发预期事件，查看接收节点与诊断。

空显式列表不等于不能派发：符合规则的 dispatch 可从指定 Agent Profile 建临时 Companion 节点。具体取决于 handler 的预设与接收组配置；不能靠空字段推断默认模型已配置。

### Node Event Handlers

列表按事件 → Graph → 节点分组，显示处理序号、动作、目标/预设/文件路径和启用状态。Delete 修改当前规则草稿，仍需应用。Refresh 只读取诊断，不保存草稿。

验证方法：应用成功 → 触发一次目标事件 → 检查节点过程/接收者 → 在统计审计中核对结果。派发 Agent 会产生模型调用；避免为普通进度事件无条件派发大量重复工作。

源码依据：`RuntimeEventsSettingsForm.vue`、`webui/src/runtimeEventsConfig.ts`、`src/runtime_events/`。

<a id="theme"></a>
## 2. 主题 / Theme

入口：**Settings → 主题**。主题资源保存在 `theme/<preset-id>/`，当前活动预设指针保存在 `.cache/theme/active.json`；以页面显示的实际路径为准。

### 预设操作

| 控件 | 用法 |
| --- | --- |
| Active | 当前正在使用的预设 ID |
| Refresh | 刷新可用预设列表 |
| Load Preset → Load | 加载并应用已有预设，替换当前主题内容 |
| Save Preset → Save | 将当前草稿保存到指定预设并应用 |
| 页顶 Save | 保存当前正在编辑的主题 |

预设 ID 使用字母、数字、下划线和横线。先另存一个新 ID 再尝试大范围调整，便于随时加载原主题。

### 按面板编辑

左侧选择 Theme Panel，右侧按分组显示该面板现有字段。字段来自当前主题数据，并非每个面板都有完全相同的设置。

| 控件类型 | 如何使用 |
| --- | --- |
| 颜色 | 用选色器、颜色文本或调色板设置，支持透明色按钮 |
| 透明度 | 0–100% 滑条，结合背景检查可读性 |
| 下拉字段 | 只选择该字段允许的选项 |
| Image | 填资源名，或 Browse 上传图片 |
| 其他文本字段 | 按该主题字段支持的样式值填写；需要时查看高级 JSON |

上传图片后字段指向对应预设的资源；当前允许的图片格式及上限由后端校验，单文件上限为 50 MB。上传完成不等于所有主题草稿已保存，最终仍需保存主题或预设。

修改后检查桌面与窄屏的文字、按钮和输入框对比度；出现无效样式或加载错误时重载一个已知预设。主题保存/加载会刷新页面主题，无需重启模型后端。
