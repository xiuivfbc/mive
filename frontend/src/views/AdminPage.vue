<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NButton, NTabs, NTabPane } from 'naive-ui'
import ModelConfigTab from '@/components/admin/ModelConfigTab.vue'
import PlatformTab from '@/components/admin/PlatformTab.vue'

const router = useRouter()
const { t } = useI18n()

// Tab
const activeTab = ref<'models' | 'platform'>('models')
</script>

<template>
  <div class="admin-page">
    <div class="admin-header">
      <NButton @click="router.push('/worlds')" quaternary>
        <template #icon>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8l4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </template>
        {{ t('common.back', '返回') }}
      </NButton>
      <h1>{{ t('admin.title', '管理后台') }}</h1>
    </div>

    <NTabs v-model:value="activeTab" type="line" animated>
      <NTabPane name="models" :tab="t('admin.modelsTab', '模型配置')">
        <div class="tab-content">
          <ModelConfigTab />
        </div>
      </NTabPane>

      <NTabPane name="platform" :tab="t('admin.platformTab', '平台设置')">
        <div class="tab-content">
          <PlatformTab />
        </div>
      </NTabPane>
    </NTabs>
  </div>
</template>

<style scoped>
.admin-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.admin-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.admin-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
}

.tab-content {
  padding: 16px 0;
}
</style>
