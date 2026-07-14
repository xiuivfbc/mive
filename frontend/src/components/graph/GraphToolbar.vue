<script setup lang="ts">
import { NButton, NButtonGroup, NTooltip } from 'naive-ui'

const emit = defineEmits<{
  'zoom-in': []
  'zoom-out': []
  'fit': []
  'layout-change': [name: string]
}>()
</script>

<template>
  <div class="graph-toolbar">
    <NButtonGroup size="small">
      <NTooltip trigger="hover" placement="bottom">
        <template #trigger>
          <NButton @click="emit('zoom-in')">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </NButton>
        </template>
        {{ $t('graph.zoomIn') }}
      </NTooltip>
      <NTooltip trigger="hover" placement="bottom">
        <template #trigger>
          <NButton @click="emit('zoom-out')">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </NButton>
        </template>
        {{ $t('graph.zoomOut') }}
      </NTooltip>
      <NTooltip trigger="hover" placement="bottom">
        <template #trigger>
          <NButton @click="emit('fit')">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </NButton>
        </template>
        {{ $t('graph.fitCanvas') }}
      </NTooltip>
    </NButtonGroup>
    <NButtonGroup size="small" class="graph-toolbar__layouts">
      <NButton @click="emit('layout-change', 'cose')">{{ $t('graph.layoutForce') }}</NButton>
      <NButton @click="emit('layout-change', 'circle')">{{ $t('graph.layoutCircle') }}</NButton>
      <NButton @click="emit('layout-change', 'grid')">{{ $t('graph.layoutGrid') }}</NButton>
    </NButtonGroup>
  </div>
</template>

<style scoped>
.graph-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-card);
  backdrop-filter: blur(8px);
  padding: 4px;
  border-radius: var(--radius);
  border: 1px solid rgba(0,0,0,0.08);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.graph-toolbar__layouts {
  margin-left: 6px;
}

/* BREEZE */
[data-theme="breeze"] .graph-toolbar {
  background: rgba(255, 255, 255, 0.9);
}
</style>
