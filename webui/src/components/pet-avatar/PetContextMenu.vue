<script setup lang="ts">
import type { PetAvatarSummary } from '../../api'

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
    <button class="pet-context-item" type="button" @click="emit('openMainPage')">OpenMainPage</button>
    <button class="pet-context-item danger" type="button" @click="emit('close')">Close</button>
    <button class="pet-context-item danger" type="button" @click="emit('closeAll')">CloseAll</button>
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
