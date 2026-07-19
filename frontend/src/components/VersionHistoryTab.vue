<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NCard, NButton, NSpace, NTag, NEmpty, NSpin, NInput } from 'naive-ui'
import { useVersionHistory } from '@/composables/useVersionHistory'

const props = defineProps<{ worldId: string }>()

const { t } = useI18n()

const {
  versions,
  loading,
  creating,
  updating,
  loadVersions,
  onRollback,
  renameVersion,
  onDelete: onDeleteRaw,
  onCreateVersion,
  onUpdateSnapshot,
} = useVersionHistory(props.worldId)

function onDelete(versionId: string) {
  onDeleteRaw(versionId)
  // Clean up expanded state for deleted version
  const next = new Set(expandedVersionIds.value)
  next.delete(versionId)
  expandedVersionIds.value = next
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 过滤掉 sync 自动同步的轻量快照（无记忆/对话，仅内部跟踪用） */
function isSyncVersion(ver: { created_by: string | null }): boolean {
  return !!ver.created_by?.startsWith('sync:')
}

const visibleVersions = computed(() => versions.value.filter((v) => !isSyncVersion(v)))

const editingVersionId = ref<string | null>(null)
const editingName = ref('')
const expandedVersionIds = ref<Set<string>>(new Set())

function getVersionTitle(summary: string | null, createdAt: string): string {
  return summary?.trim() || formatDate(createdAt)
}

function startEdit(versionId: string, current: string | null) {
  editingVersionId.value = versionId
  editingName.value = current?.trim() || ''
}

function cancelEdit() {
  editingVersionId.value = null
  editingName.value = ''
}

async function saveEdit(versionId: string) {
  try {
    await renameVersion(versionId, editingName.value)
    cancelEdit()
  } catch {
    // Error already handled by composable
  }
}

function isExpanded(versionId: string): boolean {
  return expandedVersionIds.value.has(versionId)
}

function toggleExpanded(versionId: string) {
  const next = new Set(expandedVersionIds.value)
  if (next.has(versionId)) {
    next.delete(versionId)
  } else {
    next.add(versionId)
  }
  expandedVersionIds.value = next
}

function isLatest(ver: { id: string }): boolean {
  return visibleVersions.value.length > 0 && visibleVersions.value[0].id === ver.id
}

function getCharacterName(snapshot: { characters: { id: string; name?: string | null }[] }, id: string): string {
  const character = snapshot.characters.find((c) => c.id === id)
  return character?.name?.trim() || id.slice(0, 8)
}

function formatRelation(
  snapshot: { characters: { id: string; name?: string | null }[] },
  rel: { character_a: string; character_b: string; type: string | null; direction: string; description: string | null }
): string {
  const left = getCharacterName(snapshot, rel.character_a)
  const right = getCharacterName(snapshot, rel.character_b)
  const arrow = rel.direction === 'bidirectional' ? '<->' : '->'
  const type = rel.type ? ` (${rel.type})` : ''
  const desc = rel.description ? ` - ${rel.description}` : ''
  return `${left} ${arrow} ${right}${type}${desc}`
}

onMounted(() => {
  loadVersions()
})

defineExpose({ onCreateVersion, creating })
</script>

<template>
  <div class="version-history">
    <div class="version-history__actions">
      <NButton size="small" type="primary" :loading="creating" @click="onCreateVersion">
        {{ $t('version.createVersion') }}
      </NButton>
    </div>
    <!-- 版本列表 -->
    <NSpin :show="loading">
      <NEmpty v-if="!loading && visibleVersions.length === 0" :description="$t('version.noVersions')" />
      <div v-else class="version-history__list">
        <NCard
          v-for="ver in visibleVersions"
          :key="ver.id"
          size="small"
          class="version-card"
        >
          <template #header>
            <span>{{ getVersionTitle(ver.summary, ver.created_at) }}</span>
          </template>
          <template #header-extra>
            <span class="version-card__meta">
              {{ formatDate(ver.created_at) }}
            </span>
          </template>

          <div class="version-card__body">
            <div v-if="editingVersionId === ver.id" class="version-card__edit">
              <NInput
                v-model:value="editingName"
                size="small"
                :placeholder="$t('version.namePlaceholder')"
                @keydown.enter.stop.prevent="saveEdit(ver.id)"
              />
              <NSpace :size="6" align="center">
                <NButton size="tiny" type="primary" @click.stop="saveEdit(ver.id)">
                  {{ $t('version.saveName') }}
                </NButton>
                <NButton size="tiny" @click.stop="cancelEdit">
                  {{ $t('version.cancelEdit') }}
                </NButton>
              </NSpace>
            </div>
            <div v-if="ver.snapshot" class="version-card__summary" :title="isExpanded(ver.id) ? $t('version.collapse') : $t('version.expand')" @click.stop="toggleExpanded(ver.id)">
              <span>{{ $t('version.countSummary', { characters: ver.snapshot.characters.length, relations: ver.snapshot.relations.length, elements: ver.snapshot.elements?.length ?? 0 }) }}</span>
              <svg class="version-card__chevron" :class="{ 'version-card__chevron--open': isExpanded(ver.id) }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            </div>
            <div v-if="ver.snapshot" class="version-card__snapshot">
              <div
                v-if="isExpanded(ver.id)"
                class="version-card__side-strip version-card__side-strip--left"
                @click.stop="toggleExpanded(ver.id)"
                :title="$t('version.collapse')"
              />
              <div
                v-if="isExpanded(ver.id)"
                class="version-card__side-strip version-card__side-strip--right"
                @click.stop="toggleExpanded(ver.id)"
                :title="$t('version.collapse')"
              />
              <div class="version-card__details" :class="{ 'version-card__details--open': isExpanded(ver.id) }">
                <div v-if="ver.snapshot.elements?.length" class="snapshot-section">
                  <span class="snapshot-section__title">
                    <span class="snapshot-section__title-text">{{ $t('diff.elements') }}</span>
                    <span class="snapshot-section__count">{{ ver.snapshot.elements.length }}</span>
                  </span>
                  <div class="snapshot-section__list">
                    <NTag
                      v-for="(el, idx) in ver.snapshot.elements"
                      :key="idx"
                      size="small"
                      type="default"
                    >{{ el.name }}</NTag>
                  </div>
                </div>
                <div class="snapshot-section">
                  <span class="snapshot-section__title">
                    <span class="snapshot-section__title-text">{{ $t('diff.characters') }}</span>
                    <span class="snapshot-section__count">{{ ver.snapshot.characters.length }}</span>
                  </span>
                  <div v-if="ver.snapshot.characters.length" class="snapshot-section__list">
                    <NTag
                      v-for="c in ver.snapshot.characters"
                      :key="c.id"
                      size="small"
                      type="default"
                      :class="['snapshot-character', c.tier ? `snapshot-character--${c.tier}` : '']"
                    >{{ c.name || c.id.slice(0, 8) }}</NTag>
                  </div>
                  <span v-else class="snapshot-section__empty">-</span>
                </div>
                <div class="snapshot-section">
                  <span class="snapshot-section__title">
                    <span class="snapshot-section__title-text">{{ $t('diff.relations') }}</span>
                    <span class="snapshot-section__count">{{ ver.snapshot.relations.length }}</span>
                  </span>
                  <div v-if="ver.snapshot.relations.length" class="snapshot-section__list snapshot-section__list--stack">
                    <div
                      v-for="rel in ver.snapshot.relations"
                      :key="rel.id"
                      class="snapshot-relation"
                    >{{ formatRelation(ver.snapshot, rel) }}</div>
                  </div>
                  <span v-else class="snapshot-section__empty">-</span>
                </div>
              </div>
            </div>
            <span v-else class="version-card__initial">{{ $t('version.initial') }}</span>
          </div>

          <template #action>
            <NSpace :size="8" justify="end" align="center">
              <NButton
                size="tiny"
                quaternary
                @click.stop="startEdit(ver.id, ver.summary)"
              >{{ $t('version.rename') }}</NButton>
              <NButton
                v-if="ver.snapshot"
                size="tiny"
                quaternary
                :loading="updating"
                @click="onUpdateSnapshot(ver.id)"
              >{{ $t('version.updateSnapshot') }}</NButton>
              <NButton
                v-if="ver.snapshot"
                size="tiny"
                quaternary
                @click="toggleExpanded(ver.id)"
              >{{ isExpanded(ver.id) ? $t('version.collapse') : $t('version.expand') }}</NButton>
              <NButton
                size="tiny"
                type="error"
                quaternary
                :disabled="isLatest(ver)"
                @click="onDelete(ver.id)"
              >{{ $t('version.delete') }}</NButton>
              <NButton
                v-if="isLatest(ver)"
                size="tiny"
                class="btn-accent"
                disabled
              >{{ $t('version.current') }}</NButton>
              <NButton
                v-else
                size="tiny"
                @click="onRollback(ver.id)"
              >{{ $t('version.rollback') }}</NButton>
            </NSpace>
          </template>
        </NCard>
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
:deep(.n-card) {
  border: none;
  border-radius: var(--radius);
}

.version-history {
  height: 100%;
  overflow-y: auto;
  padding: 8px 0;
}

.version-history__actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
  padding: 0 4px;
}

.version-history__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.version-card {
  border-radius: var(--radius) !important;
}

.version-card__meta {
  font-size: 12px;
  color: var(--text-muted);
}

.version-card__body {
  min-height: 24px;
}

.version-card__summary {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  user-select: none;
}

.version-card__summary:hover {
  color: var(--text-primary);
}

.version-card__chevron {
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.version-card__chevron--open {
  transform: rotate(180deg);
}

.version-card__edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}

.version-card__initial {
  font-size: 12px;
  color: var(--text-muted);
}


.version-card__snapshot {
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
}

.version-card__side-strip {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 14px;
  cursor: pointer;
  z-index: 1;
  border-radius: 4px;
  transition: background 0.15s ease;
}

.version-card__side-strip--left {
  left: -14px;
}

.version-card__side-strip--right {
  right: -14px;
}

.version-card__side-strip:hover {
  background: color-mix(in srgb, var(--accent) 18%, transparent);
}

.version-card__details {
  max-height: 0;
  opacity: 0;
  overflow: hidden;
  transform: translateY(-4px);
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  transition: max-height 0.25s ease, opacity 0.2s ease, transform 0.2s ease, padding 0.2s ease, border-color 0.2s ease, background 0.2s ease;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.version-card__details--open {
  max-height: 1400px;
  opacity: 1;
  transform: translateY(0);
  padding: 10px 12px 12px;
  border-color: var(--border-subtle);
  background: var(--bg-card);
  pointer-events: auto;
}

.snapshot-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.snapshot-section__title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  letter-spacing: 0.01em;
}

.snapshot-section__title-text {
  font-weight: 600;
  color: var(--text-primary);
}

.snapshot-section__count {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  color: var(--text-muted);
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--bg-page);
}

.snapshot-section__list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.snapshot-section__list--stack {
  flex-direction: column;
}

:deep(.snapshot-section__list .n-tag) {
  border-radius: 999px;
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--bg-page);
  color: var(--text-primary);
  font-size: 12px;
  padding: 2px 8px;
}

:deep(.snapshot-section__list .n-tag.snapshot-character--core) {
  border-color: var(--accent);
  color: var(--text-primary);
}

:deep(.snapshot-section__list .n-tag.snapshot-character--supporting) {
  border-color: var(--text-secondary);
}

:deep(.snapshot-section__list .n-tag.snapshot-character--extra) {
  border-color: var(--text-muted);
}

.snapshot-section__empty {
  font-size: 12px;
  color: var(--text-muted);
}

.snapshot-relation {
  font-size: 12px;
  color: var(--text-primary);
  padding: 6px 8px 6px 20px;
  border: none;
  border-radius: 10px;
  background: var(--bg-page);
  position: relative;
  line-height: 1.4;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.02);
}

.snapshot-relation::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  position: absolute;
  left: 8px;
  top: 12px;
  opacity: 0.8;
}

.btn-accent {
  background: var(--accent) !important;
  color: #fff !important;
  border: none !important;
  opacity: 1 !important;
}

.btn-accent:disabled {
  background: var(--accent) !important;
  color: #fff !important;
  opacity: 0.85 !important;
  cursor: default !important;
}
</style>
