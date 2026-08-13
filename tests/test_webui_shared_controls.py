from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_control_primitives_use_one_semantic_token_system():
    style = _read("webui/src/style.css")
    action = _read("webui/src/components/ActionButton.vue")
    danger = _read("webui/src/components/DangerButton.vue")
    text_input = _read("webui/src/components/FormTextInput.vue")
    select = _read("webui/src/components/FormSelect.vue")
    checkbox = _read("webui/src/components/FormCheckbox.vue")
    close = _read("webui/src/components/DialogCloseButton.vue")

    for token in (
        "--ui-control-height",
        "--ui-control-height-compact",
        "--ui-control-border",
        "--ui-button-background",
        "--ui-primary-background",
        "--ui-danger-background",
        "--ui-dialog-backdrop",
        "--ui-dialog-background",
        "--ui-dialog-shadow",
    ):
        assert token in style

    assert "var(--ui-button-background" in action
    assert "var(--ui-danger-background" in danger
    assert "var(--ui-control-background" in text_input
    assert "var(--ui-control-background" in select
    assert "form-checkbox" in checkbox
    assert "dialog-close-button" in close


def test_provider_select_reveals_configured_descriptions_on_hover_and_focus():
    selector = _read("webui/src/components/ProviderSelect.vue")
    node_fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")
    companion = _read("webui/src/components/settings/CompanionSettingsForm.vue")
    settings = _read("webui/src/components/settings/ModelProviderSettingsForm.vue")

    assert "provider.description" in selector
    assert ".provider-select__option:hover .provider-select__description" in selector
    assert ".provider-select__option:focus-visible .provider-select__description" in selector
    assert "<ProviderSelect" in node_fields
    assert "<ProviderSelect" in companion
    assert "stringValue('description')" in settings


def test_common_destructive_and_close_actions_are_reused_in_core_surfaces():
    destructive_surfaces = (
        "webui/src/components/FileExplorer.vue",
        "webui/src/components/MemoryContentView.vue",
        "webui/src/components/agent-board/NodeCardItem.vue",
        "webui/src/components/agent-board/NodeRuntimeEventsSection.vue",
        "webui/src/mobile/MobileWorkspace.vue",
        "webui/src/components/pet-avatar/PetContextMenu.vue",
    )
    closable_surfaces = (
        "webui/src/components/ImageLightbox.vue",
        "webui/src/components/MemoryFileDiffDialog.vue",
        "webui/src/components/WebFolderPickerDialog.vue",
        "webui/src/mobile/MobileNodeConfigDialog.vue",
        "webui/src/mobile/MobileNodeCreateDialog.vue",
    )

    for path in destructive_surfaces:
        assert "DangerButton" in _read(path), path
    for path in closable_surfaces:
        assert "DialogCloseButton" in _read(path), path


def test_graph_panel_actions_use_one_compact_height():
    source = _read("webui/src/components/MemoryContentView.vue")

    assert '<DangerButton\n          compact\n          :disabled="!selectedGraphProfileId"' in source
    assert '<DangerButton\n                  compact\n                  :disabled="graphMemoryClearingId === graph.id"' in source
    assert '<DangerButton v-if="canDeleteGraph(graph)" compact' in source


def test_settings_navigation_and_provider_cards_use_selection_control_sizes():
    settings = _read("webui/src/components/SettingsPage.vue")
    providers = _read("webui/src/components/settings/ModelProviderSettingsForm.vue")
    selection = _read("webui/src/components/SelectionButton.vue")

    assert "<SelectionButton" in settings
    assert "<SelectionButton" in providers
    assert "stacked" in providers
    assert "--ui-selection-height" in selection
    assert "--ui-selection-stacked-height" in selection
    assert "outline-offset: -2px" in selection


def test_major_dialogs_share_surface_tokens():
    dialog_surfaces = (
        "webui/src/components/MemoryFileDiffDialog.vue",
        "webui/src/components/MemorySaveDialog.vue",
        "webui/src/components/WebFolderPickerDialog.vue",
        "webui/src/components/ExpandableTextarea.vue",
        "webui/src/components/agent-board/FieldFileListPicker.vue",
        "webui/src/components/agent-board/NodeAppendFilePickerSheet.vue",
        "webui/src/mobile/MobileNodeConfigDialog.vue",
        "webui/src/mobile/MobileNodeCreateDialog.vue",
    )

    for path in dialog_surfaces:
        source = _read(path)
        assert "var(--ui-dialog-backdrop)" in source, path
        assert "var(--ui-dialog-background)" in source, path
        assert "var(--ui-dialog-border)" in source, path
