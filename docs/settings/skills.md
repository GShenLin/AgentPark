# Skill 管理与能力接入

[Settings 索引](README.md) · [MCP 配置](defaults.md#11-mcp-服务器) · [知识库](knowledge.md)

入口：**Settings → Skill 管理**。这里管理 Skill 文件与加载来源；真正让某个 Agent 使用能力，还需要在该节点配置中选择。

## 1. 选择加载来源

默认优先级是：项目 `.agents/skills` → 后端系统用户 `~/.agents/skills` → 按添加顺序的自定义来源。

1. 展开 **管理加载路径**，核对每个来源的实际绝对路径、存在状态和错误。
2. 添加自定义根目录，例如 `D:\Shared\Skills`；目录内应包含多个 Skill 文件夹。
3. 点击添加加载路径，等待刷新并确认 Skill 出现。
4. 移除时选择对应自定义来源，确认停止加载；文件仍留在原目录。

自定义路径属于后端设备，不是当前浏览器设备。配置位于本机 `.cache/skill-roots.json`；路径必须为绝对路径，不得与已有根目录重叠/嵌套。移除来源前需解除它包含的已有引用。

Skill 用相对路径标识，例如 `Game/Design/combat`。同路径重复时前面的来源优先，页面保留全部版本并显示 `shadowed_by` 提示。不要只按显示名称推断实际运行版本。

## 2. 搜索、阅读与检查依赖

1. 用顶部搜索查名称、用途或路径；搜索覆盖全部来源与层级。
2. 按来源和分类文件夹浏览，点击某个 Skill 的详情。
3. 阅读完整 `SKILL.md`，需要时切换“查看原文”。
4. 查看依赖工具、MCP 服务、附带脚本和资源，以及节点/模板引用位置。
5. 按说明准备外部 CLI、账号或本地服务，再到目标节点选用。

管理页读取说明，不执行其中脚本；预览不执行嵌入 HTML 或自动加载远程图片。格式错误、目录不可读、缺失依赖和发现错误会明确显示，应先处理再运行任务。

## 3. 创建分类与整理

不含 `SKILL.md` 的目录视作分类，可以多层组织；含 `SKILL.md` 的目录整体视作一个 Skill，内部脚本和素材不会被当作分类展开。

| 操作 | 步骤与效果 |
| --- | --- |
| 新建文件夹 | 选择来源/父目录，点新建文件夹，填名称并保存 |
| 整理 Skill | 点击整理，选择同来源下的目标父目录，可同时改文件夹名 |
| 整理分类 | 操作分类目录，连同子目录整体移动 |
| 删除 | 确认移入回收区；说明、脚本与素材整体移出已安装列表 |
| 恢复 | 在回收区点击恢复；原父目录需存在，且目标无同名目录 |

文件夹名须以字母或数字开头，后续使用字母、数字、下划线、短横线和点；用途说明与正文可用中文。重命名目录不会改写 Skill 内部名称和正文路径。移动仅在同一加载来源内进行。

## 4. 引用保护

被节点、Agent 模板或 Graph 模板按路径引用的 Skill/文件夹，不能直接移动或删除。页面会列出引用位置：

1. 到所列配置中取消旧引用并保存。
2. 返回管理页刷新，完成移动/删除。
3. 在需要的节点或模板中从新路径重新选择，保存并发起新任务验证。

引用扫描失败也会阻止整理，先修复报错的配置，不应当作“无引用”处理。链接和 junction 不允许通过管理页读取或整理。

删除记录保存在加载根目录旁 `.skill-trash/<root-id>/`，每个来源分别管理；删除父分类后，恢复子项前先恢复父目录。移入回收区不是卸载外部依赖软件。

## 5. 在 Agent 中真正启用

| 能力种类 | 管理位置 | 节点中的选择 |
| --- | --- | --- |
| Tool | 项目已注册工具模块/函数 | `tools` |
| MCP | 默认设置中的 `mcpServers` 或能力依赖 | `mcp_servers` |
| Skill | 本页来源目录中的 Skill | `skills` |
| Plugin | `plugins/` 中的有效插件及其依赖 | `plugins` |

选择后保存节点，下一次执行装载新能力。自有 Agent 的 Skill 先提供描述，模型通过激活接口装载所需资源与工具；下一条用户消息的激活状态按运行时规则重新建立。阅读某个文件不等于已完成 Skill 激活。

安装到目录、在管理页可见、被节点选中、运行中激活、工具调用成功是不同步骤。原生 Harness 有自己的能力发现，不应推断本页中的所有 Skill 都会自动复制到 Harness 工作区。

### 离线检查

将下面示例的 Graph 和节点 ID 替换为真实 ID，并使用已安装依赖的 Python：

```powershell
python -m src.cli capabilities list --graph default --node YOUR_NODE --refresh --json
python -m src.cli capabilities enable --kind skill --name YOUR_SKILL --graph default --node YOUR_NODE
python -m src.cli config validate --graph default --node YOUR_NODE --json
```

CLI 还支持 `tool`、`mcp`、`plugin` 种类与 disable 操作，修改在下次 Agent 执行生效。未发现的能力先看 descriptors 中的诊断，不反复改相近名称。

更多说明：[Skill 管理合同](../skill-management.md)、[能力系统](../capability-system.md)、[编写 Skill / 插件](../skill-plugin-authoring.md)。
