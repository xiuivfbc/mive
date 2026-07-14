<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Character } from '@/types/character'
import type { Element } from '@/types/world'
import { ELEMENT_CATEGORIES } from '@/types/world'
import type { Participant } from '@/types/chatSession'
import { useCharacterColors } from '@/composables/useCharacterColors'
import { NTooltip } from 'naive-ui'

const props = withDefaults(defineProps<{
  disabled?: boolean
  placeholder?: string
  eventMode?: boolean
  streaming?: boolean
  sending?: boolean
  worldId?: string
  characters?: Character[]
  // Participant management: null = new session (show hint selector), array = active session
  participants?: Participant[] | null
  participantMode?: 'auto' | 'edit'
  // User role: null = 时空旅行者，string = character_id
  userRole?: string | null
  // World user character id — excluded from hint selector (still shown in role picker)
  userCharacterId?: string | null
  // Portrait map: character id -> portrait_url
  characterPortraitMap?: Record<string, string>
  // Advanced options (collapsed by default)
  memoriesEnabled?: boolean
  actionDescriptions?: boolean
  showNarration?: boolean
  elementRerank?: boolean
  sessionStarted?: boolean
  // Element injection
  elementInjectionEnabled?: boolean
  elementInjectionIds?: string[]
  // Constraint
  constraintText?: string
}>(), {
  disabled: false,
  streaming: false,
  sending: false,
  characters: () => [],
  participants: null,
  participantMode: 'auto',
  userRole: null,
  userCharacterId: null,
  characterPortraitMap: () => ({}),
  memoriesEnabled: true,
  actionDescriptions: false,
  showNarration: false,
  elementRerank: false,
  sessionStarted: false,
  elementInjectionEnabled: false,
  elementInjectionIds: () => [],
  constraintText: '',
})

const emit = defineEmits<{
  send: [content: string, participantMode: 'auto' | 'edit' | 'include', participants: Participant[] | null]
  'update:eventMode': [value: boolean]
  'update:participantMode': [value: 'auto' | 'edit']
  'update:participants': [value: Participant[]]
  'update:userRole': [value: string | null]
  'update:memoriesEnabled': [value: boolean]
  'update:actionDescriptions': [value: boolean]
  'update:showNarration': [value: boolean]
  'update:elementRerank': [value: boolean]
  'update:elementInjectionEnabled': [value: boolean]
  'update:elementInjectionIds': [value: string[]]
  'update:constraintText': [value: string]
  interrupt: []
  'avatar-change': [payload: { characterId: string; portraitUrl: string | null }]
}>()

const content = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const chatInputRef = ref<HTMLElement | null>(null)
const showAddPicker = ref(false)
const showRolePicker = ref(false)
const showAdvancedOptions = ref(true)

// --- 元素和约束弹窗 ---
const showElementPicker = ref(false)
const showConstraintModal = ref(false)
const worldElements = ref<Element[]>([])
const elementPickerLoading = ref(false)
const activeElementCategory = ref('')

// --- 约束编辑本地状态 ---
const localConstraintText = ref('')

// --- 角色选择弹窗 ---
const showPickerDialog = ref(false)
const pickerSearchQuery = ref('')
const pickerSearchInput = ref<HTMLInputElement | null>(null)
const pickerMode = ref<'hint' | 'participant'>('hint')
const selectingRole = ref(false)  // true = 列表点击选扮演角色
const MAX_VISIBLE_CHIPS = 12

// --- 头像上传 ---
const fileInputRef = ref<HTMLInputElement | null>(null)
const pendingAvatarCharId = ref<string | null>(null)
const uploadingAvatarId = ref<string | null>(null)

function onAvatarClick(charId: string) {
  pendingAvatarCharId.value = charId
  fileInputRef.value?.click()
}

async function onFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file || !pendingAvatarCharId.value) return
  if (!file.type.startsWith('image/')) {
    window.alert(t('character.invalidFileType'))
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    window.alert(t('character.fileTooLarge'))
    return
  }
  uploadingAvatarId.value = pendingAvatarCharId.value
  try {
    const base64 = await fileToBase64(file)
    emit('avatar-change', { characterId: pendingAvatarCharId.value, portraitUrl: base64 })
  } finally {
    uploadingAvatarId.value = null
    if (fileInputRef.value) fileInputRef.value.value = ''
  }
}

function onClearAvatar(charId: string) {
  emit('avatar-change', { characterId: charId, portraitUrl: null })
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function handleClickOutside(e: MouseEvent) {
  if (!chatInputRef.value?.contains(e.target as Node)) {
    showRolePicker.value = false
    showAddPicker.value = false
  }
}

// 弹窗点击外部关闭（弹窗在 body 上，需要单独处理）
function handlePickerOverlayClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('picker-overlay')) {
    closePicker()
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

const userRoleCharacter = computed(() =>
  props.characters?.find((c) => c.id === props.userRole) ?? null
)

// User role character info for participant list display
const userRoleParticipant = computed<Participant | null>(() => {
  if (!props.userRole) return null
  const char = userRoleCharacter.value
  return char ? { id: char.id, name: char.name } : null
})

function selectUserRole(charId: string | null) {
  emit('update:userRole', charId)
  showRolePicker.value = false
}

// --- New session hint mode (participants == null) ---
// Reuse existing chip selection as LLM hint
const hintSelectedIds = ref<Set<string>>(new Set())
const hintMode = ref<'include' | 'only'>('include')

// --- Edit mode pending changes ---
// Track local edits before send
const pendingParticipants = ref<Participant[] | null>(null)

const localParticipants = computed<Participant[]>(() => {
  const base = pendingParticipants.value !== null ? pendingParticipants.value : (props.participants ?? [])
  // Filter out the user's role character to avoid duplicate chips
  if (props.userRole) {
    return base.filter((p) => p.id !== props.userRole)
  }
  return base
})

const { t } = useI18n()

const { getColor } = useCharacterColors()

const canSend = computed(() => content.value.trim().length > 0)

const resolvedPlaceholder = computed(() => {
  if (props.eventMode === true) return t('chat.eventPlaceholder')
  if (props.eventMode === false) return t('chat.characterPlaceholder')
  return props.placeholder ?? t('chat.defaultPlaceholder')
})

// Tier 排序权重：core > supporting > extra
const TIER_ORDER: Record<string, number> = { core: 0, supporting: 1, extra: 2 }
function tierRank(char: Character): number {
  return TIER_ORDER[char.tier ?? char.profile?.basic?.tier ?? 'extra'] ?? 2
}

// 用户身份选择列表：用户化身在前，其余按 tier 排序
const rolePickerCharacters = computed(() => {
  const chars = props.characters ?? []
  const userChar = props.userCharacterId ? chars.find((c) => c.id === props.userCharacterId) : null
  const others = chars.filter((c) => c.id !== props.userCharacterId).sort((a, b) => tierRank(a) - tierRank(b))
  return userChar ? [userChar, ...others] : others
})

// NPC characters: exclude world user character from hint/add selectors, sorted by tier
const npcCharacters = computed(() =>
  (props.characters ?? [])
    .filter((c) => c.id !== props.userCharacterId)
    .sort((a, b) => tierRank(a) - tierRank(b))
)

// Characters not in current participant list (for add picker)
// npcCharacters already sorted by tier, filter preserves order
// Also exclude the user's current role character (already shown as "you" chip)
const addableCharacters = computed(() =>
  npcCharacters.value.filter(
    (c) => !localParticipants.value.some((p) => p.id === c.id) && c.id !== props.userRole
  )
)

function tierColor(char: Character): string {
  const tier = char.tier ?? char.profile?.basic?.tier
  if (tier === 'core') return 'chip--core'
  if (tier === 'supporting') return 'chip--supporting'
  return 'chip--extra'
}

// --- Hint mode (new session) ---
function toggleHintChar(id: string) {
  if (hintSelectedIds.value.has(id)) hintSelectedIds.value.delete(id)
  else hintSelectedIds.value.add(id)
  hintSelectedIds.value = new Set(hintSelectedIds.value)
}

// --- 折叠显示 ---
const visibleHintChars = computed(() => npcCharacters.value.slice(0, MAX_VISIBLE_CHIPS))
const hiddenHintCount = computed(() => Math.max(0, npcCharacters.value.length - MAX_VISIBLE_CHIPS))

const visibleParticipants = computed(() => {
  // userRole 占一个位置，所以参与者最多显示 MAX_VISIBLE_CHIPS - 1 个
  const maxParticipantChips = props.userRole ? MAX_VISIBLE_CHIPS - 1 : MAX_VISIBLE_CHIPS
  return localParticipants.value.slice(0, maxParticipantChips)
})
const hiddenParticipantCount = computed(() => {
  const maxParticipantChips = props.userRole ? MAX_VISIBLE_CHIPS - 1 : MAX_VISIBLE_CHIPS
  return Math.max(0, localParticipants.value.length - maxParticipantChips)
})

// --- 角色选择弹窗 ---
const TIER_LABELS: Record<string, string> = { core: 'chat.tierCore', supporting: 'chat.tierSupporting', extra: 'chat.tierExtra' }

const groupedCharacters = computed(() => {
  const query = pickerSearchQuery.value.trim().toLowerCase()
  const chars = npcCharacters.value.filter((c) => {
    if (!query) return true
    return c.name.toLowerCase().includes(query)
  })
  const groups: { tier: string; label: string; chars: Character[] }[] = []
  for (const tier of ['core', 'supporting', 'extra']) {
    const tierChars = chars.filter((c) => (c.tier ?? c.profile?.basic?.tier ?? 'extra') === tier)
    if (tierChars.length > 0) {
      groups.push({ tier, label: TIER_LABELS[tier], chars: tierChars })
    }
  }
  return groups
})

function openRolePicker() {
  pickerMode.value = props.participants === null ? 'hint' : 'participant'
  pickerSearchQuery.value = ''
  selectingRole.value = false
  if (props.participants !== null) {
    pendingParticipants.value = null
  }
  showPickerDialog.value = true
  nextTick(() => pickerSearchInput.value?.focus())
}

function closePicker() {
  showPickerDialog.value = false
  pickerSearchQuery.value = ''
}

function toggleCharSelection(char: Character) {
  if (selectingRole.value) {
    const targetId = char.id === props.userRole ? null : char.id
    selectUserRole(targetId)
    // 选择角色时自动在参与列表中打勾
    if (targetId) {
      if (props.participants === null) {
        hintSelectedIds.value.add(targetId)
        hintSelectedIds.value = new Set(hintSelectedIds.value)
      } else {
        const exists = localParticipants.value.some(p => p.id === targetId)
        if (!exists) {
          pendingParticipants.value = [...(pendingParticipants.value ?? props.participants ?? []), { id: char.id, name: char.name }]
        }
      }
    }
    selectingRole.value = false
  } else if (pickerMode.value === 'hint') {
    toggleHintChar(char.id)
  } else {
    if (localParticipants.value.some(p => p.id === char.id)) {
      removeParticipant(char.id)
    } else {
      addParticipant(char)
    }
  }
}

const pickerModeLabel = computed(() => {
  if (props.participants === null) {
    return hintMode.value === 'include' ? t('chat.includeMode') : t('chat.onlyMode')
  }
  return props.participantMode === 'auto' ? t('chat.autoMode') : t('chat.editMode')
})

function togglePickerMode() {
  if (props.participants === null) {
    hintMode.value = hintMode.value === 'only' ? 'include' : 'only'
  } else {
    toggleParticipantMode()
  }
}


// --- Edit mode ---
function removeParticipant(id: string) {
  if (props.participantMode !== 'edit') return
  const base = props.participants ?? []
  pendingParticipants.value = (pendingParticipants.value ?? base).filter((p) => p.id !== id)
}

function addParticipant(char: Character) {
  if (props.participantMode !== 'edit') return
  const base = props.participants ?? []
  pendingParticipants.value = [...(pendingParticipants.value ?? base), { id: char.id, name: char.name }]
  showAddPicker.value = false
}

function toggleParticipantMode() {
  const next: 'auto' | 'edit' = props.participantMode === 'edit' ? 'auto' : 'edit'
  pendingParticipants.value = null
  emit('update:participantMode', next)
}

// --- Input ---
function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function send() {
  if (!canSend.value || props.disabled) return

  let mode: 'auto' | 'edit' | 'include' = props.participantMode ?? 'auto'
  let outParticipants: Participant[] | null = null

  if (props.eventMode || props.participants === null) {
    // Event mode (always) or new session: use hint selection
    if (hintSelectedIds.value.size > 0) {
      const chars = props.characters ?? []
      outParticipants = chars
        .filter((c) => hintSelectedIds.value.has(c.id))
        .map((c) => ({ id: c.id, name: c.name }))
      // 仅含模式：直接用选定角色，跳过选角
      // 包含模式：作为提示，让 LLM 选角
      mode = hintMode.value === 'only' ? 'edit' : 'include'
    }
    hintSelectedIds.value = new Set()
  } else if (mode === 'edit') {
    outParticipants = localParticipants.value
    pendingParticipants.value = null
  }

  emit('send', content.value.trim(), mode, outParticipants)
  content.value = ''
  nextTick(() => {
    if (textareaRef.value) textareaRef.value.style.height = 'auto'
  })
}

function toggleMode() {
  emit('update:eventMode', !props.eventMode)
}

// ── 元素选择器 ────────────────────────────────────────────────────────────────
async function openElementPicker() {
  showElementPicker.value = true
  if (worldElements.value.length === 0 && props.worldId) {
    elementPickerLoading.value = true
    try {
      const { getWorld } = await import('@/api/worlds')
      const w = await getWorld(props.worldId)
      worldElements.value = w.elements ?? []
      if (w.elements?.length && !activeElementCategory.value) {
        const cats = [...new Set(w.elements.map((e: any) => e.category).filter(Boolean))]
        activeElementCategory.value = cats[0] || ''
      }
    } catch {
      // ignore
    } finally {
      elementPickerLoading.value = false
    }
  }
}


const groupedElements = computed(() => {
  const cat = activeElementCategory.value
  if (!cat) return worldElements.value
  return worldElements.value.filter((e: Element) => e.category === cat)
})

const selectedElementIds = computed({
  get: () => props.elementInjectionIds ?? [],
  set: (v: string[]) => emit('update:elementInjectionIds', v),
})

function onElementCheckboxChange(id: string, event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const current = [...selectedElementIds.value]
  if (checked) {
    if (!current.includes(id)) current.push(id)
  } else {
    const idx = current.indexOf(id)
    if (idx !== -1) current.splice(idx, 1)
  }
  selectedElementIds.value = current
}

function clearAllSelectedElements() {
  emit('update:elementInjectionIds', [])
}

function applyElementSelection() {
  emit('update:elementInjectionEnabled', selectedElementIds.value.length > 0)
  showElementPicker.value = false
}

// ── 约束编辑器 ────────────────────────────────────────────────────────────────
function openConstraintModal() {
  localConstraintText.value = props.constraintText ?? ''
  showConstraintModal.value = true
}

function applyConstraint() {
  const trimmed = localConstraintText.value.slice(0, 100)
  emit('update:constraintText', trimmed)
  showConstraintModal.value = false
}
</script>

<template>
  <div
    ref="chatInputRef"
    class="chat-input"
    :class="{
      'is-event': eventMode && !streaming,
      'is-disabled': disabled && !streaming,
      'is-streaming': streaming,
      'has-chars': (eventMode || participants === null) && characters && characters.length > 0 && !streaming,
      'has-participants': participants !== null && !eventMode && !streaming,
    }"
  >
    <!-- 推演进行中 -->
    <template v-if="streaming">
      <div class="chat-input__top-row">
        <button class="chat-input__mode-btn chat-input__mode-btn--active" type="button" @click="emit('interrupt')"><svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M9 1L3 9h4.5l-1 6L13 7H8.5z" fill="currentColor"/></svg></button>
        <span class="chat-input__streaming-hint">{{ $t('chat.streaming') }}<span class="chat-input__dots"></span></span>
      </div>
    </template>

    <!-- 正常输入 -->
    <template v-else>

      <!-- 统一选项行（事件/角色模式共用）：齿轮 + 展开后选项 -->
      <div class="chat-input__role-row">
        <div v-if="!streaming" class="role-selector" @click="showAdvancedOptions = !showAdvancedOptions">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M6.5 2h3l.3 1.2 1.1.4 1-.7 2.1 2.1-.7 1 .4 1.1L14.8 8v3l-1.2.3-.4 1.1.7 1-2.1 2.1-1-.7-1.1.4L9.5 16h-3l-.3-1.2-1.1-.4-1 .7L3 13l.7-1-.4-1.1L2 9.5v-3l1.2-.3.4-1.1-.7-1L5.1 2l1 .7 1.1-.4z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.2"/></svg>
          <span>{{ $t('chat.optionsExpand') }}</span>
        </div>
        <Transition name="fade">
          <div v-if="showAdvancedOptions" class="role-options-inline">
            <!-- 角色选择按钮：仅非事件模式显示 -->
            <div
              v-if="eventMode !== true && characters && npcCharacters.length > 0"
              class="option-chip option-chip--role"
              @click="openRolePicker()"
            >
              <span>{{ $t('chat.roleSelect') }}</span>
            </div>
            <div
              class="option-chip"
              :class="{ disabled: !actionDescriptions }"
              @click="emit('update:actionDescriptions', !actionDescriptions)"
            >
              <span>{{ actionDescriptions ? $t('chat.actionDescOn') : $t('chat.actionDescOff') }}</span>
            </div>
            <div
              class="option-chip"
              :class="{ disabled: !showNarration }"
              @click="emit('update:showNarration', !showNarration)"
            >
              <span>{{ showNarration ? $t('chat.narrationOn') : $t('chat.narrationOff') }}</span>
            </div>
            <div
              class="option-chip"
              :class="{ disabled: !elementInjectionEnabled }"
              @click="openElementPicker()"
            >
              <span>{{ elementInjectionEnabled ? $t('chat.elementInjectionOn') : $t('chat.elementInjectionOff') }}</span>
            </div>
            <div
              class="option-chip"
              :class="{ disabled: !constraintText }"
              @click="openConstraintModal()"
            >
              <span>{{ constraintText ? $t('chat.constraintOn') : $t('chat.constraintOff') }}</span>
            </div>
            <div
              class="option-chip"
              :class="{ disabled: !elementRerank }"
              @click="emit('update:elementRerank', !elementRerank)"
            >
              <span>{{ elementRerank ? $t('chat.rerankOn') : $t('chat.rerankOff') }}</span>
            </div>
            <div
              v-if="!sessionStarted"
              class="option-chip"
              :class="{ disabled: !memoriesEnabled }"
              @click="emit('update:memoriesEnabled', !memoriesEnabled)"
            >
              <span>{{ memoriesEnabled ? $t('chat.memoryOn') : $t('chat.memoryOff') }}</span>
            </div>
          </div>
        </Transition>
        <!-- 占位：保持分隔线位置稳定 -->
        <div v-if="!showAdvancedOptions" class="role-options-inline role-options-inline--phantom"></div>
      </div>

      <div class="chat-input__top-row">
        <!-- ⚡ 事件模式切换 -->
        <NTooltip v-if="eventMode !== undefined" trigger="hover" placement="top">
          <template #trigger>
            <button
              class="chat-input__mode-btn"
              :class="{ active: eventMode }"
              type="button"
              @click="toggleMode"
            ><svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M9 1L3 9h4.5l-1 6L13 7H8.5z" fill="currentColor"/></svg></button>
          </template>
          {{ eventMode ? $t('chat.exitEventMode') : $t('chat.injectEvent') }}
        </NTooltip>

        <textarea
          ref="textareaRef"
          v-model="content"
          class="chat-input__textarea"
          :placeholder="resolvedPlaceholder"
          :disabled="disabled"
          rows="1"
          @keydown="handleKeydown"
          @input="autoResize"
        />

        <button
          class="chat-input__send-btn"
          type="button"
          :disabled="!canSend || disabled"
          :title="sending ? $t('chat.sendingButton') : (disabled ? $t('chat.sendingButton') : $t('chat.sendButton'))"
          @click="send"
        >
          <svg v-if="!sending && !disabled" width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path d="M2 8l12-5-5 12-2-5-5-2z" fill="currentColor"/>
          </svg>
          <svg v-else class="spin" width="15" height="15" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="5.5" stroke="currentColor" stroke-width="1.5" stroke-dasharray="20 14" opacity="0.7"/>
          </svg>
        </button>
      </div>
    </template>
  </div>

  <!-- 角色选择弹窗 -->
  <Teleport to="body">
    <Transition name="picker-fade">
      <div
        v-if="showPickerDialog"
        class="picker-overlay"
        @click="handlePickerOverlayClick"
      >
        <div class="picker-dialog" role="dialog" aria-modal="true" :aria-label="$t('chat.pickerTitle')" @keydown.escape="closePicker">
          <div class="picker-header">
            <span class="picker-title">{{ $t('chat.pickerTitle') }}</span>
            <button class="picker-close" type="button" :aria-label="$t('chat.pickerClose')" @click="closePicker">×</button>
          </div>
          <!-- 你扮演：一行显示当前角色 + 选择按钮 + 重置 -->
          <div class="picker-role-bar">
            <span class="picker-role-bar__label">{{ $t('chat.youAre') }}</span>
            <span class="picker-role-bar__value">
              {{ userRoleCharacter ? userRoleCharacter.name : $t('chat.defaultRole') }}
            </span>
            <button
              v-if="userRole"
              class="picker-role-bar__reset"
              type="button"
              :title="$t('chat.clearRole')"
              @click="selectUserRole(null)"
            >{{ $t('chat.clearRole') }}</button>
            <button
              class="picker-role-bar__btn"
              type="button"
              :class="{ 'is-active': selectingRole }"
              @click="selectingRole = !selectingRole"
            >{{ selectingRole ? $t('common.cancel') : $t('chat.roleSelect') }}</button>
          </div>
          <!-- 让谁参与 -->
          <div class="picker-participant-header">
            <span class="picker-title" style="font-size:13px">{{ $t('chat.whoParticipates') }}</span>
            <button
              class="picker-mode-btn"
              type="button"
              @click="togglePickerMode"
            >{{ pickerModeLabel }}</button>
          </div>
          <div class="picker-search-wrapper">
            <input
              ref="pickerSearchInput"
              v-model="pickerSearchQuery"
              class="picker-search"
              type="text"
              :placeholder="$t('chat.pickerSearch')"
              @keydown.escape="closePicker"
            />
          </div>
          <div class="picker-body">
            <div v-if="groupedCharacters.length === 0" class="picker-empty">
              {{ pickerSearchQuery.trim() ? '—' : $t('chat.pickerSearch') }}
            </div>
            <div
              v-for="group in groupedCharacters"
              :key="group.tier"
              class="picker-group"
            >
              <div class="picker-group__label">{{ $t(group.label) }}</div>
              <button
                v-for="char in group.chars"
                :key="char.id"
                class="picker-item"
                :class="{
                  'is-selected': selectingRole ? (userRole === char.id) : (pickerMode === 'hint' ? hintSelectedIds.has(char.id) : localParticipants.some(p => p.id === char.id)),
                  'is-user-role': userRole === char.id,
                  'is-role-selecting': selectingRole,
                }"
                type="button"
                @click="toggleCharSelection(char)"
              >
                <span class="picker-item__check" :class="{ 'is-radio': selectingRole }">
                  <span
                    v-if="selectingRole ? (userRole === char.id) : (pickerMode === 'hint' ? hintSelectedIds.has(char.id) : localParticipants.some(p => p.id === char.id))"
                    class="picker-item__check-mark"
                  >{{ selectingRole ? '●' : '✓' }}</span>
                </span>
                <span
                  class="picker-item__avatar-wrapper"
                  :title="$t('character.setAvatar')"
                  @click.stop="onAvatarClick(char.id)"
                >
                  <img
                    v-if="characterPortraitMap[char.id]"
                    :src="characterPortraitMap[char.id]"
                    class="picker-item__avatar"
                  />
                  <span v-else class="char-chip__dot" :style="{ background: getColor(char.name) }" />
                  <button
                    v-if="characterPortraitMap[char.id]"
                    class="picker-item__avatar-clear"
                    type="button"
                    :title="$t('character.clearAvatar')"
                    @click.stop="onClearAvatar(char.id)"
                  >&times;</button>
                  <span v-if="uploadingAvatarId === char.id" class="picker-item__avatar-loading">&#x23F3;</span>
                </span>
                <span class="picker-item__name">{{ char.name }}</span>
                <span v-if="userRole === char.id" class="picker-item__you">{{ $t('chat.youBadge') }}</span>
              </button>
            </div>
          </div>
          <input
            ref="fileInputRef"
            type="file"
            accept="image/*"
            style="display: none"
            @change="onFileChange"
          />
          <div class="picker-footer">
            <button class="picker-footer__btn" type="button" @click="closePicker">{{ $t('chat.pickerClose') }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 元素选择弹窗 -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showElementPicker" class="modal-overlay" @click.self="showElementPicker = false">
        <div class="modal-dialog element-picker">
          <div class="modal-header">
            <span>{{ $t('chat.elementSelectorTitle') }}</span>
            <button class="modal-close" type="button" @click="showElementPicker = false">&times;</button>
          </div>
          <div class="element-picker__tabs">
            <button
              v-for="cat in ELEMENT_CATEGORIES"
              :key="cat"
              class="element-picker__tab"
              :class="{ active: activeElementCategory === cat }"
              type="button"
              @click="activeElementCategory = cat"
            >{{ cat }}</button>
          </div>
          <div class="element-picker__body" v-if="!elementPickerLoading">
            <label
              v-for="elem in groupedElements"
              :key="elem.id"
              class="element-picker__item"
            >
              <input
                type="checkbox"
                :value="elem.id"
                :checked="selectedElementIds.includes(elem.id)"
                @change="onElementCheckboxChange(elem.id, $event)"
              />
              <span>{{ elem.name }}</span>
            </label>
            <div v-if="groupedElements.length === 0" class="element-picker__empty">
              {{ $t('worldDetail.noElementsFiltered') }}
            </div>
          </div>
          <div v-else class="element-picker__loading">{{ $t('common.loading') }}</div>
          <div class="element-picker__footer">
            <span class="element-picker__count">{{ selectedElementIds.length }} {{ $t('chat.elementSelected') }}</span>
            <button class="element-picker__clear-btn" type="button" @click="clearAllSelectedElements">
              {{ $t('chat.elementClearAll') }}
            </button>
            <button class="element-picker__apply-btn" type="button" @click="applyElementSelection">
              {{ $t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- 约束文本弹窗 -->
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="showConstraintModal" class="modal-overlay" @click.self="showConstraintModal = false">
        <div class="modal-dialog constraint-modal">
          <div class="modal-header">
            <span>{{ $t('chat.constraintTitle') }}</span>
            <button class="modal-close" type="button" @click="showConstraintModal = false">&times;</button>
          </div>
          <textarea
            v-model="localConstraintText"
            class="constraint-modal__textarea"
            :maxlength="100"
            :placeholder="$t('chat.constraintPlaceholder')"
            rows="6"
          ></textarea>
          <div class="constraint-modal__counter">{{ localConstraintText.length }}/100</div>
          <div class="constraint-modal__hint">{{ $t('chat.constraintHint') }}</div>
          <div class="modal-footer">
            <button class="constraint-modal__apply-btn" type="button" @click="applyConstraint">
              {{ $t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.chat-input {
  display: flex;
  flex-direction: column;
  background: var(--bg-input);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 12px;
  transition: border-color 0.15s;
  min-width: 0;
  overflow: visible;
}

.chat-input:focus-within {
  border-color: rgba(0, 0, 0, 0.15);
}

/* ── 上栏 ── */
.chat-input__top-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 16px;
}

/* ── 旧 hint 选择器行 ── */
.chat-input__char-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 22px 10px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
}

/* ── 参与者 chip 行 ── */
.chat-input__participant-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 20px 8px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  min-height: 44px;
}

.participant-row__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
  min-width: 0;
}

.participant-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 14px;
  border-radius: 20px;
  font-size: 15px;
  color: var(--text-primary);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid rgba(0,0,0,0.08);
  white-space: nowrap;
  user-select: none;
}

.participant-chip.is-removable {
  cursor: pointer;
  transition: background 0.15s;
}

.participant-chip.is-removable:hover {
  background: color-mix(in srgb, #e04040 18%, transparent);
  border-color: rgba(224, 64, 64, 0.4);
}

.participant-chip--user-role {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 18%, transparent);
  font-weight: 600;
}

.participant-chip__you-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 0 6px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  margin-left: 3px;
  line-height: 1.5;
  letter-spacing: 0.02em;
}

.participant-chip__remove {
  font-size: 11px;
  opacity: 0.6;
  line-height: 1;
  margin-left: 1px;
}

/* ── 添加参与者 ── */
.participant-add-wrapper {
  position: relative;
}

.participant-add-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: none;
  color: var(--accent);
  font-size: 18px;
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1;
}

.participant-add-btn:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.participant-add-picker {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  z-index: 100;
  background: var(--bg-input);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: var(--radius);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 180px;
  max-height: 240px;
  overflow-y: auto;
  box-shadow: var(--shadow-dialog);
}

.add-picker__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: 6px;
  border: none;
  background: none;
  font-size: 15px;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}

.add-picker__item:hover {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

/* ── hint selector (reused from old) ── */
.char-row__mode-btn {
  flex-shrink: 0;
  padding: 1px 7px;
  border-radius: 4px;
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--accent);
  font-size: 11px;
  color: #fff;
  cursor: pointer;
  transition: opacity 0.15s;
  letter-spacing: 0.02em;
  user-select: none;
}
.char-row__mode-btn:hover {
  opacity: 0.85;
}

.char-row__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  min-width: 0;
}

.char-chip__dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-right: 2px;
  vertical-align: middle;
  opacity: 0.85;
}

.char-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 14px;
  border-radius: 20px;
  border: 1px solid transparent;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text-muted);
  background: none;
  white-space: nowrap;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0.6;
}
.char-chip:hover { opacity: 1; }

.char-chip.chip--core { border-color: var(--accent); }
.char-chip.chip--core.is-selected { background: var(--accent); color: #fff; opacity: 1; }
.char-chip.chip--core:not(.is-selected):hover { background: color-mix(in srgb, var(--accent) 12%, transparent); opacity: 1; }

.char-chip.chip--supporting { border-color: rgba(80,180,160,0.5); color: rgba(80,180,160,0.9); }
.char-chip.chip--supporting.is-selected { background: rgba(80,180,160,0.85); color: #fff; border-color: rgba(80,180,160,0.85); opacity: 1; }
.char-chip.chip--supporting:not(.is-selected):hover { background: rgba(80,180,160,0.1); opacity: 1; }

.char-chip.chip--extra { border-color: rgba(128,128,128,0.35); }
.char-chip.chip--extra.is-selected { background: rgba(128,128,128,0.25); border-color: rgba(128,128,128,0.6); color: var(--text-primary); opacity: 1; }
.char-chip.chip--extra:not(.is-selected):hover { background: rgba(128,128,128,0.08); opacity: 1; }

/* ── ⚡ 模式切换 ── */
.chat-input__mode-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  padding: 0;
  margin-bottom: 1px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 6px;
  background: var(--accent);
  font-size: 18px;
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  line-height: 1;
}
.chat-input__mode-btn:hover { opacity: 0.85; }
.chat-input__mode-btn.active { background: var(--accent); color: #fff; }
.chat-input__mode-btn--active { background: var(--accent); color: #fff; }

/* textarea */
.chat-input__textarea {
  flex: 1;
  min-width: 0;
  padding: 0;
  background: none;
  border: none;
  outline: none;
  resize: none;
  font-size: 18px;
  line-height: 1.6;
  color: var(--text-primary);
  font-family: inherit;
  min-height: 30px;
  max-height: 160px;
  overflow-y: auto;
  scrollbar-width: none;
}
.chat-input__textarea::-webkit-scrollbar { display: none; }
.chat-input__textarea::placeholder { color: var(--text-muted); opacity: 0.7; }
.chat-input__textarea:disabled { opacity: 0.5; cursor: not-allowed; }

/* 发送按钮 */
.chat-input__send-btn {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  padding: 0;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.chat-input__send-btn:hover:not(:disabled) { opacity: 0.85; transform: scale(1.06); }
.chat-input__send-btn:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

@keyframes dots {
  0%   { content: ''; }
  25%  { content: '.'; }
  50%  { content: '..'; }
  75%  { content: '...'; }
}
.chat-input__dots::after {
  content: '';
  animation: dots 1.6s steps(1, end) infinite;
}

.chat-input__streaming-hint {
  flex: 1;
  font-size: 16px;
  line-height: 1.55;
  color: var(--text-muted);
  user-select: none;
  padding: 2px 0;
}

.option-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 15px;
  border: 1px solid rgba(0,0,0,0.08) !important;
  background: var(--bg-input);
  color: var(--text-secondary);
  user-select: none;
  transition: all 0.2s;
}

.option-chip:hover {
  background: var(--accent-dim);
  color: var(--accent);
}

.option-chip.disabled {
  border-color: var(--border-subtle);
  color: var(--text-secondary);
}

.option-chip--rerank.locked {
  border-color: var(--border-subtle);
  color: var(--text-muted);
  opacity: 0.6;
}

.option-chip__lock {
  font-size: 10px;
  line-height: 1;
}

/* ── "+N 更多" 按钮 ── */
.more-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 14px;
  border-radius: 20px;
  border: 1px dashed color-mix(in srgb, var(--text-muted) 40%, transparent);
  font-size: 13px;
  cursor: pointer;
  color: var(--text-muted);
  background: none;
  white-space: nowrap;
  transition: all 0.15s;
}
.more-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

/* ── 角色选择弹窗 ── */
.picker-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(2px);
}

.picker-dialog {
  background: var(--bg-card);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  width: 480px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.picker-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 22px 12px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
}

.picker-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.picker-close {
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  font-size: 18px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}
.picker-close:hover {
  background: color-mix(in srgb, var(--text-muted) 12%, transparent);
  color: var(--text-primary);
}

.picker-search-wrapper {
  padding: 12px 22px;
}

.picker-search {
  width: 100%;
  padding: 10px 16px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 8px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 15px;
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
}
.picker-search:focus {
  border-color: var(--accent);
}
.picker-search::placeholder {
  color: var(--text-muted);
  opacity: 0.6;
}

.picker-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 22px 12px;
  scrollbar-width: thin;
}

.picker-empty {
  text-align: center;
  padding: 28px 0;
  color: var(--text-muted);
  font-size: 15px;
}

.picker-group {
  margin-bottom: 10px;
}

.picker-group__label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  padding: 9px 0 6px;
  border-bottom: 1px solid color-mix(in srgb, var(--text-muted) 12%, transparent);
  margin-bottom: 3px;
}

.picker-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border: none;
  border-radius: 6px;
  background: none;
  font-size: 15px;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}
.picker-item:hover {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.picker-item.is-selected {
  background: color-mix(in srgb, var(--accent) 12%, transparent);
}
.picker-item.is-user-role {
  opacity: 0.6;
  cursor: default;
}

.picker-item.is-role-selecting:hover {
  background: color-mix(in srgb, var(--accent) 16%, transparent);
}

.picker-item__check.is-radio {
  border-radius: 50%;
}

.picker-item__check {
  width: 20px;
  height: 20px;
  border: 1.5px solid color-mix(in srgb, var(--text-muted) 40%, transparent);
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.12s;
}
.picker-item.is-selected .picker-item__check {
  background: var(--accent);
  border-color: var(--accent);
}

.picker-item__check-mark {
  color: #fff;
  font-size: 13px;
  line-height: 1;
}

.picker-item__avatar-wrapper {
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.picker-item__avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
}

.picker-item__avatar-clear {
  position: absolute;
  top: -4px;
  right: -4px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 10px;
  line-height: 1;
  padding: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.15s, background 0.15s;
}

.picker-item__avatar-wrapper:hover .picker-item__avatar-clear {
  opacity: 1;
}

.picker-item__avatar-clear:hover {
  background: rgba(224, 64, 64, 0.85);
}

.picker-item__avatar-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.4);
  border-radius: 50%;
  font-size: 12px;
}

.picker-item__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-item__you {
  font-size: 11px;
  font-weight: 700;
  padding: 0 6px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  line-height: 1.5;
}

.picker-footer {
  padding: 12px 22px 16px;
  border-top: 1px solid rgba(0,0,0,0.06);
  display: flex;
  justify-content: flex-end;
}

.picker-footer__btn {
  padding: 8px 24px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 6px;
  background: none;
  color: var(--accent);
  font-size: 15px;
  cursor: pointer;
  transition: all 0.15s;
}
.picker-footer__btn:hover {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

/* 弹窗动画 */
.picker-fade-enter-active,
.picker-fade-leave-active {
  transition: opacity 0.2s ease;
}
.picker-fade-enter-from,
.picker-fade-leave-to {
  opacity: 0;
}

/* ── INK ── */
[data-theme="ink"] .chat-input { box-shadow: var(--shadow-card); }
[data-theme="ink"] .chat-input:focus-within { border-color: rgba(0, 0, 0, 0.15); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 10%, transparent); }
[data-theme="ink"] .chat-input__char-row,
[data-theme="ink"] .chat-input__participant-row { border-bottom-color: rgba(0, 0, 0, 0.06); }
[data-theme="ink"] .chat-input__mode-btn.active,
[data-theme="ink"] .chat-input__mode-btn:hover { color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
[data-theme="ink"] .participant-add-picker { border-color: rgba(0, 0, 0, 0.08); }
[data-theme="ink"] .picker-dialog { box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25); }

/* ── BREEZE ── */
[data-theme="breeze"] .chat-input { box-shadow: var(--shadow-card); }
[data-theme="breeze"] .chat-input:focus-within { border-color: rgba(0, 0, 0, 0.15); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent); }
[data-theme="breeze"] .chat-input__char-row,
[data-theme="breeze"] .chat-input__participant-row { border-bottom-color: rgba(0, 0, 0, 0.06); }
[data-theme="breeze"] .chat-input__mode-btn.active,
[data-theme="breeze"] .chat-input__mode-btn:hover { color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); }
[data-theme="breeze"] .participant-add-picker { border-color: rgba(0, 0, 0, 0.08); }
[data-theme="breeze"] .picker-dialog { box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15); }

/* Role selector */
.chat-input__role-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px 7px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  position: relative;
  flex-wrap: wrap;
}

.role-options-inline {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.role-options-inline--phantom {
  height: 28px;
  visibility: hidden;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.role-selector {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  font-size: 13px;
  padding: 5px 12px;
  border-radius: 6px;
  background: var(--bg-input);
  border: 1px solid rgba(0,0,0,0.08) !important;
  color: var(--text-secondary);
  user-select: none;
  transition: background 0.15s;
}

.role-selector:hover {
  background: var(--accent-dim);
  color: var(--accent);
}

.role-selector__value {
  font-weight: 600;
  color: var(--accent);
}

.role-selector__caret {
  font-size: 10px;
  opacity: 0.6;
}

.role-picker {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 8px;
  background: var(--bg-input);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: var(--radius);
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  z-index: 100;
  min-width: 140px;
  max-height: 200px;
  overflow-y: auto;
}

.role-picker__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 14px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 15px;
  color: var(--text-primary);
  text-align: left;
  transition: background 0.12s;
}

.role-picker__item:hover {
  background: var(--bg-input);
}

.role-picker__item.is-active {
  color: var(--accent);
  font-weight: 600;
}

/* ── 弹窗（Teleport to body，scoped 样式仍生效）── */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(2px);
}

.modal-dialog {
  background: var(--bg-card);
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: var(--radius);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  width: 420px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 14px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.modal-close {
  width: 28px;
  height: 28px;
  border: none;
  background: none;
  font-size: 18px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}
.modal-close:hover {
  background: color-mix(in srgb, var(--text-muted) 12%, transparent);
  color: var(--text-primary);
}

.modal-footer {
  padding: 14px 22px 18px;
  border-top: 1px solid rgba(0,0,0,0.06);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* ── 元素选择器 ── */
.element-picker__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 14px 22px 10px;
  border-bottom: 1px solid rgba(0,0,0,0.04);
}

.element-picker__tab {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.12s;
}
.element-picker__tab:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.element-picker__tab.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.element-picker {
  height: 420px;
}

.element-picker__body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 22px;
}

.element-picker__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 6px;
  font-size: 15px;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.1s;
  border-radius: 4px;
}
.element-picker__item:hover {
  background: color-mix(in srgb, var(--accent) 6%, transparent);
}

.element-picker__item input[type="checkbox"] {
  accent-color: var(--accent);
  flex-shrink: 0;
}

.element-picker__empty {
  text-align: center;
  padding: 36px 0;
  color: var(--text-muted);
  font-size: 15px;
}

.element-picker__loading {
  text-align: center;
  padding: 36px 0;
  color: var(--text-muted);
  font-size: 15px;
}

.element-picker__footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 22px 18px;
  border-top: 1px solid rgba(0,0,0,0.06);
}

.element-picker__count {
  font-size: 14px;
  color: var(--text-muted);
  flex: 1;
}

.element-picker__clear-btn {
  padding: 7px 16px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 14px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}
.element-picker__clear-btn:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.element-picker__apply-btn {
  padding: 7px 18px;
  border-radius: 6px;
  border: none;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  transition: opacity 0.12s;
}
.element-picker__apply-btn:hover {
  opacity: 0.85;
}

/* ── 约束编辑器 ── */
.constraint-modal__textarea {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid rgba(0,0,0,0.08);
  border-radius: 8px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  outline: none;
  box-sizing: border-box;
  line-height: 1.5;
}
.constraint-modal__textarea:focus {
  border-color: var(--accent);
}
.constraint-modal__textarea::placeholder {
  color: var(--text-muted);
  opacity: 0.6;
}

.constraint-modal__counter {
  text-align: right;
  font-size: 13px;
  color: var(--text-muted);
  padding: 6px 4px 0;
}

.constraint-modal__hint {
  font-size: 14px;
  color: var(--text-muted);
  padding: 4px 4px 0;
  line-height: 1.5;
}

.constraint-modal__apply-btn {
  padding: 9px 26px;
  border-radius: 6px;
  border: none;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  cursor: pointer;
  transition: opacity 0.12s;
}
.constraint-modal__apply-btn:hover {
  opacity: 0.85;
}

/* ── 角色选择弹窗：你扮演（一行 + 选择按钮）── */
.picker-role-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 22px 11px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
}

.picker-role-bar__label {
  font-size: 14px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.picker-role-bar__value {
  font-size: 15px;
  font-weight: 600;
  color: var(--accent);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker-role-bar__btn {
  flex-shrink: 0;
  padding: 5px 14px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 14px;
  color: var(--accent);
  cursor: pointer;
  transition: all 0.12s;
}
.picker-role-bar__btn:hover {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
.picker-role-bar__btn.is-active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.picker-role-bar__reset {
  flex-shrink: 0;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 14px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s;
}
.picker-role-bar__reset:hover {
  color: var(--color-error);
  border-color: var(--color-error);
  background: color-mix(in srgb, var(--color-error) 8%, transparent);
}

.picker-participant-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px 8px;
}

.picker-mode-btn {
  flex-shrink: 0;
  padding: 4px 11px;
  border-radius: 4px;
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--accent);
  font-size: 13px;
  color: #fff;
  cursor: pointer;
  transition: opacity 0.15s;
  letter-spacing: 0.02em;
  user-select: none;
}
.picker-mode-btn:hover {
  opacity: 0.85;
}

/* ── 角色选择按钮（更多选项中）── */
.option-chip--role {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  font-weight: 600;
}
</style>
