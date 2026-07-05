# AgentPark 节点 Skill 发现与调用机制笔记

## 1. 总览

AgentPark 中的 skill 是节点级能力配置。它不是全局自动生效，也不是一被选择就立即执行，而是由节点配置显式选择后，在节点运行时加载为：

- 给模型看的任务说明；
- 可选的资源索引；
- 可选的脚本工具；
- 可选的 MCP 依赖。

以 `agent_node` 为例，完整链路是：

```text
节点 config.skills
  -> CapabilityRegistry 发现 skills/
  -> load_node_skills 读取 SKILL.md / skill.json / resources
  -> resolve_agent_capabilities 合并 skill、plugin、MCP、tools
  -> agent_node 注入 <skills_instructions>
  -> 如果有脚本，注册 skill__xxx__yyy tool
  -> Agent 根据上下文决定是否使用 skill 或调用脚本工具
```

## 2. Skill 发现机制

节点公共配置字段定义在 `nodes/base_node.py`：

```python
common_config_defaults = {"plugins": [], "skills": [], "working_path": ""}
```

其中 `skills` 是一个多选字段：

```json
{
  "skills": {
    "type": "multiselect",
    "label": "Skills",
    "description": "List of node-scoped skill names loaded from the project skills folder."
  }
}
```

UI 中的 skill 下拉列表来自 `CapabilityRegistry`。它会调用：

```python
list_available_skill_options()
```

该函数扫描项目根目录下：

```text
skills/**/SKILL.md
```

每个可用 skill 必须是一个目录，并包含 `SKILL.md`。

## 3. Skill 文件格式

`SKILL.md` 必须包含 YAML frontmatter，至少有：

```md
---
name: demo
description: Demo skill
---

这里是 skill 的正文说明。
```

加载时会校验：

- 必须存在 YAML frontmatter；
- 必须有 `name`；
- 必须有 `description`；
- skill 路径必须在 `skills/` 根目录内，不能使用绝对路径或 `..` 逃逸。

正文部分会去掉 frontmatter 后作为 skill 指令注入给模型。

## 4. 节点运行时加载流程

`agent_node` 运行时会先读取节点配置，然后调用：

```python
resolve_agent_capabilities(...)
```

这个函数会解析节点配置里的：

```json
"skills": ["some-skill"]
```

并调用：

```python
load_node_skills(...)
```

加载结果是 `SkillDefinition`，里面包含：

- `name`
- `description`
- `path`
- `content`
- `version`
- `mcp_servers`
- `mcp_server_configs`
- `resource_root`
- `resources`
- `script_tools`

## 5. Skill 注入机制

Skill 加载后不是直接执行，而是被渲染成一段上下文：

```xml
<skills_instructions>
...
<skill>
<name>...</name>
<description>...</description>
<path>...</path>
...SKILL.md 正文...
</skill>
</skills_instructions>
```

然后通过：

```python
agent.Message(role, instructions, persist=False)
```

注入到 Agent 的本次运行上下文中。

注意：

- `persist=False`，所以 skill 指令不会写入节点长期 memory；
- OpenAI Responses 模式下通常使用 `developer` role；
- 其他 provider 通常使用 `system` role；
- Skill 是节点级的，只有配置了该 skill 的节点会注入。

## 6. Skill 的两种形态

### 6.1 纯指令型 Skill

只有 `SKILL.md`，没有脚本。

这种 skill 的作用是告诉模型：

- 遇到某类任务时如何分析；
- 该遵守什么流程；
- 需要读取什么资源；
- 有哪些边界和注意事项。

它本身不会变成工具，也不会强制执行。模型是否使用它，取决于当前任务和上下文。

### 6.2 带脚本工具的 Skill

如果 skill 目录中存在：

```text
skill.json
scripts/xxx.py
```

或：

```text
skill.json
scripts/xxx.js
```

则加载器会读取脚本工具声明。

脚本声明由 `src/skills/script_manifest.py` 解析。注册后，工具名格式为：

```text
skill__<skill_name>__<script_id>
```

例如：

```text
skill__demo__echo
```

模型可以像调用普通 function tool 一样调用它。

## 7. Skill 脚本调用机制

脚本工具注册由：

```python
register_skill_script_tools(agent, skill_definitions)
```

完成。

每个脚本工具会生成一个 OpenAI/function-call 风格的 tool declaration：

```json
{
  "type": "function",
  "function": {
    "name": "skill__demo__echo",
    "description": "...",
    "parameters": {
      "type": "object",
      "properties": {}
    }
  }
}
```

实际执行时调用：

```python
run_skill_script(...)
```

执行规则：

- Python 脚本使用当前 `sys.executable`；
- JS/MJS/CJS 脚本使用 `node`；
- 参数会通过 stdin 传入；
- 参数也会写入环境变量 `AITOOLS_SKILL_SCRIPT_ARGS`；
- 脚本 ID 写入 `AITOOLS_SKILL_SCRIPT_ID`；
- 是否允许写入写入 `AITOOLS_SKILL_SCRIPT_ALLOW_WRITE`；
- 执行结果会包装成 JSON，包含 `stdout`、`stderr`、`exit_code`、`timed_out` 等字段。

## 8. Skill 脚本安全约束

脚本 manifest 有明确限制：

- `entry` 必须在 skill 目录下；
- 脚本入口通常要求在 `scripts/` 下；
- 不允许绝对路径；
- 不允许 `.` 或 `..` 路径段；
- 支持 `.py`、`.js`、`.mjs`、`.cjs`；
- `timeoutSeconds` 必须在 1 到 300 秒之间；
- `argsSchema` 必须是 object schema；
- 写能力脚本需要显式启用。

这能避免 skill 脚本随意逃逸目录或无限运行。

## 9. Skill 资源读取机制

Skill 可以包含资源目录，例如：

```text
references/
assets/
scripts/
agents/
```

系统不会把这些资源内容全部塞进 prompt，而是构建资源索引。模型如果需要读取资源，需要调用工具：

```text
list_skill_resources
read_skill_resource
```

这两个工具位于：

```text
functions/skill_resource_tools.py
```

只有当已选中的 skill 存在资源时，`resolve_agent_capabilities` 才会自动把：

```text
skill_resource_tools
```

加入节点工具列表。

这样做的好处是：

- 避免大型 reference 默认污染上下文；
- 让模型按需读取；
- 降低 token 消耗；
- 保持资源访问在 skill 根目录内。

## 10. Skill 与 MCP 依赖

Skill 可以声明 MCP 依赖。

加载 skill 时会读取 skill 目录中的依赖配置，并把其中的 MCP server 合并进节点运行计划：

```python
selected_skill_dependencies = collect_loaded_skill_dependencies(selected_skill_definitions)
```

最终：

```python
merged_mcp_server_names = [
  *node_config_mcp_servers,
  *plugin_mcp_servers,
  *skill_mcp_servers
]
```

所以，选择一个 skill 可能会间接启用它依赖的 MCP server。

## 11. Skill 与 Plugin 的关系

Plugin 可以带来：

- tools；
- skills；
- skill definitions；
- MCP servers；
- MCP configs；
- tool definitions。

`agent_node` 会把节点直接选择的 skill 和 plugin 带来的 skill definition 合并：

```python
skill_definitions = [
  *capability_plan.selected_skill_definitions,
  *capability_plan.plugin_capabilities.skill_definitions,
]
```

然后统一：

- 注册 skill 脚本工具；
- 注入 skill 指令；
- 绑定 skill resource roots。

## 12. Agent Node 中的实际运行顺序

`agent_node` 的关键运行顺序是：

```text
1. 读取节点配置
2. resolve_agent_capabilities
3. create_agent
4. bind_agent_runtime_context
5. load_configured_tools
6. register_plugin_tool_definitions
7. register_skill_script_tools
8. register_mcp_server_tools
9. 注入 system/developer prompt
10. 注入 operational memory
11. 注入 MCP server context
12. 注入 skill instructions
13. 加载历史消息
14. 注入当前用户输入
15. agent.Send(run_tools=True)
```

Skill 注入发生在当前用户输入之前，因此模型在处理用户请求时已经能看到 skill 说明。

## 13. 机制边界

需要注意：

- Skill 默认不是强制执行器；
- 纯 `SKILL.md` 只是指令上下文；
- 真正可执行的是注册成 tool 的 skill script；
- 资源不会自动读取，需要模型调用 `read_skill_resource`；
- Skill 指令本次运行有效，不持久化进 memory；
- 如果 skill 加载失败，节点运行会失败，而不是静默跳过；
- 如果 skill 脚本失败，会把错误作为 tool result 返回给模型。

## 14. 一个节点选择 Skill 后的实际效果

假设某个 Agent 节点配置为：

```json
{
  "skills": ["openai-docs"]
}
```

运行时会发生：

```text
1. 扫描 skills/openai-docs/SKILL.md
2. 读取 name、description 和正文
3. 读取 references/ 等资源索引
4. 如存在 skill.json，加载脚本工具
5. 自动注册 skill_resource_tools
6. 将 skill 内容注入 developer/system 消息
7. Agent 根据当前任务决定是否读取资源或调用工具
```

## 15. 总结

AgentPark 的 skill 机制可以理解为：

> 节点级、可发现、可注入、可扩展工具的任务能力包。

它的设计重点不是“全局安装一个能力后自动执行”，而是：

- 在具体节点上显式选择；
- 运行时加载并校验；
- 将说明注入当前上下文；
- 必要时暴露资源读取工具；
- 必要时暴露脚本工具；
- 由模型在任务上下文中调用。

这个机制适合把垂直领域经验、操作手册、资源文件和少量自动化脚本封装为可复用能力，再挂载到不同 Agent 节点上。
