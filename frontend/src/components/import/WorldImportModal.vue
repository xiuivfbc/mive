<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NModal, NCard, NForm, NFormItem, NInput, NButton, NSpace, NTag, NSelect,
  NRadioGroup, NRadio, NAlert, useMessage,
} from 'naive-ui'
import type { WorldFieldsPreviewResponse, ImportCharacterReq, ImportRelationReq } from '@/api/importApi'
import { previewWorldFields, confirmWorldFields } from '@/api/importApi'
import { parseApiError } from '@/utils/apiError'
import { extractPromptSection, extractFirstJsonBlock } from '@/utils/importPrompt'
import worldFieldsMd from '@docs/import-prompts/world-fields.md?raw'

const props = defineProps<{
  show: boolean
  worldId: string
  worldName?: string
  onSuccess: () => void
}>()

const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const { t, locale } = useI18n()
const messageApi = useMessage()

const promptTemplate = computed(() => extractPromptSection(worldFieldsMd, locale.value))

function copyPrompt() {
  let text = promptTemplate.value
  if (props.worldName) {
    text = text
      .replace(/\{输入你想要的作品名称\}/g, props.worldName)
      .replace(/\{input the name of the work\}/g, props.worldName)
  }
  navigator.clipboard.writeText(text)
  messageApi.success(t('common.copied'))
}

const jsonInput = ref('')
const loading = ref(false)
const parsingError = ref<string | null>(null)

function copyErrorPrompt() {
  let base = promptTemplate.value
  if (props.worldName) {
    base = base
      .replace(/\{输入你想要的作品名称\}/g, props.worldName)
      .replace(/\{input the name of the work\}/g, props.worldName)
  }
  const text = [
    base,
    '',
    '---',
    '',
    '## 错误信息',
    '',
    `> **${parsingError.value}**`,
    '',
    '## 需要修复的输入',
    '',
    '```json',
    jsonInput.value,
    '```',
    '',
    '---',
    '',
    '请参考上面的格式要求，帮我修复上述 JSON 数据中的错误。',
  ].join('\n')
  navigator.clipboard.writeText(text)
  messageApi.success(t('common.copied'))
}

// Preview state
let previewData: WorldFieldsPreviewResponse | null = null
const fieldStrategies = ref<Record<string, string>>({})
const showingPreview = ref(false)

// Valid field keys
const FIELD_KEYS = ['plot_summary', 'common_sense', 'core_conflict', 'tone_and_atmosphere', 'plot_development'] as const
const FIELD_LABELS: Record<string, string> = {
  plot_summary: 'worldDetail.worldDescription',
  common_sense: 'worldDetail.commonSense',
  core_conflict: 'worldDetail.coreConflict',
  tone_and_atmosphere: 'worldDetail.toneAndAtmosphere',
  plot_development: 'worldDetail.plotDevelopment',
}

function resetState() {
  jsonInput.value = ''
  parsingError.value = null
  previewData = null
  fieldStrategies.value = {}
  showingPreview.value = false
}

watch(() => props.show, (v) => {
  if (v) resetState()
})

async function handleParse() {
  if (!jsonInput.value.trim()) {
    parsingError.value = t('import.parseEmpty')
    return
  }
  loading.value = true
  parsingError.value = null
  try {
    const rawData = extractFirstJsonBlock(jsonInput.value)
    const parsed = JSON.parse(rawData)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      parsingError.value = t('import.parseInvalid')
      return
    }

    // Filter to valid field keys
    const filteredData: Record<string, string> = {}
    const strategies: Record<string, string> = {}
    for (const key of FIELD_KEYS) {
      const val = parsed[key]
      if (val === undefined || val === null) continue
      if (typeof val === 'string') {
        filteredData[key] = val
      } else if (Array.isArray(val)) {
        filteredData[key] = val.join('\n')
      } else if (typeof val === 'number' || typeof val === 'boolean') {
        filteredData[key] = String(val)
      } else {
        continue
      }
      strategies[key] = 'overwrite'
    }

    if (Object.keys(filteredData).length === 0) {
      parsingError.value = t('import.parseNoFields')
      return
    }

    // Preview
    previewData = await previewWorldFields(props.worldId, filteredData, strategies)
    fieldStrategies.value = strategies
    showingPreview.value = true
  } catch (e: unknown) {
    parsingError.value = t('import.parseSyntax')
    console.error('JSON parse failed:', e)
  } finally {
    loading.value = false
  }
}

async function handleConfirm() {
  if (!previewData || !showingPreview.value) return
  loading.value = true
  try {
    const data: Record<string, string> = {}
    const strategies: Record<string, string> = {}
    for (const [key, entry] of Object.entries(previewData.world_fields ?? {})) {
      const strategy = fieldStrategies.value[key] ?? 'overwrite'
      if (strategy === 'skip') continue
      data[key] = entry.merged
      strategies[key] = strategy
    }
    await confirmWorldFields(props.worldId, data, strategies)
    messageApi.success(t('import.success'))
    emit('update:show', false)
    props.onSuccess()
  } catch (e: unknown) {
    messageApi.error(parseApiError(e, t))
  } finally {
    loading.value = false
  }
}

function handleCancel() {
  showingPreview.value = false
  previewData = null
}

function getStrategyLabel(s: string): string {
  return s === 'overwrite' ? t('import.overwrite') : s === 'append' ? t('import.append') : t('common.cancel')
}
</script>

<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    :mask-closable="!loading"
    preset="card"
    :title="$t('import.worldTitle')"
    style="width: 640px"
    :closable="!loading"
  >
    <!-- Step 1: Paste JSON -->
    <div v-if="!showingPreview">
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 12px;">
        <p style="font-size: 13px; color: var(--text-tertiary); margin: 0;">
          {{ $t('import.worldHint') }}
        </p>
        <NButton size="tiny" quaternary @click="copyPrompt">{{ $t('import.copyPrompt') }}</NButton>
      </div>
      <NFormItem>
        <NInput
          v-model:value="jsonInput"
          type="textarea"
          :rows="8"
          :placeholder="$t('import.jsonPlaceholder')"
          :disabled="loading"
        />
      </NFormItem>
      <div v-if="parsingError" style="margin-top: 8px;">
        <NAlert type="error" style="margin-bottom: 8px;">{{ parsingError }}</NAlert>
        <div style="display: flex; justify-content: flex-end;">
          <NButton size="small" secondary @click="copyErrorPrompt">
            {{ $t('import.copyErrorPrompt') }}
          </NButton>
        </div>
      </div>
    </div>

    <!-- Step 2: Preview & Confirm -->
    <div v-else>
      <div v-for="(entry, key) in previewData?.world_fields ?? {}" :key="key" style="margin-bottom: 16px;">
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 4px;">
          <div style="display: flex; align-items: center;">{{ $t(FIELD_LABELS[key] ?? key) }}</div>
          <NSelect
            class="world-import-strategy-select"
            :value="fieldStrategies[key]"
            :options="[
              { label: $t('import.overwrite'), value: 'overwrite' },
              { label: $t('import.append'), value: 'append' },
              { label: $t('import.skip'), value: 'skip' },
            ]"
            size="small"
            @update:value="(v: string) => fieldStrategies[key] = v"
          />
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 12px;">
          <div>
            <div style="color: var(--text-tertiary);">{{ $t('import.oldValue') }}</div>
            <div style="background: var(--bg-secondary); padding: 6px 8px; border-radius: 4px; max-height: 60px; overflow: auto; white-space: pre-wrap;">
              {{ entry.old || '—' }}
            </div>
          </div>
          <div>
            <div style="color: var(--text-tertiary);">{{ $t('import.newValue') }}</div>
            <div style="background: var(--bg-secondary); padding: 6px 8px; border-radius: 4px; max-height: 60px; overflow: auto; white-space: pre-wrap;">
              {{ entry.merged || '—' }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Footer: conditional buttons based on step -->
    <template #footer>
      <NSpace v-if="!showingPreview" justify="end">
        <NButton @click="emit('update:show', false)" :disabled="loading">{{ $t('common.cancel') }}</NButton>
        <NButton type="primary" :loading="loading" :disabled="!jsonInput.trim()" @click="handleParse">
          {{ $t('import.parseButton') }}
        </NButton>
      </NSpace>
      <NSpace v-else justify="end">
        <NButton @click="handleCancel" :disabled="loading">{{ $t('import.backToParse') }}</NButton>
        <NButton type="primary" :loading="loading" @click="handleConfirm">
          {{ $t('import.confirmButton') }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.world-import-strategy-select :deep(.n-base-selection-input__content) {
  justify-content: center;
}
</style>
