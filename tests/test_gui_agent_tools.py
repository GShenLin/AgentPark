import json


def test_run_gui_agent_task_selects_gui_provider_and_returns_image(monkeypatch, tmp_path):
    import functions.gui_agent_tools as gui_tools

    image_path = tmp_path / "last.png"
    image_path.write_bytes(b"png")

    class _FakeLoader:
        def get_all_providers(self):
            return {
                "gemini": {"supportmode": ["chat"]},
                "doubao-seed-1-6-vision-250815": {"supportmode": ["GUIAgent"]},
            }

    class _FakeNode:
        def on_input(self, message, context):
            assert context.get("provider_id") == "doubao-seed-1-6-vision-250815"
            assert context.get("mode") == "GUIAgent"
            assert context.get("verify_mode") == "GUIAgent"
            assert isinstance(message, dict)
            return {
                "display": "GUI loop done.",
                "routes": [
                    {
                        "output_index": 0,
                        "payload": {
                            "role": "assistant",
                            "parts": [
                                {"type": "resource", "resource": {"kind": "image", "uri": str(image_path)}},
                                {
                                    "type": "structured",
                                    "data": {
                                        "status": "done",
                                        "finished": True,
                                        "reason": "ok",
                                        "instruction": "open browser",
                                        "steps": [{"step": 1}],
                                        "run_dir": str(tmp_path / "run"),
                                    },
                                },
                            ],
                        },
                    }
                ],
            }

    monkeypatch.setattr(gui_tools, "ConfigLoader", lambda: _FakeLoader())
    monkeypatch.setattr(gui_tools, "Node", _FakeNode)

    raw = gui_tools.run_gui_agent_task(task="open browser")
    payload = json.loads(raw)

    assert payload["status"] == "done"
    assert payload["finished"] is True
    assert payload["provider_id"] == "doubao-seed-1-6-vision-250815"
    assert payload["final_image_path"] == str(image_path)


def test_run_gui_agent_task_prefers_marked_after_image_for_click_feedback(monkeypatch, tmp_path):
    import functions.gui_agent_tools as gui_tools

    fallback_image = tmp_path / "fallback_last.png"
    fallback_image.write_bytes(b"png")
    marked_after = tmp_path / "step_01_after_marked.png"
    marked_after.write_bytes(b"png")

    class _FakeLoader:
        def get_all_providers(self):
            return {
                "doubao-seed-1-6-vision-250815": {"supportmode": ["GUIAgent"]},
            }

    class _FakeNode:
        def on_input(self, _message, _context):
            return {
                "display": "GUI loop done.",
                "routes": [
                    {
                        "output_index": 0,
                        "payload": {
                            "role": "assistant",
                            "parts": [
                                {"type": "resource", "resource": {"kind": "image", "uri": str(fallback_image)}},
                                {
                                    "type": "structured",
                                    "data": {
                                        "status": "done",
                                        "finished": True,
                                        "reason": "ok",
                                        "instruction": "open browser",
                                        "steps": [
                                            {
                                                "step": 1,
                                                "action_name": "click",
                                                "screenshot_after_marked": str(marked_after),
                                            }
                                        ],
                                        "run_dir": str(tmp_path / "run"),
                                    },
                                },
                            ],
                        },
                    }
                ],
            }

    monkeypatch.setattr(gui_tools, "ConfigLoader", lambda: _FakeLoader())
    monkeypatch.setattr(gui_tools, "Node", _FakeNode)

    raw = gui_tools.run_gui_agent_task(task="open browser")
    payload = json.loads(raw)

    assert payload["status"] == "done"
    assert payload["finished"] is True
    assert payload["final_image_path"] == str(marked_after)


def test_run_gui_agent_task_blocks_when_no_gui_provider(monkeypatch):
    import functions.gui_agent_tools as gui_tools

    class _FakeLoader:
        def get_all_providers(self):
            return {"gemini": {"supportmode": ["chat"]}}

    monkeypatch.setattr(gui_tools, "ConfigLoader", lambda: _FakeLoader())

    raw = gui_tools.run_gui_agent_task(task="open browser")
    payload = json.loads(raw)

    assert payload["status"] == "blocked"
    assert payload["retryable"] is False
    assert "no provider supports GUIAgent" in str(payload.get("error") or "")


def test_run_gui_agent_task_errors_on_invalid_node_output(monkeypatch):
    import functions.gui_agent_tools as gui_tools

    class _FakeLoader:
        def get_all_providers(self):
            return {
                "doubao-seed-1-6-vision-250815": {"supportmode": ["GUIAgent"]},
            }

    class _FakeNode:
        def on_input(self, _message, _context):
            return {"display": "bad", "output": {"parts": []}}

    monkeypatch.setattr(gui_tools, "ConfigLoader", lambda: _FakeLoader())
    monkeypatch.setattr(gui_tools, "Node", _FakeNode)

    raw = gui_tools.run_gui_agent_task(task="open browser")
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert payload["task_failed"] is True
    assert str(payload.get("error") or "").startswith("invalid_gui_agent_output:")
