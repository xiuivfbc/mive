<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listWorlds, deleteWorld } from '@/api/worlds'
import type { WorldDoc } from '@/types/world'
import { parseApiError } from '@/utils/apiError'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import WorldCard from '@/components/worlds/WorldCard.vue'
import CreateWorldDialog from '@/components/worlds/CreateWorldDialog.vue'
import TemplateWorldDialog from '@/components/worlds/TemplateWorldDialog.vue'
import UsageBadge from '@/components/billing/UsageBadge.vue'
import { NButton, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()

const router = useRouter()
const messageApi = useMessage()
const authStore = useAuthStore()

async function handleLogout() {
  // Self-hosted: no logout needed, but keep the button for consistency
  // The auth store doesn't have a logout method in single-tenant mode
}
const worlds = ref<WorldDoc[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const showCreateDialog = ref(false)
const showTemplateDialog = ref(false)

const scaleStats = computed(() => {
  const stats = { standard: 0, detailed: 0, deep: 0, all: 0 }
  worlds.value.forEach(w => {
    const scale = w.scale || 'standard'
    if (scale in stats) stats[scale as keyof typeof stats]++
  })
  return stats
})

async function fetchWorlds() {
  loading.value = true
  error.value = null
  try {
    worlds.value = await listWorlds()
  } catch (e) {
    error.value = parseApiError(e, t)
  } finally {
    loading.value = false
  }
}

function onCreated() {
  showCreateDialog.value = false
  fetchWorlds()
}

function onTemplateCreated() {
  showTemplateDialog.value = false
  fetchWorlds()
}

async function onDeleteWorld(worldId: string) {
  try {
    await deleteWorld(worldId)
    worlds.value = worlds.value.filter(w => w.world_id !== worldId)
    messageApi.success(t('worldList.deleteSuccess', '世界已删除'))
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  }
}

function goToDetail(worldId: string) {
  router.push(`/world/${worldId}`)
}

onMounted(fetchWorlds)
</script>

<template>
  <div class="world-list-page">
    <div class="header-section">
      <PageHeader :title="$t('worldList.title')" :subtitle="$t('worldList.subtitle')">
        <template #title-prefix><span class="title-accent" @click="router.push('/welcome')">V</span></template>
        <template #title-suffix>
          <button v-if="authStore.user?.isAdmin" class="admin-btn" :title="$t('worldList.adminPanel')" @click="router.push('/admin')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </button>
        </template>
        <div class="header-actions">
          <NButton type="primary" @click="showCreateDialog = true">
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
            </template>
            {{ $t('template.createFromWork') }}
          </NButton>
          <NButton @click="showTemplateDialog = true">
            <template #icon>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 3h5v4H2zM9 3h5v4H9zM2 9h5v4H2zM9 9h5v4H9z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
            </template>
            {{ $t('worldList.createFromTemplate') }}
          </NButton>
        </div>
        <UsageBadge />
        <div v-if="authStore.user" class="user-info">
          <img v-if="authStore.user.avatarUrl" :src="authStore.user.avatarUrl" class="user-avatar user-avatar--img" />
          <span v-else class="user-avatar">{{ authStore.user.username[0].toUpperCase() }}</span>
          <span class="user-name">{{ authStore.user.username }}</span>
          <NButton size="small" @click="handleLogout">{{ $t('worldList.logout') }}</NButton>
        </div>
      </PageHeader>

      <div v-if="!loading && !error && worlds.length > 0" class="stats-bar">
        <span class="stats-label">{{ $t('worldList.scaleDistribution') }}</span>
        <div class="stat-item"><span class="stat-num">{{ scaleStats.standard }}</span> {{ $t('worldList.scaleStandard') }}</div>
        <div class="stat-item"><span class="stat-num">{{ scaleStats.detailed }}</span> {{ $t('worldList.scaleDetailed') }}</div>
        <div class="stat-item"><span class="stat-num">{{ scaleStats.deep }}</span> {{ $t('worldList.scaleDeep') }}</div>
        <div class="stat-item"><span class="stat-num">{{ scaleStats.all }}</span> {{ $t('worldList.scaleAll') }}</div>
      </div>
    </div>

    <div class="content">
      <LoadingState v-if="loading" :rows="3" />
      <ErrorState v-else-if="error" :message="error" @retry="fetchWorlds" />
      <EmptyState
        v-else-if="worlds.length === 0"
        :title="$t('worldList.emptyTitle')"
        :description="$t('worldList.emptyDesc')"
      />
      <div v-else class="card-grid">
        <WorldCard
          v-for="(world, index) in worlds"
          :key="world.world_id"
          :world="world"
          :featured="index === 0"
          :style="{ animationDelay: `${index * 0.07}s` }"
          @click="goToDetail(world.world_id)"
          @delete="onDeleteWorld"
        />
      </div>
    </div>

    <CreateWorldDialog
      v-model:visible="showCreateDialog"
      @created="onCreated"
    />
    <TemplateWorldDialog
      v-model:visible="showTemplateDialog"
      @created="onTemplateCreated"
    />
  </div>
</template>

<style scoped>
.world-list-page {
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  overscroll-behavior: contain;
  padding: 0 var(--spacing-xs);
}

.header-section {
  flex-shrink: 0;
  padding: var(--spacing-lg) 0;
  position: relative;
}

/* large ambient gradient behind header */
.header-section::before {
  content: '';
  position: absolute;
  top: -60px;
  left: -200px;
  right: -200px;
  height: 360px;
  background: radial-gradient(
    ellipse 70% 100% at 30% 0%,
    var(--accent) 0%,
    transparent 50%
  );
  opacity: 0.08;
  pointer-events: none;
  z-index: 0;
}

.header-section > * {
  position: relative;
  z-index: 1;
}

/* hero header overrides */
.header-section :deep(.page-header) {
  padding: var(--spacing-2xl) 0 var(--spacing-2xl);
  align-items: flex-end;
}

.header-section :deep(.page-header__after) {
  display: none;
}

.header-section :deep(.page-header__accent) {
  width: 5px;
  height: 48px;
}

.header-section :deep(.page-header__title) {
  font-size: var(--font-3xl);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.header-section :deep(.page-header__subtitle) {
  font-size: 15px;
  margin-top: 6px;
  color: var(--text-secondary);
}

.content {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  margin-top: var(--spacing-lg);
  padding-bottom: var(--spacing-lg);
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
}

.stats-bar {
  display: flex;
  align-items: baseline;
  gap: 24px;
  padding: var(--spacing-sm) 0;
  font-size: 13px;
  color: var(--text-muted);
  border-bottom: none;
  margin-top: var(--spacing-xs);
}

.stats-label {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.stat-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.stat-num {
  font-weight: 700;
  color: var(--text-primary);
  font-size: var(--font-xl);
  font-family: var(--font-display);
  letter-spacing: -0.01em;
}

.title-accent {
  color: var(--accent);
  cursor: pointer;
}


.header-actions {
  display: flex;
  gap: var(--spacing-sm);
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding-left: var(--spacing-sm);
  border-left: 1px solid rgba(0,0,0,0.06);
}

.user-info .n-button {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--gradient-accent);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-avatar--img {
  object-fit: cover;
  background: none;
}

.user-name {
  font-size: 13px;
  color: var(--text-secondary);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  margin-left: 6px;
  vertical-align: middle;
  flex-shrink: 0;
}

.admin-btn:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-primary);
}

@media (max-width: 768px) {
  .world-list-page {
    padding: 12px var(--spacing-xs) 0;
  }

  .header-actions {
    flex-direction: column;
    gap: var(--spacing-xs);
  }

  .user-info {
    flex-direction: column;
    align-items: center;
    padding-left: 0;
    border-left: none;
    padding-top: var(--spacing-sm);
    border-top: 1px solid rgba(0, 0, 0, 0.06);
  }

  .stats-bar {
    flex-wrap: wrap;
    gap: 12px;
  }

  .card-grid {
    grid-template-columns: 1fr;
  }

  .usage-badge {
    display: none;
  }
}
</style>
