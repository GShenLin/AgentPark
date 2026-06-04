import base64
import json
import time
from pathlib import Path


def _write_sample_png(path: Path) -> Path:
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5WZ8kAAAAASUVORK5CYII="
    )
    path.write_bytes(raw)
    return path


def _find_structured(output_envelope: dict) -> dict:
    parts = output_envelope.get("parts") if isinstance(output_envelope, dict) else []
    for part in parts if isinstance(parts, list) else []:
        if isinstance(part, dict) and str(part.get("type") or "") == "structured":
            data = part.get("data")
            if isinstance(data, dict):
                return data
    return {}


def _extract_output_payload(result: dict) -> dict:
    if not isinstance(result, dict):
        return {}
    output = result.get("output")
    if isinstance(output, dict):
        return output
    routes = result.get("routes")
    if isinstance(routes, list) and routes:
        first = routes[0]
        if isinstance(first, dict):
            payload = first.get("payload")
            if isinstance(payload, dict):
                return payload
    return {}


def test_gui_agent_node_mock_loop_reaches_finished(monkeypatch, tmp_path):
    import nodes.base_node as base_node
    from nodes.gui_agent_node import Node

    monkeypatch.setattr(base_node, "_get_runtime_root", lambda: str(tmp_path))

    seed = _write_sample_png(tmp_path / "seed.png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "open a new tab and finish"},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
        ],
    }

    node = Node()
    result = node.on_input(
        message,
        {
            "graph_id": "g1",
            "node_instance_id": "gui1",
            "instruction": "open new tab and finish",
            "mock_actions": [
                "click(point='<point>500 500</point>')",
                "finished(content='ok')",
            ],
            "dry_run": "true",
            "verify_on_finish": "false",
            "max_steps": "4",
            "step_delay_seconds": "0",
        },
    )

    output = _extract_output_payload(result)
    assert isinstance(output, dict)
    data = _find_structured(output)
    assert data.get("finished") is True
    assert data.get("status") == "done"

    steps = data.get("steps")
    assert isinstance(steps, list)
    assert len(steps) == 2
    assert steps[0].get("action_name") == "click"
    assert steps[1].get("action_name") == "finished"
    marked_after = str(steps[0].get("screenshot_after_marked") or "")
    assert marked_after
    assert Path(marked_after).exists()
    assert str(steps[0].get("screenshot_after") or "") == marked_after

    run_dir = Path(str(data.get("run_dir") or ""))
    assert run_dir.exists()
    exec_log = run_dir / "execution.jsonl"
    assert exec_log.exists()
    lines = [json.loads(line) for line in exec_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(str(item.get("event") or "") == "step" for item in lines)
    step_events = [item for item in lines if str(item.get("event") or "") == "step"]
    assert step_events
    first_step_event = step_events[0]
    assert isinstance(first_step_event.get("execute"), dict)
    assert "screen_changed" in first_step_event.get("execute")

    resource_parts = [p for p in (output.get("parts") or []) if isinstance(p, dict) and p.get("type") == "resource"]
    assert len(resource_parts) >= 3
    for part in resource_parts:
        res = part.get("resource") or {}
        uri = str(res.get("uri") or "")
        if uri:
            assert Path(uri).exists()


def test_gui_agent_node_drag_generates_marked_feedback(monkeypatch, tmp_path):
    import nodes.base_node as base_node
    from nodes.gui_agent_node import Node

    monkeypatch.setattr(base_node, "_get_runtime_root", lambda: str(tmp_path))

    seed = _write_sample_png(tmp_path / "seed_drag.png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "drag and finish"},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
        ],
    }

    node = Node()
    result = node.on_input(
        message,
        {
            "graph_id": "g_drag",
            "node_instance_id": "gui_drag",
            "instruction": "drag once and finish",
            "mock_actions": [
                "drag(start_point='<point>100 100</point>', end_point='<point>900 900</point>')",
                "finished(content='ok')",
            ],
            "dry_run": "true",
            "verify_on_finish": "false",
        },
    )

    output = _extract_output_payload(result)
    assert isinstance(output, dict)
    data = _find_structured(output)
    assert data.get("finished") is True
    steps = data.get("steps")
    assert isinstance(steps, list)
    assert len(steps) == 2
    assert steps[0].get("action_name") == "drag"
    marked_after = str(steps[0].get("screenshot_after_marked") or "")
    assert marked_after
    assert Path(marked_after).exists()
    execute = steps[0].get("execute")
    assert isinstance(execute, dict)
    marker_meta = execute.get("marked_coordinates")
    assert isinstance(marker_meta, dict)
    assert marker_meta.get("action") == "drag"
    assert isinstance(marker_meta.get("start"), list)
    assert isinstance(marker_meta.get("end"), list)


def test_gui_agent_node_scroll_without_point_still_marks_feedback(monkeypatch, tmp_path):
    import nodes.base_node as base_node
    from nodes.gui_agent_node import Node

    monkeypatch.setattr(base_node, "_get_runtime_root", lambda: str(tmp_path))

    seed = _write_sample_png(tmp_path / "seed_scroll.png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "scroll and finish"},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
        ],
    }

    node = Node()
    result = node.on_input(
        message,
        {
            "graph_id": "g_scroll",
            "node_instance_id": "gui_scroll",
            "instruction": "scroll once and finish",
            "mock_actions": [
                "scroll(direction='down')",
                "finished(content='ok')",
            ],
            "dry_run": "true",
            "verify_on_finish": "false",
        },
    )

    output = _extract_output_payload(result)
    assert isinstance(output, dict)
    data = _find_structured(output)
    assert data.get("finished") is True
    steps = data.get("steps")
    assert isinstance(steps, list)
    assert len(steps) == 2
    assert steps[0].get("action_name") == "scroll"
    marked_after = str(steps[0].get("screenshot_after_marked") or "")
    assert marked_after
    assert Path(marked_after).exists()
    execute = steps[0].get("execute")
    assert isinstance(execute, dict)
    marker_meta = execute.get("marked_coordinates")
    assert isinstance(marker_meta, dict)
    assert marker_meta.get("action") == "scroll"
    assert isinstance(marker_meta.get("point"), list)


class _FakeVerifier:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def Message(self, *_args, **_kwargs):
        return None

    def Send(self, *_args, **_kwargs):
        return self.response_text


def test_gui_agent_node_verify_finished_requires_structured_done_or_finished_action(tmp_path):
    from nodes.gui_agent_node import Node

    seed = _write_sample_png(tmp_path / "verify_seed.png")
    node = Node()

    done, _reason = node._verify_finished(
        verifier_agent=_FakeVerifier("still not complete yet"),
        verify_prompt="check",
        instruction="task",
        screenshot_path=str(seed),
        planner_response="Action: finished(content='x')",
        mode="chat",
    )
    assert done is False

    done, _reason = node._verify_finished(
        verifier_agent=_FakeVerifier('{"done": true, "reason": "ok"}'),
        verify_prompt="check",
        instruction="task",
        screenshot_path=str(seed),
        planner_response="Action: finished(content='x')",
        mode="chat",
    )
    assert done is True

    done, _reason = node._verify_finished(
        verifier_agent=_FakeVerifier('{"action": "finished", "content": "done"}'),
        verify_prompt="check",
        instruction="task",
        screenshot_path=str(seed),
        planner_response="Action: finished(content='x')",
        mode="chat",
    )
    assert done is True

    done, _reason = node._verify_finished(
        verifier_agent=_FakeVerifier('{"content": "done"}'),
        verify_prompt="check",
        instruction="task",
        screenshot_path=str(seed),
        planner_response="Action: finished(content='x')",
        mode="chat",
    )
    assert done is True

    done, _reason = node._verify_finished(
        verifier_agent=_FakeVerifier('{"name":"finished","parameters":{"content":"done"}}'),
        verify_prompt="check",
        instruction="task",
        screenshot_path=str(seed),
        planner_response="Action: finished(content='x')",
        mode="chat",
    )
    assert done is True


def test_gui_agent_node_call_planner_includes_previous_feedback_image(tmp_path):
    from nodes.gui_agent_node import Node

    class _FakePlanner:
        def __init__(self):
            self.calls = []

        def Message(self, role, content, persist=False):
            self.calls.append({"role": role, "content": content, "persist": persist})

        def Send(self, *_args, **_kwargs):
            return "Thought: continue\nAction: wait"

    screenshot = _write_sample_png(tmp_path / "before.png")
    feedback = _write_sample_png(tmp_path / "after_marked.png")
    planner = _FakePlanner()
    node = Node()

    response = node._call_planner(
        planner_agent=planner,
        instruction="open google",
        step_index=2,
        screenshot_path=str(screenshot),
        planner_feedback_path=str(feedback),
        history=[{"step": 1, "action": "click", "result": "{\"ok\":true}"}],
        mode="GUIAgent",
    )

    assert response.startswith("Thought:")
    assert planner.calls
    payload = planner.calls[0]
    assert payload["role"] == "user"
    content = payload["content"]
    assert isinstance(content, list)
    image_parts = [item for item in content if isinstance(item, dict) and item.get("type") == "image_url"]
    assert len(image_parts) == 2


def test_gui_agent_node_parse_action_requires_action_line():
    from nodes.gui_agent_node import Node

    node = Node()
    thought, action = node._parse_action("action=click(point='<point>940 15</point>')")
    assert thought == ""
    assert action == ""


def test_gui_agent_node_parse_action_rejects_json_action():
    from nodes.gui_agent_node import Node

    node = Node()
    thought, action = node._parse_action('{"action":"click","point":[150,18]}')
    assert thought == ""
    assert action == ""


def test_gui_agent_node_parse_action_args_rejects_csv_click():
    from nodes.gui_agent_node import Node

    node = Node()
    parsed = node._parse_action_args("click, 203, 15, minimize button", width=1920, height=1080)
    assert parsed.get("name") != "click"
    assert parsed.get("point") is None


def test_gui_agent_node_parse_action_args_rejects_open_app_positional():
    from nodes.gui_agent_node import Node

    node = Node()
    parsed = node._parse_action_args("open_app('Unreal Engine')", width=1920, height=1080)
    assert parsed.get("name") == "open_app"
    assert node._validate_action_args(parsed) == "unsupported action: open_app"


def test_gui_agent_node_parse_action_args_supports_type_text_alias():
    from nodes.gui_agent_node import Node

    node = Node()
    parsed = node._parse_action_args("type(text='google.com', target='url_bar')", width=1920, height=1080)
    assert parsed.get("name") == "type"
    assert parsed.get("content") == "google.com"
    assert parsed.get("target") == "url_bar"


def test_gui_agent_node_validate_hotkey_is_unsupported():
    from nodes.gui_agent_node import Node

    node = Node()
    parsed = node._parse_action_args("hotkey(key='ctrl l')", width=1920, height=1080)
    assert parsed.get("name") == "hotkey"
    assert node._validate_action_args(parsed) == "unsupported action: hotkey"


def test_gui_agent_node_repairs_unsupported_action(monkeypatch, tmp_path):
    import nodes.base_node as base_node
    import nodes.gui_agent_node as gui_agent_node
    from nodes.gui_agent_node import Node

    monkeypatch.setattr(base_node, "_get_runtime_root", lambda: str(tmp_path))

    class _FakePlanner:
        def __init__(self):
            self._responses = [
                "点击“games”区域中显示女性角色的游戏模板，以进入项目创建界面。",
                "Thought: repair\nAction: click(point='<point>500 500</point>')",
                "Thought: done\nAction: finished(content='ok')",
            ]
            self.send_calls = 0

        def Message(self, *_args, **_kwargs):
            return None

        def Send(self, *_args, **_kwargs):
            self.send_calls += 1
            if not self._responses:
                return "Thought: done\nAction: finished(content='ok')"
            return self._responses.pop(0)

    fake_agent = _FakePlanner()
    monkeypatch.setattr(gui_agent_node, "create_agent", lambda *_args, **_kwargs: fake_agent)

    seed = _write_sample_png(tmp_path / "seed_repair.png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "open third person project"},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
        ],
    }

    node = Node()
    result = node.on_input(
        message,
        {
            "graph_id": "g2",
            "node_instance_id": "gui_repair",
            "provider_id": "fake-provider",
            "verify_on_finish": "false",
            "dry_run": "true",
        },
    )

    output = _extract_output_payload(result)
    assert isinstance(output, dict)
    data = _find_structured(output)
    assert data.get("finished") is True
    assert data.get("status") == "done"

    steps = data.get("steps")
    assert isinstance(steps, list)
    assert len(steps) == 2
    first = steps[0]
    assert first.get("action_name") == "click"
    repair = first.get("repair")
    assert isinstance(repair, dict)
    assert repair.get("triggered") is True
    assert repair.get("applied") is True
    assert "点击“games”" in str(first.get("planner_response_raw") or "")
    assert fake_agent.send_calls == 3


def test_gui_agent_node_repairs_invalid_action_args(monkeypatch, tmp_path):
    import nodes.base_node as base_node
    import nodes.gui_agent_node as gui_agent_node
    from nodes.gui_agent_node import Node

    monkeypatch.setattr(base_node, "_get_runtime_root", lambda: str(tmp_path))

    class _FakePlanner:
        def __init__(self):
            self._responses = [
                "Thought: first\nAction: click(target='url_bar')",
                "Thought: repair\nAction: click(point='<point>500 500</point>')",
                "Thought: done\nAction: finished(content='ok')",
            ]
            self.send_calls = 0

        def Message(self, *_args, **_kwargs):
            return None

        def Send(self, *_args, **_kwargs):
            self.send_calls += 1
            if not self._responses:
                return "Thought: done\nAction: finished(content='ok')"
            return self._responses.pop(0)

    fake_agent = _FakePlanner()
    monkeypatch.setattr(gui_agent_node, "create_agent", lambda *_args, **_kwargs: fake_agent)

    seed = _write_sample_png(tmp_path / "seed_invalid_args.png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "open browser and focus address bar"},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
        ],
    }

    node = Node()
    result = node.on_input(
        message,
        {
            "graph_id": "g3",
            "node_instance_id": "gui_invalid_args",
            "provider_id": "fake-provider",
            "verify_on_finish": "false",
            "dry_run": "true",
        },
    )

    output = _extract_output_payload(result)
    assert isinstance(output, dict)
    data = _find_structured(output)
    assert data.get("finished") is True
    assert data.get("status") == "done"

    steps = data.get("steps")
    assert isinstance(steps, list)
    assert len(steps) == 2
    first = steps[0]
    assert first.get("action_name") == "click"
    repair = first.get("repair")
    assert isinstance(repair, dict)
    assert repair.get("validation_repair_applied") is True
    assert repair.get("validation_error") == "click missing point"
    assert fake_agent.send_calls == 3


def test_gui_agent_node_planner_timeout_stops_loop(monkeypatch, tmp_path):
    import nodes.base_node as base_node
    import nodes.gui_agent_node as gui_agent_node
    from nodes.gui_agent_node import Node

    monkeypatch.setattr(base_node, "_get_runtime_root", lambda: str(tmp_path))

    class _SlowPlanner:
        def Message(self, *_args, **_kwargs):
            return None

        def Send(self, *_args, **_kwargs):
            time.sleep(0.2)
            return "Thought: late\nAction: wait"

    slow_agent = _SlowPlanner()
    monkeypatch.setattr(gui_agent_node, "create_agent", lambda *_args, **_kwargs: slow_agent)

    seed = _write_sample_png(tmp_path / "seed_timeout.png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "open a new tab and type google.com"},
            {"type": "resource", "resource": {"uri": str(seed), "kind": "image"}},
        ],
    }

    node = Node()
    result = node.on_input(
        message,
        {
            "graph_id": "g4",
            "node_instance_id": "gui_timeout",
            "provider_id": "fake-provider",
            "verify_on_finish": "false",
            "dry_run": "true",
            "planner_timeout_seconds": "0.05",
        },
    )

    output = _extract_output_payload(result)
    assert isinstance(output, dict)
    data = _find_structured(output)
    assert data.get("finished") is False
    assert data.get("status") == "stopped"
    assert str(data.get("reason") or "").startswith("planner_failed: call timeout after")
    steps = data.get("steps")
    assert isinstance(steps, list)
    assert steps[0].get("status") == "planner_failed"
