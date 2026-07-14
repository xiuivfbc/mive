<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getWorld } from '@/api/worlds'
import { updateCharacter as updateCharacterApi } from '@/api/characters'
import { useCharacters } from '@/composables/useCharacters'
import { useParticipants } from '@/composables/useParticipants'
import { useChatOrchestration } from '@/composables/useChatOrchestration'
import type { WorldDoc } from '@/types/world'
import type { Message } from '@/types/message'
import type { ChatSession, Participant } from '@/types/chatSession'
import MessageList from '@/components/chat/MessageList.vue'
import ChatInput from '@/components/chat/ChatInput.vue'
import ChatHistoryDrawer from '@/components/chat/ChatHistoryDrawer.vue'
import QueueBar from '@/components/chat/QueueBar.vue'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useCharacterColors } from '@/composables/useCharacterColors'
import { useLocale } from '@/composables/useLocale'

const props = defineProps<{ id: string }>()
const router = useRouter()
const messageApi = useMessage()
const { t } = useI18n()
const { resetColors } = useCharacterColors()
const { locale } = useLocale()

const world = ref<WorldDoc | null>(null)
const messageListRef = ref<InstanceType<typeof MessageList> | null>(null)

// --- Character & Participant composables ---
const worldIdRef = computed(() => props.id)

const {
  characters,
  characterPortraitMap,
  characterNameMap,
  loadCharacters,
  updateCharacter: updateCharacterInList,
} = useCharacters({ worldId: worldIdRef })

const worldUserCharacterId = computed(() => world.value?.user_character_id ?? null)

const {
  chatParticipants,
  chatParticipantMode,
  chatUserRole,
  previousUserRoles,
  userRoleCharacter,
  userDisplayName,
  userAvatarUrl,
  userCharacterMap,
  applyServerParticipants,
  restoreSessionParticipants,
  resetParticipants,
} = useParticipants({ characters, worldUserCharacterId })

// --- Orchestration composable ---
const {
  messages,
  sortedMessages,
  sending,
  isFakeStreaming,
  isStreaming,
  hasMore,
  loading,
  currentSessionId,
  sessionStarted,
  eventStarted,
  enrichMode,
  memoriesEnabled,
  actionDescriptions,
  showNarration,
  elementRerank,
  elementInjectionEnabled,
  elementInjectionIds,
  constraintText,
  currentEventTitle,
  currentTimelineEventId,
  rewindableEvents,
  queueDisplayItems,
  isProcessing,
  handleSend: orchHandleSend,
  handleEventInject: orchHandleEventInject,
  handleInputInterrupt: orchHandleInputInterrupt,
  handleGoOn: orchHandleGoOn,
  handleEnrich: orchHandleEnrich,
  handleEnrichSubmit: orchHandleEnrichSubmit,
  handleEndHere: orchHandleEndHere,
  handleRewindSelect: orchHandleRewindSelect,
  handleDiscard: orchHandleDiscard,
  handleResume: orchHandleResume,
  startNewSession: orchStartNewSession,
  loadMore,
  removeQueueItem,
  init: orchInit,
  beforeUnmount: orchBeforeUnmount,
} = useChatOrchestration({
  worldId: worldIdRef,
  messageListRef,
  t,
  messageApi,
  restoreSessionParticipants,
  resetParticipants,
  applyServerParticipants,
  chatUserRole,
})

// --- UI-only state (not orchestration concerns) ---
const eventMode = ref(false)
const eventSending = ref(false) // 立即隐藏引导气泡
const showInterruptMenu = ref(false)
const showFabMenu = ref(false)
const fabGroupRef = ref<HTMLElement | null>(null)
const fabTooltipText = ref('')
const fabTooltipX = ref(0)
const fabTooltipY = ref(0)
const showFabTooltip = ref(false)
let fabLongPressTimer: ReturnType<typeof setTimeout> | null = null
const showRewindPicker = ref(false)
const showHistory = ref(false)
const showAiDisclaimer = ref(true)
const showEventLifecycle = ref(false)

// 事件注入提示 Toast：5s 自动消失
watch(currentEventTitle, (newTitle, oldTitle) => {
  if (newTitle && !oldTitle) {
    messageApi.info(t('chat.eventInjected'), { duration: 5000 })
  }
  if (!newTitle) showEventLifecycle.value = false
})

// 点击外部关闭生命周期菜单 & FAB 菜单
function onDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.chat-page__lifecycle-menu') && !target.closest('.event-banner__bolt')) {
    showEventLifecycle.value = false
  }
  if (fabGroupRef.value && !fabGroupRef.value.contains(target)) {
    showFabMenu.value = false
  }
}

function toggleFabMenu() {
  showFabMenu.value = !showFabMenu.value
}

function closeFabMenu() {
  showFabMenu.value = false
}

function onFabTouchStart(e: TouchEvent, text: string) {
  cancelFabLongPress()
  const btn = e.currentTarget as HTMLElement
  const rect = btn.getBoundingClientRect()
  fabTooltipText.value = text
  fabTooltipX.value = rect.left + rect.width / 2
  fabTooltipY.value = rect.top - 6
  fabLongPressTimer = setTimeout(() => { showFabTooltip.value = true }, 500)
}

function onFabTouchEnd() {
  cancelFabLongPress()
}

function onFabTouchMove() {
  cancelFabLongPress()
}

function cancelFabLongPress() {
  if (fabLongPressTimer) { clearTimeout(fabLongPressTimer); fabLongPressTimer = null }
  showFabTooltip.value = false
}

onMounted(() => document.addEventListener('click', onDocumentClick, true))
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick, true)
  cancelFabLongPress()
})

// 事件生命周期菜单：点击 banner 闪电按钮切换
function toggleEventLifecycle() {
  showEventLifecycle.value = !showEventLifecycle.value
}

function closeEventLifecycle() {
  showEventLifecycle.value = false
}

async function lifecyclePause() {
  closeEventLifecycle()
  await orchHandleInputInterrupt()
  showInterruptMenu.value = false
}

async function lifecycleGoOn() {
  closeEventLifecycle()
  await orchHandleGoOn()
}

async function lifecycleEnrich() {
  closeEventLifecycle()
  showInterruptMenu.value = false
  await orchHandleEnrich()
}

async function lifecycleEndHere() {
  closeEventLifecycle()
  showInterruptMenu.value = false
  await orchHandleEndHere()
}

function lifecycleRewind() {
  closeEventLifecycle()
  showInterruptMenu.value = false
  showRewindPicker.value = true
}

async function lifecycleDiscard() {
  closeEventLifecycle()
  showInterruptMenu.value = false
  await orchHandleDiscard()
}

// --- Starter prompts (random pick 3 from mode-specific pool) ---
const EVENT_POOL_KEYS = Array.from({ length: 28 }, (_, i) => `chat.eventPool.${i + 1}`)
const CHAT_POOL_KEYS = Array.from({ length: 20 }, (_, i) => `chat.chatPool.${i + 1}`)

function pickRandom3(keys: string[]): string[] {
  const shuffled = [...keys].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, 3).map(k => t(k))
}

const starterPrompts = ref(pickRandom3(eventMode.value ? EVENT_POOL_KEYS : CHAT_POOL_KEYS))

watch(eventMode, () => {
  starterPrompts.value = pickRandom3(eventMode.value ? EVENT_POOL_KEYS : CHAT_POOL_KEYS)
})

async function handleStarterPrompt(prompt: string) {
  if (eventMode.value) {
    eventSending.value = true // 立即隐藏引导气泡
    await handleEventInject(prompt)
  } else {
    await handleSend(prompt)
  }
}

// --- Avatar upload state ---
const avatarFileInput = ref<HTMLInputElement | null>(null)
const pendingAvatarCharId = ref<string | null>(null)
const pendingAvatarCharName = ref<string>('')

// --- Thin wrappers that manage UI state around orchestration ---

async function handleSend(content: string, participantMode: 'auto' | 'edit' | 'include' = 'auto', participants: Participant[] | null = null) {
  await orchHandleSend(content, participantMode, participants)
}

async function handleEventInject(rawInput: string) {
  eventSending.value = true // 立即隐藏引导气泡
  try {
    await orchHandleEventInject(rawInput)
  } catch {
    // 事件注入失败时重置，允许用户重试
    eventSending.value = false
  }
  // eventMode 不自动回退，由用户通过闪电按钮手动切换
}

async function handleInputInterrupt() {
  if (isStreaming.value) {
    await orchHandleInputInterrupt()
    showInterruptMenu.value = true
  } else if (isFakeStreaming.value) {
    await orchHandleInputInterrupt()
  }
}

async function handleGoOn() {
  showInterruptMenu.value = false
  await orchHandleGoOn()
}

async function handleEnrich() {
  showInterruptMenu.value = false
  await orchHandleEnrich()
}

async function handleEnrichSubmit(additionalContext: string) {
  await orchHandleEnrichSubmit(additionalContext)
}

async function handleEndHere() {
  showInterruptMenu.value = false
  await orchHandleEndHere()
}

function handleShowRewind() {
  showInterruptMenu.value = false
  showRewindPicker.value = true
}

async function handleRewindSelect(cardMessageId: string) {
  showRewindPicker.value = false
  await orchHandleRewindSelect(cardMessageId)
}

async function handleDiscard() {
  showInterruptMenu.value = false
  await orchHandleDiscard()
}

function handleAvatarClick(payload: { characterId: string; characterName: string }) {
  pendingAvatarCharId.value = payload.characterId
  pendingAvatarCharName.value = payload.characterName
  avatarFileInput.value?.click()
}

async function onAvatarFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file || !pendingAvatarCharId.value) return
  if (!file.type.startsWith('image/')) {
    messageApi.error(t('character.invalidFileType'))
    return
  }
  if (file.size > 2 * 1024 * 1024) {
    messageApi.error(t('character.fileTooLarge'))
    return
  }
  try {
    const base64 = await fileToBase64(file)
    const updated = await updateCharacterApi(props.id, pendingAvatarCharId.value, { portrait_url: base64 })
    updateCharacterInList(updated)
    messageApi.success(t('character.avatarUpdated'))
  } catch {
    messageApi.error(t('character.uploadFailed'))
  } finally {
    if (avatarFileInput.value) avatarFileInput.value.value = ''
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function handleAvatarChange(payload: { characterId: string; portraitUrl: string | null }) {
  try {
    const updated = await updateCharacterApi(props.id, payload.characterId, { portrait_url: payload.portraitUrl })
    updateCharacterInList(updated)
    messageApi.success(payload.portraitUrl ? t('character.avatarUpdated') : t('character.avatarCleared'))
  } catch {
    messageApi.error(t('character.uploadFailed'))
  }
}

async function handleResume(session: ChatSession, sessionMessages: Message[]) {
  // Restore mode based on session type
  eventMode.value = session.type === 'event'
  eventSending.value = false // 恢复会话时重置，确保引导气泡状态正确
  showInterruptMenu.value = false
  showRewindPicker.value = false
  resetColors()
  await orchHandleResume(
    session.id,
    sessionMessages,
    session.participants as unknown as Array<string | Participant> | null,
    session.participant_mode,
    !!(session.participants && session.participants.length > 0),
    session.element_injection_ids,
    session.constraints,
  )
}

function getEventTitle(msg: Message): string {
  try {
    return (JSON.parse(msg.content) as { title?: string }).title ?? msg.content.slice(0, 30)
  } catch {
    return msg.content.slice(0, 30)
  }
}

function formatTime(vt: string): string {
  return new Date(vt).toLocaleString(locale.value, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function goBack() {
  router.push(`/world/${props.id}`)
}

function startNewSession() {
  // eventMode 保留，不随新会话重置
  eventSending.value = false // 新会话重置，确保引导气泡可再次显示
  showInterruptMenu.value = false
  showRewindPicker.value = false
  resetColors()
  orchStartNewSession()
}

function shareChat() {
  const msgs = sortedMessages.value.filter(
    m => m.type !== 'event' && m.type !== 'system' && m.status !== 'failed',
  )
  if (!msgs.length) {
    messageApi.warning(t('chat.shareEmpty'))
    return
  }
  const lines = msgs.map(m => {
    let label: string
    if (m.sender_type === 'narrator' || m.sender_type === 'system') {
      label = t('chat.narrationLabel')
    } else if (m.sender_type === 'user') {
      label = userDisplayName.value || t('chat.youBadge')
    } else {
      label = m.sender_name || '??'
    }
    // 动作描写用双引号包裹，其余保留原文
    const text = m.content
      .replace(/\*([^*]+)\*/g, '「$1」')
      .trim()
    return text ? `[${label}]：${text}` : ''
  }).filter(Boolean)
  if (!lines.length) {
    messageApi.warning(t('chat.shareEmpty'))
    return
  }
  const result = lines.join('\n\n')
  navigator.clipboard.writeText(result).then(
    () => messageApi.success(t('chat.shareCopied')),
    () => messageApi.error(t('chat.shareFailed')),
  )
}

function handleDeleteSession(deletedSessionId: string) {
  if (currentSessionId.value === deletedSessionId) {
    startNewSession()
  }
}

onMounted(async () => {
  const w = await getWorld(props.id)
  world.value = w
  try {
    await loadCharacters()
  } catch {
    try {
      await loadCharacters()
    } catch {
      messageApi.error(t('chat.loadCharactersFailed'))
    }
  }

  // --- Mode persistence: restore eventMode on refresh, reset on fresh entry ---
  const sessionKey = `mive_chat_session_active:${props.id}`
  const modeKey = `mive_chat_mode:${props.id}`

  if (sessionStorage.getItem(sessionKey)) {
    // Refresh scenario: restore mode from localStorage
    const savedMode = localStorage.getItem(modeKey)
    if (savedMode === 'event') {
      eventMode.value = true
    }
  } else {
    // Fresh entry from world page or new tab: clear old mode, use default
    localStorage.removeItem(modeKey)
    eventMode.value = false
  }

  // Mark current session as active
  sessionStorage.setItem(sessionKey, '1')

  orchInit()
})

// --- Persist eventMode to localStorage on change ---
watch(eventMode, (newVal) => {
  const modeKey = `mive_chat_mode:${props.id}`
  if (newVal) {
    localStorage.setItem(modeKey, 'event')
  } else {
    localStorage.removeItem(modeKey)
  }
})

onBeforeUnmount(() => {
  orchBeforeUnmount()
})
</script>

<template>
  <div class="chat-page">
    <div class="chat-page__header">
      <button class="chat-page__back" @click="goBack">
        <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
          <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="chat-page__header-info">
        <span class="chat-page__title">{{ world?.source.title ?? $t('chat.loadingTitle') }}</span>
      </div>
    </div>

    <Transition name="banner">
      <div v-if="currentEventTitle" class="chat-page__event-banner">
        <button class="event-banner__bolt" @click="toggleEventLifecycle" :title="$t('chat.eventManage')">⚡</button>
        <span class="event-banner__title">{{ currentEventTitle }}</span>
      </div>
    </Transition>

    <!-- 事件生命周期管理菜单 -->
    <Transition name="banner">
      <div v-if="showEventLifecycle" class="chat-page__lifecycle-menu">
        <span class="lifecycle-menu__label">{{ $t('chat.eventLifecycle') }}</span>
        <button v-if="isStreaming" class="lifecycle-menu__btn" @click="lifecyclePause">{{ $t('chat.pause') }}</button>
        <button v-if="!isStreaming && eventStarted" class="lifecycle-menu__btn lifecycle-menu__btn--primary" @click="lifecycleGoOn">{{ $t('chat.goOn') }}</button>
        <button v-if="eventStarted" class="lifecycle-menu__btn" @click="lifecycleEnrich">{{ $t('chat.enrich') }}</button>
        <button v-if="eventStarted" class="lifecycle-menu__btn" @click="lifecycleEndHere">{{ $t('chat.endHere') }}</button>
        <button class="lifecycle-menu__btn" @click="lifecycleRewind" :disabled="rewindableEvents.length === 0">{{ $t('chat.rewind') }}</button>
        <button class="lifecycle-menu__btn lifecycle-menu__btn--danger" @click="lifecycleDiscard">{{ $t('chat.discard') }}</button>
      </div>
    </Transition>

    <Transition name="disclaimer-fade">
      <div v-if="showAiDisclaimer" class="ai-disclaimer">
        <span class="ai-disclaimer__text">{{ $t('legal.aiDisclaimer') }}</span>
        <button class="ai-disclaimer__close" @click="showAiDisclaimer = false" :aria-label="$t('common.close')">×</button>
      </div>
    </Transition>

    <MessageList
      ref="messageListRef"
      :messages="sortedMessages"
      :has-more="hasMore"
      :loading="loading"
      :current-event-id="currentTimelineEventId"
      :character-portrait-map="characterPortraitMap"
      :character-name-map="characterNameMap"
      :user-character-map="userCharacterMap"
      @load-more="loadMore"
      @avatar-click="handleAvatarClick"
    />

    <!-- Starter Prompts（空会话引导） -->
    <Transition name="starter-fade">
      <div v-if="!loading && sortedMessages.length === 0 && !sending && !isFakeStreaming && !isProcessing && !eventSending" class="chat-page__starter-prompts">
        <button
          v-for="(prompt, idx) in starterPrompts"
          :key="idx"
          class="starter-prompt"
          @click="handleStarterPrompt(prompt)"
        >
          <span class="starter-prompt__text">{{ prompt }}</span>
        </button>
      </div>
    </Transition>

    <!-- 消息队列显示（浮动） -->
    <QueueBar
      :items="queueDisplayItems"
      @remove="removeQueueItem"
    />


    <!-- 打断后操作菜单 -->
    <div v-if="showInterruptMenu" class="chat-page__interrupt-menu">
      <span class="interrupt-menu__label">{{ $t('chat.selectAction') }}</span>
      <button class="interrupt-menu__btn interrupt-menu__btn--primary" @click="handleGoOn">{{ $t('chat.goOn') }}</button>
      <button class="interrupt-menu__btn" @click="handleEnrich">{{ $t('chat.enrich') }}</button>
      <button class="interrupt-menu__btn" @click="handleEndHere">{{ $t('chat.endHere') }}</button>
      <button class="interrupt-menu__btn" @click="handleShowRewind" :disabled="rewindableEvents.length === 0">{{ $t('chat.rewind') }}</button>
      <button class="interrupt-menu__btn interrupt-menu__btn--danger" @click="handleDiscard">{{ $t('chat.discard') }}</button>
    </div>

    <!-- Rewind 事件选择器 -->
    <div v-else-if="showRewindPicker" class="chat-page__rewind-picker">
      <div class="rewind-picker__header">
        <span class="rewind-picker__title">{{ $t('chat.rewindTitle') }}</span>
        <button class="rewind-picker__cancel" @click="showRewindPicker = false; showInterruptMenu = true">{{ $t('common.cancel') }}</button>
      </div>
      <div class="rewind-picker__list">
        <button
          v-for="msg in rewindableEvents"
          :key="msg.id"
          class="rewind-picker__item"
          @click="handleRewindSelect(msg.id)"
        >
          <span class="rewind-picker__item-icon">⚡</span>
          <span class="rewind-picker__item-title">{{ getEventTitle(msg) }}</span>
          <span class="rewind-picker__item-time">{{ formatTime(msg.created_at ?? '') }}</span>
        </button>
      </div>
    </div>

    <!-- 丰富事件补充输入框 -->
    <div v-else-if="enrichMode" class="chat-page__enrich-bar">
      <ChatInput
        :disabled="false"
        :placeholder="$t('chat.enrichPlaceholder')"
        @send="handleEnrichSubmit"
      />
      <button class="enrich-bar__cancel" @click="enrichMode = false; showInterruptMenu = false">{{ $t('common.cancel') }}</button>
    </div>

    <!-- 正常输入区 / 推演状态输入区 -->
    <div v-else class="chat-page__input-area">
      <ChatInput
        v-model:event-mode="eventMode"
        v-model:participant-mode="chatParticipantMode"
        v-model:user-role="chatUserRole"
        v-model:memories-enabled="memoriesEnabled"
        v-model:action-descriptions="actionDescriptions"
        v-model:show-narration="showNarration"
        v-model:element-rerank="elementRerank"
        v-model:element-injection-enabled="elementInjectionEnabled"
        v-model:element-injection-ids="elementInjectionIds"
        v-model:constraint-text="constraintText"
        :disabled="eventStarted"
        :streaming="isStreaming"
        :sending="sending || isFakeStreaming || isProcessing"
        :world-id="props.id"
        :characters="characters"
        :participants="chatParticipants"
        :user-character-id="worldUserCharacterId"
        :character-portrait-map="characterPortraitMap"
        :session-started="sessionStarted"
        @send="(content, pMode, pList) => eventMode ? handleEventInject(content) : handleSend(content, pMode, pList)"
        @interrupt="handleInputInterrupt"
        @avatar-change="handleAvatarChange"
      />
    </div>
  </div>

  <input
    ref="avatarFileInput"
    type="file"
    accept="image/*"
    style="display: none"
    @change="onAvatarFileChange"
  />

  <ChatHistoryDrawer
    :world-id="props.id"
    v-model:show="showHistory"
    :character-portrait-map="characterPortraitMap"
    :character-name-map="characterNameMap"
    :user-character-map="userCharacterMap"
    @resume="handleResume"
    @delete="handleDeleteSession"
  />

  <!-- 聊天页专属浮动按钮：新会话、分享、历史记录，与全局 toolbar 同行 -->
  <div ref="fabGroupRef" class="chat-page__fab-group">
    <!-- 桌面端：横向排列 -->
    <button class="chat-page__fab chat-page__fab--inline" @click="startNewSession" :title="$t('chat.newSession')">
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
        <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
    </button>
    <button class="chat-page__fab chat-page__fab--inline" @click="shareChat" :title="$t('chat.share')">
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
        <path d="M10 2h4v4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M14 2L8 8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
        <path d="M12 9v4a1 1 0 01-1 1H3a1 1 0 01-1-1V5a1 1 0 011-1h4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <button class="chat-page__fab chat-page__fab--inline" @click="showHistory = true" :title="$t('chat.history')">
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2" opacity="0.6"/>
        <path d="M8 4v4l2.5 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <!-- 移动端：三点按钮 + 竖向展开 -->
    <button class="chat-page__fab chat-page__fab--dots" @click="toggleFabMenu" :aria-label="$t('common.more')">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
        <circle cx="8" cy="3" r="1.5"/>
        <circle cx="8" cy="8" r="1.5"/>
        <circle cx="8" cy="13" r="1.5"/>
      </svg>
    </button>
    <div class="chat-page__fab-menu" :class="{ open: showFabMenu }">
      <button
        class="chat-page__fab"
        @click="startNewSession(); closeFabMenu()"
        @touchstart="onFabTouchStart($event, $t('chat.newSession'))"
        @touchend="onFabTouchEnd"
        @touchmove="onFabTouchMove"
        @touchcancel="onFabTouchEnd"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </button>
      <button
        class="chat-page__fab"
        @click="shareChat(); closeFabMenu()"
        @touchstart="onFabTouchStart($event, $t('chat.share'))"
        @touchend="onFabTouchEnd"
        @touchmove="onFabTouchMove"
        @touchcancel="onFabTouchEnd"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M10 2h4v4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M14 2L8 8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
          <path d="M12 9v4a1 1 0 01-1 1H3a1 1 0 01-1-1V5a1 1 0 011-1h4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <button
        class="chat-page__fab"
        @click="showHistory = true; closeFabMenu()"
        @touchstart="onFabTouchStart($event, $t('chat.history'))"
        @touchend="onFabTouchEnd"
        @touchmove="onFabTouchMove"
        @touchcancel="onFabTouchEnd"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2" opacity="0.6"/>
          <path d="M8 4v4l2.5 1.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
    <!-- 长按提示 -->
    <Teleport to="body">
      <div
        v-if="showFabTooltip"
        class="fab-longpress-tooltip"
        :style="{ left: fabTooltipX + 'px', top: fabTooltipY + 'px' }"
      >{{ fabTooltipText }}</div>
    </Teleport>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100vh; /* Fallback for older browsers */
  height: 100dvh; /* Dynamic viewport height for mobile */
  background: var(--bg-deep);
}

.chat-page__header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px 28px 12px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
  backdrop-filter: blur(12px);
  z-index: 10;
}

.chat-page__back {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.chat-page__back:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-primary);
}

/* === 聊天页浮动按钮组（与全局 toolbar 同行） === */
.chat-page__fab-group {
  position: fixed;
  top: 18px;
  right: 190px;
  z-index: 200;
  display: flex;
  align-items: center;
  gap: 10px;
  pointer-events: all;
}

.chat-page__fab {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.chat-page__fab:hover {
  background: var(--accent-hover);
  transform: scale(1.1);
}

/* 移动端三点按钮 & 下拉菜单，默认隐藏 */
.chat-page__fab--dots {
  display: none;
}

.chat-page__fab-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 6px;
  border-radius: 20px;
  border: 1px solid rgba(0,0,0,0.08);
  background: var(--bg-deep);
  backdrop-filter: blur(16px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.25);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: all 0.15s;
  pointer-events: none;
  z-index: 100;
}

.chat-page__fab-menu.open {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
  pointer-events: auto;
}

.chat-page__fab-menu .chat-page__fab {
  border: none;
  background: transparent;
  color: var(--accent);
}

.chat-page__fab-menu .chat-page__fab:hover {
  background: var(--accent);
  color: #fff;
}

@media (max-width: 768px) {
  .chat-page__fab-group {
    top: 18px;
    right: 190px;
  }

  .chat-page__fab--inline {
    display: none;
  }

  .chat-page__fab--dots {
    display: flex;
  }
}

.chat-page__header-info {
  flex: 1;
  min-width: 0;
}

.chat-page__title {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 17px;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}

/* === BREEZE === */
[data-theme="breeze"] .chat-page {
  background: var(--bg-deep);
}
[data-theme="breeze"] .chat-page__header {
  background: color-mix(in srgb, var(--bg-card) 88%, transparent);
  border-bottom-color: rgba(0, 0, 0, 0.06);
}
[data-theme="breeze"] .chat-page__back:hover {
  background: rgba(0, 0, 0, 0.06);
  color: var(--text-primary);
}

/* === AI Disclaimer Banner === */
.ai-disclaimer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 18px;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.5;
  flex-shrink: 0;
}
.ai-disclaimer__text {
  flex: 1;
}
.ai-disclaimer__close {
  flex-shrink: 0;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  opacity: 0.6;
}
.ai-disclaimer__close:hover {
  opacity: 1;
}
.disclaimer-fade-enter-active,
.disclaimer-fade-leave-active {
  transition: all 0.2s ease;
}
.disclaimer-fade-enter-from,
.disclaimer-fade-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

/* === Sticky Event Banner === */
.chat-page__event-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 28px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
  min-height: 44px;
  z-index: 9;
}

.event-banner__bolt {
  font-size: 16px;
  flex-shrink: 0;
  cursor: pointer;
  background: none;
  border: none;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background 0.15s;
  line-height: 1;
}

.event-banner__bolt:hover {
  background: var(--bg-input);
}

.event-banner__title {
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.banner-enter-active, .banner-leave-active {
  transition: all 0.2s ease;
}
.banner-enter-from, .banner-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

[data-theme="ink"] .chat-page__event-banner {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
  border-bottom-color: color-mix(in srgb, var(--accent) 12%, transparent);
}
[data-theme="ink"] .event-banner__title { color: var(--accent); }

[data-theme="breeze"] .chat-page__event-banner {
  background: color-mix(in srgb, var(--accent) 3%, transparent);
  border-bottom-color: color-mix(in srgb, var(--accent) 10%, transparent);
}
[data-theme="breeze"] .event-banner__title { color: var(--accent); }

/* === 打断菜单 === */
.chat-page__interrupt-menu {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 28px;
  border-top: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.interrupt-menu__label {
  font-size: 15px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.interrupt-menu__btn {
  padding: 10px 18px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 15px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s;
}

.interrupt-menu__btn:hover {
  background: var(--bg-input);
  border-color: var(--accent);
  color: var(--accent);
}

.interrupt-menu__btn--primary {
  border-color: var(--accent);
  color: var(--accent);
}

.interrupt-menu__btn--primary:hover {
  background: var(--accent);
  color: var(--bg-deep);
}

.interrupt-menu__btn--danger:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.interrupt-menu__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* === 事件生命周期菜单 === */
.chat-page__lifecycle-menu {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 28px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
  flex-wrap: wrap;
  z-index: 9;
}

.lifecycle-menu__label {
  font-size: 15px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.lifecycle-menu__btn {
  padding: 7px 16px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 14px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s;
}

.lifecycle-menu__btn:hover {
  background: var(--bg-input);
  border-color: var(--accent);
  color: var(--accent);
}

.lifecycle-menu__btn--primary {
  border-color: var(--accent);
  color: var(--accent);
}

.lifecycle-menu__btn--primary:hover {
  background: var(--accent);
  color: var(--bg-deep);
}

.lifecycle-menu__btn--danger:hover {
  border-color: var(--color-error);
  color: var(--color-error);
}

.lifecycle-menu__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* === Rewind 选择器 === */
.chat-page__rewind-picker {
  border-top: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
  background: var(--bg-deep);
}

.rewind-picker__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px 10px;
}

.rewind-picker__title {
  font-size: 15px;
  color: var(--text-muted);
}

.rewind-picker__cancel {
  font-size: 14px;
  color: var(--text-muted);
  background: none;
  border: none;
  cursor: pointer;
  padding: 5px 10px;
}

.rewind-picker__cancel:hover { color: var(--text-primary); }

.rewind-picker__list {
  max-height: 280px;
  overflow-y: auto;
  padding: 0 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rewind-picker__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
  width: 100%;
}

.rewind-picker__item:hover {
  background: var(--bg-input);
  border-color: var(--accent);
}

.rewind-picker__item-icon { font-size: 17px; flex-shrink: 0; }

.rewind-picker__item-title {
  flex: 1;
  font-size: 15px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rewind-picker__item-time {
  font-size: 13px;
  color: var(--text-muted);
  flex-shrink: 0;
}

/* === 丰富事件栏 === */
.chat-page__enrich-bar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 14px 22px 16px;
  border-top: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.chat-page__enrich-bar :deep(.chat-input) {
  flex: 1;
  min-width: 0;
}

.enrich-bar__cancel {
  flex-shrink: 0;
  padding: 10px 18px;
  border-radius: 8px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  font-size: 15px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  align-self: flex-end;
  margin-bottom: 1px;
}

.enrich-bar__cancel:hover {
  color: var(--text-primary);
  background: var(--bg-input);
}

/* === 正常输入区 === */
.chat-page__input-area {
  padding: 14px 22px 16px;
  border-top: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}

/* === Starter Prompts === */
.chat-page__starter-prompts {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 24px 28px;
  flex-shrink: 0;
}

.starter-prompt {
  display: inline-block;
  padding: 12px 22px;
  border-radius: 16px;
  border: 1px solid rgba(0,0,0,0.08);
  background: color-mix(in srgb, var(--accent) 6%, transparent);
  color: var(--text-primary);
  font-size: 15px;
  line-height: 1.6;
  cursor: pointer;
  transition: all 0.2s;
  max-width: 80%;
  text-align: left;
}

.starter-prompt:hover {
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  border-color: var(--accent);
  transform: translateY(-1px);
}

.starter-prompt__text {
  pointer-events: none;
}

.starter-fade-enter-active,
.starter-fade-leave-active {
  transition: all 0.3s ease;
}

.starter-fade-enter-from,
.starter-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

</style>

<style>
/* 长按提示（Teleport 到 body，不能用 scoped） */
.fab-longpress-tooltip {
  position: fixed;
  transform: translate(-50%, -100%);
  padding: 4px 10px;
  border-radius: 6px;
  background: var(--text-primary, #fff);
  color: var(--bg-deep, #111);
  font-size: 12px;
  font-family: inherit;
  white-space: nowrap;
  pointer-events: none;
  z-index: 9999;
  opacity: 0;
  animation: fab-tooltip-in 0.15s ease forwards;
}

@keyframes fab-tooltip-in {
  from { opacity: 0; transform: translate(-50%, -100%) translateY(4px); }
  to { opacity: 1; transform: translate(-50%, -100%) translateY(0); }
}
</style>
