<script setup lang="ts">
import { computed } from 'vue'
import type { QueueItem } from '@/types/message'

const props = defineProps<{
  items: QueueItem[]
}>()

const emit = defineEmits<{
  'remove': [id: string]
}>()

const pendingItems = computed(() =>
  props.items.filter((item) => item.status === 'pending')
)

const processingItem = computed(() =>
  props.items.find((item) => item.status === 'processing') ?? null
)

const failedItems = computed(() =>
  props.items.filter((item) => item.status === 'failed')
)

const queuedCount = computed(() => pendingItems.value.length + failedItems.value.length)

function truncateContent(content: string, maxLen = 40): string {
  if (content.length <= maxLen) return content
  return content.slice(0, maxLen) + '...'
}

function handleRemove(id: string) {
  emit('remove', id)
}
</script>

<template>
  <div v-if="items.length > 0" class="queue-bar">
    <div class="queue-bar__header">
      <span class="queue-bar__title">{{ $t('chat.queueTitle') || '消息队列' }}</span>
      <span class="queue-bar__count">{{ queuedCount }}</span>
    </div>

    <div class="queue-bar__list">
      <!-- Processing item -->
      <div
        v-if="processingItem"
        :key="processingItem.id"
        class="queue-item queue-item--processing"
      >
        <span class="queue-item__status-icon">
          <span class="queue-item__spinner"></span>
        </span>
        <span class="queue-item__content">{{ truncateContent(processingItem.content) }}</span>
      </div>

      <!-- Pending items -->
      <div
        v-for="item in pendingItems"
        :key="item.id"
        class="queue-item queue-item--pending"
      >
        <span class="queue-item__status-icon">⏳</span>
        <span class="queue-item__content">{{ truncateContent(item.content) }}</span>
        <button
          class="queue-item__remove"
          @click.stop="handleRemove(item.id)"
          :aria-label="$t('common.delete') || '删除'"
        >
          ×
        </button>
      </div>

      <!-- Failed items -->
      <div
        v-for="item in failedItems"
        :key="item.id"
        class="queue-item queue-item--failed"
      >
        <span class="queue-item__status-icon queue-item__status-icon--error">⚠</span>
        <span class="queue-item__content queue-item__content--failed">{{ truncateContent(item.content) }}</span>
        <button
          class="queue-item__remove"
          @click.stop="handleRemove(item.id)"
          :aria-label="$t('common.delete') || '删除'"
        >
          ×
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.queue-bar {
  position: fixed;
  bottom: 120px;
  right: 20px;
  width: 25vw;
  max-width: 320px;
  min-width: 200px;
  max-height: 300px;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  box-shadow: var(--shadow-bubble);
  z-index: 100;
  overflow: hidden;
}

.queue-bar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.queue-bar__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.queue-bar__count {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  padding: 1px 7px;
  border-radius: 10px;
}

.queue-bar__list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.queue-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
  transition: background 0.15s;
}

.queue-item--pending {
  background: color-mix(in srgb, var(--accent) 4%, transparent);
}

.queue-item--pending:hover {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.queue-item--processing {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.queue-item--failed {
  background: color-mix(in srgb, var(--color-error) 8%, transparent);
}

.queue-item__status-icon {
  flex-shrink: 0;
  font-size: 12px;
  width: 16px;
  text-align: center;
}

.queue-item__status-icon--error {
  color: var(--color-error);
}

.queue-item__spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: none;
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.queue-item__content {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.queue-item__content--failed {
  color: var(--color-error);
  opacity: 0.8;
}

.queue-item__remove {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: 14px;
  cursor: pointer;
  opacity: 0.5;
  transition: all 0.15s;
  line-height: 1;
}

.queue-item__remove:hover {
  opacity: 1;
  background: color-mix(in srgb, var(--color-error) 12%, transparent);
  color: var(--color-error);
}

/* Theme overrides */
[data-theme="ink"] .queue-bar {
  background: color-mix(in srgb, var(--bg-card) 95%, transparent);
}

[data-theme="breeze"] .queue-bar {
  background: color-mix(in srgb, var(--bg-card) 92%, transparent);
}

</style>
