# Agent 配置与 Provider 参数映射

应用层通过 `create_agent(..., agent_config=AgentConfig(...))` 创建 Agent。
工厂在实例化之前解析所选模型，校验 Provider 的显式参数映射，然后保存该实例的调用方案。
普通节点、对话压缩、长期记忆、目标评估、规划和工具任务均通过这个方案发送。

## 边界

- `AgentConfig`：一次 Agent 实例的推理配置，包括模式、工具执行开关、联网、思考、推理强度、推理摘要、流式开关和模式参数。
- `AgentSendContext`：每次调用的工具声明、工具执行覆盖值和文本/思考流回调。它不能覆盖实例的 Provider、模型或推理参数。
- `ProviderParameterMapping`：构造参数与发送参数的来源名到目标名映射。每个通用字段必须声明目标名，或在发送映射中明确标记为不适用。
- `AgentInvocation`：创建时生成的参数快照，发送时复制使用，避免 Provider 修改可变配置影响下一次发送。
- Provider 运行时：继续负责 HTTP 协议字段、消息、媒体选项和响应的具体转换。例如 `reasoning_effort` 到 `reasoning.effort` 的 HTTP 映射属于协议实现。

模型选择仍使用现有 `model_id` 及 Provider 模型允许列表。工作目录、插件、技能、MCP、节点身份和历史策略属于节点运行环境，不作为任意关键字传给 Provider。

## 使用

```python
from src.providers import AgentConfig, AgentSendContext, create_agent, send_agent

agent = create_agent(
    "provider-id",
    model_id="allowed-model-id",
    memory_file_path="scratch.md",
    internal_memory_enabled=False,
    agent_config=AgentConfig(
        run_tools=False,
        web_search="disabled",
        thinking="enabled",
        reasoning_effort="high",
        reasoning_summary="concise",
        stream=True,
    ),
)
agent.Message("user", "Task input", persist=False)
result = send_agent(agent, AgentSendContext(stream_handler=on_text))
```

`BaseAgent.send()` 使用相同的配置方案。Provider 的大写 `Send()` 是底层实现接口；应用层不直接拼接参数调用它。Provider 内部的工具循环和协议重试可以继续调用自己的底层接口。

## 不适用参数与错误

已知通用字段在目标 Provider 不适用时，由显式映射或现有模型/传输能力矩阵排除。排除原因记录在实例的 `_agent_invocation.excluded_fields` 和日志中。例如豆包预设包含 `reasoning_summary` 时，该字段不会进入 `DouBaoAgent.Send()`；OpenAI Responses 则保留它。

媒体生成的联网等参数由媒体模式处理，不套用聊天传输的能力限制。Hyper3D 和 Alpha Matting 只允许专用媒体方法，统一发送入口会明确拒绝。

未知字段、错误类型及无效通用枚举值会报错。映射中的目标参数与真实函数签名不一致，或实现新增了映射中没有的必填参数，会在实例化之前报错。函数签名仅用于检查显式契约，不用于猜测支持哪些字段或静默过滤。

Provider 内部抛出的异常直接传播，不通过捕获 `TypeError` 删除参数后重试。

## 扩展与验证

新增 Provider 时，注册实现类并在 `PROVIDER_PARAMETER_MAPPINGS` 添加完整映射。名称不同可直接配置来源名到目标名，不需要修改节点、压缩和记忆调用方。模型能力沿用 `build_provider_feature_matrix`，Agnes 聊天采用 OpenAI 能力规则。

关键测试：

- `tests/test_agent_parameter_mapping.py`：全部注册实现的真实构造/发送签名、能力差异、字段别名、模型切换、类型错误、映射缺漏、配置隔离和异常传播。
- `tests/test_agent_invocation_integration.py`：使用真实工厂与真实 `Send()` 实现，隔离网络传输，覆盖普通节点、压缩、记忆各阶段、Provider 切换以及管理器/工具调用。
- 现有 Provider 协议测试继续检查具体 HTTP 参数和流式/工具协议。

修改预设或切换 Provider 后，下一次创建 Agent 会重新解析配置并生成新方案；已经创建的实例保留它自己的参数快照。
