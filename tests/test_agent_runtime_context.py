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
            responses_system_prompt_as_instructions=True,
            skill_resource_roots={"demo": str(tmp_path / "skill")},
            persist_assistant_tool_call_note=lambda message: calls.append(message),
        ),
    )

    resolved = get_agent_runtime_context(agent)

    assert resolved == bound
    assert resolved.graph_id == "g1"
    assert resolved.node_id == "Agent1"
    assert resolved.collaboration_mode == "plan"
    assert resolved.responses_system_prompt_as_instructions is True
    assert resolved.skill_resource_roots == {"demo": str(tmp_path / "skill")}
    assert resolved.persist_assistant_tool_call_note is not None
    resolved.persist_assistant_tool_call_note({"role": "assistant"})
    assert calls == [{"role": "assistant"}]


def test_agent_runtime_context_reads_legacy_attributes(tmp_path):
    from src.providers.agent_runtime_context import get_agent_runtime_context

    agent = SimpleNamespace(
        _aitools_graph_id="legacy-graph",
        _aitools_node_id="legacy-node",
        _aitools_node_type_id="agent_node",
        _aitools_workspace_root=str(tmp_path),
        _aitools_working_path=str(tmp_path / "work"),
        _aitools_collaboration_mode="plan",
        _aitools_shell="powershell",
        config={},
    )

    resolved = get_agent_runtime_context(agent)

    assert resolved.graph_id == "legacy-graph"
    assert resolved.node_id == "legacy-node"
    assert resolved.node_type_id == "agent_node"
    assert resolved.workspace_root == str(tmp_path)
    assert resolved.working_path == str(tmp_path / "work")
    assert resolved.collaboration_mode == "plan"
    assert resolved.shell == "powershell"
