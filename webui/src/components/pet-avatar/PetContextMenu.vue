<script setup lang="ts">
import type { PetAvatarSummary } from '../../api'
import ActionButton from '../ActionButton.vue'
import DangerButton from '../DangerButton.vue'

defineProps<{
  left: number
  top: number
  loading: boolean
  avatars: PetAvatarSummary[]
  selectedAvatarId: string
}>()

const emit = defineEmits<{
  openMainPage: []
  close: []
  closeAll: []
  changeAvatar: [avatarId: string]
}>()
</script>

<template>
  <section class="pet-context-menu" :style="{ left: `${left}px`, top: `${top}px` }" @pointerdown.stop @contextmenu.prevent.stop>
    <ActionButton class="pet-context-item" variant="menu" @click="emit('openMainPage')">OpenMainPage</ActionButton>
    <DangerButton class="pet-context-item" variant="menu" @click="emit('close')">Close</DangerButton>
    <DangerButton class="pet-context-item" variant="menu" @click="emit('closeAll')">CloseAll</DangerButton>
    <div class="pet-context-section">ChangeAvatar</div>
    <div v-if="loading" class="pet-context-empty">Loading</div>
    <button
      v-for="item in avatars"
      :key="item.id"
      class="pet-context-item"
      :class="{ active: selectedAvatarId === item.id }"
      type="button"
      @click="emit('changeAvatar', item.id)"
    >
      <span>{{ item.name || item.id }}</span>
      <span class="pet-context-meta">{{ selectedAvatarId === item.id ? 'Current' : item.id }}</span>
    </button>
    <div v-if="!loading && !avatars.length" class="pet-context-empty">No avatars</div>
  </section>
</template>
