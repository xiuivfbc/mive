<script setup lang="ts">
import type { WorldDoc } from '@/types/world'
import { NPopconfirm } from 'naive-ui'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLocale } from '@/composables/useLocale'
import MarkdownText from '@/components/common/MarkdownText.vue'

const props = withDefaults(defineProps<{
  world: WorldDoc
  descOverride?: string | null
  featured?: boolean
}>(), {
  descOverride: null,
  featured: false,
})
const emit = defineEmits<{ click: []; delete: [id: string] }>()

const { t } = useI18n()
const { locale } = useLocale()

const title = computed(() => props.world.source.title ?? t('worldCard.untitled'))
const author = computed(() => props.world.source.author)

// Markdown-rendered then visually clipped with CSS line-clamp (see .world-card__desc),
// so we no longer truncate the raw string — slicing characters could cut Markdown
// syntax (e.g. `**`) in half and produce broken markup.
const description = computed(() => {
  const src = props.descOverride || props.world.source.common_sense || props.world.source.plot_summary
  return src || t('worldCard.noElements')
})

const formattedDate = computed(() => {
  if (!props.world.meta.created_at) return ''
  return new Date(props.world.meta.created_at).toLocaleDateString(locale.value)
})

const elementCount = computed(() => {
  return props.world.element_count ?? props.world.elements.length
})

const characterCount = computed(() => {
  return props.world.character_count ?? 0
})

const relationshipCount = computed(() => {
  return props.world.relationship_count ?? 0
})

function handleDelete(e: MouseEvent) {
  e.stopPropagation()
  emit('delete', props.world.world_id)
}
</script>

<template>
  <div class="world-card" :class="{ 'world-card--featured': featured }" @click="$emit('click')">
    <div class="world-card__glow" />
    <NPopconfirm @positive-click="handleDelete">
      <template #trigger>
        <button class="world-card__delete" @click.stop title="删除">&times;</button>
      </template>
      {{ $t('worldCard.deleteConfirm', { name: title }) }}
    </NPopconfirm>
    <div class="world-card__content">
      <h3 class="world-card__title">{{ title }}</h3>
      <p v-if="author" class="world-card__author">{{ author }}</p>
      <MarkdownText class="world-card__desc" :text="description" />
      <div class="world-card__meta">
        <span class="world-card__meta-item">
          <svg viewBox="0 0 16 16" fill="none" width="14" height="14"><path d="M2 4a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V4z" stroke="currentColor" stroke-width="1.2" opacity="0.6"/><path d="M5 6h6M5 8h4M5 10h5" stroke="currentColor" stroke-width="1" opacity="0.4"/></svg>
          {{ elementCount }} {{ $t('worldList.elements') }}
        </span>
        <span class="world-card__meta-item">
          <svg viewBox="0 0 16 16" fill="none" width="14" height="14"><circle cx="8" cy="5" r="3" stroke="currentColor" stroke-width="1.2" opacity="0.6"/><path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" stroke-width="1.2" opacity="0.4"/></svg>
          {{ characterCount }} {{ $t('worldList.characters') }}
        </span>
        <span class="world-card__meta-item">
          <svg viewBox="0 0 16 16" fill="none" width="14" height="14"><path d="M4 8h8M8 4v8" stroke="currentColor" stroke-width="1.2" opacity="0.4"/><circle cx="4" cy="8" r="2" stroke="currentColor" stroke-width="1" opacity="0.6"/><circle cx="12" cy="8" r="2" stroke="currentColor" stroke-width="1" opacity="0.6"/></svg>
          {{ relationshipCount }} {{ $t('worldList.relations') }}
        </span>
        <span class="world-card__meta-item">
          {{ formattedDate }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.world-card {
  position: relative;
  border-radius: var(--radius);
  background: linear-gradient(135deg, var(--bg-card), var(--accent-glow));
  border: 1px solid transparent;
  overflow: hidden;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
  transition: transform 0.4s cubic-bezier(0.23, 1, 0.32, 1),
              box-shadow 0.4s cubic-bezier(0.23, 1, 0.32, 1);
  animation: fadeInUp 0.6s cubic-bezier(0.23, 1, 0.32, 1) backwards;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: translateY(0); }
}

.world-card:hover {
  transform: translateY(-6px);
  box-shadow: var(--shadow-card-hover);
}

.world-card:hover .world-card__glow {
  opacity: 1;
}

.world-card__glow {
  position: absolute;
  inset: 0;
  background: radial-gradient(
    ellipse 60% 50% at 20% 0%,
    var(--accent-glow) 0%,
    transparent 70%
  );
  opacity: 0;
  transition: opacity 0.5s ease;
  pointer-events: none;
}

.world-card__delete {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: all 0.3s;
  z-index: 2;
}

/* 触摸设备始终显示删除按钮 */
@media (hover: none) {
  .world-card__delete {
    opacity: 1;
    background: rgba(0, 0, 0, 0.05);
  }
}

.world-card:hover .world-card__delete {
  opacity: 1;
}

.world-card__delete:hover {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.world-card__content {
  position: relative;
  padding: 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 160px;
}

.world-card__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  line-height: 1.3;
}

.world-card__author {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.world-card__desc {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.8;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}

.world-card__meta {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(0,0,0,0.06);
}

.world-card__meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* === COLOR THEMES — unified card pattern === */
[data-theme="ink"] .world-card,
[data-theme="breeze"] .world-card,
[data-theme="sakura"] .world-card,
[data-theme="ember"] .world-card,
[data-theme="sunflower"] .world-card,
[data-theme="ocean"] .world-card,
[data-theme="indigo"] .world-card {
  border: none;
}
[data-theme="ink"] .world-card:hover,
[data-theme="breeze"] .world-card:hover,
[data-theme="sakura"] .world-card:hover,
[data-theme="ember"] .world-card:hover,
[data-theme="sunflower"] .world-card:hover,
[data-theme="ocean"] .world-card:hover,
[data-theme="indigo"] .world-card:hover {
  border-color: transparent;
}
[data-theme="ink"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #e6f5f0);
  box-shadow: var(--shadow-card);
}
[data-theme="ink"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(20, 212, 168, 0.15);
}
[data-theme="breeze"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(152, 115, 247, 0.15);
}
[data-theme="sakura"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(233, 30, 99, 0.15);
}
[data-theme="ember"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(245, 124, 0, 0.15);
}
[data-theme="sunflower"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(230, 168, 23, 0.15);
}
[data-theme="ocean"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(41, 121, 255, 0.15);
}
[data-theme="indigo"][data-mode="dark"] .world-card {
  background: color-mix(in srgb, var(--bg-card) 20%, #202225 80%);
  border: 1px solid rgba(67, 56, 202, 0.15);
}

[data-theme="breeze"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #f1ecfb);
  box-shadow: var(--shadow-card);
}
[data-theme="sakura"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #fbe8ee);
  box-shadow: var(--shadow-card);
}
[data-theme="ember"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #fbecdb);
  box-shadow: var(--shadow-card);
}
[data-theme="sunflower"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #fbf2d8);
  box-shadow: var(--shadow-card);
}
[data-theme="ocean"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #dfe9fb);
  box-shadow: var(--shadow-card);
}
[data-theme="indigo"] .world-card {
  background: linear-gradient(145deg, var(--bg-card), #e4e1f7);
  box-shadow: var(--shadow-card);
}

</style>
