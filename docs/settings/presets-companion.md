# 节点预设与 Companion

[Settings 索引](README.md) · [模型配置](models.md) · [默认设置](defaults.md)

<a id="node-presets"></a>
## 节点预设 / Node Presets

入口：**Settings → 节点预设**。预设保存在 `agent/*.json`，页面左侧选择现有条目，右侧复用画板节点的 schema 配置表单。

### 创建与编辑

1. 先在画板创建并配置实际节点，验证模型、指令和工具可用。
2. 右键该节点选择 **SaveToProfile**，按保存对话框填写预设身份。
3. 到 Settings → 节点预设，选择刚保存的条目。
4. 修改 Preset name 及 Node configuration 中实际显示的字段。
5. 需要时展开 Preset metadata and event rules，编辑元数据和规则。
6. 点击 **Save Profile**，等待成功反馈，再用该预设创建一个新节点验证。

当前编辑器用于编辑已有预设，没有独立的“空白新建预设”按钮。Reload 重读已保存内容；Delete Preset 删除预设文件，操作前检查 Companion、后台推理与粘贴设置是否仍在引用它。

### Node configuration

不同节点类型和 Provider 显示不同字段，常用普通 Agent 字段如下。

| 配置 | 怎么使用 |
| --- | --- |
| Provider / Model | 选择有效连接和明确模型，不能只配置 Provider 名称 |
| Instruction / System prompt | 定义任务职责、交付要求与约束；提示词库入口按节点 schema 显示 |
| Working path | 后端机器的任务工作目录；在远程执行时按远端工作区规则处理 |
| 思考、搜索等推理字段 | 以当前 Provider 功能矩阵允许值为准，禁用字段不表示可强行填值 |
| Tools | 勾选确实需要的工具；运行时还会应用访问身份过滤 |
| MCP Servers | 选择已登记并能启动的服务 |
| Skills | 选择流程能力；阅读依赖后按需激活 |
| Plugins | 选择已发现的插件，插件资源和依赖需先安装 |
| 多模态/语音 | 仅在节点与 Provider 支持时显示相应生成或语音字段 |

若编辑器显示没有 schema，先核对 `node_type_id` 是否仍被当前代码注册、Provider 是否有效。不要将整个预设改成空对象来掩盖错误。

### 元数据与事件规则

| 字段 | 含义 |
| --- | --- |
| Node type | 只读类型 ID；决定配置 schema |
| Node name | 从预设创建节点时使用的可选名称 |
| Description | 预设用途说明 |
| Source graph / Source node | 来源标识，用于记录预设出处，不等于实时绑定该节点 |
| Event rules | 预设保存的高级事件 JSON，与普通字段分别编辑 |
| Format | 校验/格式化规则文本；最终仍需 Save Profile |

先在节点的事件配置中验证规则，再保存在预设中复用。规则要引用真实事件、动作和存在的目标/预设，操作见 [运行事件](events-theme.md#runtime-events)。

### 修改预设会影响谁

| 使用方式 | 修改后的影响 |
| --- | --- |
| 普通节点从预设创建 | 新节点获得配置；已存在普通节点不因修改预设而批量更新 |
| Companion 的 `profile_id` | 下一轮解析所选预设的最新模型、指令与能力 |
| 历史压缩 `profile_id` | 下一次后台推理读取预设，不使用原节点模型替代 |
| 长期记忆提取/合成预设 | 后续模型调用读取最新预设；内部任务不装载普通工具 |
| Paste Agent 选择 | 后续粘贴创建时使用所选预设 |
| 事件 node.dispatch 的预设 | 后续派发按规则构建任务，需保证引用继续有效 |

因此，改动被多个后台任务共享的预设前，先考虑它们是否都适用。角色指令、明确模型与服务可用性比预设显示名称更重要。

<a id="companion"></a>
## 伴侣 / Companion

入口：**Settings → 伴侣**。表单当前只有两项核心选择：

| 字段 | 作用 |
| --- | --- |
| Preset / `profile_id` | 指定一个存在的 `agent_node` 推理预设 |
| Working Path / `working_path` | Companion 在当前设备上的工作目录 |

模型、提示词和能力在节点预设编辑器中管理，不在 Companion 页重复设置。

### 配置流程

1. 先在节点预设中准备一个模型可用、职责清晰的 Companion 角色。
2. 在 Companion 页选择该预设，填写存在的本地工作目录。
3. 点击页顶保存。
4. 用已安装依赖的 Python 运行 `python -m src.cli chat`，或通过项目的 Companion 使用入口发起测试。
5. 查看实际工具与模型是否对应预设。修改预设后用新一轮对话验证。

配置位于当前记忆根目录下的 Companion 节点目录；默认路径为 `memories/Companion/Companion/config.json`，以设置页显示的路径为准。身份和会话状态属于 Companion 节点，本地工作目录也由节点保管。

### 启动修复如何使用它

Windows 标准启动流程失败时，会通过同一 Companion 预设执行独立修复，保留上下文与日志，再重新构建并检查后端就绪。恢复任务会为本地修复设置执行目录与能力，不修改你选择的预设。

这要求 Python 环境仍能加载 Agent 运行时、预设有效、模型可用且服务可达。缺少账号或安装依赖时，不能期待未配置的 Companion 自动完成一切。最多修复次数与日志位置见 [启动修复](../startup-repair.md)。

### 常见问题

| 现象 | 处理 |
| --- | --- |
| 下拉里没有期望角色 | 检查预设是否为 `agent_node`，是否成功保存到 `agent/` |
| 缺预设或缺模型报错 | 恢复预设或改选有效预设，并明确选择模型；不依赖隐式替代 |
| 修改预设后旧普通节点未改变 | 在实际节点编辑配置；预设不是全体节点的实时继承关系 |
| 修复仍失败 | 查看 `.runtime/startup-*.log`、服务器错误日志和 `startup-repair/` 记录 |

源码依据：`NodePresetEditor.vue`、`NodePresetMetadataPanel.vue`、`CompanionSettingsForm.vue`、`src/agent_profile_inference.py`、`src/companion_paths.py`。
