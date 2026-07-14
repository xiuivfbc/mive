<script setup lang="ts">
import type { ImportRelationPreview } from '@/api/importApi'

defineProps<{
  rel: ImportRelationPreview
}>()
</script>

<template>
  <div style="display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px;">
    <span>{{ rel.character_a }}</span>
    <span style="color: var(--text-tertiary);">↔</span>
    <span>{{ rel.character_b }}</span>
    <NTag v-if="rel.type" size="small" type="default">{{ rel.type }}</NTag>
    <NTag size="small" :type="rel.status === 'valid' ? 'success' : 'error'">
      {{ rel.status === 'valid' ? $t('import.relationValid') : $t('import.relationSkipped') }}
    </NTag>
  </div>
</template>
