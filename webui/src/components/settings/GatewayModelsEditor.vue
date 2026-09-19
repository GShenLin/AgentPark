<script setup lang="ts">
import type { GatewayProvider } from '../../gatewayApi'
import { t } from '../../i18n'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'
import FormCheckbox from '../FormCheckbox.vue'
import FormSelect from '../FormSelect.vue'
import FormTextInput from '../FormTextInput.vue'
import { gatewayProtocolOptions, type GatewayModelEditor } from './gatewayModelEditor'

const props = defineProps<{ editor: GatewayModelEditor; providers: GatewayProvider[]; disabled: boolean }>()
const { groups, providerFor, addGroup, removeGroup, addModelId, removeModelId, selectProvider, toggleProtocol } = props.editor
</script>

<template>
  <section class="gateway-card">
    <div class="card-head">
      <div>
        <h2>{{ t('gateway.publicModels') }}</h2>
        <p>{{ t('gateway.modelHelp') }}</p>
      </div>
      <ActionButton compact :disabled="disabled" @click="addGroup">{{ t('gateway.addProviderGroup') }}</ActionButton>
    </div>
    <div class="model-list">
      <fieldset v-for="(group, index) in groups" :key="group.key" class="model-form" :disabled="disabled">
        <legend>{{ t('gateway.providerGroup', { index: index + 1 }) }}</legend>
        <label>
          Provider
          <FormSelect v-model="group.settings.providerId" @change="selectProvider(group.settings)">
            <option v-if="!providerFor(group.settings)" :value="group.settings.providerId" disabled>
              {{ group.settings.providerId || t('gateway.selectProvider') }}
            </option>
            <option v-for="provider in providers" :key="provider.id" :value="provider.id">
              {{ provider.id }}
            </option>
          </FormSelect>
        </label>
        <label>
          Fixed account
          <FormSelect v-model="group.settings.accountId">
            <option value="">{{ t('gateway.providerDefault') }}</option>
            <option v-for="account in providerFor(group.settings)?.accounts || []" :key="account.id" :value="account.id">
              {{ account.alias || account.identity || account.id }} · {{ account.id }}
            </option>
          </FormSelect>
        </label>
        <label class="enabled-field"><FormCheckbox v-model="group.settings.enabled" /> {{ t('gateway.enabled') }}</label>
        <div class="model-ids-field">
          <div class="model-ids-head">
            <strong>Public model IDs</strong>
            <ActionButton compact @click="addModelId(group)">{{ t('gateway.addModelId') }}</ActionButton>
          </div>
          <p>{{ t('gateway.modelIdsHelp') }}</p>
          <div v-for="(entry, modelIndex) in group.modelIds" :key="entry.key" class="model-id-row">
            <FormTextInput v-model="entry.value" :aria-label="`Public model ID ${modelIndex + 1}`" placeholder="model-id" />
            <DangerButton compact :aria-label="t('gateway.removeModelId', { index: modelIndex + 1 })" @click="removeModelId(group, entry.key)">{{ t('common.delete') }}</DangerButton>
          </div>
          <p v-if="!group.modelIds.length">{{ t('gateway.emptyModelIds') }}</p>
        </div>
        <div class="protocol-field">
          <span>{{ t('gateway.protocols') }}</span>
          <label v-for="option in gatewayProtocolOptions.filter((item) => providerFor(group.settings)?.protocols.includes(item.id))" :key="option.id">
            <FormCheckbox :model-value="group.settings.protocols.includes(option.id)" @update:model-value="toggleProtocol(group.settings, option.id, $event)" />
            {{ option.label }}
          </label>
        </div>
        <div class="form-actions">
          <DangerButton compact @click="removeGroup(group.key)">{{ t('gateway.removeProviderGroup') }}</DangerButton>
        </div>
      </fieldset>
      <p v-if="!groups.length" class="empty">{{ t('gateway.emptyModels') }}</p>
    </div>
  </section>
</template>

<style scoped src="./GatewaySettingsPanel.css"></style>
