<script setup lang="ts">
import { computed, ref, watch, h } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listTemplates, createFromTemplate } from '@/api/worlds'
import { listCharacters } from '@/api/characters'
import type { WorldDoc, WorldTemplate } from '@/types/world'
import {
  NModal, NButton, NRadioGroup, NRadio, NTabs, NTabPane, useMessage, useNotification
} from 'naive-ui'
import { usePoll } from '@/composables/usePoll'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  'update:visible': [value: boolean]
  created: [world: WorldDoc]
}>()

const message = useMessage()
const notification = useNotification()
const router = useRouter()
const { t } = useI18n()
const doneNotify = ref<ReturnType<typeof notification.create> | null>(null)

// Template i18n helpers
function tplTitle(tpl: WorldTemplate): string {
  return t(`template.${tpl.id}.title`, tpl.title)
}
function tplCategory(tpl: WorldTemplate): string {
  return t(`template.${tpl.id}.category`, tpl.category)
}
function tplDesc(tpl: WorldTemplate): string {
  return t(`template.${tpl.id}.description`, tpl.description)
}

// Phase control
type Phase = 'select' | 'scale' | 'generating'
const phase = ref<Phase>('select')
const submitting = ref(false)

// Template list
const templates = ref<WorldTemplate[]>([])
const loadingTemplates = ref(false)
const selectedTemplate = ref<WorldTemplate | null>(null)

// Category tabs
const TAB_ORDER = ['现实', '奇幻', '仙侠', '科幻', '武侠', '历史'] as const
const activeTab = ref<string>('现实')

const categories = computed(() => {
  const catSet = new Set(templates.value.map(t => t.category))
  return TAB_ORDER.filter(c => catSet.has(c))
})

const filteredTemplates = computed(() => {
  const list = templates.value.filter(t => t.category === activeTab.value)
  // 空模板排在最前面
  return [...list].sort((a, b) => (a.element_count === 0 ? -1 : 0) - (b.element_count === 0 ? -1 : 0))
})

function tabLabel(cat: string): string {
  const key = `template.tab.${cat}`
  const fallback = cat
  return t(key, fallback)
}

watch(activeTab, () => {
  if (selectedTemplate.value && selectedTemplate.value.category !== activeTab.value) {
    selectedTemplate.value = null
  }
})

// Scale
const selectedScale = ref<string>('standard')

// Generation progress
const generatedCount = ref(0)
const { start: startPoll, stop: stopPoll } = usePoll()

// Steps for generation animation
interface Step { key: string; status: 'pending' | 'active' | 'done' }
const steps = ref<Step[]>([
  { key: 'createWorld.stepSearch', status: 'pending' },
  { key: 'createWorld.stepExtract', status: 'pending' },
  { key: 'createWorld.stepGenerate', status: 'pending' },
])

let pollWorldId = ''

// ---- Template loading ----
async function loadTemplates() {
  loadingTemplates.value = true
  try {
    templates.value = await listTemplates()
  } catch (e) {
    message.error(`${t('template.loadFailed')}: ${(e as Error).message}`)
  } finally {
    loadingTemplates.value = false
  }
}

function selectTemplate(tpl: WorldTemplate) {
  selectedTemplate.value = tpl
}

// ---- Phase transitions ----
function goToScale() {
  if (!selectedTemplate.value) return
  // 空模板无预设数据，跳过规模选择直接创建
  if (selectedTemplate.value.element_count === 0) {
    handleCreate()
    return
  }
  phase.value = 'scale'
}

function goBackToSelect() {
  phase.value = 'select'
}

// ---- Template creation animation (no LLM, completes in ~6s) ----
function startTemplateAnimation(worldId: string) {
  // Step 1: 创建世界 (0s)
  steps.value[0].status = 'active'
  // Step 2: 加载元素 (2s)
  setTimeout(() => { steps.value[0].status = 'done'; steps.value[1].status = 'active' }, 2000)
  // Step 3: 生成角色 (4s)
  setTimeout(() => { steps.value[1].status = 'done'; steps.value[2].status = 'active' }, 4000)
  // 完成 (6s)
  setTimeout(async () => {
    steps.value[2].status = 'done'
    try {
      const characters = await listCharacters(worldId)
      generatedCount.value = characters.length
    } catch {
      // ignore
    }
    doneNotify.value = notification.create({
      type: 'success',
      title: t('createWorld.charGenDoneTitle'),
      content: () => h('span', {}, [
        t('createWorld.charGenSuccess', { n: generatedCount.value }),
        ' ',
        h('a', { href: `/world/${worldId}`, style: { color: 'var(--accent)', textDecoration: 'underline', cursor: 'pointer' }, onClick: (e: MouseEvent) => { e.preventDefault(); router.push(`/world/${worldId}`) } }, t('createWorld.goToWorld')),
      ]),
      duration: 0,
      closable: true,
    })
    registerAutoDestroy()
    emit('created', { world_id: worldId } as WorldDoc)
    phase.value = 'select'
    close()
  }, 6000)
}


// ---- Create from template ----
async function handleCreate() {
  if (!selectedTemplate.value) return
  submitting.value = true
  phase.value = 'generating'
  generatedCount.value = 0
  steps.value.forEach(s => s.status = 'pending')

  try {
    const world = await createFromTemplate({
      template_id: selectedTemplate.value.id,
      scale: selectedScale.value as 'standard' | 'detailed' | 'deep',
    })
    pollWorldId = world.world_id
    // 模板自带预设角色，无需调用 LLM 生成，直接播放动画
    startTemplateAnimation(world.world_id)
  } catch (e) {
    message.error(`${t('createWorld.createFailed')}: ${(e as Error).message}`)
    // 空模板跳过了规模选择，失败时回到模板选择；普通模板回到规模选择
    phase.value = (selectedTemplate.value?.element_count === 0) ? 'select' : 'scale'
    submitting.value = false
  }
}

// ---- Background run ----
function handleBackgroundRun() {
  stopPoll()
  emit('created', { world_id: pollWorldId } as WorldDoc)
  close()
}

// ---- Close / Reset ----
function close() {
  if (phase.value === 'generating') {
    phase.value = 'select'
    handleBackgroundRun()
    return
  }
  stopPoll()
  phase.value = 'select'
  submitting.value = false
  selectedTemplate.value = null
  selectedScale.value = 'standard'
  emit('update:visible', false)
}

watch(() => props.visible, (val) => {
  if (val) {
    loadTemplates()
  } else {
    stopPoll()
    phase.value = 'select'
    submitting.value = false
    selectedTemplate.value = null
    selectedScale.value = 'standard'
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
  <NModal
    :show="visible"
    :mask-closable="!(submitting && phase !== 'generating')"
    @update:show="(v: boolean) => { if (!(submitting && phase !== 'generating')) emit('update:visible', v) }"
  >
    <div class="dialog-shell" :class="{ 'scale-phase': phase === 'scale' }">
      <!-- 1. 标题栏 -->
      <div class="dialog-header">
        <span class="dialog-title">
          {{
            phase === 'select' ? $t('template.title')
              : phase === 'scale' ? $t('template.selectScale')
                : $t('createWorld.titleCreating')
          }}
        </span>
        <span
          v-if="!(submitting && phase !== 'generating')"
          class="dialog-close"
          @click="close"
        >✕</span>
      </div>

      <!-- 2. Tab 栏 -->
      <div v-if="phase === 'select' && !loadingTemplates && templates.length > 0" class="dialog-tabs">
        <NTabs v-model:value="activeTab" type="segment" size="small">
          <NTabPane
            v-for="cat in categories"
            :key="cat"
            :name="cat"
            :tab="tabLabel(cat)"
          />
        </NTabs>
      </div>
      <div v-else class="dialog-tabs-placeholder"></div>

      <!-- 3. 内容区 -->
      <div class="dialog-body" :class="{ 'scale-body': phase === 'scale' }">
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

        <div v-else-if="phase === 'scale'" class="scale-screen">
          <div class="selected-template">
            <span class="selected-label">{{ $t('template.templateLabel') }}</span>
            <span class="selected-name">{{ selectedTemplate ? tplTitle(selectedTemplate) : '' }}</span>
            <span v-if="selectedTemplate" class="selected-category">{{ tplCategory(selectedTemplate) }}</span>
          </div>
          <div class="scale-section">
            <p class="scale-hint">{{ $t('template.scaleHint') }}</p>
            <NRadioGroup v-model:value="selectedScale">
              <div class="scale-grid">
                <label
                  v-for="opt in [
                    { value: 'standard', label: $t('template.scaleStandard'), desc: $t('template.scaleStandardDesc') },
                    { value: 'detailed', label: $t('template.scaleDetailed'), desc: $t('template.scaleDetailedDesc') },
                    { value: 'deep', label: $t('template.scaleDeep'), desc: $t('template.scaleDeepDesc') },
                  ]"
                  :key="opt.value"
                  class="scale-card"
                  :class="{ selected: selectedScale === opt.value }"
                >
                  <NRadio :value="opt.value" />
                  <div class="scale-card-text">
                    <span class="scale-card-label">{{ opt.label }}</span>
                    <span class="scale-card-desc">{{ opt.desc }}</span>
                  </div>
                </label>
              </div>
            </NRadioGroup>
          </div>
        </div>

        <div v-else-if="phase === 'select'" class="select-screen">
          <div v-if="loadingTemplates" class="loading-state">
            <span class="loading-text">{{ $t('template.loading') }}</span>
          </div>
          <div v-else-if="templates.length === 0" class="empty-state">
            <span class="empty-text">{{ $t('template.noTemplates') }}</span>
          </div>
          <div v-else class="template-grid">
            <div
              v-for="tpl in filteredTemplates"
              :key="tpl.id"
              class="template-card"
              :class="{ selected: selectedTemplate?.id === tpl.id }"
              @click="selectTemplate(tpl)"
            >
              <div class="template-card__glow" />
              <div class="template-card-header">
                <span class="template-card-name">{{ tplTitle(tpl) }}</span>
              </div>
              <p class="template-card-desc">{{ tplDesc(tpl) }}</p>
              <div class="template-card-meta">
                <span class="template-card-count">{{ $t('template.elementCount', { n: tpl.element_count }) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 4. 按钮栏 -->
      <div class="dialog-footer">
        <template v-if="phase === 'select'">
          <NButton @click="close">{{ $t('common.cancel') }}</NButton>
          <NButton
            type="primary"
            :disabled="!selectedTemplate"
            @click="goToScale"
          >
            {{ $t('common.next') }}
          </NButton>
        </template>
        <template v-else-if="phase === 'scale'">
          <NButton @click="goBackToSelect">{{ $t('common.back') }}</NButton>
          <NButton
            type="primary"
            :loading="submitting"
            @click="handleCreate"
          >
            {{ $t('createWorld.create') }}
          </NButton>
        </template>
      </div>
    </div>
  </NModal>
</template>

<style scoped>
/* ===== 弹窗外壳：纯 div，不依赖 NCard ===== */
.dialog-shell {
  width: 680px;
  height: 560px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.25);
  display: grid;
  grid-template-rows: 48px 44px 1fr 52px;
  overflow: hidden;
  transition: width 0.3s ease;
}
.dialog-shell.scale-phase {
  width: fit-content;
  min-width: 400px;
  height: fit-content;
  grid-template-rows: 48px 4px 1fr 52px;
}

/* 1. 标题栏（固定 48px） */
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}

.dialog-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.dialog-close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-muted);
  transition: background 0.15s, color 0.15s;
}

.dialog-close:hover {
  background: var(--bg-secondary);
  color: var(--text-primary);
}

/* 2. Tab 栏（固定 44px） */
.dialog-tabs {
  padding: 0 20px;
  display: flex;
  align-items: center;
  overflow: hidden;
}

.dialog-tabs :deep(.n-tabs) {
  width: 100%;
}

.dialog-tabs :deep(.n-tabs-nav) {
  margin-bottom: 0;
}

.dialog-tabs-placeholder {
  height: 4px;
}

/* 3. 内容区（自动填满 1fr，可滚动） */
.dialog-body {
  overflow-y: auto;
  padding: 12px 20px;
}
.dialog-body.scale-body {
  padding-top: 4px;
  padding-bottom: 4px;
}

/* 4. 按钮栏（固定 52px） */
.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 0 20px;
}

/* ===== Generating ===== */
.generating-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.orb-container { margin-bottom: 28px; }
.orb { position: relative; width: 100px; height: 100px; }
.orb-core {
  position: absolute; top: 50%; left: 50%;
  width: 24px; height: 24px;
  background: var(--accent); border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 0 20px var(--accent), 0 0 40px var(--accent-glow);
  animation: core-pulse 2s ease-in-out infinite;
}
.orb-ring {
  position: absolute; top: 50%; left: 50%;
  border: none; border-radius: 50%; opacity: 0.4;
}
.ring-1 { width: 60px; height: 60px; margin: -30px 0 0 -30px; animation: spin 3s linear infinite; }
.ring-2 { width: 80px; height: 80px; margin: -40px 0 0 -40px; animation: spin-reverse 5s linear infinite; border-style: dashed; }
.ring-3 { width: 100px; height: 100px; margin: -50px 0 0 -50px; animation: spin 7s linear infinite; border-style: dotted; opacity: 0.25; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes spin-reverse { to { transform: rotate(-360deg); } }
@keyframes core-pulse {
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  50% { transform: translate(-50%, -50%) scale(1.3); opacity: 0.7; }
}

.steps { width: 100%; max-width: 300px; margin-bottom: 16px; }
.step-item { display: flex; align-items: center; gap: 10px; padding: 8px 0; font-size: 14px; color: var(--text-muted); transition: color 0.3s; }
.step-item.active { color: var(--text-primary); }
.step-item.done { color: var(--accent); }
.step-icon { display: flex; align-items: center; justify-content: center; width: 20px; height: 20px; flex-shrink: 0; }
.icon-done { color: var(--accent); font-weight: bold; font-size: 14px; }
.icon-pending { width: 8px; height: 8px; border-radius: 50%; background: var(--border-subtle); }
.icon-active { display: flex; align-items: center; justify-content: center; }
.spinner-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); animation: dot-pulse 1s ease-in-out infinite; }
@keyframes dot-pulse { 0%, 100% { transform: scale(0.6); opacity: 0.4; } 50% { transform: scale(1); opacity: 1; } }
.step-count { margin-left: auto; font-size: 13px; font-weight: 600; color: var(--accent); font-family: var(--font-display); }
.progress-hint { font-size: 13px; color: var(--text-muted); margin-bottom: 16px; }
.bg-btn { font-size: 12px; color: var(--text-muted); }

/* ===== Scale ===== */
.scale-screen {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  padding: 0 4px 20px;
  text-align: center;
}
.selected-template {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-secondary);
  border-radius: 20px;
  margin-bottom: 24px;
  border: 1px solid var(--border);
}
.selected-label { font-size: 13px; color: var(--text-muted); }
.selected-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.selected-category { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(var(--accent-rgb, 100, 120, 200), 0.12); color: var(--accent); font-weight: 500; }
.scale-section { width: fit-content; }
.scale-hint { font-size: 14px; color: var(--text-muted); margin: 0 0 20px; }
.scale-grid { display: flex; flex-direction: column; gap: 12px; }
.scale-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.25s ease;
  background: var(--bg-card);
  text-align: left;
}
.scale-card:hover {
  border-color: var(--accent);
  background: var(--bg-secondary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.scale-card.selected {
  border-color: var(--accent);
  background: var(--bg-secondary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 20%, transparent);
}
.scale-card.selected::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 60%;
  background: var(--accent);
  border-radius: 0 2px 2px 0;
}
.scale-card-text { display: flex; flex-direction: column; gap: 4px; }
.scale-card-label { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.scale-card-desc { font-size: 13px; color: var(--text-muted); line-height: 1.5; }

/* ===== Template cards ===== */
.select-screen { padding: 0; }
.loading-state, .empty-state { display: flex; justify-content: center; align-items: center; padding: 40px 0; }
.loading-text, .empty-text { font-size: 14px; color: var(--text-muted); }
.template-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.template-card {
  position: relative;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid rgba(0, 0, 0, 0.04);
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
  cursor: pointer;
  transition: transform 0.4s cubic-bezier(0.23, 1, 0.32, 1),
              box-shadow 0.4s cubic-bezier(0.23, 1, 0.32, 1),
              border-color 0.3s ease;
  overflow: hidden;
}

/* Theme-specific template card backgrounds */
[data-theme="ink"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(20, 212, 168, 0.02));
  box-shadow: 0 1px 3px rgba(20, 212, 168, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}
[data-theme="breeze"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(152, 115, 247, 0.02));
  box-shadow: 0 1px 3px rgba(152, 115, 247, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}
[data-theme="sakura"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(233, 30, 99, 0.02));
  box-shadow: 0 1px 3px rgba(233, 30, 99, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}
[data-theme="ember"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(245, 124, 0, 0.02));
  box-shadow: 0 1px 3px rgba(245, 124, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}
[data-theme="sunflower"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(230, 168, 23, 0.02));
  box-shadow: 0 1px 3px rgba(230, 168, 23, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}
[data-theme="ocean"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(41, 121, 255, 0.02));
  box-shadow: 0 1px 3px rgba(41, 121, 255, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}
[data-theme="indigo"] .template-card {
  background: linear-gradient(145deg, var(--bg-card), rgba(67, 56, 202, 0.02));
  box-shadow: 0 1px 3px rgba(67, 56, 202, 0.04), 0 4px 12px rgba(0, 0, 0, 0.02);
}

.template-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-card-hover);
  border-color: rgba(0, 0, 0, 0.08);
}
.template-card:hover .template-card__glow {
  opacity: 1;
}
.template-card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent), var(--shadow-card);
}
.template-card__glow {
  position: absolute;
  inset: 0;
  background: radial-gradient(
    ellipse 60% 50% at 20% 0%,
    var(--accent-glow) 0%,
    transparent 70%
  );
  opacity: 0;
  transition: opacity 0.5s ease;
  pointer-events: none;
}
.template-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--gradient-accent);
  opacity: 0.3;
  transition: opacity 0.4s;
  z-index: 1;
}
.template-card:hover::before {
  opacity: 1;
}
.template-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.template-card-name { font-size: 14px; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.template-card-desc { font-size: 12px; color: var(--text-muted); line-height: 1.6; margin: 0 0 10px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.template-card-meta { display: flex; align-items: center; }
.template-card-count { font-size: 11px; color: var(--text-muted); }
</style>
