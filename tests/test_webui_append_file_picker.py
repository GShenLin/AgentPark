from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_append_file_uses_shared_project_file_tree_on_desktop_and_mobile():
    runtime_events = _read("webui/src/components/agent-board/NodeRuntimeEventsSection.vue")
    desktop_config = _read("webui/src/components/agent-board/NodeConfigSection.vue")
    mobile_config = _read("webui/src/mobile/MobileNodeConfigDialog.vue")
    field_group = _read("webui/src/components/agent-board/NodeRuntimeEventsFieldGroup.vue")
    picker = _read("webui/src/components/agent-board/NodeAppendFilePickerSheet.vue")

    assert "selectFile" not in runtime_events
    assert "mobileFilePicker" not in runtime_events
    assert "listNodeInstanceFiles" in runtime_events
    assert "<NodeAppendFilePickerSheet" in runtime_events
    assert "<NodeRuntimeEventsFieldGroup" in desktop_config
    assert "<NodeRuntimeEventsFieldGroup" in mobile_config
    assert "<NodeRuntimeEventsSection" in field_group
    assert "<FileExplorer" in picker
    assert 'selectable' in picker
    assert '<Teleport to="body">' in picker


def test_runtime_event_handler_enabled_toggle_is_shared_by_desktop_and_mobile():
    runtime_events = _read("webui/src/components/agent-board/NodeRuntimeEventsSection.vue")
    desktop_config = _read("webui/src/components/agent-board/NodeConfigSection.vue")
    mobile_config = _read("webui/src/mobile/MobileNodeConfigDialog.vue")
    field_group = _read("webui/src/components/agent-board/NodeRuntimeEventsFieldGroup.vue")

    assert ':checked="handler.enabled !== false"' in runtime_events
    assert "{ enabled: ($event.target as HTMLInputElement).checked }" in runtime_events
    assert 'class="handler-enabled"' in runtime_events
    assert "<NodeRuntimeEventsFieldGroup" in desktop_config
    assert "<NodeRuntimeEventsFieldGroup" in mobile_config
    assert "<NodeRuntimeEventsSection" in field_group
    assert "mobileFilePicker" not in runtime_events
