<script setup lang="ts">
import type { ImportElementPreview } from '@/api/importApi'

defineProps<{
  el: ImportElementPreview
}>()
</script>

<template>
  <div style="display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px;">
    <NTag v-if="el.category" size="small">{{ el.category }}</NTag>
    <NTag size="small" type="default">{{ el.name }}</NTag>
    <NTag size="small" :type="el.status === 'new' ? 'success' : 'warning'">
      {{ el.status === 'new' ? $t('import.new') : $t('import.existing') }}
    </NTag>
    <span style="flex: 1; color: var(--text-tertiary); font-size: 12px;">{{ (el.brief || '').slice(0, 50) }}</span>
  </div>
</template>
