from types import SimpleNamespace


def test_agent_runtime_context_bind_and_read(tmp_path):
    from src.providers.agent_runtime_context import AgentRuntimeContext
    from src.providers.agent_runtime_context import bind_agent_runtime_context
    from src.providers.agent_runtime_context import get_agent_runtime_context

    calls = []
    active_calls = {}
    agent = SimpleNamespace(config={})

    def begin_tool_call(call_id):
        event = object()
        active_calls[call_id] = event
        return event

    def end_tool_call(call_id, event):
        if active_calls.get(call_id) is event:
            active_calls.pop(call_id, None)

    bound = bind_agent_runtime_context(
        agent,
        AgentRuntimeContext(
            graph_id="g1",
            node_id="Agent1",
            node_type_id="agent_node",
            node_directory=str(tmp_path / "node"),
            workspace_root=str(tmp_path),
            working_path=str(tmp_path / "work"),
            collaboration_mode="plan",
            shell="powershell",
            responses_instruction="Use the Responses instructions field.",
            skill_resource_roots={"demo": str(tmp_path / "skill")},
            persist_assistant_progress=lambda message: calls.append(message),
            persist_provider_turn_metadata=lambda message: calls.append(message),
            begin_tool_call_cancellation=begin_tool_call,
            end_tool_call_cancellation=end_tool_call,
        ),
    )

    resolved = get_agent_runtime_context(agent)

    assert resolved == bound
    assert resolved.graph_id == "g1"
    assert resolved.node_id == "Agent1"
    assert resolved.node_directory == str(tmp_path / "node")
    assert resolved.collaboration_mode == "plan"
    assert resolved.responses_instruction == "Use the Responses instructions field."
    assert resolved.skill_resource_roots == {"demo": str(tmp_path / "skill")}
    assert resolved.persist_assistant_progress is not None
    assert resolved.persist_provider_turn_metadata is not None
    resolved.persist_assistant_progress({"role": "assistant_progress"})
    assert calls == [{"role": "assistant_progress"}]
    resolved.persist_provider_turn_metadata({"role": "provider_turn"})
    assert calls[-1] == {"role": "provider_turn"}
    cancel_event = resolved.begin_tool_call_cancellation("call-1")
    assert active_calls == {"call-1": cancel_event}
    resolved.end_tool_call_cancellation("call-1", cancel_event)
    assert active_calls == {}


def test_agent_runtime_context_reads_bound_attributes(tmp_path):
    from src.providers.agent_runtime_context import get_agent_runtime_context

    agent = SimpleNamespace(
        _agentpark_graph_id="graph-1",
        _agentpark_node_id="node-1",
        _agentpark_node_type_id="agent_node",
        _agentpark_node_directory=str(tmp_path / "node"),
        _agentpark_workspace_root=str(tmp_path),
        _agentpark_working_path=str(tmp_path / "work"),
        _agentpark_collaboration_mode="plan",
        _agentpark_shell="powershell",
        config={},
    )

    resolved = get_agent_runtime_context(agent)

    assert resolved.graph_id == "graph-1"
    assert resolved.node_id == "node-1"
    assert resolved.node_type_id == "agent_node"
    assert resolved.node_directory == str(tmp_path / "node")
    assert resolved.workspace_root == str(tmp_path)
    assert resolved.working_path == str(tmp_path / "work")
    assert resolved.collaboration_mode == "plan"
    assert resolved.shell == "powershell"
