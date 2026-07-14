<script setup lang="ts">
import { reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NInputNumber, NTag, useMessage, useDialog } from 'naive-ui'
import { parseApiError } from '@/utils/apiError'
import {
  getConfigGroup,
  updateConfigGroup,
  resetConfigGroup,
  type AdminConfigItem,
} from '@/api/adminConfig'

const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()

interface GroupState {
  items: AdminConfigItem[]
  form: Record<string, any>
  loading: boolean
  saving: boolean
  resetting: boolean
}

const groups = reactive<Record<string, GroupState>>({
  llm: { items: [], form: {}, loading: false, saving: false, resetting: false },
  sub_llm: { items: [], form: {}, loading: false, saving: false, resetting: false },
  embedding: { items: [], form: {}, loading: false, saving: false, resetting: false },
  rerank: { items: [], form: {}, loading: false, saving: false, resetting: false },
})

const GROUP_LABELS: Record<string, string> = {
  llm: t('admin.config.groupMain'),
  sub_llm: t('admin.config.groupSub'),
  embedding: t('admin.config.groupEmbedding'),
  rerank: t('admin.config.groupRerank'),
}

const FIELD_LABELS: Record<string, string> = {
  provider: 'Provider',
  api_key: 'API Key',
  model: 'Model',
  base_url: 'Base URL',
  api_format: 'API Format',
  rpm: t('admin.config.fieldRpm'),
  max_inflight: t('admin.config.fieldMaxInflight'),
  max_retries: t('admin.config.fieldMaxRetries'),
  dim: t('admin.config.fieldDim'),
}

const INT_FIELDS = new Set(['rpm', 'max_inflight', 'max_retries', 'dim'])

async function loadGroup(group: string) {
  const state = groups[group]
  state.loading = true
  try {
    const data = await getConfigGroup(group)
    state.items = data.items
    // Initialize form with current values
    state.form = {}
    for (const item of data.items) {
      state.form[item.key] = item.source === 'override'
        ? (INT_FIELDS.has(item.key) ? null : '')
        : (INT_FIELDS.has(item.key) ? Number(item.value) : item.value)
    }
  } catch (e: any) {
    message.error(parseApiError(e, t))
  } finally {
    state.loading = false
  }
}

async function saveGroup(group: string) {
  const state = groups[group]
  state.saving = true
  try {
    // Only send non-empty values, convert to string for API
    const values: Record<string, string> = {}
    for (const [key, val] of Object.entries(state.form)) {
      if (val !== '' && val !== null && val !== undefined) {
        values[key] = String(val)
      }
    }
    if (Object.keys(values).length === 0) {
      message.warning(t('admin.config.fillAtLeastOne'))
      return
    }
    const data = await updateConfigGroup(group, values)
    state.items = data.items
    // Clear form after save
    state.form = {}
    for (const item of data.items) {
      state.form[item.key] = INT_FIELDS.has(item.key) ? null : ''
    }
    message.success(t('admin.config.saveSuccess'))
  } catch (e: any) {
    message.error(parseApiError(e, t))
  } finally {
    state.saving = false
  }
}

async function resetGroup(group: string) {
  const state = groups[group]
  dialog.warning({
    title: t('admin.config.resetTitle'),
    content: t('admin.config.resetConfirm', { group: GROUP_LABELS[group] }),
    positiveText: t('common.confirm'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      state.resetting = true
      try {
        const data = await resetConfigGroup(group)
        state.items = data.items
        state.form = {}
        for (const item of data.items) {
          state.form[item.key] = INT_FIELDS.has(item.key) ? null : ''
        }
        message.success(t('admin.config.resetSuccess'))
      } catch (e: any) {
        message.error(parseApiError(e, t))
      } finally {
        state.resetting = false
      }
    },
  })
}

onMounted(() => {
  loadGroup('llm')
  loadGroup('sub_llm')
  loadGroup('embedding')
  loadGroup('rerank')
})
</script>

<template>
  <div class="model-config-tab">
    <div v-for="groupKey in ['llm', 'sub_llm', 'embedding', 'rerank']" :key="groupKey" class="config-section">
      <div class="section-header">
        <h3 class="section-title">{{ GROUP_LABELS[groupKey] }}</h3>
        <div class="section-actions">
          <NButton
            size="small"
            type="error"
            :loading="groups[groupKey].resetting"
            @click="resetGroup(groupKey)"
          >
            {{ t('admin.config.resetDefault') }}
          </NButton>
          <NButton
            size="small"
            type="primary"
            :loading="groups[groupKey].saving"
            @click="saveGroup(groupKey)"
          >
            {{ t('admin.config.save') }}
          </NButton>
        </div>
      </div>

      <div v-if="groups[groupKey].loading" class="loading-text">{{ t('admin.config.loading') }}</div>

      <div v-else class="config-fields">
        <div v-for="item in groups[groupKey].items" :key="item.key" class="config-field">
          <div class="field-header">
            <label class="field-label">{{ FIELD_LABELS[item.key] || item.key }}</label>
            <NTag v-if="item.source === 'override'" type="success" size="small">{{ t('admin.config.overridden') }}</NTag>
            <NTag v-else type="default" size="small">{{ t('admin.config.envVar') }}</NTag>
          </div>
          <div class="field-input">
            <NInputNumber
              v-if="INT_FIELDS.has(item.key)"
              v-model:value="groups[groupKey].form[item.key]"
              :placeholder="item.source === 'override' ? item.value : `${t('admin.config.current')}: ${item.value || '(' + t('admin.config.empty') + ')'}`"
              size="small"
              :min="0"
              style="width: 100%"
            />
            <NInput
              v-else
              v-model:value="groups[groupKey].form[item.key]"
              :placeholder="item.source === 'override' ? item.value : `${t('admin.config.current')}: ${item.value || '(' + t('admin.config.empty') + ')'}`"
              :type="item.key.includes('key') || item.key.includes('secret') ? 'password' : 'text'"
              show-password-on="click"
              size="small"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.model-config-tab {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.config-section {
  background: var(--bg-card);
  border-radius: var(--radius-md, 8px);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.section-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}
.section-actions {
  display: flex;
  gap: 8px;
}
.loading-text {
  text-align: center;
  color: var(--text-muted);
  padding: 20px 0;
}
.config-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.config-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.field-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
.field-input {
  max-width: 400px;
}
</style>
