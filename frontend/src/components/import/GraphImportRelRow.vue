<script setup lang="ts">
import { ref } from 'vue'
import type { ImportRelationPreview } from '@/api/importApi'

defineProps<{
  rel: ImportRelationPreview
}>()

const expanded = ref(false)
</script>

<template>
  <div
    :style="{
      border: '1px solid var(--border-color)',
      borderRadius: '6px',
      padding: '8px',
      marginBottom: '6px',
      fontSize: '13px',
      background: rel.status === 'update' ? 'var(--bg-card)' : undefined,
    }"
  >
    <div style="display: flex; align-items: center; gap: 8px;">
      <span style="font-weight: 500;">{{ rel.character_a }}</span>
      <span style="color: var(--text-tertiary);">↔</span>
      <span style="font-weight: 500;">{{ rel.character_b }}</span>
      <NTag v-if="rel.type" size="small" type="default">{{ rel.type }}</NTag>
      <NTag
        size="small"
        :type="rel.status === 'valid' ? 'success' : rel.status === 'update' ? 'warning' : 'error'"
      >
        {{
          rel.status === 'valid'
            ? $t('import.relationNew')
            : rel.status === 'update'
              ? $t('import.relationUpdate')
              : $t('import.relationSkipped')
        }}
      </NTag>
      <NButton
        v-if="rel.status === 'update' && (rel.old_type !== undefined || rel.old_description !== undefined)"
        size="tiny"
        quaternary
        @click="expanded = !expanded"
      >
        {{ expanded ? $t('common.collapse') : $t('import.showDiff') }}
      </NButton>
    </div>
    <div v-if="expanded && rel.status === 'update'" style="margin-top: 8px; display: flex; flex-direction: column; gap: 6px;">
      <div v-if="rel.old_type !== undefined || rel.type" style="display: flex; gap: 8px; align-items: flex-start;">
        <span style="color: var(--text-tertiary); white-space: nowrap; min-width: 40px;">类型</span>
        <span v-if="rel.old_type" style="color: var(--text-tertiary); text-decoration: line-through;">{{ rel.old_type }}</span>
        <span v-if="rel.type && rel.old_type" style="color: var(--text-secondary);">→</span>
        <span v-if="rel.type" style="color: var(--accent);">{{ rel.type }}</span>
      </div>
      <div v-if="rel.old_description !== undefined || rel.description" style="display: flex; gap: 8px; align-items: flex-start;">
        <span style="color: var(--text-tertiary); white-space: nowrap; min-width: 40px;">描述</span>
        <span v-if="rel.old_description" style="color: var(--text-tertiary); text-decoration: line-through; flex: 1;">{{ rel.old_description }}</span>
        <span v-if="rel.description && rel.old_description" style="color: var(--text-secondary);">→</span>
        <span v-if="rel.description" style="color: var(--accent); flex: 1;">{{ rel.description }}</span>
      </div>
    </div>
  </div>
</template>
