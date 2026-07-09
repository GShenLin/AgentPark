from types import SimpleNamespace


def test_agent_runtime_context_bind_and_read(tmp_path):
    from src.providers.agent_runtime_context import AgentRuntimeContext
    from src.providers.agent_runtime_context import bind_agent_runtime_context
    from src.providers.agent_runtime_context import get_agent_runtime_context

    calls = []
    agent = SimpleNamespace(config={})

    bound = bind_agent_runtime_context(
        agent,
        AgentRuntimeContext(
            graph_id="g1",
            node_id="Agent1",
            node_type_id="agent_node",
            workspace_root=str(tmp_path),
            working_path=str(tmp_path / "work"),
            collaboration_mode="plan",
            shell="powershell",
            responses_instruction="Use the Responses instructions field.",
            skill_resource_roots={"demo": str(tmp_path / "skill")},
            persist_assistant_tool_call_note=lambda message: calls.append(message),
        ),
    )

    resolved = get_agent_runtime_context(agent)

    assert resolved == bound
    assert resolved.graph_id == "g1"
    assert resolved.node_id == "Agent1"
    assert resolved.collaboration_mode == "plan"
    assert resolved.responses_instruction == "Use the Responses instructions field."
    assert resolved.skill_resource_roots == {"demo": str(tmp_path / "skill")}
    assert resolved.persist_assistant_tool_call_note is not None
    resolved.persist_assistant_tool_call_note({"role": "assistant"})
    assert calls == [{"role": "assistant"}]


def test_agent_runtime_context_reads_bound_attributes(tmp_path):
    from src.providers.agent_runtime_context import get_agent_runtime_context

    agent = SimpleNamespace(
        _agentpark_graph_id="graph-1",
        _agentpark_node_id="node-1",
        _agentpark_node_type_id="agent_node",
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
    assert resolved.workspace_root == str(tmp_path)
    assert resolved.working_path == str(tmp_path / "work")
    assert resolved.collaboration_mode == "plan"
    assert resolved.shell == "powershell"
