from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_desktop_node_note_has_dedicated_graph_metadata_and_floating_card_display():
    context = _read("webui/src/components/agent-board/context.ts")
    persistence = _read("webui/src/components/agent-board/boardGraphPersistence.ts")
    config = _read("webui/src/components/agent-board/NodeConfigSection.vue")
    field = _read("webui/src/components/agent-board/NodeNoteField.vue")
    card = _read("webui/src/components/agent-board/NodeCardItem.vue")
    floating_note = _read("webui/src/components/agent-board/NodeFloatingNote.vue")

    assert "nodeNotes: Ref<NodeNotes>" in context
    assert "setNodeNote:" in context
    assert "node_notes: normalizeNodeNotes(options.nodeNotes.value)" in persistence
    assert "<NodeNoteField" in config
    assert config.index("<NodeNoteField") > config.index("<NodeRuntimeEventsFieldGroup")
    assert "ctx.setNodeNote(props.nodeId" in field
    assert "<NodeFloatingNote" in card
    assert "v-if=\"text\"" in floating_note
    assert "bottom: calc(100% + 8px)" in floating_note


def test_mobile_node_selection_renders_note_above_node_row():
    item = _read("webui/src/mobile/MobileNodeListItem.vue")
    api_types = _read("webui/src/apiTypes.ts")

    assert "note?: string" in api_types
    assert '<div v-if="node.note" class="node-note">{{ node.note }}</div>' in item


def test_node_note_does_not_enter_profile_editor_fields():
    profile_editor = _read("webui/src/components/settings/NodeProfilerEditor.vue")
    profile_api = _read("src/web_backend/profile_api.py")

    assert "node_notes" not in profile_editor
    assert 'graph_profile.pop("node_notes", None)' in profile_api
