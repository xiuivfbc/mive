<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { NTag, useMessage } from 'naive-ui'
import { parseApiError } from '@/utils/apiError'
import client from '@/api/client'

const { t } = useI18n()
const message = useMessage()

const platformMode = ref<'matterbridge' | 'discord' | 'none'>('none')
const loading = ref(true)

// Matterbridge state
interface MatterbridgeBinding {
  id: string
  world_id: string
  api_url: string
  enabled: boolean
  status?: string
}
const mbBindings = ref<MatterbridgeBinding[]>([])
const mbLoading = ref(false)

// Discord state
interface DiscordBinding {
  id: string
  world_id: string
  guild_id: string
  channel_id: string
}
const dcBindings = ref<DiscordBinding[]>([])
const dcLoading = ref(false)

async function detectPlatform() {
  loading.value = true
  try {
    await client.get('/api/matterbridge/status')
    platformMode.value = 'matterbridge'
  } catch {
    platformMode.value = 'none'
  } finally {
    loading.value = false
  }
}

async function loadBindings() {
  if (platformMode.value === 'matterbridge') {
    await loadMatterbridgeBindings()
  } else if (platformMode.value === 'discord') {
    await loadDiscordBindings()
  }
}

async function loadMatterbridgeBindings() {
  mbLoading.value = true
  try {
    const { data: worlds } = await client.get('/api/worlds')
    const allBindings: MatterbridgeBinding[] = []
    for (const world of worlds) {
      try {
        const { data } = await client.get(`/api/worlds/${world.id}/matterbridge`)
        if (data.bindings) {
          allBindings.push(...data.bindings.map((b: any) => ({ ...b, world_id: world.id })))
        }
      } catch {
        // No bindings for this world
      }
    }
    mbBindings.value = allBindings
  } catch (e: any) {
    message.error(parseApiError(e, t))
  } finally {
    mbLoading.value = false
  }
}

async function loadDiscordBindings() {
  dcLoading.value = true
  try {
    const { data: worlds } = await client.get('/api/worlds')
    const allBindings: DiscordBinding[] = []
    for (const world of worlds) {
      try {
        const { data } = await client.get(`/api/worlds/${world.id}/discord-binding`)
        if (data.bindings) {
          allBindings.push(...data.bindings.map((b: any) => ({ ...b, world_id: world.id })))
        }
      } catch {
        // No bindings for this world
      }
    }
    dcBindings.value = allBindings
  } catch (e: any) {
    message.error(parseApiError(e, t))
  } finally {
    dcLoading.value = false
  }
}

onMounted(async () => {
  await detectPlatform()
  await loadBindings()
})
</script>

<template>
  <div class="platform-tab">
    <div v-if="loading" class="loading-text">{{ t('admin.platform.detecting') }}</div>

    <div v-else-if="platformMode === 'none'" class="empty-state">
      <p>{{ t('admin.platform.noConfig') }}</p>
      <p class="hint">{{ t('admin.platform.noConfigHint') }}</p>
    </div>

    <!-- Matterbridge Panel -->
    <template v-else-if="platformMode === 'matterbridge'">
      <div class="mode-badge">
        <NTag type="success" size="small">{{ t('admin.platform.matterbridgeMode') }}</NTag>
        <span class="mode-hint">{{ t('admin.platform.matterbridgeHint') }}</span>
      </div>

      <div v-if="mbLoading" class="loading-text">{{ t('admin.platform.loadingBindings') }}</div>

      <div v-else-if="mbBindings.length === 0" class="empty-state">
        <p>{{ t('admin.platform.noMatterbridgeBindings') }}</p>
      </div>

      <div v-else class="binding-list">
        <div v-for="binding in mbBindings" :key="binding.id" class="binding-card">
          <div class="binding-info">
            <span class="binding-world">{{ t('admin.platform.worldLabel', { id: binding.world_id }) }}</span>
            <span class="binding-url">{{ binding.api_url }}</span>
          </div>
          <div class="binding-status">
            <NTag :type="binding.enabled ? 'success' : 'default'" size="small">
              {{ binding.enabled ? t('admin.platform.enabled') : t('admin.platform.disabled') }}
            </NTag>
          </div>
        </div>
      </div>
    </template>

    <!-- Discord Bot Panel -->
    <template v-else-if="platformMode === 'discord'">
      <div class="mode-badge">
        <NTag type="info" size="small">{{ t('admin.platform.discordMode') }}</NTag>
        <span class="mode-hint">{{ t('admin.platform.discordHint') }}</span>
      </div>

      <div v-if="dcLoading" class="loading-text">{{ t('admin.platform.loadingBindings') }}</div>

      <div v-else-if="dcBindings.length === 0" class="empty-state">
        <p>{{ t('admin.platform.noDiscordBindings') }}</p>
      </div>

      <div v-else class="binding-list">
        <div v-for="binding in dcBindings" :key="binding.id" class="binding-card">
          <div class="binding-info">
            <span class="binding-world">{{ t('admin.platform.worldLabel', { id: binding.world_id }) }}</span>
            <span class="binding-guild">{{ t('admin.platform.serverLabel', { id: binding.guild_id }) }}</span>
            <span class="binding-channel">{{ t('admin.platform.channelLabel', { id: binding.channel_id }) }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.platform-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.mode-badge {
  display: flex;
  align-items: center;
  gap: 12px;
}
.mode-hint {
  font-size: 13px;
  color: var(--text-muted);
}
.loading-text {
  text-align: center;
  color: var(--text-muted);
  padding: 20px 0;
}
.empty-state {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 0;
}
.empty-state .hint {
  font-size: 12px;
  margin-top: 8px;
}
.binding-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.binding-card {
  background: var(--bg-card);
  border-radius: var(--radius-md, 8px);
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.binding-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.binding-world, .binding-url, .binding-guild, .binding-channel {
  font-size: 13px;
  color: var(--text-secondary);
}
.binding-url {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}
</style>
