<script setup lang="ts">
import { ref } from 'vue'
import type { ImportCharacterPreview } from '@/api/importApi'

const props = defineProps<{
  char: ImportCharacterPreview
}>()

const expanded = ref(false)
</script>

<template>
  <div style="border: 1px solid var(--border-color); border-radius: 6px; padding: 8px; margin-bottom: 6px; font-size: 13px;">
    <div style="display: flex; align-items: center; gap: 8px;">
      <NTag size="small" type="default">{{ char.name }}</NTag>
      <NTag size="small" type="default">{{ char.tier }}</NTag>
      <NTag size="small" :type="char.status === 'new' ? 'success' : char.status === 'existing' ? 'warning' : 'default'">
        {{ char.status === 'new' ? $t('import.new') : char.status === 'existing' ? $t('import.existing') : $t('import.duplicate') }}
      </NTag>
      <span style="flex: 1; color: var(--text-tertiary); font-size: 12px;">{{ char.brief || '—' }}</span>
      <NButton v-if="char.personality || char.speech_style" size="tiny" quaternary @click="expanded = !expanded">
        {{ expanded ? $t('common.collapse') : $t('common.expand') }}
      </NButton>
    </div>
    <div v-if="expanded" style="margin-top: 6px; padding: 6px 8px; background: var(--bg-card); border-radius: 4px; display: flex; flex-direction: column; gap: 4px;">
      <div v-if="char.detail" style="display: flex; gap: 4px;">
        <span style="color: var(--text-secondary); white-space: nowrap;">{{ $t('character.detail') }}:</span>
        <span style="color: var(--text-primary);">{{ char.detail }}</span>
      </div>
      <div v-if="char.personality" style="display: flex; gap: 4px;">
        <span style="color: var(--text-secondary); white-space: nowrap;">{{ $t('character.personality') }}:</span>
        <span style="color: var(--text-primary);">{{ char.personality }}</span>
      </div>
      <div v-if="char.speech_style" style="display: flex; gap: 4px;">
        <span style="color: var(--text-secondary); white-space: nowrap;">{{ $t('character.speechStyle') }}:</span>
        <span style="color: var(--text-primary);">{{ char.speech_style }}</span>
      </div>
    </div>
  </div>
</template>
