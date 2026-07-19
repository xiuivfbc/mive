<script setup lang="ts">
import { ref, watch, h } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { checkWiki, createWorld, getGenerationStatus, getCreationStatus } from '@/api/worlds'
import type { WikiCandidate } from '@/api/worlds'
import { listCharacters } from '@/api/characters'
import type { WorldDoc, CreateWorldRequest } from '@/types/world'
import {
  NModal, NCard, NForm, NFormItem, NInput, NButton, NSelect,
  NCheckbox, NSpace, useMessage, useNotification
} from 'naive-ui'
import { usePoll } from '@/composables/usePoll'
import { useTabNotification } from '@/composables/useTabNotification'
import WikiPreviewModal from './WikiPreviewModal.vue'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  created: [world: WorldDoc]
}>()

const message = useMessage()
const notification = useNotification()
const router = useRouter()
const { t } = useI18n()
const { notifyOnce } = useTabNotification()
const doneNotify = ref<ReturnType<typeof notification.create> | null>(null)
const submitting = ref(false)
const phase = ref<'form' | 'wiki-select' | 'generating'>('form')
const ipDisclaimerAccepted = ref(false)
const ipShake = ref(false)

// wiki-select phase state
const wikiSelectCandidates = ref<WikiCandidate[]>([])
const selectedWikiUrl = ref<string | null>(null)
const manualWikiUrl = ref('')
const manualWikiUrlError = ref(false)
const workLanguage = ref<string | null>(null)
const showAdvanced = ref(false)

// wiki 候选 "查看全文" 预览弹窗状态（与候选确认流程互相独立）
const previewVisible = ref(false)
const previewUrl = ref<string | null>(null)
const previewPageTitle = ref<string | null>(null)

function openWikiPreview(c: WikiCandidate) {
  previewUrl.value = c.url
  previewPageTitle.value = c.page_title
  previewVisible.value = true
}

const workLanguageOptions = [
  { label: '中文', value: 'zh' },
  { label: '日文', value: 'ja' },
  { label: '英文', value: 'en' },
  { label: '韩文', value: 'ko' },
  { label: '法文', value: 'fr' },
  { label: '德文', value: 'de' },
  { label: '西班牙文', value: 'es' },
]

// 角色生成状态
const generatedCount = ref(0)
const expectedMin = ref(5)
const { start: startPoll, stop: stopPoll } = usePoll()

interface Step { key: string; status: 'pending' | 'active' | 'done' }
const steps = ref<Step[]>([
  { key: 'createWorld.stepSearch', status: 'pending' },
  { key: 'createWorld.stepExtract', status: 'pending' },
  { key: 'createWorld.stepGenerate', status: 'pending' },
])

const form = ref<CreateWorldRequest>({
  title: '',
  author: null,
  description: null,
  urls: [],
  scale: 'standard',
})

const EXPECTED_MIN: Record<string, number> = {
  standard: 5,
  detailed: 10,
  deep: 30,
  all: 0,
}

const scaleOptions = [
  { value: 'standard', icon: '\u{1F3C3}', nameKey: 'worldDetail.scaleStandard', descKey: 'createWorld.scaleStandardDesc' },
  { value: 'detailed', icon: '\u{1F4D6}', nameKey: 'worldDetail.scaleDetailed', descKey: 'createWorld.scaleDetailedDesc' },
  { value: 'deep', icon: '\u{1F50D}', nameKey: 'worldDetail.scaleDeep', descKey: 'createWorld.scaleDeepDesc' },
  { value: 'all', icon: '\u{1F30C}', nameKey: 'worldDetail.scaleAll', descKey: 'createWorld.scaleAllDesc' },
]

const urlInputs = ref<string[]>([''])

function addUrl() { urlInputs.value.push('') }
function removeUrl(index: number) { urlInputs.value.splice(index, 1) }

let pollWorldId = ''

function startPollingCharGen(worldId: string) {
  steps.value[2].status = 'active'
  startPoll(
    async () => {
      const { status } = await getGenerationStatus(worldId)
      if (status === 'completed') {
        const characters = await listCharacters(worldId)
        generatedCount.value = characters.length
        steps.value[2].status = 'done'
        doneNotify.value = notification.create({
          type: 'success',
          title: t('createWorld.charGenDoneTitle'),
          content: () => h('span', {}, [
            t('createWorld.charGenSuccess', { n: characters.length }),
            ' ',
            h('a', { href: `/world/${worldId}`, style: { color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer' }, onClick: (e: MouseEvent) => { e.preventDefault(); router.push(`/world/${worldId}`) } }, t('createWorld.goToWorld')),
          ]),
          duration: 0,
          closable: true,
        })
        notifyOnce('world-created', '🌍 世界创建完成')
        registerAutoDestroy()
        emit('created', { world_id: worldId } as WorldDoc)
        phase.value = 'form'
        close()
        return true
      }
      if (status === 'failed') {
        doneNotify.value = notification.create({
          type: 'error',
          title: t('createWorld.charGenFailedTitle'),
          content: () => h('span', {}, [
            t('createWorld.charGenFailed'),
            ' ',
            h('a', { href: `/world/${worldId}`, style: { color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer' }, onClick: (e: MouseEvent) => { e.preventDefault(); router.push(`/world/${worldId}`) } }, t('createWorld.goToWorld')),
          ]),
          duration: 0,
          closable: true,
        })
        notifyOnce('world-char-gen-fail', '❌ 角色生成失败')
        registerAutoDestroy()
        emit('created', { world_id: worldId } as WorldDoc)
        phase.value = 'form'
        close()
        return true
      }
      return false
    },
    5000,
    1800000,
    () => {
      notifyOnce('world-char-gen-timeout', '⏰ 角色生成超时')
      emit('created', { world_id: worldId } as WorldDoc)
      phase.value = 'form'
      close()
    },
  )
}

function startPolling(worldId: string) {
  steps.value[0].status = 'active'

  startPoll(
    async () => {
      const { status } = await getCreationStatus(worldId)
      if (status === 'ready') {
        steps.value[0].status = 'done'
        steps.value[1].status = 'done'
        // 世界内容就绪，后端已自动触发角色生成，前端仅轮询进度
        stopPoll()
        startPollingCharGen(worldId)
        return true
      }
      if (status === 'failed') {
        message.error(t('createWorld.createFailed'))
        notifyOnce('world-create-fail', '❌ 世界创建失败')
        phase.value = 'form'
        submitting.value = false
        return true
      }
      // creating：根据时间推进步骤动画
      if (steps.value[0].status === 'active') {
        // 保持步骤 1 active 直到 ready
      }
      return false
    },
    5000,
    1800000,
    () => {
      // 超时
      notifyOnce('world-create-timeout', '⏰ 世界创建超时')
      emit('created', { world_id: worldId } as WorldDoc)
      phase.value = 'form'
      close()
    },
  )
}


async function handleSubmit() {
  if (!form.value.title.trim()) return
  if (!ipDisclaimerAccepted.value) {
    ipShake.value = false
    void document.body.offsetHeight
    ipShake.value = true
    setTimeout(() => { ipShake.value = false }, 600)
    return
  }

  submitting.value = true
  try {
    const wiki = await checkWiki(form.value.title, form.value.author, workLanguage.value, form.value.scale)
    const candidates = wiki.results ?? []

    // 快速路径：LLM 门控通过，跳过 wiki 选择直接创建
    if (wiki.fast_path) {
      try {
        await doCreateWorld(null, true, wiki.fast_path_characters)
      } catch (e) {
        phase.value = 'form'
        message.error(`${t('createWorld.createFailed')}: ${(e as Error).message}`)
      }
      return
    }

    wikiSelectCandidates.value = candidates
    selectedWikiUrl.value = candidates.length === 1 ? candidates[0].url : null
    manualWikiUrl.value = ''
    manualWikiUrlError.value = false
    phase.value = 'wiki-select'
  } catch (e) {
    message.error(`${t('createWorld.createFailed')}: ${(e as Error).message}`)
  } finally {
    submitting.value = false
  }
}

function selectCandidate(url: string) {
  if (manualWikiUrl.value.trim()) return
  if (selectedWikiUrl.value === url) {
    selectedWikiUrl.value = null
  } else {
    selectedWikiUrl.value = url
  }
}

function isValidHttpUrl(value: string): boolean {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

async function handleWikiSelectConfirm() {
  const manual = manualWikiUrl.value.trim()
  if (manual && !isValidHttpUrl(manual)) {
    manualWikiUrlError.value = true
    return
  }
  manualWikiUrlError.value = false
  submitting.value = true
  try {
    const confirmedUrl = manual || selectedWikiUrl.value || null
    await doCreateWorld(confirmedUrl)
  } catch (e) {
    phase.value = 'wiki-select'
    message.error(`${t('createWorld.createFailed')}: ${(e as Error).message}`)
    submitting.value = false
  }
}

async function doCreateWorld(confirmedWikiUrl: string | null = null, fastPath = false, fastPathCharacters?: string[]) {
  form.value.urls = urlInputs.value.filter(u => u.trim())
  expectedMin.value = EXPECTED_MIN[form.value.scale ?? 'standard'] ?? 15
  phase.value = 'generating'
  generatedCount.value = 0
  steps.value.forEach(s => s.status = 'pending')

  message.info(t('createWorld.generatingTip'), { duration: 10000 })

  const { world_id } = await createWorld({
    ...form.value,
    confirmed_wiki_url: confirmedWikiUrl,
    fast_path: fastPath,
    fast_path_characters: fastPathCharacters,
  })
  pollWorldId = world_id
  startPolling(world_id)
}

function resetDialog() {
  stopPoll()
  phase.value = 'form'
  submitting.value = false
  wikiSelectCandidates.value = []
  selectedWikiUrl.value = null
  manualWikiUrl.value = ''
  manualWikiUrlError.value = false
  emit('update:visible', false)
}

function handleBackgroundRun() {
  emit('created', { world_id: pollWorldId } as WorldDoc)
  resetDialog()
}

function close() {
  if (phase.value === 'generating') {
    handleBackgroundRun()
    return
  }
  resetDialog()
}

watch(() => props.visible, (val) => {
  if (!val) {
    stopPoll()
    phase.value = 'form'
    submitting.value = false
    wikiSelectCandidates.value = []
    selectedWikiUrl.value = null
    manualWikiUrl.value = ''
    manualWikiUrlError.value = false
    form.value = { title: '', author: null, description: null, urls: [], scale: 'standard' }
    urlInputs.value = ['']
    ipDisclaimerAccepted.value = false
    workLanguage.value = null
    showAdvanced.value = false
  }
})

function registerAutoDestroy() {
  const notif = doneNotify.value!
  const remove = router.afterEach((to) => {
    if (to.path.match(/^\/world\//)) {
      notif.destroy()
      doneNotify.value = null
      remove()
    }
  })
}
</script>

<template>
  <NModal :show="visible" :mask-closable="phase !== 'generating' && !submitting" @update:show="(v: boolean) => { if (phase !== 'generating' && !submitting) emit('update:visible', v) }">
    <NCard
      class="create-world-card"
      :title="phase === 'form' ? $t('createWorld.title') : phase === 'wiki-select' ? $t('createWorld.titleWikiSelect') : $t('createWorld.titleCreating')"
      :bordered="false"
      :closable="!(submitting && phase !== 'generating')"
      @close="close"
    >
      <!-- 等待动画 -->
      <div v-if="phase === 'generating'" class="generating-screen">
        <div class="orb-container">
          <div class="orb">
            <div class="orb-ring ring-1"></div>
            <div class="orb-ring ring-2"></div>
            <div class="orb-ring ring-3"></div>
            <div class="orb-core"></div>
          </div>
        </div>

        <div class="steps">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="step-item"
            :class="step.status"
          >
            <span class="step-icon">
              <span v-if="step.status === 'done'" class="icon-done">&#10003;</span>
              <span v-else-if="step.status === 'active'" class="icon-active">
                <span class="spinner-dot"></span>
              </span>
              <span v-else class="icon-pending"></span>
            </span>
            <span class="step-label">{{ $t(step.key) }}</span>
            <span v-if="step.key === 'createWorld.stepGenerate' && generatedCount > 0" class="step-count">
              {{ generatedCount }}
            </span>
          </div>
        </div>

        <div class="progress-hint">
          <template v-if="generatedCount > 0">
            {{ $t('createWorld.generatedCount', { n: generatedCount }) }}
          </template>
          <template v-else>
            {{ $t('createWorld.connectingLLM') }}
          </template>
        </div>

        <NButton quaternary size="small" class="bg-btn" @click="handleBackgroundRun">
          {{ $t('createWorld.runInBackground') }}
        </NButton>
      </div>

      <!-- wiki 选择 -->
      <div v-else-if="phase === 'wiki-select'" class="wiki-select-screen">
        <template v-if="wikiSelectCandidates.length > 0">
          <p class="wiki-select-hint">{{ $t('createWorld.wikiSelectFoundHint') }}</p>
          <div class="wiki-candidates">
            <div
              v-for="c in wikiSelectCandidates"
              :key="c.url"
              class="wiki-candidate-item"
              :class="{ selected: selectedWikiUrl === c.url && !manualWikiUrl.trim(), dimmed: !!manualWikiUrl.trim() }"
              @click="selectCandidate(c.url)"
            >
              <div class="wiki-candidate-check">
                <span v-if="selectedWikiUrl === c.url && !manualWikiUrl.trim()" class="wiki-check-icon">&#10003;</span>
              </div>
              <div class="wiki-candidate-body">
                <div class="wiki-candidate-title">{{ c.page_title || c.url }}</div>
                <div class="wiki-candidate-meta">
                  <span class="wiki-lang-badge">{{ c.lang }}</span>
                  <a class="wiki-candidate-url" :href="c.url" target="_blank" rel="noopener" @click.stop>{{ c.url }}</a>
                </div>
                <div v-if="c.excerpt" class="wiki-candidate-excerpt">{{ c.excerpt }}</div>
                <NButton
                  text
                  size="tiny"
                  class="wiki-candidate-preview-btn"
                  @click.stop="openWikiPreview(c)"
                >
                  {{ $t('createWorld.wikiPreviewOpen') }}
                </NButton>
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <p class="wiki-select-hint wiki-select-hint--none">{{ $t('createWorld.wikiSelectNoneHint', { title: form.title }) }}</p>
        </template>

        <div class="wiki-select-manual">
          <p class="wiki-select-manual-label">{{ $t('createWorld.wikiSelectManualLabel') }}</p>
          <NInput
            v-model:value="manualWikiUrl"
            :placeholder="$t('createWorld.wikiSelectManualPlaceholder')"
            :status="manualWikiUrlError ? 'error' : undefined"
            @input="manualWikiUrlError = false"
          />
          <p v-if="manualWikiUrlError" class="wiki-select-manual-error">{{ $t('createWorld.wikiSelectManualError') }}</p>
        </div>
      </div>

      <!-- 表单 -->
      <NForm v-else-if="phase === 'form'" :model="form">
        <NFormItem :label="$t('createWorld.titleLabel')" required>
          <NInput v-model:value="form.title" :placeholder="$t('createWorld.titlePlaceholder')" :disabled="submitting" />
        </NFormItem>

        <NFormItem :label="$t('worldDetail.scaleLabel')" required class="scale-form-item">
          <div class="scale-cards">
            <div
              v-for="opt in scaleOptions"
              :key="opt.value"
              class="scale-card"
              :class="{ active: form.scale === opt.value }"
              @click="form.scale = opt.value"
            >
              <span class="scale-card-icon">{{ opt.icon }}</span>
              <div class="scale-card-body">
                <span class="scale-card-name">{{ $t(opt.nameKey) }}</span>
                <span class="scale-card-desc">{{ $t(opt.descKey) }}</span>
              </div>
            </div>
          </div>
          <Transition name="hint-fade">
            <p v-if="form.scale === 'all'" class="scale-all-hint">{{ $t('worldDetail.scaleAllWarning') }}</p>
          </Transition>
        </NFormItem>

        <div class="advanced-toggle" @click="showAdvanced = !showAdvanced">
          <span class="advanced-toggle-text">{{ $t('createWorld.advancedOptions') }}</span>
          <span class="advanced-toggle-arrow" :class="{ open: showAdvanced }">&#9662;</span>
        </div>

        <Transition name="collapse">
          <div v-show="showAdvanced" class="advanced-section">
            <NFormItem :label="$t('createWorld.authorLabel')">
              <NInput v-model:value="form.author" :placeholder="$t('createWorld.authorPlaceholder')" :disabled="submitting" />
            </NFormItem>
            <NFormItem :label="$t('createWorld.workLanguageLabel')">
              <NSelect
                v-model:value="workLanguage"
                :options="workLanguageOptions"
                :placeholder="$t('createWorld.workLanguagePlaceholder')"
                clearable
                :disabled="submitting"
              />
            </NFormItem>
            <NFormItem :label="$t('createWorld.briefLabel')">
              <NInput
                v-model:value="form.description"
                type="textarea"
                :rows="3"
                :placeholder="$t('createWorld.briefPlaceholder')"
                :disabled="submitting"
              />
            </NFormItem>
            <NFormItem :label="$t('createWorld.urlLabel')">
              <NSpace vertical style="width: 100%">
                <NInput
                  v-for="(_, i) in urlInputs"
                  :key="i"
                  v-model:value="urlInputs[i]"
                  :placeholder="$t('createWorld.urlPlaceholder')"
                  :disabled="submitting"
                >
                  <template #suffix>
                    <NButton
                      v-if="urlInputs.length > 1"
                      text
                      type="error"
                      size="small"
                      :disabled="submitting"
                      @click="removeUrl(i)"
                    >
                      {{ $t('common.delete') }}
                    </NButton>
                  </template>
                </NInput>
                <NButton dashed size="small" :disabled="submitting" @click="addUrl">{{ $t('createWorld.addUrl') }}</NButton>
              </NSpace>
            </NFormItem>
          </div>
        </Transition>
      </NForm>

      <template #footer>
        <template v-if="phase === 'form'">
          <div class="ip-disclaimer" :class="{ 'ip-disclaimer--shake': ipShake }">
            <NCheckbox v-model:checked="ipDisclaimerAccepted" size="small" :disabled="submitting">
              <span class="ip-disclaimer__text">{{ $t('legal.ipDisclaimerText') }}</span>
            </NCheckbox>
          </div>
          <NSpace justify="end">
            <NButton :disabled="submitting" @click="close">{{ $t('common.cancel') }}</NButton>
            <NButton
              type="primary"
              :loading="submitting"
              :disabled="!form.title.trim()"
              @click="handleSubmit"
            >
              {{ $t('createWorld.nextStep') }}
            </NButton>
          </NSpace>
        </template>
        <template v-else-if="phase === 'wiki-select'">
          <NSpace justify="end">
            <NButton :disabled="submitting" @click="phase = 'form'">{{ $t('common.back') }}</NButton>
            <NButton
              type="primary"
              :loading="submitting"
              @click="handleWikiSelectConfirm"
            >
              {{ $t('createWorld.wikiSelectStart') }}
            </NButton>
          </NSpace>
        </template>
      </template>
    </NCard>
  </NModal>

  <WikiPreviewModal
    v-model:visible="previewVisible"
    :url="previewUrl"
    :page-title="previewPageTitle"
    :title="form.title"
    :author="form.author"
  />
</template>

<style scoped>
.create-world-card {
  width: 600px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
}

:deep(.n-card) {
  border: none;
  border-radius: var(--radius);
}

@media (max-width: 768px) {
  .create-world-card {
    width: 100%;
  }

  .scale-cards {
    grid-template-columns: 1fr;
  }
}

.scale-form-item {
  position: relative;
}

.scale-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  width: 100%;
}

.scale-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bg-card);
  border: 1.5px solid var(--border-subtle, #333);
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
}

.scale-card:hover {
  border-color: var(--accent);
  background: var(--bg-card-hover, var(--bg-card));
}

.scale-card.active {
  border-color: var(--accent);
  background: var(--bg-card-hover, var(--bg-card));
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent);
}

.scale-card-icon {
  font-size: 22px;
  line-height: 1;
  flex-shrink: 0;
  margin-top: 2px;
}

.scale-card-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.scale-card-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.scale-card-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
}

.advanced-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 8px 0;
  user-select: none;
}

.advanced-toggle-text {
  font-size: 13px;
  color: var(--text-muted);
  transition: color 0.2s;
}

.advanced-toggle:hover .advanced-toggle-text {
  color: var(--accent);
}

.advanced-toggle-arrow {
  font-size: 12px;
  color: var(--text-muted);
  transition: transform 0.25s ease;
}

.advanced-toggle-arrow.open {
  transform: rotate(180deg);
}

.advanced-section {
  overflow: hidden;
}

.collapse-enter-active,
.collapse-leave-active {
  transition: max-height 0.3s ease, opacity 0.25s ease;
}

.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
}

.collapse-enter-to,
.collapse-leave-from {
  max-height: 500px;
  opacity: 1;
}

.scale-all-hint {
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  font-size: 12px;
  color: var(--text-muted);
  margin: 4px 0 0;
  line-height: 1.4;
  z-index: 1;
}

.scale-all-hint::before {
  content: '⚠️';
  position: relative;
  top: -2px;
  margin-right: 4px;
}

.hint-fade-enter-active,
.hint-fade-leave-active {
  transition: opacity 0.2s ease;
}

.hint-fade-enter-from,
.hint-fade-leave-to {
  opacity: 0;
}

.ip-disclaimer {
  width: 100%;
  margin-bottom: 8px;
}
.ip-disclaimer--shake {
  animation: ip-shake 0.5s ease-in-out;
  color: var(--error-color, #d03050);
}
.ip-disclaimer--shake .ip-disclaimer__text {
  color: var(--error-color, #d03050);
}
@keyframes ip-shake {
  0%, 100% { transform: translateX(0); }
  10%, 50%, 90% { transform: translateX(-6px); }
  30%, 70% { transform: translateX(6px); }
}
.ip-disclaimer__text {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.generating-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 0 12px;
}

.orb-container {
  margin-bottom: 28px;
}

.orb {
  position: relative;
  width: 100px;
  height: 100px;
}

.orb-core {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 24px;
  height: 24px;
  background: var(--accent);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 20px var(--accent), 0 0 40px var(--accent-glow);
  animation: core-pulse 2s ease-in-out infinite;
}

.orb-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  border: none;
  border-radius: 50%;
  opacity: 0.4;
}

.ring-1 {
  width: 60px;
  height: 60px;
  margin: -30px 0 0 -30px;
  animation: spin 3s linear infinite;
}

.ring-2 {
  width: 80px;
  height: 80px;
  margin: -40px 0 0 -40px;
  animation: spin-reverse 5s linear infinite;
  border-style: dashed;
}

.ring-3 {
  width: 100px;
  height: 100px;
  margin: -50px 0 0 -50px;
  animation: spin 7s linear infinite;
  border-style: dotted;
  opacity: 0.25;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes spin-reverse {
  to { transform: rotate(-360deg); }
}

@keyframes core-pulse {
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  50% { transform: translate(-50%, -50%) scale(1.3); opacity: 0.7; }
}

.steps {
  width: 100%;
  max-width: 300px;
  margin-bottom: 16px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  font-size: 14px;
  color: var(--text-muted);
  transition: color 0.3s;
}

.step-item.active {
  color: var(--text-primary);
}

.step-item.done {
  color: var(--accent);
}

.step-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.icon-done {
  color: var(--accent);
  font-weight: bold;
  font-size: 14px;
}

.icon-pending {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-subtle);
}

.icon-active {
  display: flex;
  align-items: center;
  justify-content: center;
}

.spinner-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--accent);
  animation: dot-pulse 1s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { transform: scale(0.6); opacity: 0.4; }
  50% { transform: scale(1); opacity: 1; }
}

.step-count {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--accent);
  font-family: var(--font-display);
}

.progress-hint {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.bg-btn {
  font-size: 12px;
  color: var(--text-muted);
}

/* wiki-select phase */
.wiki-select-screen {
  padding: 4px 0 8px;
}

.wiki-select-hint {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 12px;
}

.wiki-select-hint--none {
  color: var(--text-muted);
}

.wiki-candidates {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  max-height: 50vh;
  overflow-y: auto;
  padding-right: 2px;
}

.wiki-candidate-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bg-card);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 10px;
  box-shadow: var(--shadow-card);
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, background 0.2s, opacity 0.2s;
}

.wiki-candidate-item:hover {
  border-color: var(--accent);
  background: var(--bg-card-hover);
  box-shadow: 0 0 0 1px var(--accent), var(--shadow-card);
}

.wiki-candidate-item.selected {
  border-color: var(--accent);
  background: var(--bg-card-hover);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent), var(--shadow-card);
}

.wiki-candidate-item.dimmed {
  opacity: 0.45;
  pointer-events: none;
}

.wiki-candidate-check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.wiki-check-icon {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent);
  line-height: 1;
}

.wiki-candidate-body {
  flex: 1;
  min-width: 0;
}

.wiki-candidate-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.wiki-candidate-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wiki-lang-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-glow);
  border-radius: 4px;
  padding: 1px 5px;
  flex-shrink: 0;
  text-transform: uppercase;
}

.wiki-candidate-url {
  font-size: 12px;
  color: var(--text-muted);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wiki-candidate-url:hover {
  color: var(--accent);
  text-decoration: underline;
}

.wiki-candidate-excerpt {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 6px;
}

.wiki-candidate-preview-btn {
  display: block;
  margin-top: 6px;
  margin-left: auto;
  color: var(--accent) !important;
}

.wiki-select-manual {
  margin-top: 4px;
}

.wiki-select-manual-label {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0 0 6px;
}

.wiki-select-manual-error {
  font-size: 12px;
  color: var(--error-color, #d03050);
  margin: 4px 0 0;
}
</style>
