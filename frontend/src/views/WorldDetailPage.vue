<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, nextTick, watch, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getWorld, updatePlotSummary, updateCommonSense, updatePlotDevelopment, updateCoreConflict, updateToneAndAtmosphere, updateWorldTitle } from '@/api/worlds'
import { listCharacters } from '@/api/characters'
import { listRelations } from '@/api/relations'
import { getGraphData, getGraphConfig } from '@/api/graph'
import type { WorldDoc } from '@/types/world'
import type { Character } from '@/types/character'
import type { Relation } from '@/types/relation'
import type { GraphDataResponse } from '@/api/graph'
import LoadingState from '@/components/common/LoadingState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import MarkdownText from '@/components/common/MarkdownText.vue'
import ElementFilter from '@/components/elements/ElementFilter.vue'
import ElementCard from '@/components/elements/ElementCard.vue'
import ElementFormModal from '@/components/elements/ElementFormModal.vue'
import WorldImportModal from '@/components/import/WorldImportModal.vue'
import GraphImportModal from '@/components/import/GraphImportModal.vue'
import ElementImportModal from '@/components/import/ElementImportModal.vue'
import { NTabs, NTabPane, NButton, NSpace, NCard, NTag, NModal, NForm, NFormItem, NRadioGroup, NRadio, NProgress, NDivider, NInput, NDropdown, useMessage } from 'naive-ui'
import { useProposalManagement } from '@/composables/useProposalManagement'
import { useGraphBuild } from '@/composables/useGraphBuild'
import { useElementCrud } from '@/composables/useElementCrud'
import { parseApiError } from '@/utils/apiError'
import { useLocale } from '@/composables/useLocale'

const GraphCanvas = defineAsyncComponent(() => import('@/components/graph/GraphCanvas.vue'))
const graphCanvasRef = ref<InstanceType<typeof GraphCanvas> | null>(null)
const CommandBar = defineAsyncComponent(() => import('@/components/graph/CommandBar.vue'))
const ManualEditPanel = defineAsyncComponent(() => import('@/components/graph/ManualEditPanel.vue'))
const VersionHistoryTab = defineAsyncComponent(() => import('@/components/VersionHistoryTab.vue'))

const HOSTNAME_LABELS: Array<[RegExp, string]> = [
  [/moegirl\.org\.cn$/, '萌娘百科'],
  [/baike\.baidu\.com$/, '百度百科'],
  [/zh\.wikipedia\.org$/, '维基百科（中文）'],
  [/ja\.wikipedia\.org$/, '维基百科（日文）'],
  [/en\.wikipedia\.org$/, 'Wikipedia'],
  [/wikipedia\.org$/, '维基百科'],
  [/fandom\.com$/, 'Fandom'],
]

function getUrlLabel(url: string): string {
  try {
    const { hostname } = new URL(url)
    for (const [pattern, label] of HOSTNAME_LABELS) {
      if (pattern.test(hostname)) return label
    }
    return hostname
  } catch {
    return url.slice(0, 30)
  }
}

const props = defineProps<{ id: string }>()
const router = useRouter()
const { t } = useI18n()
const messageApi = useMessage()
const { locale } = useLocale()

const world = ref<WorldDoc | null>(null)

const sourceUrlLabels = computed(() => {
  const urls = world.value?.source.source_urls ?? []
  const labelCount: Record<string, number> = {}
  const labelIndex: Record<string, number> = {}
  for (const url of urls) {
    const label = getUrlLabel(url)
    labelCount[label] = (labelCount[label] ?? 0) + 1
  }
  return urls.map(url => {
    const label = getUrlLabel(url)
    if (labelCount[label] > 1) {
      labelIndex[label] = (labelIndex[label] ?? 0) + 1
      return { url, label: `${label} ${labelIndex[label]}` }
    }
    return { url, label }
  })
})

const showSubUrls = ref(false)
const subSourceUrlLabels = computed(() => {
  const urls = world.value?.source.sub_source_urls ?? []
  return urls.map(url => ({ url, label: getUrlLabel(url) }))
})
const characters = ref<Character[]>([])
const relations = ref<Relation[]>([])
const commandBarActive = ref(false)
const sideTab = ref<'manual' | 'command'>('manual')
const mobilePanelOpen = ref(false)
const loading = ref(true)
const error = ref<string | null>(null)
const currentTab = ref('graph')
const editingTitle = ref(false)
const tempTitle = ref('')
const titleInputRef = ref<HTMLInputElement | null>(null)

watch(editingTitle, async (val) => {
  if (val && world.value) {
    tempTitle.value = world.value.source.title || ''
    await nextTick()
    titleInputRef.value?.focus()
  }
})

const {
  generating,
  onGenerateCharacters,
} = useProposalManagement(props.id, async () => {
  characters.value = await listCharacters(props.id)
  graphLoaded.value = false
})

// Graph tab lazy loading
const graphLoaded = ref(false)
const zepAvailable = ref(false)

// M6: Graph build state (composable)
const {
  graphStatus,
  graphBuildProgress,
  graphBuildMessage,
  graphBuilding,
  onBuildGraph: _onBuildGraph,
} = useGraphBuild(props.id, async () => {
  graphLoaded.value = false
  await onTabChange('graph')
})

async function onBuildGraph() {
  await _onBuildGraph()
}

// Element tab state (composable)
const {
  selectedCategory,
  showElementModal,
  editingElement,
  elementCategories,
  filteredElements,
  openAddElement,
  openEditElement,
  handleElementSave,
  handleDeleteElement,
} = useElementCrud(props.id, world)

const showGenerateDialog = ref(false)
const generateScale = ref<'standard' | 'detailed' | 'deep' | 'all'>('standard')

// Import modals
const showWorldImport = ref(false)
const showGraphImport = ref(false)
const showElementImport = ref(false)

function onDataReloaded() {
  window.location.reload()
}

function openGenerateDialog() {
  if (generating.value) return
  showGenerateDialog.value = true
}

function closeGenerateDialog() {
  if (generating.value) return
  showGenerateDialog.value = false
}

async function confirmGenerateCharacters() {
  await onGenerateCharacters(generateScale.value)
  showGenerateDialog.value = false
}

const plotSummary = computed(() => world.value?.source.plot_summary ?? '')

const plotExpanded = ref(false)
const plotOverflowing = ref(false)
const plotContentRef = ref<HTMLElement | null>(null)
const editingPlot = ref(false)
const plotDraft = ref('')
const plotSaving = ref(false)

function checkPlotOverflow() {
  // Only re-measure while collapsed: the collapsed max-height is what caps
  // clientHeight, so comparing against scrollHeight tells us whether the
  // full text would exceed 3 lines. Skip while expanded so the button
  // doesn't disappear mid-read if a resize momentarily removes the clip.
  if (plotExpanded.value) return
  const el = plotContentRef.value
  plotOverflowing.value = !!el && el.scrollHeight - el.clientHeight > 1
}

let plotResizeObserver: ResizeObserver | null = null

// The "世界" tab isn't the default active tab, and NTabPane doesn't render
// inactive panes — plotContentRef is null until the user switches to this
// tab (or later, if the plot summary loads while already on it). Watching
// the ref itself (rather than only onMounted) catches the element whenever
// it actually appears.
watch(plotContentRef, (el) => {
  plotResizeObserver?.disconnect()
  plotResizeObserver = null
  if (!el) return
  checkPlotOverflow()
  if (window.ResizeObserver) {
    plotResizeObserver = new ResizeObserver(checkPlotOverflow)
    plotResizeObserver.observe(el)
  }
})

onBeforeUnmount(() => {
  plotResizeObserver?.disconnect()
})

watch(plotSummary, async () => {
  plotExpanded.value = false
  await nextTick()
  checkPlotOverflow()
})

function startEditPlot() {
  plotDraft.value = plotSummary.value
  editingPlot.value = true
}

function cancelEditPlot() {
  editingPlot.value = false
}

async function savePlot() {
  if (!world.value) return
  plotSaving.value = true
  try {
    await updatePlotSummary(world.value.world_id, plotDraft.value)
    world.value.source.plot_summary = plotDraft.value
    editingPlot.value = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    plotSaving.value = false
  }
}

// Common sense state
const commonSenseText = computed(() => world.value?.source.common_sense ?? '')
const editingCommonSense = ref(false)
const commonSenseDraft = ref('')
const commonSenseSaving = ref(false)

function startEditCommonSense() {
  commonSenseDraft.value = commonSenseText.value
  editingCommonSense.value = true
}

function cancelEditCommonSense() {
  editingCommonSense.value = false
}

async function saveCommonSense() {
  if (!world.value) return
  commonSenseSaving.value = true
  try {
    await updateCommonSense(world.value.world_id, commonSenseDraft.value)
    world.value.source.common_sense = commonSenseDraft.value
    editingCommonSense.value = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    commonSenseSaving.value = false
  }
}

// Plot development state
const plotDevelopmentText = computed(() => world.value?.source.plot_development ?? '')
const editingPlotDevelopment = ref(false)
const plotDevelopmentDraft = ref('')
const plotDevelopmentSaving = ref(false)

function startEditPlotDevelopment() {
  plotDevelopmentDraft.value = plotDevelopmentText.value
  editingPlotDevelopment.value = true
}

function cancelEditPlotDevelopment() {
  editingPlotDevelopment.value = false
}

async function savePlotDevelopment() {
  if (!world.value) return
  plotDevelopmentSaving.value = true
  try {
    await updatePlotDevelopment(world.value.world_id, plotDevelopmentDraft.value)
    world.value.source.plot_development = plotDevelopmentDraft.value
    editingPlotDevelopment.value = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    plotDevelopmentSaving.value = false
  }
}

// Core conflict state
const coreConflictText = computed(() => world.value?.source.core_conflict ?? '')
const editingCoreConflict = ref(false)
const coreConflictDraft = ref('')
const coreConflictSaving = ref(false)

function startEditCoreConflict() {
  coreConflictDraft.value = coreConflictText.value
  editingCoreConflict.value = true
}

function cancelEditCoreConflict() {
  editingCoreConflict.value = false
}

async function saveCoreConflict() {
  if (!world.value) return
  coreConflictSaving.value = true
  try {
    await updateCoreConflict(world.value.world_id, coreConflictDraft.value)
    world.value.source.core_conflict = coreConflictDraft.value
    editingCoreConflict.value = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    coreConflictSaving.value = false
  }
}

// Tone and atmosphere state
const toneAndAtmosphereText = computed(() => world.value?.source.tone_and_atmosphere ?? '')
const editingToneAndAtmosphere = ref(false)
const toneAndAtmosphereDraft = ref('')
const toneAndAtmosphereSaving = ref(false)

function startEditToneAndAtmosphere() {
  toneAndAtmosphereDraft.value = toneAndAtmosphereText.value
  editingToneAndAtmosphere.value = true
}

function cancelEditToneAndAtmosphere() {
  editingToneAndAtmosphere.value = false
}

async function saveToneAndAtmosphere() {
  if (!world.value) return
  toneAndAtmosphereSaving.value = true
  try {
    await updateToneAndAtmosphere(world.value.world_id, toneAndAtmosphereDraft.value)
    world.value.source.tone_and_atmosphere = toneAndAtmosphereDraft.value
    editingToneAndAtmosphere.value = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  } finally {
    toneAndAtmosphereSaving.value = false
  }
}

async function saveWorldTitle() {
  if (!world.value || !tempTitle.value.trim()) {
    editingTitle.value = false
    return
  }
  try {
    await updateWorldTitle(props.id, tempTitle.value.trim())
    world.value.source.title = tempTitle.value.trim()
    editingTitle.value = false
  } catch (e) {
    messageApi.error(parseApiError(e, t))
  }
}

function cancelTitleEdit() {
  editingTitle.value = false
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString(locale.value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Share link state — not available in target (open-source fork excludes sharing)
const shareCode = ref('')
const shareUrl = ref('')
const sharingLoading = ref(false)
const sharePermission = ref('view_only')
const shareDropdownOptions = ref([])
function onShareDropdownSelect() {}
async function onGenerateShare() {}
async function onRevokeShare() {}

function goBack() {
  router.push('/worlds')
}

function goToChat() {
  router.push(`/world/${props.id}/chat`)
}

async function loadBaseData() {
  loading.value = true
  error.value = null
  try {
    const [w, chars, rels, config] = await Promise.all([
      getWorld(props.id),
      listCharacters(props.id),
      listRelations(props.id).catch(() => []),
      getGraphConfig(props.id).catch(() => ({ zep_available: false })),
    ])
    world.value = w
    // share_permission not available in target
    sharePermission.value = 'view_only'
    characters.value = chars
    relations.value = rels
    zepAvailable.value = config.zep_available
    graphLoaded.value = true // loadBaseData 已加载角色/关系，避免 onTabChange 重复拉取
  } catch (e) {
    error.value = parseApiError(e, t)
  } finally {
    loading.value = false
  }
}

function onImportClick() {
  if (currentTab.value === 'world') showWorldImport.value = true
  else if (currentTab.value === 'graph') showGraphImport.value = true
  else if (currentTab.value === 'elements') showElementImport.value = true
}

async function onTabChange(name: string) {
  currentTab.value = name
  if (name === 'graph' && !graphLoaded.value) {
    try {
      const data: GraphDataResponse = await getGraphData(props.id)
      characters.value = data.characters
      relations.value = data.relations
      graphStatus.value = data.graph_status || 'idle'
      graphLoaded.value = true
    } catch (e) {
      console.error('Failed to load graph data:', e)
    }
  }
}

async function onCommandApplied() {
  // 命令应用后刷新图谱数据
  try {
    const data: GraphDataResponse = await getGraphData(props.id)
    characters.value = data.characters
    relations.value = data.relations
  } catch (e) {
    console.error('Failed to reload graph data:', e)
  }
}

function onCharacterAdded(c: Character) {
  characters.value.push(c)
}

function onCharacterDeleted(id: string) {
  const idx = characters.value.findIndex(c => c.id === id)
  if (idx >= 0) characters.value.splice(idx, 1)
  relations.value = relations.value.filter(r => r.character_a !== id && r.character_b !== id)
  graphCanvasRef.value?.clearSelectionIfMatches(id)
}

function onRelationAdded(r: Relation) {
  relations.value.push(r)
}

function onRelationUpdated(r: Relation) {
  const idx = relations.value.findIndex(x => x.id === r.id)
  if (idx >= 0) relations.value[idx] = r
}

function onRelationDeleted(id: string) {
  const idx = relations.value.findIndex(r => r.id === id)
  if (idx >= 0) relations.value.splice(idx, 1)
  graphCanvasRef.value?.clearSelectionIfMatches(id)
}

onMounted(async () => {
  await loadBaseData()
})
</script>

<template>
  <div class="world-detail">
    <div class="world-detail__header">
      <div class="world-detail__header-left">
        <button class="world-detail__back" @click="goBack">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="world-detail__back-text">{{ $t('worldDetail.back') }}</span>
        </button>
        <div class="world-detail__accent" />
        <div>
          <h1 class="world-detail__title" @dblclick="editingTitle = true">
            <input
              v-show="editingTitle"
              v-model="tempTitle"
              autocomplete="off"
              @blur="saveWorldTitle"
              @keyup.enter="saveWorldTitle"
              @keyup.escape.prevent="cancelTitleEdit"
              class="world-detail__title-input"
              ref="titleInputRef"
            />
            <span v-show="!editingTitle">{{ world?.source.title ?? $t('common.loading') }}</span>
          </h1>
          <div v-if="world" class="world-detail__meta-row">
            <span v-if="world.source.author" class="world-detail__meta-item">{{ world.source.author }}</span>
            <span v-if="world.source.type && world.source.type !== 'template'" class="world-detail__meta-item">{{ world.source.type }}</span>
            <span v-if="world.source.detected_work_type" class="world-detail__meta-item">{{ world.source.detected_work_type }}</span>
            <span class="world-detail__meta-item">{{ characters.length }} {{ $t('worldList.characters') }}</span>
            <span class="world-detail__meta-item">{{ relations.length }} {{ $t('worldList.relations') }}</span>
            <span class="world-detail__meta-item">{{ filteredElements.length }} {{ $t('worldList.elements') }}</span>
          </div>
          <div v-if="sourceUrlLabels.length" class="world-detail__source-urls">
            <a
              v-for="item in sourceUrlLabels"
              :key="item.url"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
              class="world-detail__source-url"
              :title="item.url"
            >{{ item.label }}</a>
            <button
              v-if="subSourceUrlLabels.length"
              class="world-detail__sub-url-toggle"
              @click="showSubUrls = !showSubUrls"
            >{{ showSubUrls ? $t('worldDetail.hideSubUrls') : $t('worldDetail.showSubUrls', { count: subSourceUrlLabels.length }) }}</button>
          </div>
          <div v-if="showSubUrls && subSourceUrlLabels.length" class="world-detail__sub-urls">
            <a
              v-for="item in subSourceUrlLabels"
              :key="item.url"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
              class="world-detail__source-url"
              :title="item.url"
            >{{ item.label }}</a>
          </div>
        </div>
      </div>
      <div class="world-detail__header-right">
        <NButton
          size="small"
          quaternary
          :loading="generating"
          :disabled="generating"
          @click="openGenerateDialog"
        >
          {{ $t('worldDetail.regenerateCharacters') }}
        </NButton>

        <!-- Share link (hidden — feature not available in open-source fork) -->
        <template v-if="false"></template>

        <NButton type="primary" size="small" @click="goToChat">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M2 3h12v9H4l-2 2V3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>
              <path d="M5 6.5h6M5 8.5h4" stroke="currentColor" stroke-width="1" stroke-linecap="round" opacity="0.6"/>
            </svg>
          </template>
          {{ $t('worldDetail.toChat') }}
        </NButton>
      </div>
    </div>

    <div class="world-detail__content">
      <LoadingState v-if="loading" :rows="5" />
      <ErrorState v-else-if="error" :message="error" @retry="loadBaseData" />
      <template v-else-if="world">
        <NTabs
          type="line"
          :value="currentTab"
          @update:value="onTabChange"
          class="world-detail__tabs"
        >
          <NTabPane name="world" :tab="$t('worldDetail.tabWorld')">
            <div class="world-info-tab">
              <NCard size="small" :bordered="false">
                <div class="world-wiki-section">
                  <div class="world-wiki-header">
                    <h3 class="world-section-title">{{ $t('worldDetail.worldDescription') }}</h3>
                    <NSpace :size="6">
                      <NButton v-if="!editingPlot" size="tiny" quaternary @click="startEditPlot">
                      {{ $t('common.edit') }}
                    </NButton>
                    </NSpace>
                  </div>
                  <template v-if="editingPlot">
                    <NInput
                      v-model:value="plotDraft"
                      type="textarea"
                      :autosize="{ minRows: 5, maxRows: 15 }"
                      class="world-wiki-editor"
                    />
                    <NSpace :size="8" style="margin-top: 8px">
                      <NButton size="small" type="primary" :loading="plotSaving" @click="savePlot">
                        {{ $t('common.save') }}
                      </NButton>
                      <NButton size="small" quaternary @click="cancelEditPlot">
                        {{ $t('common.cancel') }}
                      </NButton>
                    </NSpace>
                  </template>
                  <div v-else-if="plotSummary" class="world-wiki-content-wrapper">
                    <div
                      ref="plotContentRef"
                      class="world-wiki-content"
                      :class="{
                        'world-wiki-content--collapsed': !plotExpanded,
                        'world-wiki-content--has-btn': plotOverflowing,
                      }"
                    >
                      {{ plotSummary }}
                    </div>
                    <button
                      v-if="plotOverflowing"
                      class="world-wiki-expand-btn world-wiki-expand-btn--overlay"
                      @click="plotExpanded = !plotExpanded"
                    >
                      {{ plotExpanded ? $t('common.collapse') : $t('common.expand') }}
                    </button>
                  </div>
                  <div v-else class="world-wiki-empty">
                    {{ $t('worldDetail.noPlotSummary') }}
                  </div>
                </div>

                <div class="world-common-sense-section">
                  <div class="world-wiki-header">
                    <h3 class="world-section-title">{{ $t('worldDetail.commonSense') }}</h3>
                    <NButton v-if="!editingCommonSense" size="tiny" quaternary @click="startEditCommonSense">
                      {{ $t('common.edit') }}
                    </NButton>
                  </div>
                  <template v-if="editingCommonSense">
                    <NInput
                      v-model:value="commonSenseDraft"
                      type="textarea"
                      :autosize="{ minRows: 5, maxRows: 15 }"
                      :placeholder="$t('worldDetail.addCommonSense')"
                    />
                    <NSpace :size="8" style="margin-top: 8px">
                      <NButton size="small" type="primary" :loading="commonSenseSaving" @click="saveCommonSense">
                        {{ $t('common.save') }}
                      </NButton>
                      <NButton size="small" quaternary @click="cancelEditCommonSense">
                        {{ $t('common.cancel') }}
                      </NButton>
                    </NSpace>
                  </template>
                  <MarkdownText v-else-if="commonSenseText" class="common-sense-display" :text="commonSenseText" />
                  <div v-else class="world-wiki-empty">
                    {{ $t('worldDetail.noCommonSense') }}
                  </div>
                </div>

                <div class="world-common-sense-section">
                  <div class="world-wiki-header">
                    <h3 class="world-section-title">{{ $t('worldDetail.plotDevelopment') }}</h3>
                    <NButton v-if="!editingPlotDevelopment" size="tiny" quaternary @click="startEditPlotDevelopment">
                      {{ $t('common.edit') }}
                    </NButton>
                  </div>
                  <template v-if="editingPlotDevelopment">
                    <NInput
                      v-model:value="plotDevelopmentDraft"
                      type="textarea"
                      :autosize="{ minRows: 5, maxRows: 15 }"
                      :placeholder="$t('worldDetail.addPlotDevelopment')"
                    />
                    <NSpace :size="8" style="margin-top: 8px">
                      <NButton size="small" type="primary" :loading="plotDevelopmentSaving" @click="savePlotDevelopment">
                        {{ $t('common.save') }}
                      </NButton>
                      <NButton size="small" quaternary @click="cancelEditPlotDevelopment">
                        {{ $t('common.cancel') }}
                      </NButton>
                    </NSpace>
                  </template>
                  <MarkdownText v-else-if="plotDevelopmentText" class="common-sense-display" :text="plotDevelopmentText" />
                  <div v-else class="world-wiki-empty">
                    {{ $t('worldDetail.noPlotDevelopment') }}
                  </div>
                </div>

                <div class="world-common-sense-section">
                  <div class="world-wiki-header">
                    <h3 class="world-section-title">{{ $t('worldDetail.coreConflict') }}</h3>
                    <NButton v-if="!editingCoreConflict" size="tiny" quaternary @click="startEditCoreConflict">
                      {{ $t('common.edit') }}
                    </NButton>
                  </div>
                  <template v-if="editingCoreConflict">
                    <NInput
                      v-model:value="coreConflictDraft"
                      type="textarea"
                      :autosize="{ minRows: 5, maxRows: 15 }"
                      :placeholder="$t('worldDetail.addCoreConflict')"
                    />
                    <NSpace :size="8" style="margin-top: 8px">
                      <NButton size="small" type="primary" :loading="coreConflictSaving" @click="saveCoreConflict">
                        {{ $t('common.save') }}
                      </NButton>
                      <NButton size="small" quaternary @click="cancelEditCoreConflict">
                        {{ $t('common.cancel') }}
                      </NButton>
                    </NSpace>
                  </template>
                  <MarkdownText v-else-if="coreConflictText" class="common-sense-display" :text="coreConflictText" />
                  <div v-else class="world-wiki-empty">
                    {{ $t('worldDetail.noCoreConflict') }}
                  </div>
                </div>

                <div class="world-common-sense-section">
                  <div class="world-wiki-header">
                    <h3 class="world-section-title">{{ $t('worldDetail.toneAndAtmosphere') }}</h3>
                    <NButton v-if="!editingToneAndAtmosphere" size="tiny" quaternary @click="startEditToneAndAtmosphere">
                      {{ $t('common.edit') }}
                    </NButton>
                  </div>
                  <template v-if="editingToneAndAtmosphere">
                    <NInput
                      v-model:value="toneAndAtmosphereDraft"
                      type="textarea"
                      :autosize="{ minRows: 5, maxRows: 15 }"
                      :placeholder="$t('worldDetail.addToneAndAtmosphere')"
                    />
                    <NSpace :size="8" style="margin-top: 8px">
                      <NButton size="small" type="primary" :loading="toneAndAtmosphereSaving" @click="saveToneAndAtmosphere">
                        {{ $t('common.save') }}
                      </NButton>
                      <NButton size="small" quaternary @click="cancelEditToneAndAtmosphere">
                        {{ $t('common.cancel') }}
                      </NButton>
                    </NSpace>
                  </template>
                  <MarkdownText v-else-if="toneAndAtmosphereText" class="common-sense-display" :text="toneAndAtmosphereText" />
                  <div v-else class="world-wiki-empty">
                    {{ $t('worldDetail.noToneAndAtmosphere') }}
                  </div>
                </div>

                <div class="world-info-section">
                  <h3 class="world-section-title">{{ $t('worldDetail.worldInfoTitle') }}</h3>
                  <div class="world-info-row">
                    <span class="world-info-label">{{ $t('worldDetail.createdAt') }}:</span>
                    <span class="world-info-value">{{ formatDate(world.meta.created_at) }}</span>
                  </div>
                  <div class="world-info-row">
                    <span class="world-info-label">{{ $t('worldDetail.updatedAt') }}:</span>
                    <span class="world-info-value">{{ formatDate(world.meta.updated_at) }}</span>
                  </div>
                  <div v-if="world.meta.last_analyzed_at" class="world-info-row">
                    <span class="world-info-label">{{ $t('worldDetail.lastAnalyzed') }}:</span>
                    <span class="world-info-value">{{ formatDate(world.meta.last_analyzed_at) }}</span>
                  </div>
                  <div v-if="world.source.author" class="world-info-row">
                    <span class="world-info-label">{{ $t('createWorld.authorLabel') }}:</span>
                    <span class="world-info-value">{{ world.source.author }}</span>
                  </div>
                  <div v-if="world.source.type && world.source.type !== 'template'" class="world-info-row">
                    <span class="world-info-label">{{ $t('createWorld.typeLabel') }}:</span>
                    <span class="world-info-value">{{ world.source.type }}</span>
                  </div>
                  <div v-if="world.source.detected_work_type" class="world-info-row">
                    <span class="world-info-label">{{ $t('worldDetail.workType') }}:</span>
                    <span class="world-info-value">{{ world.source.detected_work_type }}</span>
                  </div>
                </div>
              </NCard>
            </div>
          </NTabPane>

          <NTabPane name="graph" :tab="$t('worldDetail.tabGraph')">
            <!-- M6: Graph build controls -->
            <div v-if="zepAvailable" class="graph-build-bar">
              <NSpace align="center" :size="8">
                <NTag
                  :type="graphStatus === 'completed' ? 'success' : graphStatus === 'building' ? 'info' : graphStatus === 'failed' ? 'error' : 'default'"
                  size="small"
                >
                  {{ graphStatus === 'idle' ? $t('worldDetail.graphStatusIdle') : graphStatus === 'building' ? $t('worldDetail.graphStatusBuilding') : graphStatus === 'completed' ? $t('worldDetail.graphStatusReady') : $t('worldDetail.graphStatusFailed') }}
                </NTag>
                <NButton
                  v-if="graphStatus !== 'building'"
                  size="tiny"
                  type="primary"
                  :loading="graphBuilding"
                  @click="onBuildGraph"
                >
                  {{ graphStatus === 'completed' ? $t('worldDetail.rebuildGraph') : $t('worldDetail.buildGraph') }}
                </NButton>
                <span v-if="graphBuildMessage" class="graph-build-msg">{{ graphBuildMessage }}</span>
              </NSpace>
              <NProgress
                v-if="graphBuilding || graphStatus === 'building'"
                :percentage="graphBuildProgress"
                :show-indicator="true"
                status="info"
                style="margin-top: 6px"
              />
            </div>
            <div class="graph-with-command">
              <GraphCanvas
                v-if="currentTab === 'graph'"
                ref="graphCanvasRef"
                :world-id="id"
                :characters="characters"
                :relations="relations"
                :show-codes="commandBarActive"
                @character-updated="(c) => { const idx = characters.findIndex(x => x.id === c.id); if (idx >= 0) characters[idx] = c }"
                @character-deleted="onCharacterDeleted"
                @relation-updated="onRelationUpdated"
                @relation-deleted="onRelationDeleted"
              />
              <button
                class="mobile-panel-toggle"
                :class="{ open: mobilePanelOpen }"
                @click="mobilePanelOpen = !mobilePanelOpen"
              >
                <svg v-if="!mobilePanelOpen" width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M2 4h12M2 8h8M2 12h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
                <svg v-else width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </button>
              <div v-if="mobilePanelOpen" class="mobile-panel-overlay" @click="mobilePanelOpen = false" />
              <div class="graph-side-panel" :class="{ open: mobilePanelOpen }">
                <div class="side-panel-tabs">
                  <button
                    class="side-panel-tab"
                    :class="{ active: sideTab === 'manual' }"
                    @click="sideTab = 'manual'; commandBarActive = false"
                  >{{ $t('graph.tabManual') }}</button>
                  <button
                    class="side-panel-tab"
                    :class="{ active: sideTab === 'command' }"
                    @click="sideTab = 'command'; commandBarActive = false"
                  >{{ $t('graph.tabCommand') }}</button>
                </div>
                <ManualEditPanel
                  v-if="sideTab === 'manual'"
                  :world-id="id"
                  :characters="characters"
                  @character-added="onCharacterAdded"
                  @relation-added="onRelationAdded"
                  @focus-change="commandBarActive = $event"
                />
                <CommandBar
                  v-else
                  :world-id="id"
                  :characters="characters"
                  @applied="onCommandApplied"
                  @focus-change="commandBarActive = $event"
                />
              </div>
            </div>
          </NTabPane>

          <NTabPane name="elements" :tab="$t('worldDetail.tabElements')">
            <div class="elements-scroll-wrap">
              <div class="elements-tab-sticky">
                <div class="elements-tab-header">
                  <NSpace :size="6">
                    <NButton size="small" type="primary" @click="openAddElement">{{ $t('worldDetail.addElement') }}</NButton>
                  </NSpace>
                </div>
                <ElementFilter
                  :categories="elementCategories"
                  :selected="selectedCategory"
                  @change="(cat: string | null) => selectedCategory = cat"
                />
              </div>
              <div class="elements-card-list">
                <EmptyState
                  v-if="filteredElements.length === 0"
                  :title="$t('worldDetail.noElements')"
                  :description="$t('worldDetail.noElementsFiltered')"
                />
                <template v-else>
                  <ElementCard
                    v-for="el in filteredElements"
                    :key="el.id"
                    :element="el"
                    @edit="openEditElement"
                    @delete="handleDeleteElement"
                  />
                </template>
              </div>
            </div>
          </NTabPane>

          <NTabPane name="versions" :tab="$t('worldDetail.tabVersions')">
            <VersionHistoryTab :world-id="props.id" />
          </NTabPane>

          <template #suffix>
            <NButton
              v-if="currentTab !== 'versions'"
              size="tiny"
              quaternary
              @click="onImportClick"
            >{{ $t('import.importBtn') }}</NButton>
          </template>
        </NTabs>
      </template>
    </div>

    <ElementFormModal
      v-model:show="showElementModal"
      :element="editingElement"
      :default-category="selectedCategory ?? undefined"
      @save="handleElementSave"
    />

    <!-- Import modals -->
    <WorldImportModal
      v-model:show="showWorldImport"
      :world-id="id"
      :world-name="world?.source?.title ?? undefined"
      :on-success="onDataReloaded"
    />
    <GraphImportModal
      v-model:show="showGraphImport"
      :world-id="id"
      :world-name="world?.source?.title ?? undefined"
      :on-success="onDataReloaded"
    />
    <ElementImportModal
      v-model:show="showElementImport"
      :world-id="id"
      :world-name="world?.source?.title ?? undefined"
      :on-success="onDataReloaded"
    />

    <NModal v-model:show="showGenerateDialog" :mask-closable="!generating">
      <NCard :title="$t('worldDetail.generateDialogTitle')" size="small" :bordered="false" style="width: 420px">
        <NForm label-placement="left" label-width="80">
          <NFormItem :label="$t('worldDetail.scaleLabel')">
            <NRadioGroup v-model:value="generateScale" :disabled="generating">
              <NSpace vertical>
                <NRadio value="standard">{{ $t('worldDetail.scaleStandard') }}</NRadio>
                <NRadio value="detailed">{{ $t('worldDetail.scaleDetailed') }}</NRadio>
                <NRadio value="deep">{{ $t('worldDetail.scaleDeep') }}</NRadio>
                <NRadio value="all">{{ $t('worldDetail.scaleAll') }}</NRadio>
              </NSpace>
            </NRadioGroup>
          </NFormItem>
        </NForm>
        <template #footer>
          <NSpace justify="end">
            <NButton :disabled="generating" @click="closeGenerateDialog">{{ $t('common.cancel') }}</NButton>
            <NButton type="primary" :loading="generating" @click="confirmGenerateCharacters">
              {{ $t('worldDetail.startGenerate') }}
            </NButton>
          </NSpace>
        </template>
      </NCard>
    </NModal>
  </div>
</template>

<style scoped>
.world-detail {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 var(--spacing-2xl) var(--spacing-2xl);
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  overscroll-behavior: contain;
  /* background removed to inherit theme base background */
}

.world-detail__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(var(--spacing-xl) + 25px) 0 var(--spacing-lg);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  gap: var(--spacing-md);
}

.world-detail__header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  min-width: 0;
}

.world-detail__back {
  display: flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  padding: 6px 10px;
  border-radius: var(--radius);
  transition: all 0.2s;
  white-space: nowrap;
}

.world-detail__back:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-primary);
}

.world-detail__accent {
  width: 3px;
  height: 36px;
  border-radius: 2px;
  background: var(--gradient-accent);
  flex-shrink: 0;
}

.world-detail__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
  line-height: 1.3;
  cursor: pointer;
}

.world-detail__title-input {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.02em;
  line-height: 1.3;
  border: none;
  background: transparent;
  padding: 0;
  border-radius: 0;
  outline: none;
  width: auto;
  min-width: 200px;
}

.world-detail__meta-row {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.world-detail__meta-item::before {
  content: '';
  display: inline-block;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-muted);
  vertical-align: middle;
  margin-right: 6px;
  opacity: 0.5;
}

.world-detail__meta-item:first-child::before {
  display: none;
}

.world-detail__sources-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.world-detail__sources-label {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.6;
}

.world-detail__source-tag {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  border: 1px solid var(--border-color);
  opacity: 0.8;
}

.world-detail__source-urls {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.world-detail__source-url {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.55;
  text-decoration: none;
  border-bottom: 1px dashed currentColor;
  transition: opacity 0.15s;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.world-detail__source-url:hover {
  opacity: 1;
}

.world-detail__sub-url-toggle {
  font-size: 11px;
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  opacity: 0.7;
  transition: opacity 0.15s;
}

.world-detail__sub-url-toggle:hover {
  opacity: 1;
}

.world-detail__sub-urls {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
  padding-left: 8px;
  border-left: 2px solid rgba(0,0,0,0.08);
  opacity: 0.75;
}

.world-detail__header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.world-detail__share-code {
  font-size: 12px;
  font-family: var(--font-mono, monospace);
  color: var(--text-secondary);
  background: var(--bg-input);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 4px;
  padding: 4px 8px;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.world-detail__share-group {
  display: flex;
  align-items: center;
}

.world-detail__share-group > :first-child {
  border-radius: var(--radius) 0 0 var(--radius);
}

.world-detail__share-dd {
  border-radius: 0 var(--radius) var(--radius) 0;
  padding: 0 6px;
  min-width: unset;
  font-size: 12px;
}

.world-detail__content {
  margin-top: var(--spacing-lg);
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.world-detail__tabs {
  --n-tab-text-color: var(--text-secondary);
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* Naive UI tabs content fills remaining space */
.world-detail__tabs :deep(.n-tabs-nav) {
  flex-shrink: 0;
}

.world-detail__tabs :deep(.n-tabs-content) {
  flex: 1;
  min-height: 0;
}

.world-detail__tabs :deep(.n-tab-pane) {
  height: 100%;
  overflow: hidden;
}

/* World tab: content scrolls within the pane */
.world-detail__tabs :deep(.world-info-tab) {
  height: 100%;
  overflow-y: auto;
}

/* Wrapper fills the tab pane, flex column layout */
.elements-scroll-wrap {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Sticky header: add button + filter tabs, never scrolls */
.elements-tab-sticky {
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 1;
  /* background removed to inherit theme base background */
  padding-bottom: var(--spacing-sm);
}

/* Card list: scrollable area, upper boundary aligns with filter bottom */
.elements-card-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.elements-tab-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--spacing-md);
}

.world-detail__tabs :deep(.element-filter) {
  margin-bottom: 0;
  padding-bottom: var(--spacing-md);
  border-bottom: 1px solid var(--color-border);
}

.graph-with-command {
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.graph-with-command > :first-child {
  flex: 1;
  min-width: 0;
}

.graph-side-panel {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: none;
  border-radius: var(--radius);
  min-height: 0;
}

.side-panel-tabs {
  display: flex;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

.side-panel-tab {
  flex: 1;
  padding: 9px 0;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.side-panel-tab:hover {
  color: var(--text-primary);
}

.side-panel-tab.active {
  color: var(--accent);
  border-bottom-color: rgba(0, 0, 0, 0.15);
}

.graph-build-bar {
  margin-bottom: 8px;
  padding: 8px 12px;
  background: var(--bg-card);
  border: none;
  border-radius: var(--radius);
  font-size: 12px;
}

.graph-build-msg {
  color: var(--text-muted);
  font-size: 11px;
}

/* Graph canvas fills container (match side panel height) */
.graph-with-command :deep(.graph-canvas__wrapper) {
  height: 100%;
  min-height: 0;
  max-height: none;
}

/* Graph controls: share page layout, larger */
.graph-with-command :deep(.graph-canvas__legend) {
  bottom: 10px;
  right: 10px;
  left: auto;
  top: auto;
  padding: 6px 10px;
  font-size: 11px;
  gap: 5px;
}

.graph-with-command :deep(.legend-chip) {
  font-size: 11px;
  padding: 2px 6px;
  gap: 4px;
}

.graph-with-command :deep(.legend-node) {
  transform: scale(0.8);
}

.graph-with-command :deep(.graph-canvas__search) {
  top: 10px;
  left: 10px;
  bottom: auto;
  right: auto;
  gap: 5px;
}

.graph-with-command :deep(.layout-btn) {
  font-size: 11px;
  padding: 3px 7px;
}

.graph-with-command :deep(.legend-search) {
  font-size: 11px;
  padding: 3px 8px;
  width: 110px;
}

/* World info tab styles */
.world-info-tab {
  padding: var(--spacing-md) 0;
}

.world-info-tab :deep(.n-card) {
  border: none;
  border-radius: var(--radius);
}

.world-info-section {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.world-info-row {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
}

.world-info-label {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 500;
  min-width: 120px;
}

.world-info-value {
  font-size: 13px;
  color: var(--text-primary);
}

.world-section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: var(--spacing-lg) 0 var(--spacing-sm) 0;
}

.world-wiki-section {
  margin-top: var(--spacing-lg);
}

.world-wiki-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-sm);
}

.world-wiki-header .world-section-title {
  margin-bottom: 0;
}

.world-wiki-empty {
  font-size: 13px;
  color: var(--text-tertiary);
  padding: var(--spacing-md);
  background: var(--bg-secondary);
  border: 1px dashed rgba(0,0,0,0.12);
  border-radius: var(--radius);
}

.world-wiki-editor {
  width: 100%;
}

.world-wiki-content-wrapper {
  position: relative;
}

.world-wiki-content {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  padding: var(--spacing-md);
  max-height: 500px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  position: relative;
}

.world-wiki-content--has-btn {
  padding-bottom: calc(var(--spacing-md) + 18px);
}

.world-wiki-content--collapsed {
  max-height: calc(1.8em * 3 + var(--spacing-md) * 2);
  overflow: hidden;
}

.world-wiki-content--collapsed.world-wiki-content--has-btn {
  max-height: calc(1.8em * 3 + var(--spacing-md) * 2 + 18px);
}

.world-wiki-content--collapsed::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(transparent, var(--bg-secondary));
  pointer-events: none;
}

.world-wiki-expand-btn {
  display: block;
  margin-top: var(--spacing-xs);
  font-size: 12px;
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  opacity: 0.8;
  transition: opacity 0.15s;
}

.world-wiki-expand-btn--overlay {
  position: absolute;
  right: var(--spacing-md);
  bottom: var(--spacing-xs);
  margin-top: 0;
  padding: 0 4px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
}

.world-wiki-expand-btn:hover {
  opacity: 1;
}

.world-common-sense-section {
  margin-top: var(--spacing-lg);
}

.common-sense-display {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  padding: var(--spacing-md);
  white-space: pre-wrap;
  word-break: break-word;
}

.world-sources-section,
.world-urls-section {
  margin-top: var(--spacing-md);
}

.world-source-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
}

.world-source-urls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
}

.world-source-url {
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px dashed var(--accent);
  transition: all 0.2s;
  padding-bottom: 1px;
}

.world-source-url:hover {
  color: var(--accent-hover, var(--accent));
  border-bottom-color: var(--accent-hover, var(--accent));
}

.world-empty-state {
  font-size: 13px;
  color: var(--text-muted);
  opacity: 0.7;
  padding: var(--spacing-md) 0;
  font-style: italic;
}

/* === INK specific === */
[data-theme="ink"] .world-detail__header {
  border-bottom-color: rgba(20, 212, 168, 0.12);
}
/* Mobile panel toggle — hidden on desktop */
.mobile-panel-toggle {
  display: none;
}

.mobile-panel-overlay {
  display: none;
}

@media (max-width: 768px) {
  .world-detail {
    padding: 0 var(--spacing-sm) var(--spacing-md);
  }

  .world-detail__back-text {
    display: none;
  }

  .world-detail__header {
    padding-top: calc(var(--spacing-xl) + 40px);
    padding-bottom: var(--spacing-sm);
    gap: var(--spacing-sm);
  }

  .world-detail__header-left {
    gap: var(--spacing-sm);
  }

  .world-detail__accent {
    height: 28px;
  }

  .world-detail__title {
    font-size: 17px;
  }

  .world-detail__meta-row {
    gap: 6px;
    margin-top: 2px;
    font-size: 11px;
  }

  .world-detail__meta-item::before {
    margin-right: 4px;
  }

  .world-detail__header-right {
    flex-direction: column;
    align-items: stretch;
    gap: 4px;
  }

  .world-detail__header-right :deep(.n-button) {
    font-size: 12px;
    padding: 0 8px;
    height: 28px;
  }

  /* Graph area: stack vertically, graph gets full space */
  .graph-with-command {
    position: relative;
    flex-direction: column;
  }

  .graph-with-command > :first-child {
    flex: 1;
    min-height: 300px;
  }

  /* 侧边栏 tab 按钮缩小 */
  .side-panel-tab {
    padding: 5px 0;
    font-size: 11px;
  }

  /* Floating toggle button */
  .mobile-panel-toggle {
    display: flex;
    align-items: center;
    justify-content: center;
    position: absolute;
    bottom: 42px;
    right: 12px;
    z-index: 20;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: none;
    background: var(--bg-card);
    color: var(--accent);
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    transition: all 0.2s;
  }

  .mobile-panel-toggle:hover,
  .mobile-panel-toggle.open {
    background: var(--accent);
    color: #fff;
  }

  /* Semi-transparent backdrop */
  .mobile-panel-overlay {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 25;
    background: rgba(0, 0, 0, 0.3);
  }

  /* Side panel → bottom drawer */
  .graph-side-panel {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 30;
    width: 100%;
    max-height: 40vh;
    border: none;
    border-radius: var(--radius);
    background-clip: padding-box;
    transform: translateY(100%);
    transition: transform 0.25s ease;
    overflow-y: auto;
  }

  /* 移动端手动编辑面板：去掉 flex 限制，让内容自然撑开由父容器滚动 */
  .graph-side-panel :deep(.manual-edit) {
    flex: none;
    overflow: visible;
  }

  .graph-side-panel.open {
    transform: translateY(0);
  }
}
</style>

