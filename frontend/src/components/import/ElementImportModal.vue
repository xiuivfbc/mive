<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NModal, NInput, NButton, NSpace, NTag, NAlert, useMessage,
} from 'naive-ui'
import type {
  ElementsPreviewResponse,
  ImportElementPreview,
  ImportElementReq,
} from '@/api/importApi'
import { previewElementsImport, confirmElementsImport } from '@/api/importApi'
import { parseApiError } from '@/utils/apiError'
import { extractPromptSection, extractJsonBlocks } from '@/utils/importPrompt'
import elementsMd from '@docs/import-prompts/elements.md?raw'
import ElementImportRow from './ElementImportRow.vue'

const props = defineProps<{
  show: boolean
  worldId: string
  worldName?: string
  onSuccess: () => void
}>()

const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const { t, locale } = useI18n()
const messageApi = useMessage()

const promptTemplate = computed(() => extractPromptSection(elementsMd, locale.value))

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

let previewData: ElementsPreviewResponse | null = null
const showingPreview = ref(false)

function resetState() {
  jsonInput.value = ''
  parsingError.value = null
  previewData = null
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
    const raw = jsonInput.value.trim()
    const blocks = extractJsonBlocks(raw)
    if (blocks.length === 0) blocks.push(raw)

    const allElements: ImportElementReq[] = []

    for (const block of blocks) {
      const parsed = JSON.parse(block)

      // Try as a single element
      if (parsed.name && parsed.brief !== undefined) {
        allElements.push({
          name: parsed.name,
          category: parsed.category || '',
          brief: parsed.brief || '',
          detail: parsed.detail || '',
        })
        continue
      }

      // Try as an array of elements
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          if (item.name && item.brief !== undefined) {
            allElements.push({
              name: item.name,
              category: item.category || '',
              brief: item.brief || '',
              detail: item.detail || '',
            })
          }
        }
        continue
      }

      // Try as an object with elements key
      if (parsed.elements && Array.isArray(parsed.elements)) {
        for (const item of parsed.elements) {
          if (item.name && item.brief !== undefined) {
            allElements.push({
              name: item.name,
              category: item.category || '',
              brief: item.brief || '',
              detail: item.detail || '',
            })
          }
        }
      }

      // Also try "items" key
      if (parsed.items && Array.isArray(parsed.items)) {
        for (const item of parsed.items) {
          if (item.name && item.brief !== undefined) {
            allElements.push({
              name: item.name,
              category: item.category || '',
              brief: item.brief || '',
              detail: item.detail || '',
            })
          }
        }
      }
    }

    if (allElements.length === 0) {
      parsingError.value = t('import.elementParseEmpty')
      return
    }

    // Preview
    previewData = await previewElementsImport(props.worldId, allElements)
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
    const elements: ImportElementReq[] = []
    for (const ep of previewData.elements) {
      elements.push({
        name: ep.name,
        category: ep.category,
        brief: ep.brief,
        detail: ep.detail,
      })
    }

    await confirmElementsImport(props.worldId, elements)
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
</script>

<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    :mask-closable="!loading"
    preset="card"
    :title="$t('import.elementTitle')"
    style="width: 640px; max-height: 85vh"
    :closable="!loading"
  >
    <!-- Step 1: Paste JSON -->
    <div v-if="!showingPreview">
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 12px;">
        <p style="font-size: 13px; color: var(--text-tertiary); margin: 0;">
          {{ $t('import.elementHint') }}
        </p>
        <NButton size="tiny" quaternary @click="copyPrompt">{{ $t('import.copyPrompt') }}</NButton>
      </div>
      <NFormItem>
        <NInput
          v-model:value="jsonInput"
          type="textarea"
          :rows="10"
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
      <NSpace style="margin-bottom: 12px;" :size="12">
        <NTag type="success">{{ $t('import.new') }}: {{ previewData?.new_elements ?? 0 }}</NTag>
        <NTag type="warning">{{ $t('import.existing') }}: {{ previewData?.existing_elements ?? 0 }}</NTag>
      </NSpace>

      <div style="margin-bottom: 12px;">
        <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px;">
          {{ $t('import.elements') }} ({{ previewData?.elements?.length ?? 0 }})
        </div>
        <ElementImportRow
          v-for="el in previewData?.elements"
          :key="el.name"
          :el="el"
        />
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
