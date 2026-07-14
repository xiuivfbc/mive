<template>
  <NModal v-model:show="visible" preset="card" :title="t('quoteModal.title')" style="width: 420px;">
    <NTabs type="line" default-value="write">
      <NTabPane name="write" :tab="t('quoteModal.writeTab')">
        <div v-if="!eligible" class="gate-hint">
          {{ t('quoteModal.noPermission') }}
        </div>
        <template v-else>
          <NInput
            v-model:value="content"
            type="textarea"
            :maxlength="40"
            :placeholder="t('quoteModal.placeholder')"
            show-count
            :disabled="submitting"
          />
          <div v-if="auditResult" class="audit-result" :class="auditResult.approved ? 'approved' : 'rejected'">
            {{ auditResult.approved ? t('quoteModal.approved') : t('quoteModal.rejected') }}
            <span v-if="auditResult.reason">{{ t('quoteModal.rejectedReason', { reason: auditResult.reason }) }}</span>
          </div>
          <NButton
            type="primary"
            block
            :loading="submitting"
            :disabled="!content.trim()"
            @click="submit"
            style="margin-top: 12px;"
          >
            {{ t('quoteModal.submit') }}
          </NButton>
        </template>
      </NTabPane>
      <NTabPane name="my" :tab="t('quoteModal.myTab')">
        <NEmpty v-if="myQuotes.length === 0" :description="t('quoteModal.empty')" />
        <div v-for="q in myQuotes" :key="q.id" class="my-quote-item">
          <div class="my-quote-content">{{ q.content }}</div>
          <div class="my-quote-meta">
            <NTag :type="statusTagType(q.status)" size="small">{{ q.status }}</NTag>
            <NButton text type="error" size="small" @click="remove(q.id)">{{ t('quoteModal.delete') }}</NButton>
          </div>
          <div v-if="q.ai_reason" class="my-quote-reason">{{ q.ai_reason }}</div>
        </div>
      </NTabPane>
    </NTabs>
  </NModal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NModal, NTabs, NTabPane, NInput, NButton, NTag, NEmpty, useMessage } from 'naive-ui'
import {
  createWelcomeQuote,
  getMyQuotes,
  deleteWelcomeQuote,
  checkEligibility,
  type WelcomeQuote
} from '../api/welcomeQuotes'

const { t } = useI18n()
const message = useMessage()

const visible = defineModel<boolean>('show', { default: false })
const content = ref('')
const submitting = ref(false)
const eligible = ref(false)
const myQuotes = ref<WelcomeQuote[]>([])
const auditResult = ref<{ approved: boolean; reason?: string } | null>(null)

watch(visible, async (v) => {
  if (v) {
    auditResult.value = null
    content.value = ''
    try {
      const [elig, quotes] = await Promise.all([checkEligibility(), getMyQuotes()])
      eligible.value = elig.eligible
      myQuotes.value = quotes
    } catch { /* ignore */ }
  }
})

async function submit() {
  if (!content.value.trim()) return
  submitting.value = true
  auditResult.value = null
  try {
    const result = await createWelcomeQuote(content.value.trim())
    auditResult.value = { approved: result.status === 'approved', reason: result.ai_reason || undefined }
    if (result.status === 'approved') {
      message.success(t('quoteModal.approved'))
    }
    const quotes = await getMyQuotes()
    myQuotes.value = quotes
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

async function remove(id: string) {
  try {
    await deleteWelcomeQuote(id)
    myQuotes.value = myQuotes.value.filter(q => q.id !== id)
    message.success(t('quoteModal.deleted'))
  } catch { message.error('删除失败') }
}

function statusTagType(status: string) {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'error'
  return 'warning'
}
</script>

<style scoped>
.gate-hint {
  text-align: center;
  color: rgba(200, 180, 255, 0.6);
  padding: 24px 0;
  font-size: 0.9rem;
}
.audit-result {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
}
.audit-result.approved {
  background: rgba(100, 220, 140, 0.1);
  color: #64dc8c;
}
.audit-result.rejected {
  background: rgba(255, 100, 100, 0.1);
  color: #ff8888;
}
.my-quote-item {
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.my-quote-content {
  font-size: 0.9rem;
  color: rgba(200, 180, 255, 0.85);
}
.my-quote-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 4px;
}
.my-quote-reason {
  font-size: 0.75rem;
  color: rgba(255, 100, 100, 0.6);
  margin-top: 2px;
}
</style>
