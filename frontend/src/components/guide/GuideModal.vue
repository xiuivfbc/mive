<template>
  <n-modal :show="show" :closable="!onboardingMode" :mask-closable="!onboardingMode" @update:show="onGuideModalUpdateShow">
    <div class="guide-modal">
      <div class="guide-modal__header">
        <span class="guide-modal__icon">📖</span>
        <h2 class="guide-modal__title">{{ $t('guide.modal.title') }}</h2>
        <button v-if="!onboardingMode" class="guide-modal__close" @click="$emit('update:show', false)">✕</button>
      </div>

      <div class="guide-modal__tabs">
        <button
          class="guide-modal__tab"
          :class="{
            'guide-modal__tab--active': activeTab === 'quickstart',
            'guide-modal__tab--disabled': false,
          }"
          @click="trySwitchTab('quickstart')"
        >
          {{ $t('guide.tab.quickstart') }}
          <span v-if="onboardingMode && tab1Done" class="guide-modal__tab-check">✓</span>
        </button>
        <button
          class="guide-modal__tab"
          :class="{
            'guide-modal__tab--active': activeTab === 'persona',
            'guide-modal__tab--disabled': onboardingMode && activeTab !== 'persona' && !tab1Done && !(activeTab === 'quickstart' && currentStep === steps.length - 1),
            'guide-modal__tab--hint': showPersonaTabHint,
          }"
          @click="trySwitchTab('persona')"
        >
          {{ $t('guide.tab.persona') }}
          <span v-if="onboardingMode && tab2Done" class="guide-modal__tab-check">&#x2713;</span>
        </button>
        <button
          class="guide-modal__tab"
          :class="{
            'guide-modal__tab--active': activeTab === 'insights',
            'guide-modal__tab--disabled': onboardingMode && activeTab !== 'insights' && (!tab1Done || !tab2Done),
            'guide-modal__tab--hint': showInsightsTabHint,
          }"
          @click="trySwitchTab('insights')"
        >
          {{ $t('guide.tab.insights') }}
          <span v-if="onboardingMode && tab3Done" class="guide-modal__tab-check">&#x2713;</span>
        </button>
      </div>

      <!-- Tab 1: 快速上手 -->
      <div v-if="activeTab === 'quickstart'" class="guide-modal__content">
        <!-- Progress bar -->
        <div class="slide-progress">
          <div
            v-for="step in steps"
            :key="step.key"
            class="slide-progress__seg"
            :class="{ 'slide-progress__seg--done': step.num <= currentStep + 1, 'slide-progress__seg--active': step.num === currentStep + 1 }"
            @click="!onboardingMode && (currentStep = step.num - 1)"
          >
            <div class="slide-progress__dot">{{ step.num }}</div>
            <div class="slide-progress__label">{{ $t(step.titleKey) }}</div>
          </div>
          <div class="slide-progress__bar">
            <div class="slide-progress__fill" :style="{ width: ((currentStep) / (steps.length - 1) * 100) + '%' }"></div>
          </div>
        </div>

        <!-- Slide area -->
        <div class="slide-stage">
          <Transition :name="slideDirection" mode="out-in">
            <div class="slide" :key="currentStep">
              <div v-if="steps[currentStep].favicon" class="slide__emoji slide__emoji--img">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="56" height="56">
                  <rect width="32" height="32" rx="6" fill="#0eb5a0"/>
                  <path d="M8 8 L16 24 L24 8" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                </svg>
              </div>
              <div v-else class="slide__emoji">{{ steps[currentStep].emoji }}</div>
              <div class="slide__title">{{ $t(steps[currentStep].titleKey) }}</div>
              <div class="slide__desc" v-html="$t(steps[currentStep].descKey)"></div>
            </div>
          </Transition>
        </div>

        <!-- Navigation -->
        <div class="slide-nav">
          <button
            v-if="currentStep > 0"
            class="slide-nav__btn slide-nav__btn--prev"
            @click="prevStep"
          >
            ← {{ $t('guide.prev') }}
          </button>
          <div class="slide-nav__dots">
            <span
              v-for="step in steps"
              :key="step.key"
              class="slide-nav__dot"
              :class="{ 'slide-nav__dot--active': step.num === currentStep + 1 }"
              @click="!onboardingMode && (currentStep = step.num - 1)"
            ></span>
          </div>
          <button
            v-if="currentStep < steps.length - 1"
            class="slide-nav__btn slide-nav__btn--next"
            :class="{ 'slide-nav__btn--hint': onboardingMode && !tab1Done }"
            @click="nextStep"
          >
            {{ $t('guide.next') }} →
          </button>
          <button
            v-else-if="!onboardingMode"
            class="slide-nav__btn slide-nav__btn--start"
            @click="$emit('update:show', false)"
          >
            {{ $t('guide.start') }} 🚀
          </button>
          <button
            v-else
            class="slide-nav__btn slide-nav__btn--start"
            :class="{ 'slide-nav__btn--hint': onboardingMode && !tab1Done }"
            @click="tab1Done = true; message.success($t('guide.onboarding.hint'))"
            :disabled="tab1Done"
          >
            {{ tab1Done ? $t('guide.onboarding.done') : $t('guide.onboarding.completeStep') }}
          </button>
        </div>
      </div>

      <!-- Tab 2: 你是哪类人 -->
      <div v-if="activeTab === 'persona'" class="guide-modal__content guide-modal__content--persona">
        <div class="persona-stack">
          <div
            v-for="group in personaGroups"
            :key="group.key"
            class="persona-card"
            :class="{ 'persona-card--selected': selectedGroup === group.key, 'persona-card--hint': onboardingMode && !tab2Done && hintGroupKey === group.key && selectedGroup !== group.key }"
            @click="toggleGroup(group.key)"
          >
            <div class="persona-card__head">
              <span class="persona-card__emoji">{{ group.emoji }}</span>
              <div class="persona-card__info">
                <div class="persona-card__name">{{ $t(group.nameKey) }}</div>
                <div class="persona-card__desc">{{ $t(group.descKey) }}</div>
              </div>
              <span class="persona-card__arrow" :class="{ 'persona-card__arrow--open': selectedGroup === group.key }">▾</span>
            </div>
            <Transition name="slide-down">
              <div v-if="selectedGroup === group.key" class="persona-card__intents">
                <div
                  v-for="intent in group.intents"
                  :key="intent.key"
                  class="intent-item"
                  :class="{ 'intent-item--expanded': expandedIntents.has(intent.key), 'intent-item--hint': onboardingMode && !tab2Done && selectedGroup === hintGroupKey && hintIntentKey === intent.key && !expandedIntents.has(intent.key) }"
                  @click.stop="toggleIntent(intent.key)"
                >
                  <div class="intent-item__head">
                    <div class="intent-item__name">{{ $t(intent.nameKey) }}</div>
                    <span class="intent-item__arrow">{{ expandedIntents.has(intent.key) ? '▾' : '▸' }}</span>
                  </div>
                  <div class="intent-item__desc">{{ $t(intent.descKey) }}</div>
                  <Transition name="slide-down">
                    <div v-if="expandedIntents.has(intent.key)" class="intent-item__lines">
                      <div v-for="(_, i) in intent.lineKeys" :key="i" class="intent-item__line">
                        {{ $t(intent.lineKeys[i]) }}
                      </div>
                    </div>
                  </Transition>
                </div>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <!-- Tab 3: 小巧思 -->
      <div v-if="activeTab === 'insights'" class="guide-modal__content guide-modal__content--insights">
        <div class="insights-subtabs">
          <button
            class="guide-modal__tab guide-modal__tab--sub"
            :class="{
              'guide-modal__tab--active': insightsSubTab === 'current',
              'guide-modal__tab--disabled': onboardingMode && !canAccessInsightSubTab('current'),
            }"
            @click="trySwitchInsightSubTab('current')"
          >
            {{ $t('guide.tab.current') }}
          </button>
          <button
            class="guide-modal__tab guide-modal__tab--sub"
            :class="{
              'guide-modal__tab--active': insightsSubTab === 'recent',
              'guide-modal__tab--disabled': onboardingMode && !canAccessInsightSubTab('recent'),
              'guide-modal__tab--hint': showRecentSubTabHint,
            }"
            @click="trySwitchInsightSubTab('recent')"
          >
            {{ $t('guide.insights.recent') }}
          </button>
          <button
            class="guide-modal__tab guide-modal__tab--sub"
            :class="{
              'guide-modal__tab--active': insightsSubTab === 'all',
              'guide-modal__tab--disabled': onboardingMode && !canAccessInsightSubTab('all'),
              'guide-modal__tab--hint': showAllSubTabHint,
            }"
            @click="trySwitchInsightSubTab('all')"
          >
            {{ $t('guide.insights.all') }}
          </button>
        </div>

        <!-- Current page context help -->
        <template v-if="insightsSubTab === 'current'">
          <div class="insights-content" v-if="currentContextHelp">
            <div class="insights-markdown" v-html="currentContextHelp" @click="onMarkdownClick"></div>
          </div>
          <div v-else class="insights-empty">
            {{ $t('guide.noHelp') }}
          </div>
        </template>

        <!-- Recent / All content -->
        <template v-else-if="insightsSubTab === 'recent' || insightsSubTab === 'all'">
          <div class="insights-content" v-if="currentInsightContent">
            <div class="insights-markdown" v-html="currentInsightContent"></div>
          </div>
          <div v-else class="insights-empty">
            {{ $t('guide.insights.empty') }}
          </div>
        </template>
      </div>

      <div v-if="activeTab === 'persona' || activeTab === 'insights'" class="guide-modal__footer">
        <button
          v-if="onboardingMode"
          class="guide-modal__done"
          :class="{ 'guide-modal__done--hint': showDoneHint }"
          :disabled="(activeTab === 'persona' ? !tab2Done : !tab3Done) || (activeTab === 'persona' ? personaDoneClicked : insightsDoneClicked)"
          @click="handleOnboardingTabDone"
        >
          {{ (activeTab === 'persona' ? personaDoneClicked : insightsDoneClicked) ? $t('guide.onboarding.done') : (activeTab === 'persona' ? tab2Done : tab3Done) ? $t('guide.onboarding.completeStep') : $t('guide.onboarding.needInteract') }}
        </button>
        <button v-else class="guide-modal__done" @click="$emit('update:show', false)">{{ $t('guide.done') }}</button>
      </div>

      <div v-if="onboardingMode" class="guide-modal__skip">
        <button class="guide-modal__skip-btn" @click="emit('skip')">{{ $t('guide.onboarding.skip') }}</button>
      </div>

    </div>
  </n-modal>

  <!-- Image lightbox -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="lightboxSrc" class="guide-lightbox" @click="lightboxSrc = ''">
        <img :src="lightboxSrc" class="guide-lightbox__img" @click.stop />
        <button class="guide-lightbox__close" @click="lightboxSrc = ''">✕</button>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { NModal, useMessage } from 'naive-ui'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  show: boolean
  allContent?: string
  recentContent?: string
  contextHelp?: string
  onboardingMode?: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'onboarding-complete': []
  'skip': []
}>()

const route = useRoute()
const message = useMessage()
const { t } = useI18n()

const activeTab = ref<'quickstart' | 'persona' | 'insights'>('quickstart')
const insightsSubTab = ref<'current' | 'recent' | 'all'>('current')
watch(() => props.show, (val) => {
  if (val) {
    activeTab.value = props.onboardingMode ? 'quickstart' : 'insights'
    currentStep.value = 0
    insightsSubTab.value = 'current'
    visitedInsightSubTabs.value = new Set(['current'])
    tab1Done.value = false
    tab2Done.value = false
    tab3Done.value = false
    personaDoneClicked.value = false
    insightsDoneClicked.value = false
    selectedGroup.value = null
    expandedIntents.value = new Set()

    // Show welcome toast when onboarding starts, visible for 5 seconds
    if (props.onboardingMode) {
      message.success(t('guide.onboarding.welcome'), { duration: 5000 })
    }
  }
})
const selectedGroup = ref<string | null>(null)
const expandedIntents = ref(new Set<string>())
const currentStep = ref(0)
const lightboxSrc = ref('')
const slideDirection = ref<'slide-next' | 'slide-prev'>('slide-next')

// Onboarding state
const tab1Done = ref(false)
const tab2Done = ref(false)
const tab3Done = ref(false)
const personaDoneClicked = ref(false)
const insightsDoneClicked = ref(false)
const visitedInsightSubTabs = ref(new Set<string>(['current']))

const insightsSubTabOrder: Array<'current' | 'recent' | 'all'> = ['current', 'recent', 'all']

const tab2ConditionMet = computed(() => selectedGroup.value !== null && expandedIntents.value.size > 0)

// Onboarding visual hint states
const showPersonaTabHint = computed(() => props.onboardingMode && !tab2Done.value && activeTab.value !== 'persona' && (tab1Done.value || (activeTab.value === 'quickstart' && currentStep.value === steps.length - 1)))
const showInsightsTabHint = computed(() => props.onboardingMode && tab2Done.value && !tab3Done.value && activeTab.value !== 'insights')
const showRecentSubTabHint = computed(() => props.onboardingMode && activeTab.value === 'insights' && visitedInsightSubTabs.value.has('current') && !visitedInsightSubTabs.value.has('recent'))
const showAllSubTabHint = computed(() => props.onboardingMode && activeTab.value === 'insights' && visitedInsightSubTabs.value.has('recent') && !visitedInsightSubTabs.value.has('all'))
const showDoneHint = computed(() => {
  if (!props.onboardingMode) return false
  if (activeTab.value === 'persona') return tab2Done.value && !personaDoneClicked.value
  if (activeTab.value === 'insights') return tab3Done.value && !insightsDoneClicked.value
  return false
})

// Hint targets for persona tab (deterministic: first group, first intent)
const hintGroupKey = computed(() => {
  if (!props.onboardingMode || tab2Done.value) return null
  return personaGroups[0]?.key ?? null
})
const hintIntentKey = computed(() => {
  if (!props.onboardingMode || tab2Done.value) return null
  const group = personaGroups[0]
  return group?.intents[0]?.key ?? null
})

// Auto-detect tab2 completion when conditions change
watch(tab2ConditionMet, (met) => {
  if (met && props.onboardingMode) {
    tab2Done.value = true
    message.success(t('guide.onboarding.hint'))
  }
})

function canAccessInsightSubTab(subTab: string): boolean {
  if (!props.onboardingMode) return true
  const idx = insightsSubTabOrder.indexOf(subTab as typeof insightsSubTabOrder[number])
  // Can access if all previous subtabs have been visited
  return insightsSubTabOrder.slice(0, idx).every(s => visitedInsightSubTabs.value.has(s))
}

function trySwitchInsightSubTab(subTab: 'current' | 'recent' | 'all') {
  if (props.onboardingMode && !canAccessInsightSubTab(subTab)) {
    message.warning(t('guide.onboarding.needInteract'))
    return
  }
  insightsSubTab.value = subTab
  visitedInsightSubTabs.value.add(subTab)
  // Check if all required subtabs visited
  if (props.onboardingMode && !tab3Done.value) {
    if (insightsSubTabOrder.every(s => visitedInsightSubTabs.value.has(s))) {
      tab3Done.value = true
      message.success(t('guide.onboarding.allDone'))
    }
  }
}

function trySwitchTab(tab: 'quickstart' | 'persona' | 'insights') {
  if (!props.onboardingMode) {
    activeTab.value = tab
    return
  }
  // In onboarding mode, check if previous tabs are done
  if (tab === 'quickstart') {
    activeTab.value = tab
  } else if (tab === 'persona') {
    const onLastSlide = activeTab.value === 'quickstart' && currentStep.value === steps.length - 1
    if (!tab1Done.value && !onLastSlide) {
      message.warning(t('guide.onboarding.tabLocked'))
      return
    }
    activeTab.value = tab
  } else if (tab === 'insights') {
    if (!tab1Done.value || !tab2Done.value) {
      message.warning(t('guide.onboarding.tabLocked'))
      return
    }
    activeTab.value = tab
  }
}

function handleOnboardingTabDone() {
  if (activeTab.value === 'persona' && tab2Done.value) {
    personaDoneClicked.value = true
  } else if (activeTab.value === 'insights' && tab3Done.value) {
    insightsDoneClicked.value = true
    emit('onboarding-complete')
  }
}

function onGuideModalUpdateShow(val: boolean) {
  if (props.onboardingMode && !val && !(tab1Done.value && tab2Done.value && tab3Done.value)) {
    // Block close in onboarding mode unless all done
    message.warning(t('guide.onboarding.tabLocked'))
    return
  }
  emit('update:show', val)
}

const steps = [
  { key: 's0', num: 1, emoji: '', favicon: true, titleKey: 'guide.quickstart.step0.title', descKey: 'guide.quickstart.step0.desc' },
  { key: 's1', num: 2, emoji: '🌍', titleKey: 'guide.quickstart.step1.title', descKey: 'guide.quickstart.step1.desc' },
  { key: 's2', num: 3, emoji: '🕸️', titleKey: 'guide.quickstart.step2.title', descKey: 'guide.quickstart.step2.desc' },
  { key: 's3', num: 4, emoji: '⚡', titleKey: 'guide.quickstart.step3.title', descKey: 'guide.quickstart.step3.desc' },
  { key: 's4', num: 5, emoji: '💬', titleKey: 'guide.quickstart.step4.title', descKey: 'guide.quickstart.step4.desc' },
  { key: 's5', num: 6, emoji: '💡', titleKey: 'guide.quickstart.step5.title', descKey: 'guide.quickstart.step5.desc' },
]

function nextStep() {
  if (currentStep.value < steps.length - 1) {
    slideDirection.value = 'slide-next'
    currentStep.value++
  }
}

function prevStep() {
  if (currentStep.value > 0) {
    slideDirection.value = 'slide-prev'
    currentStep.value--
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && lightboxSrc.value) {
    lightboxSrc.value = ''
    return
  }
  if (!props.show || activeTab.value !== 'quickstart') return
  if (e.key === 'ArrowRight') nextStep()
  else if (e.key === 'ArrowLeft') prevStep()
}

watch(lightboxSrc, (val) => {
  document.body.style.overflow = val ? 'hidden' : ''
})

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  document.body.style.overflow = ''
})

function toggleIntent(key: string) {
  const next = new Set(expandedIntents.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedIntents.value = next
}

function toggleGroup(key: string) {
  if (selectedGroup.value === key) {
    selectedGroup.value = null
  } else {
    selectedGroup.value = key
    expandedIntents.value = new Set()
  }
}

// Context help: render markdown for current route
const currentContextHelp = computed(() => {
  try {
    const map = JSON.parse(props.contextHelp ?? '{}')
    const routeName = route.name as string | undefined
    if (!routeName) return ''
    const raw = map[routeName]
    if (!raw?.trim()) return ''
    return DOMPurify.sanitize(marked.parse(raw, { async: false }) as string, {
      ALLOWED_URI_REGEXP: /^(?:(?:https?|data:image\/(png|jpeg|gif|webp);base64,):)/i,
      ADD_URI_SAFE_ATTR: ['src'],
    })
  } catch {
    return ''
  }
})

// Recent / All insight content
const currentInsightContent = computed(() => {
  const raw = insightsSubTab.value === 'recent' ? (props.recentContent ?? '') : (props.allContent ?? '')
  if (!raw.trim()) return ''
  return DOMPurify.sanitize(marked.parse(raw, { async: false }) as string, {
    ALLOWED_URI_REGEXP: /^(?:(?:https?|data:image\/(png|jpeg|gif|webp);base64,):)/i,
    ADD_URI_SAFE_ATTR: ['src'],
  })
})

function onMarkdownClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target.tagName === 'IMG' && (target as HTMLImageElement).src) {
    lightboxSrc.value = (target as HTMLImageElement).src
  }
}

const personaGroups = [
  {
    key: 'creator',
    emoji: '🎨',
    nameKey: 'guide.group.creator.name',
    descKey: 'guide.group.creator.desc',
    intents: [
      { key: 'immerse', nameKey: 'guide.intent.immerse.name', descKey: 'guide.intent.immerse.desc', lineKeys: ['guide.intent.immerse.line1', 'guide.intent.immerse.line2', 'guide.intent.immerse.line3'] },
      { key: 'altplot', nameKey: 'guide.intent.altplot.name', descKey: 'guide.intent.altplot.desc', lineKeys: ['guide.intent.altplot.line1', 'guide.intent.altplot.line2', 'guide.intent.altplot.line3'] },
    ],
  },
  {
    key: 'enthusiast',
    emoji: '⚔️',
    nameKey: 'guide.group.enthusiast.name',
    descKey: 'guide.group.enthusiast.desc',
    intents: [
      { key: 'living', nameKey: 'guide.intent.living.name', descKey: 'guide.intent.living.desc', lineKeys: ['guide.intent.living.line1', 'guide.intent.living.line2', 'guide.intent.living.line3'] },
      { key: 'different', nameKey: 'guide.intent.different.name', descKey: 'guide.intent.different.desc', lineKeys: ['guide.intent.different.line1', 'guide.intent.different.line2', 'guide.intent.different.line3'] },
    ],
  },
  {
    key: 'publisher',
    emoji: '📢',
    nameKey: 'guide.group.publisher.name',
    descKey: 'guide.group.publisher.desc',
    intents: [
      { key: 'ipextend', nameKey: 'guide.intent.ipextend.name', descKey: 'guide.intent.ipextend.desc', lineKeys: ['guide.intent.ipextend.line1', 'guide.intent.ipextend.line2', 'guide.intent.ipextend.line3'] },
      { key: 'inspiration', nameKey: 'guide.intent.inspiration.name', descKey: 'guide.intent.inspiration.desc', lineKeys: ['guide.intent.inspiration.line1', 'guide.intent.inspiration.line2', 'guide.intent.inspiration.line3'] },
    ],
  },
  {
    key: 'casual',
    emoji: '🌟',
    nameKey: 'guide.group.casual.name',
    descKey: 'guide.group.casual.desc',
    intents: [
      { key: 'tryout', nameKey: 'guide.intent.tryout.name', descKey: 'guide.intent.tryout.desc', lineKeys: ['guide.intent.tryout.line1', 'guide.intent.tryout.line2', 'guide.intent.tryout.line3'] },
    ],
  },
]
</script>

<style scoped>
.guide-modal {
  background: var(--bg-card);
  border: none;
  border-radius: var(--radius-lg);
  padding: var(--spacing-xl);
  max-width: 560px;
  width: 95vw;
  box-shadow: var(--shadow-dialog);
  height: 660px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}
/* Header */
.guide-modal__header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  flex-shrink: 0;
}

.guide-modal__icon {
  font-size: 22px;
}

.guide-modal__title {
  flex: 1;
  font-size: var(--font-xl);
  font-family: var(--font-display);
  color: var(--text-primary);
  margin: 0;
}

.guide-modal__close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 18px;
  padding: 4px;
  border-radius: 6px;
  transition: background var(--duration-fast);
}

.guide-modal__close:hover {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

/* Tabs */
.guide-modal__tabs {
  display: flex;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-lg);
  flex-shrink: 0;
}

.guide-modal__tab {
  flex: 1;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius-sm);
  background: var(--bg-main);
  color: var(--text-secondary);
  font-size: var(--font-md);
  cursor: pointer;
  transition: all var(--duration-fast);
}

.guide-modal__tab:hover {
  background: var(--bg-card-hover);
}

.guide-modal__tab--active {
  background: var(--accent-dim);
  color: var(--accent);
  border-color: var(--accent);
}

.guide-modal__tab--disabled {
  opacity: 0.45;
  cursor: not-allowed;
  pointer-events: none;
}

.guide-modal__tab-check {
  margin-left: 4px;
  color: var(--accent);
  font-weight: 700;
}

/* Content */
.guide-modal__content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: visible;
}

.guide-modal__content--persona {
  overflow-y: auto;
  padding: 2px 0;
}

/* Progress bar */
.slide-progress {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  position: relative;
  padding-top: 4px;
  margin-bottom: var(--spacing-xl);
  padding-bottom: var(--spacing-md);
}

.slide-progress__bar {
  position: absolute;
  bottom: 0;
  left: 16px;
  right: 16px;
  height: 3px;
  background: var(--border);
  border-radius: 2px;
  z-index: 0;
}

.slide-progress__fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.4s ease;
}

.slide-progress__seg {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  position: relative;
  z-index: 1;
}

.slide-progress__dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-main);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-xs);
  font-weight: 700;
  color: var(--text-muted);
  transition: all 0.3s ease;
}

.slide-progress__seg--done .slide-progress__dot {
  border-color: var(--accent);
  color: var(--accent);
}

.slide-progress__seg--active .slide-progress__dot {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  transform: scale(1.15);
}

.slide-progress__label {
  font-size: var(--font-xs);
  color: var(--text-muted);
  white-space: normal;
  text-align: center;
  line-height: 1.3;
  max-width: 72px;
  transition: color 0.3s ease;
}

.slide-progress__seg--active .slide-progress__label {
  color: var(--accent);
  font-weight: 600;
}

.slide-progress__seg--done .slide-progress__label {
  color: var(--text-secondary);
}

/* Slide stage */
.slide-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.slide {
  text-align: center;
  padding: var(--spacing-md);
}

.slide__emoji {
  font-size: 56px;
  margin-bottom: var(--spacing-md);
  animation: slide-emoji-in 0.5s ease-out;
}
.slide__emoji--img {
  font-size: 0;
  line-height: 0;
}

@keyframes slide-emoji-in {
  0% { transform: scale(0.6); opacity: 0; }
  60% { transform: scale(1.1); }
  100% { transform: scale(1); opacity: 1; }
}

.slide__title {
  font-size: var(--font-xl);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: var(--spacing-sm);
  font-family: var(--font-display);
}

.slide__desc {
  font-size: var(--font-md);
  color: var(--text-secondary);
  line-height: 1.7;
  max-width: 360px;
  margin: 0 auto;
}

/* Slide transitions */
.slide-next-enter-active,
.slide-next-leave-active,
.slide-prev-enter-active,
.slide-prev-leave-active {
  transition: all 0.3s ease;
}

.slide-next-enter-from {
  transform: translateX(40px);
  opacity: 0;
}

.slide-next-leave-to {
  transform: translateX(-40px);
  opacity: 0;
}

.slide-prev-enter-from {
  transform: translateX(-40px);
  opacity: 0;
}

.slide-prev-leave-to {
  transform: translateX(40px);
  opacity: 0;
}

/* Slide navigation */
.slide-nav {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--spacing-lg);
  padding-top: var(--spacing-sm);
}

.slide-nav__dots {
  display: flex;
  gap: 8px;
}

.slide-nav__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border);
  cursor: pointer;
  transition: all 0.3s ease;
}

.slide-nav__dot--active {
  background: var(--accent);
  transform: scale(1.3);
}

.slide-nav__btn {
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-sm);
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--bg-main);
  color: var(--text-secondary);
  font-size: var(--font-sm);
  cursor: pointer;
  transition: all var(--duration-fast);
  white-space: nowrap;
}

.slide-nav__btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}

.slide-nav__btn--next,
.slide-nav__btn--start {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.slide-nav__btn--next:hover,
.slide-nav__btn--start:hover {
  background: var(--accent-hover);
  color: #fff;
}
/* Persona stack (Tab 2) */
.persona-stack {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.persona-card {
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  cursor: pointer;
  transition: border-color var(--duration-fast);
  overflow: hidden;
}

.persona-card:hover {
  border-color: var(--accent);
}

.persona-card--selected {
  border-color: var(--accent);
  background: var(--accent-dim);
}

.persona-card__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-md);
}

.persona-card__emoji {
  font-size: 24px;
  flex-shrink: 0;
}

.persona-card__info {
  flex: 1;
}

.persona-card__name {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.persona-card__desc {
  font-size: var(--font-xs);
  color: var(--text-muted);
  line-height: 1.4;
}

.persona-card__arrow {
  font-size: var(--font-xs);
  color: var(--text-muted);
  transition: transform 0.2s ease;
  flex-shrink: 0;
}

.persona-card__arrow--open {
  transform: rotate(180deg);
}

.persona-card__intents {
  padding: 0 var(--spacing-md) var(--spacing-md);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

/* Intent item (inside card) */
.intent-item {
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--bg-main);
  transition: all var(--duration-fast);
}

.intent-item:hover {
  border-color: var(--accent);
}

.intent-item--expanded {
  border-color: var(--accent);
}

.intent-item__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.intent-item__name {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
}

.intent-item__arrow {
  font-size: var(--font-xs);
  color: var(--text-muted);
  flex-shrink: 0;
}

.intent-item__desc {
  font-size: var(--font-xs);
  color: var(--text-muted);
  margin-top: 2px;
}

.intent-item__lines {
  padding-top: var(--spacing-xs);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.intent-item__line {
  font-size: var(--font-xs);
  color: var(--text-secondary);
  line-height: 1.5;
  padding-left: 14px;
  position: relative;
}

.intent-item__line::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.6;
}

/* Slide-down transition */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  max-height: 0;
}

.slide-down-enter-to,
.slide-down-leave-from {
  max-height: 500px;
}

/* Footer */
.guide-modal__footer {
  text-align: center;
  flex-shrink: 0;
  padding-top: var(--spacing-md);
}

/* Skip link */
.guide-modal__skip {
  text-align: center;
  flex-shrink: 0;
  padding-top: var(--spacing-sm);
  padding-bottom: var(--spacing-xs);
}

.guide-modal__skip-btn {
  background: none;
  border: none;
  color: var(--accent);
  font-size: var(--font-xs);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
  transition: opacity var(--duration-fast);
}

.guide-modal__skip-btn:hover {
  opacity: 0.8;
}

.guide-modal__done {
  padding: var(--spacing-sm) var(--spacing-xl);
  border-radius: var(--radius-sm);
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--accent);
  color: #fff;
  font-size: var(--font-md);
  cursor: pointer;
  transition: background var(--duration-fast);
}

.guide-modal__done:hover {
  background: var(--accent-hover);
}

.guide-modal__done:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* Insights sub-tabs */
.insights-subtabs {
  display: flex;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-md);
  flex-shrink: 0;
  flex-wrap: wrap;
  padding: 2px 0;
}

.guide-modal__tab--sub {
  flex: unset;
  padding: var(--spacing-xs) var(--spacing-md);
  font-size: var(--font-sm);
}

/* Insights content */
.guide-modal__content--insights {
  overflow-y: auto;
  padding: 4px 0;
}

.insights-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.insights-markdown {
  font-size: var(--font-sm);
  color: var(--text-secondary);
  line-height: 1.7;
}

.insights-markdown :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: opacity var(--duration-fast);
}

.insights-markdown :deep(img:hover) {
  opacity: 0.85;
}

.insights-markdown :deep(h1),
.insights-markdown :deep(h2),
.insights-markdown :deep(h3) {
  color: var(--text-primary);
  margin-top: var(--spacing-md);
  margin-bottom: var(--spacing-xs);
  font-family: var(--font-display);
}

.insights-markdown :deep(h1) { font-size: var(--font-xl); }
.insights-markdown :deep(h2) { font-size: var(--font-lg); }
.insights-markdown :deep(h3) { font-size: var(--font-md); }

.insights-markdown :deep(p) {
  margin-bottom: var(--spacing-sm);
}

.insights-markdown :deep(ul),
.insights-markdown :deep(ol) {
  padding-left: var(--spacing-lg);
  margin-bottom: var(--spacing-sm);
}

.insights-markdown :deep(li) {
  margin-bottom: 4px;
}

.insights-markdown :deep(code) {
  background: var(--bg-main);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 0.9em;
}

.insights-markdown :deep(blockquote) {
  border-left: 3px solid rgba(0,0,0,0.08);
  padding-left: var(--spacing-md);
  color: var(--text-muted);
  margin: var(--spacing-sm) 0;
}

.insights-markdown :deep(a) {
  color: var(--accent);
  text-decoration: none;
}

.insights-markdown :deep(a:hover) {
  text-decoration: underline;
}

.insights-empty {
  text-align: center;
  color: var(--text-muted);
  padding: var(--spacing-2xl) 0;
  font-size: var(--font-sm);
}

/* Image lightbox */
.guide-lightbox {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.guide-lightbox__img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: var(--radius-sm);
  cursor: default;
}

.guide-lightbox__close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: rgba(0, 0, 0, 0.5);
  border: none;
  color: #fff;
  font-size: 20px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.guide-lightbox__close:hover {
  background: rgba(0, 0, 0, 0.7);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Onboarding hint animations */
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 4px 1px var(--accent); }
  50% { box-shadow: 0 0 12px 4px var(--accent); }
}

.guide-modal__tab--hint {
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.guide-modal__done--hint {
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.slide-nav__btn--hint {
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.persona-card--hint {
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.intent-item--hint {
  animation: pulse-glow 1.5s ease-in-out infinite;
}
</style>
