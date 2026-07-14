<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NModal, NCard, NButton, NSpin, NEmpty } from 'naive-ui'
import { getWikiPreview } from '@/api/worlds'
import { parseApiError } from '@/utils/apiError'

const props = defineProps<{
  visible: boolean
  url: string | null
  pageTitle?: string | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const { t } = useI18n()

// 同一次弹窗组件生命周期内缓存已抓取的全文，避免重复请求同一 URL
const cache = new Map<string, { content: string; truncated: boolean }>()

const loading = ref(false)
const errorMsg = ref<string | null>(null)
const content = ref('')
const truncated = ref(false)

async function load(url: string) {
  const cached = cache.get(url)
  if (cached) {
    content.value = cached.content
    truncated.value = cached.truncated
    errorMsg.value = null
    loading.value = false
    return
  }
  loading.value = true
  errorMsg.value = null
  try {
    const result = await getWikiPreview(url)
    cache.set(url, result)
    content.value = result.content
    truncated.value = result.truncated
  } catch (e) {
    errorMsg.value = parseApiError(e, t)
  } finally {
    loading.value = false
  }
}

function retry() {
  if (props.url) void load(props.url)
}

watch(
  () => [props.visible, props.url] as const,
  ([visible, url]) => {
    if (visible && url) {
      void load(url)
    }
  },
  { immediate: true },
)

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <NModal :show="visible" @update:show="(v: boolean) => emit('update:visible', v)">
    <NCard
      style="width: 640px; max-width: 90vw;"
      :title="pageTitle || t('createWorld.wikiPreviewTitle')"
      :bordered="false"
      closable
      @close="close"
    >
      <div v-if="loading" class="wiki-preview-loading">
        <NSpin size="medium" />
        <p class="wiki-preview-loading-text">{{ t('createWorld.wikiPreviewLoading') }}</p>
      </div>
      <div v-else-if="errorMsg" class="wiki-preview-error">
        <NEmpty :description="errorMsg" />
        <NButton type="primary" size="small" @click="retry">
          {{ t('createWorld.wikiPreviewRetry') }}
        </NButton>
      </div>
      <div v-else class="wiki-preview-body">
        <p v-if="truncated" class="wiki-preview-truncated-hint">
          {{ t('createWorld.wikiPreviewTruncatedHint') }}
        </p>
        <div class="wiki-preview-content">{{ content }}</div>
      </div>
    </NCard>
  </NModal>
</template>

<style scoped>
:deep(.n-card) {
  border: none;
  border-radius: var(--radius);
}

.wiki-preview-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 0;
}

.wiki-preview-loading-text {
  color: var(--text-muted);
  font-size: 13px;
  margin: 0;
}

.wiki-preview-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 20px 0;
}

.wiki-preview-truncated-hint {
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-card-hover);
  border-radius: 6px;
  padding: 6px 10px;
  margin: 0 0 12px;
}

.wiki-preview-content {
  max-height: 60vh;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
}
</style>
