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


def test_shared_action_controls_are_used_across_settings_and_dialogs():
    danger_button = _read("webui/src/components/DangerButton.vue")
    image_lightbox = _read("webui/src/components/ImageLightbox.vue")
    settings_delete_surfaces = [
        _read("webui/src/components/settings/AccessSettingsPanel.vue"),
        _read("webui/src/components/settings/DefaultSettingsForm.vue"),
        _read("webui/src/components/settings/GatewaySettingsPanel.vue"),
        _read("webui/src/components/settings/ModelProviderSettingsForm.vue"),
        _read("webui/src/components/settings/RuntimeEventsSettingsForm.vue"),
    ]
    dialog_surfaces = [
        image_lightbox,
        _read("webui/src/components/MemorySaveDialog.vue"),
        _read("webui/src/components/WebFolderPickerDialog.vue"),
        _read("webui/src/mobile/MobileNodeCreateDialog.vue"),
        _read("webui/src/mobile/MobileNodeConfigDialog.vue"),
    ]

    assert "variant?: 'default' | 'menu'" in danger_button
    assert all("<DangerButton" in surface for surface in settings_delete_surfaces)
    assert all("<DialogCloseButton" in surface for surface in dialog_surfaces)
    assert '<button class="image-lightbox-close"' not in image_lightbox


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
    assert "NodeProfilerMetadataPanel" in editor
    assert "NodeProfilerProfileList" in editor
    assert "NodeProfilerToolbar" in editor


def test_desktop_node_config_loads_profile_into_current_node():
    desktop_config = _read(
        "webui/src/components/agent-board/NodeConfigSection.vue"
    )
    load_control = _read(
        "webui/src/components/agent-board/NodeProfileLoadControl.vue"
    )

    assert "<NodeProfileLoadControl" in desktop_config
    config_title = '<div class="section-title">{{ t(\'common.config\') }}</div>'
    assert config_title in desktop_config
    assert desktop_config.index(config_title) < desktop_config.index("<NodeProfileLoadControl")
    assert "loadAgentProfileIntoNode" in desktop_config
    assert "graph_id: currentGraphId()" in desktop_config
    assert "node_id: nodeId" in desktop_config
    assert "加载 Profile 将替换当前尚未保存的修改" in desktop_config
    assert "resetDraftFromConfig(result.config.after)" in desktop_config
    assert "runtimeEventsRevision.value += 1" in desktop_config
    assert "listAgentProfiles" in load_control
    assert "profile.node_type_id" in load_control
    assert "LoadProfile" in load_control
    assert '<Teleport to="body">' in load_control
    assert "agentProfileDescription(activeProfile)" in load_control
    assert ".profile-description-popover p" in load_control
    assert "font-size: 18px" in load_control
    assert ':show-description="false"' in load_control

    editor = _read("webui/src/components/settings/NodeProfilerEditor.vue")
    metadata_panel = _read("webui/src/components/settings/NodeProfilerMetadataPanel.vue")
    assert 'v-model:description="profileDescription"' in editor
    assert "agentProfileDescription(profile)" in editor
    assert 'v-model="description"' in metadata_panel


def test_desktop_node_config_auto_applies_non_text_fields():
    desktop_config = _read("webui/src/components/agent-board/NodeConfigSection.vue")
    config_fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")
    auto_apply = _read("webui/src/components/agent-board/nodeConfigAutoApply.ts")

    assert "createNodeConfigAutoApplyQueue" in desktop_config
    assert "applyMode === 'explicit'" in desktop_config
    assert ':explicit-dirty-keys="Object.keys(dirtyKeys)"' in desktop_config
    assert '@apply-field="applyField"' in desktop_config
    assert "async function applyChanges(requestedKeys?: string[])" in desktop_config
    assert "Apply${dirtyCount" not in desktop_config
    assert "function setExplicitField(key: string, value: any)" in config_fields
    assert '@update:model-value="setExplicitField(key, $event)"' in config_fields
    assert 'v-if="isExplicitDirty(key)"' in config_fields
    assert "emit('apply-field', key)" in config_fields
    assert "setField('provider_id', String(providerId || '').trim())" in config_fields
    assert "await ctx.setNodeFields(nodeId, normalizedFields)" in desktop_config
    assert "revertFailedAutoApply(batch)" in desktop_config
    assert "pendingByNode" in auto_apply


def test_node_profiler_editor_does_not_persist_unedited_template_defaults():
    editor = _read("webui/src/components/settings/NodeProfilerEditor.vue")

    assert "persistedFieldKeys" in editor
    assert "editedFieldKeys" in editor
    assert "const includedKeys = new Set" in editor
    assert "...persistedFieldKeys.value" in editor
    assert "...Object.keys(editedFieldKeys.value)" in editor


def test_node_profiler_editor_has_delete_action_and_name_only_profile_list():
    editor = _read("webui/src/components/settings/NodeProfilerEditor.vue")
    toolbar = _read("webui/src/components/settings/NodeProfilerToolbar.vue")
    profile_list = _read("webui/src/components/settings/NodeProfilerProfileList.vue")

    assert "deleteAgentProfile" in editor
    assert "async function deleteProfile()" in editor
    assert "window.dispatchEvent(new CustomEvent('agent-profiles-changed'))" in editor
    assert '@delete="deleteProfile"' in editor
    assert "<DangerButton" in toolbar
    assert "Delete Profile" in toolbar
    assert "{{ profile.name || profile.id }}" in profile_list
    assert "AgentProfileChoiceSummary" not in profile_list


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
    assert '<ProviderSelect' in fields
    assert ':providers="providers"' in fields
    assert ':option-ids="providerOptions"' in fields
    assert '@change="setProvider($event)"' in fields

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
    assert ".auth/api-keys/aliases.json" in auth_fields
    assert "Speech Access Key ID" in auth_fields
    assert "Speech Secret Access Key" in auth_fields
    assert "speechBaseUrl" not in runtime
    assert "speechApiKey" not in runtime


def test_provider_settings_supports_frontend_multi_account_selection():
    settings = _read("webui/src/components/settings/ModelProviderSettingsForm.vue")
    auth_fields = _read("webui/src/components/settings/ProviderAuthFields.vue")
    account_control = _read("webui/src/components/settings/ProviderOfficialAuthControl.vue")
    api = _read("webui/src/settingsApi.ts")

    assert ':auth-account-id="stringValue(\'authAccountId\')"' in settings
    assert "@account=\"setField('authAccountId', $event)\"" in settings
    assert ":provider-auth-id=\"providerAuthId\"" in settings
    assert "watch(" in settings and "loadCodexAuthStatus(providerId)" in settings
    assert "account: [accountId: string]" in auth_fields
    assert "addProviderApiKeyAccount" in account_control
    assert "activateProviderAccount" in account_control
    assert "deleteProviderAccount" in account_control
    assert "添加 API Key 账号" in account_control
    assert "当前 Provider" in account_control
    assert "export async function addProviderApiKeyAccount" in api


def test_provider_api_key_name_uses_alias_dropdown_and_explicit_add_form():
    auth_fields = _read("webui/src/components/settings/ProviderAuthFields.vue")
    alias_field = _read("webui/src/components/settings/ApiKeyAliasField.vue")
    api = _read("webui/src/settingsApi.ts")
    routes = _read("src/web_backend/route_registry.py")

    assert "<ApiKeyAliasField" in auth_fields
    assert "getApiKeyAliases" in alias_field
    assert "addApiKeyAlias" in alias_field
    assert '<FormSelect' in alias_field
    assert '>Add</ActionButton>' in alias_field
    assert 'placeholder="Name"' in alias_field
    assert 'placeholder="API Key"' in alias_field
    assert 'type="password"' in alias_field
    assert "emit('update:modelValue', result.selected || safeName)" in alias_field
    assert "export async function getApiKeyAliases" in api
    assert "export async function addApiKeyAlias" in api
    assert '"/api/provider-auth/api-key-aliases"' in routes


def test_provider_settings_exposes_strict_local_alpha_matting_contract():
    auth_fields = _read("webui/src/components/settings/ProviderAuthFields.vue")
    support_modes = _read("webui/src/components/settings/SupportModeMultiSelect.vue")

    assert '<option value="alpha_matting">alpha_matting</option>' in auth_fields
    assert "!['codex', 'oauth', 'none'].includes(authMode)" in auth_fields
    assert 'v-if="authMode !== \'none\'"' in auth_fields
    assert "image_matting: 'image_matting'" in support_modes


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


def test_node_config_fields_support_nullable_color_picker_fields():
    fields = _read("webui/src/components/agent-board/NodeConfigFields.vue")
    color_picker = _read("webui/src/components/agent-board/FieldColorPicker.vue")

    assert "<FieldColorPicker" in fields
    assert "getFieldType(key) === 'color'" in fields
    assert 'type="color"' in color_picker
    assert "emit('update-value', color)" in color_picker
    assert "emit('update-value', '')" in color_picker


def test_node_cards_reuse_resource_preview_and_lightbox_for_image_outputs():
    card = _read("webui/src/components/agent-board/NodeCardItem.vue")
    resource = _read("webui/src/components/MemoryResourcePart.vue")
    projection = _read("webui/src/nodeRuntimeProjection.ts")

    assert "<MemoryResourcePart" in card
    assert ":part=\"previewImageResource\"" in card
    assert "compact" in card
    assert "<ImageLightbox" in resource
    assert "'last_output_resources'" in projection


def test_speaker_management_indexes_outside_model_provider_form():
    form = _read("webui/src/components/settings/ModelProviderSettingsForm.vue")
    panel = _read("webui/src/components/settings/DoubaoSpeechManagementPanel.vue")
    api = _read("webui/src/doubaoSpeechManagementApi.ts")

    assert "speechSpeakerOptions" not in form
    assert "speaker-options" not in panel
    assert "config/audio_speaker.json" in panel
    assert "speaker_option_count" in api
