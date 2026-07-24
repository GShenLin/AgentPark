from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_node_profiler_editor_is_shared_by_desktop_and_mobile_settings():
    settings_page = _read("webui/src/components/SettingsPage.vue")
    desktop_workspace = _read("webui/src/DesktopWorkspace.vue")
    mobile_workspace = _read("webui/src/mobile/MobileWorkspace.vue")

    assert "NodeProfilerEditor.vue" in settings_page
    assert "label: 'NodeProfilerEditor'" in settings_page
    assert "<NodeProfilerEditor" in settings_page
    assert 'v-else-if="isNodeProfilerEditor"' in settings_page
    assert ':providers="providers"' in settings_page
    assert ':available-tools="availableTools"' in settings_page
    assert "<SettingsPage" in desktop_workspace
    assert "<SettingsPage" in mobile_workspace


def test_node_profiler_editor_reuses_node_configuration_fields():
    editor = _read("webui/src/components/settings/NodeProfilerEditor.vue")
    api = _read("webui/src/api.ts")
    api_types = _read("webui/src/apiTypes.ts")

    assert "import NodeConfigFields" in editor
    assert "<NodeConfigFields" in editor
    assert ':schema="templateSchema"' in editor
    assert ':fields="draftFields"' in editor
    assert '@update-field="setNodeField"' in editor
    assert "getNodeTemplate" in editor
    assert "normalizeSchemaFieldValue" in editor
    assert "NodeProfiler JSON" not in editor
    assert "Format JSON" not in editor
    assert "delete fields.instruction" in editor
    assert "delete fields.system_prompt" in editor
    assert "updateAgentProfile" in editor
    assert "Discard unsaved NodeProfiler changes?" in editor
    assert '@dirty="nodeProfilerDirty = $event"' in _read("webui/src/components/SettingsPage.vue")
    assert "method: 'PUT'" in api
    assert "export type AgentProfileEditorPayload" in api_types
    assert "node_profiler:" in api_types
    assert "instruction: string" in api_types
    assert "system_prompt: string" in api_types


def test_node_profiler_editor_does_not_persist_unedited_template_defaults():
    editor = _read("webui/src/components/settings/NodeProfilerEditor.vue")

    assert "persistedFieldKeys" in editor
    assert "editedFieldKeys" in editor
    assert "const includedKeys = new Set" in editor
    assert "...persistedFieldKeys.value" in editor
    assert "...Object.keys(editedFieldKeys.value)" in editor


def test_agent_node_config_is_partitioned_by_support_mode_without_changing_other_nodes():
    fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")
    groups = _read("webui/src/components/agent-board/nodeConfigFieldGroups.ts")

    assert "createNodeConfigFieldSections(" in fields
    assert "function setProvider(providerId: string)" in fields
    assert "agentProviderModes(provider)" in fields
    provider_options_body = fields.split("const providerOptions = computed", 1)[1].split("const activeSupportModes", 1)[0]
    assert "props.fields.mode" not in provider_options_body
    assert "isModeField" not in fields
    assert "activeSupportModes.value" in fields
    assert "setField('mode'" not in fields
    assert '@change="setProvider(($event.target as HTMLSelectElement).value)"' in fields

    desktop_config = _read("webui/src/components/agent-board/NodeConfigSection.vue")
    mobile_config = _read("webui/src/mobile/MobileNodeConfigDialog.vue")
    assert "getNodeTemplate(safeTypeId, { providerId: contextKey }, { signal })" in desktop_config
    assert "getNodeTemplate(typeId, { providerId: contextKey })" in mobile_config
    assert "loadedSchemaContextKey" in desktop_config
    assert "loadedSchemaContextKey" in mobile_config
    assert "templateSchema.value = nextSchema" in desktop_config
    assert "templateSchema.value = nextSchema" in mobile_config
    assert "fieldSchemaCache.value = preserveDraft" in desktop_config
    assert "fieldSchemaCache.value = preserveDraft" in mobile_config

    create_schema = _read("webui/src/composables/useProviderDrivenTemplateSchema.ts")
    assert "options.schema.value = (template.schema || {})" in create_schema
    assert "options.fields.value.mode" not in create_schema
    assert "return { loading }" in create_schema
    assert "creatingNode || providerSchemaLoading" in _read(
        "webui/src/components/agent-board/NodePalette.vue"
    )
    assert "creatingNode || providerSchemaLoading" in _read(
        "webui/src/components/agent-board/CanvasContextMenu.vue"
    )
    assert "creating || providerSchemaLoading" in _read(
        "webui/src/mobile/MobileNodeCreateDialog.vue"
    )

    desktop_input = _read("webui/src/components/agent-board/NodeInputDock.vue")
    mobile_input = _read("webui/src/mobile/MobileWorkspace.vue")
    assert "const audioInputEnabled = computed(() => isAgentNode.value)" in desktop_input
    assert "const audioInputEnabled = computed(() => isAgentNode.value)" in mobile_input
    assert "meta: { support_mode: 'audio_generation' }" not in desktop_input
    assert "meta: { support_mode: 'audio_generation' }" not in mobile_input

    config_fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")
    file_picker = _read("webui/src/components/agent-board/FieldFileListPicker.vue")
    assert "getFieldType(key) === 'file_list'" in config_fields
    assert "<FieldFileListPicker" in config_fields
    assert "<FileExplorer" in file_picker
    assert "v-model:selected-paths=\"selectedPaths\"" in file_picker

    image_dimensions = _read("webui/src/components/agent-board/FieldImageDimensions.vue")
    assert "getFieldType(key) === 'image_dimensions'" in config_fields
    assert "<FieldImageDimensions" in config_fields
    assert config_fields.index("getFieldType(key) === 'image_dimensions'") < config_fields.index('v-else-if="isSelectField(key)"')
    assert "getFieldContainerTag(key)" in config_fields
    assert "Aspect ratio" in image_dimensions
    assert "Resolution" in image_dimensions
    assert "Image width" in image_dimensions
    assert "Image height" in image_dimensions

    assert "label: 'Common'" in groups
    assert "const owners = supportModes.filter" in groups
    assert "group.modes.map((mode) => SUPPORT_MODE_LABELS[mode] || mode).join(' / ')" in groups
    assert "'provider_id'" in groups.split("const COMMON_AGENT_FIELDS", 1)[1].split("])", 1)[0]
    assert "Environment" not in groups
    assert "Behavior" not in groups
    assert "Ability" not in groups

    non_agent_branch = groups.split("if (String(typeId || '').trim() !== 'agent_node')", 1)[1]
    assert "keys: [...schemaKeys]" in non_agent_branch
    assert "const visibleKeys = [...schemaKeys]" in non_agent_branch


def test_doubao_audio_provider_uses_dedicated_x_api_key_and_primary_url():
    settings = _read("webui/src/components/settings/ModelProviderSettingsForm.vue")
    auth_fields = _read("webui/src/components/settings/ProviderAuthFields.vue")
    runtime = _read("src/providers/doubao_audio_generation.py")

    assert "Speech Base URL" not in settings
    assert "Speech API Key Override" not in settings
    assert 'config.get("baseUrl")' in runtime
    assert "require_doubao_x_api_key" in runtime
    assert 'self.config.get("apiKey")' not in runtime
    assert "const isDoubaoAudioProvider = computed" in settings
    assert "selectedProvider.value.supportmode.includes('audio_generation')" in settings
    assert ':show-doubao-speech-auth="isDoubaoAudioProvider"' in settings
    assert "X-Api-Key" in auth_fields
    assert "for Doubao speech APIs" in auth_fields
    assert ".env/apiKey.json" in auth_fields
    assert "Speech Access Key ID" in auth_fields
    assert "Speech Secret Access Key" in auth_fields
    assert "speechBaseUrl" not in runtime
    assert "speechApiKey" not in runtime


def test_agent_combobox_uses_explicit_reopenable_dropdown():
    fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")
    combobox = _read("webui/src/components/agent-board/FieldCombobox.vue")

    assert "<FieldCombobox" in fields
    assert "<datalist" not in fields
    assert "@click=\"openMenu\"" in combobox
    assert "if (!normalizedQuery.value) return props.options" in combobox
    assert "role=\"listbox\"" in combobox
    assert "@click=\"selectOption(option)\"" in combobox


def test_node_config_fields_apply_schema_declared_visibility_dependencies():
    fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")

    assert "const visibleWhen = field.visible_when" in fields
    assert "Object.prototype.hasOwnProperty.call(visibleWhen, 'equals')" in fields
    assert "props.fields[dependency] === visibleWhen.equals" in fields


def test_speaker_management_indexes_outside_model_provider_form():
    form = _read("webui/src/components/settings/ModelProviderSettingsForm.vue")
    panel = _read("webui/src/components/settings/DoubaoSpeechManagementPanel.vue")
    api = _read("webui/src/doubaoSpeechManagementApi.ts")

    assert "speechSpeakerOptions" not in form
    assert "speaker-options" not in panel
    assert "config/audio_speaker.json" in panel
    assert "speaker_option_count" in api
