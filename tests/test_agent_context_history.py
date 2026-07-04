from types import SimpleNamespace


def test_agent_context_history_round_trips_items(tmp_path):
    from src.providers.agent_context_history import load_agent_context_history
    from src.providers.agent_context_history import save_agent_context_history

    agent = SimpleNamespace(memory=SimpleNamespace(current_memory_path=str(tmp_path / "memory.md")))
    items = [
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": "<permissions instructions>\nbody\n</permissions instructions>"}],
        }
    ]

    save_agent_context_history(agent, items)

    assert load_agent_context_history(agent) == items
