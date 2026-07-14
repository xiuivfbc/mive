<script setup lang="ts">
import type { Element } from '@/types/world'
import { normalizeCategory } from '@/types/world'
import { NCard, NTag, NCollapse, NCollapseItem, NButton, NPopconfirm } from 'naive-ui'
import MarkdownText from '@/components/common/MarkdownText.vue'

defineProps<{ element: Element }>()
const emit = defineEmits<{ edit: [element: Element]; delete: [element: Element] }>()

type TagType = 'default' | 'primary' | 'info' | 'success' | 'warning' | 'error'

const colorMap: Record<string, TagType> = {
  场所: 'info',
  势力: 'error',
  规则: 'success',
  事件: 'warning',
  物品: 'primary',
  文化: 'default',
  其他: 'default',
}

function getTagColor(category: string): TagType {
  return colorMap[normalizeCategory(category)] ?? 'default'
}
</script>

<template>
  <NCard size="small" class="element-card" :bordered="true" :style="{ borderColor: 'rgba(0,0,0,0.08)', borderWidth: '1px' }">
    <div class="element-card__header">
      <NTag :type="getTagColor(element.category)" size="small" round>
        {{ element.category }}
      </NTag>
      <div class="element-card__actions">
        <NButton text size="tiny" @click="emit('edit', element)">{{ $t('common.edit') }}</NButton>
        <NPopconfirm @positive-click="emit('delete', element)" :positive-text="$t('common.delete')" :negative-text="$t('common.cancel')">
          <template #trigger>
            <NButton text size="tiny" type="error">{{ $t('common.delete') }}</NButton>
          </template>
          {{ $t('element.deleteConfirm', { name: element.name }) }}
        </NPopconfirm>
      </div>
    </div>
    <h4 class="element-card__name">{{ element.name }}</h4>
    <MarkdownText class="element-card__brief" :text="element.brief" />
    <NCollapse class="element-card__collapse">
      <NCollapseItem :title="$t('element.expandDetail')" :name="element.id">
        <MarkdownText class="element-card__detail" :text="element.detail" />
      </NCollapseItem>
    </NCollapse>
  </NCard>
</template>

<style scoped>
.element-card {
  margin-bottom: 8px;
  transition: border-color 0.2s ease;
  border-radius: var(--radius) !important;
}

.element-card:hover {
  border-color: var(--border);
}

.element-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.element-card__actions {
  display: flex;
  gap: 8px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.element-card:hover .element-card__actions {
  opacity: 1;
}

.element-card__name {
  margin: 0 0 4px;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.element-card__brief {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
}

.element-card__collapse {
  margin-top: 8px;
}

.element-card__detail {
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  color: var(--text-secondary);
}

/* INK */
[data-theme="ink"] .element-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(201, 168, 76, 0.015));
}

</style>
