<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NModal, NCard, NForm, NInput, NButton, NSpace, NTag, NSelect,
  NAlert, useMessage,
} from 'naive-ui'
import type {
  GraphPreviewResponse,
  ImportCharacterPreview,
  ImportRelationPreview,
  ImportCharacterReq,
  ImportRelationReq,
} from '@/api/importApi'
import { previewGraphImport, confirmGraphImport } from '@/api/importApi'
import { parseApiError } from '@/utils/apiError'
import { extractPromptSection, extractJsonBlocks } from '@/utils/importPrompt'
import graphMd from '@docs/import-prompts/graph-characters-relations.md?raw'
import GraphImportCharRow from './GraphImportCharRow.vue'
import GraphImportRelRow from './GraphImportRelRow.vue'

const props = defineProps<{
  show: boolean
  worldId: string
  worldName?: string
  onSuccess: () => void
}>()

const emit = defineEmits<{ 'update:show': [value: boolean] }>()

const { t, locale } = useI18n()
const messageApi = useMessage()

const promptTemplate = computed(() => extractPromptSection(graphMd, locale.value))

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

const jsonInput = ref('')
const loading = ref(false)
const parsingError = ref<string | null>(null)

let previewData: GraphPreviewResponse | null = null
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

    if (blocks.length === 0) {
      // Try the whole text as a single object
      blocks.push(raw)
    }

    // Parse characters and relations
    const allChars: ImportCharacterReq[] = []
    const allRels: ImportRelationReq[] = []

    for (const block of blocks) {
      const parsed = JSON.parse(block)

      // Try as a single character
      if (parsed.name && (parsed.brief !== undefined || parsed.detail !== undefined)) {
        allChars.push({
          name: parsed.name,
          tier: parsed.tier || 'extra',
          brief: parsed.brief || '',
          detail: parsed.detail || '',
          personality: parsed.personality || '',
          speech_style: parsed.speech_style || '',
        })
        continue
      }

      // Try as a single relation
      if (parsed.character_a && parsed.character_b) {
        allRels.push({
          character_a: parsed.character_a,
          character_b: parsed.character_b,
          type: parsed.type || null,
          description: parsed.description || null,
          direction: parsed.direction || 'bidirectional',
        })
        continue
      }

      // Try as a list of characters
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          if (item.name && (item.brief !== undefined || item.detail !== undefined)) {
            allChars.push({
              name: item.name,
              tier: item.tier || 'extra',
              brief: item.brief || '',
              detail: item.detail || '',
              personality: item.personality || '',
              speech_style: item.speech_style || '',
            })
          } else if (item.character_a && item.character_b) {
            allRels.push({
              character_a: item.character_a,
              character_b: item.character_b,
              type: item.type || null,
              description: item.description || null,
              direction: item.direction || 'bidirectional',
            })
          }
        }
        continue
      }

      // Try as an object with characters/relations keys
      if (parsed.characters && Array.isArray(parsed.characters)) {
        for (const item of parsed.characters) {
          allChars.push({
            name: item.name,
            tier: item.tier || 'extra',
            brief: item.brief || '',
            detail: item.detail || '',
            personality: item.personality || '',
            speech_style: item.speech_style || '',
          })
        }
      }
      if (parsed.relations && Array.isArray(parsed.relations)) {
        for (const item of parsed.relations) {
          allRels.push({
            character_a: item.character_a,
            character_b: item.character_b,
            type: item.type || null,
            description: item.description || null,
            direction: item.direction || 'bidirectional',
          })
        }
      }
      if (parsed.chars && Array.isArray(parsed.chars)) {
        for (const item of parsed.chars) {
          allChars.push({
            name: item.name,
            tier: item.tier || 'extra',
            brief: item.brief || '',
            detail: item.detail || '',
            personality: item.personality || '',
            speech_style: item.speech_style || '',
          })
        }
      }
    }

    if (allChars.length === 0 && allRels.length === 0) {
      parsingError.value = t('import.graphParseEmpty')
      return
    }

    // Preview
    previewData = await previewGraphImport(props.worldId, allChars, allRels)
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
    const chars: ImportCharacterReq[] = []
    const rels: ImportRelationReq[] = []

    for (const cp of previewData.characters) {
      chars.push({
        name: cp.name,
        tier: cp.tier,
        brief: cp.brief,
        detail: cp.detail,
        personality: cp.personality,
        speech_style: cp.speech_style,
      })
    }
    for (const rp of previewData.relations) {
      if (rp.status === 'valid' || rp.status === 'update') {
        rels.push({
          character_a: rp.character_a,
          character_b: rp.character_b,
          type: rp.type,
          description: rp.description,
          direction: rp.direction,
        })
      }
    }

    const result = await confirmGraphImport(props.worldId, chars, rels)
    messageApi.success(t('import.graphSuccess', result))
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
    :title="$t('import.graphTitle')"
    style="width: 720px; max-height: 85vh"
    :closable="!loading"
  >
    <!-- Step 1: Paste JSON -->
    <div v-if="!showingPreview">
      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 12px;">
        <p style="font-size: 13px; color: var(--text-tertiary); margin: 0;">
          {{ $t('import.graphHint') }}
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
    <div v-else class="graph-import-preview">
      <!-- Summary -->
      <NSpace style="margin-bottom: 12px; flex-shrink: 0;" :size="12">
        <NTag type="success">{{ $t('import.new') }}: {{ previewData?.new_characters ?? 0 }}</NTag>
        <NTag type="warning">{{ $t('import.existing') }}: {{ previewData?.existing_characters ?? 0 }}</NTag>
        <NTag type="success">{{ $t('import.newRelations') }}: {{ previewData?.valid_relations ?? 0 }}</NTag>
        <NTag v-if="(previewData?.updated_relations ?? 0) > 0" type="warning">{{ $t('import.updatedRelations') }}: {{ previewData?.updated_relations ?? 0 }}</NTag>
        <NTag v-if="(previewData?.skipped_relations ?? 0) > 0" type="error">{{ $t('import.skippedRelations') }}: {{ previewData?.skipped_relations ?? 0 }}</NTag>
      </NSpace>

      <div class="graph-import-preview__scroll">
        <!-- Characters preview -->
        <div style="margin-bottom: 12px;">
          <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px;">
            {{ $t('import.characters') }} ({{ previewData?.characters?.length ?? 0 }})
          </div>
          <GraphImportCharRow
            v-for="char in previewData?.characters"
            :key="char.index"
            :char="char"
          />
        </div>

        <!-- Relations preview -->
        <div v-if="previewData?.relations?.length" style="margin-bottom: 12px;">
          <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px;">
            {{ $t('import.relations') }} ({{ previewData?.relations?.length ?? 0 }})
          </div>
          <GraphImportRelRow
            v-for="rel in previewData?.relations"
            :key="rel.character_a + rel.character_b"
            :rel="rel"
          />
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
.graph-import-preview {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-height: 55vh;
}

.graph-import-preview__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
