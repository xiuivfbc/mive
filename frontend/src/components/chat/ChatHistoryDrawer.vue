<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { NSpin } from 'naive-ui'
import { listChatSessions, getChatSessionMessages, deleteChatSession } from '@/api/chatSessions'
import { deleteSessionMemories } from '@/api/memories'
import type { ChatSession } from '@/types/chatSession'
import type { Message } from '@/types/message'
import MessageBubble from './MessageBubble.vue'
import { useLocale } from '@/composables/useLocale'

const props = defineProps<{
  worldId: string
  show: boolean
  characterPortraitMap?: Record<string, string>
  characterNameMap?: Record<string, string>
  /** Map of character_id -> {name, portrait_url} for per-message user role identity */
  userCharacterMap?: Record<string, { name: string; portrait_url: string | null }>
}>()
const emit = defineEmits<{
  'update:show': [boolean]
  'resume': [session: ChatSession, messages: Message[]]
  'delete': [sessionId: string]
}>()
const { locale } = useLocale()

const panelRef = ref<HTMLElement | null>(null)
const sessions = ref<ChatSession[]>([])
const loadingSessions = ref(false)
const selectedSession = ref<ChatSession | null>(null)
const sessionMessages = ref<Message[]>([])
const loadingMessages = ref(false)

const sortedSessions = computed(() =>
  [...sessions.value].sort(
    (a, b) => new Date(b.last_active_at ?? b.created_at).getTime() - new Date(a.last_active_at ?? a.created_at).getTime(),
  ),
)

function close() {
  emit('update:show', false)
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const res = await listChatSessions(props.worldId)
    sessions.value = res.sessions
  } finally {
    loadingSessions.value = false
  }
}

async function selectSession(session: ChatSession) {
  selectedSession.value = session
  loadingMessages.value = true
  sessionMessages.value = []
  try {
    const res = await getChatSessionMessages(props.worldId, session.id)
    sessionMessages.value = res.messages
  } finally {
    loadingMessages.value = false
  }
}

function back() {
  selectedSession.value = null
  sessionMessages.value = []
}

const deletingId = ref<string | null>(null)
const resumingId = ref<string | null>(null)
const clearedMemoryIds = ref<Set<string>>(new Set())
const clearingMemoryId = ref<string | null>(null)

async function deleteSession(e: Event, session: ChatSession) {
  e.stopPropagation()
  deletingId.value = session.id
  try {
    await deleteChatSession(props.worldId, session.id)
    sessions.value = sessions.value.filter((s) => s.id !== session.id)
    emit('delete', session.id)
  } finally {
    deletingId.value = null
  }
}

async function clearMemories(e: Event, session: ChatSession) {
  e.stopPropagation()
  clearingMemoryId.value = session.id
  try {
    await deleteSessionMemories(props.worldId, session.id)
    clearedMemoryIds.value = new Set([...clearedMemoryIds.value, session.id])
  } catch {
    ;(window as any).$message?.error('清除记忆失败，请稍后重试')
  } finally {
    clearingMemoryId.value = null
  }
}

async function resumeSession(e: Event, session: ChatSession) {
  e.stopPropagation()
  // 如果已在详情视图且消息已加载，直接复用；否则重新拉取
  if (selectedSession.value?.id === session.id && sessionMessages.value.length > 0) {
    emit('resume', session, sessionMessages.value)
    close()
    return
  }
  resumingId.value = session.id
  try {
    const res = await getChatSessionMessages(props.worldId, session.id)
    emit('resume', session, res.messages)
    close()
  } finally {
    resumingId.value = null
  }
}

function formatDate(dt: string) {
  return new Date(dt).toLocaleString(locale.value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.show) close()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

watch(
  () => props.show,
  (val) => {
    if (val) {
      selectedSession.value = null
      loadSessions()
      // 延迟 focus 到面板本身，确保面板已渲染
      setTimeout(() => panelRef.value?.focus(), 50)
    }
  }
)
</script>

<template>
  <Teleport to="body">
    <Transition name="history-fade">
      <div v-if="show" class="history-overlay" @click.self="close">
        <div
          ref="panelRef"
          class="history-panel"
          role="dialog"
          aria-modal="true"
          :aria-label="$t('chatHistory.title')"
          tabindex="-1"
        >
          <!-- 会话列表视图 -->
          <template v-if="!selectedSession">
            <div class="history-panel__header">
              <span class="history-panel__title">{{ $t('chatHistory.title') }}</span>
              <button class="history-panel__close" @click="close" :aria-label="$t('common.close')">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </button>
            </div>

            <div v-if="loadingSessions" class="history-panel__body">
              <div class="history-panel__loading"><NSpin size="small" /></div>
            </div>
            <div v-else class="history-panel__body">
              <template v-if="sortedSessions.length > 0">
                <div
                  v-for="s in sortedSessions"
                  :key="s.id"
                  class="history-panel__item"
                  @click="selectSession(s)"
                >
                  <span class="history-panel__item-icon">{{ s.type === 'event' ? '⚡' : '💬' }}</span>
                  <span class="history-panel__item-body">
                    <span class="history-panel__item-title">
                      <span v-if="s.type === 'event'" class="history-panel__type-tag history-panel__type-tag--event">{{ $t('chatHistory.typeEvent') }}</span>
                      <span v-else class="history-panel__type-tag history-panel__type-tag--chat">{{ $t('chatHistory.typeChat') }}</span>
                      {{ s.title ?? $t('chatHistory.fallbackTitle') }}
                    </span>
                    <span class="history-panel__item-time">{{ formatDate(s.last_active_at ?? s.created_at) }}</span>
                  </span>
                  <div class="history-panel__item-actions">
                    <button
                      class="history-panel__item-resume"
                      :class="{ loading: resumingId === s.id }"
                      @click="resumeSession($event, s)"
                      :aria-label="$t('chatHistory.continueChat')"
                      :title="$t('chatHistory.continueChat')"
                    >{{ $t('chatHistory.continueSession') }}</button>
                    <button
                      class="history-panel__item-clear-memory"
                      :class="{ loading: clearingMemoryId === s.id, cleared: clearedMemoryIds.has(s.id) }"
                      :disabled="clearedMemoryIds.has(s.id) || clearingMemoryId === s.id"
                      @click="clearMemories($event, s)"
                      title="清除记忆"
                    >{{ clearedMemoryIds.has(s.id) ? '已清除' : '清除记忆' }}</button>
                    <button
                      class="history-panel__item-delete"
                      :class="{ loading: deletingId === s.id }"
                      @click="deleteSession($event, s)"
                      :aria-label="$t('common.delete')"
                      :title="$t('common.delete')"
                    >
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                        <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                      </svg>
                    </button>
                  </div>
                </div>
              </template>
              <div v-else class="history-panel__empty">{{ $t('chatHistory.noDialogues') }}</div>
            </div>
          </template>

          <!-- 消息详情视图 -->
          <template v-else>
            <div class="history-panel__header">
              <button class="history-panel__back" @click="back" :aria-label="$t('common.back')">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M10 3L5 8l5 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </button>
              <span class="history-panel__title">{{ selectedSession.title ?? $t('chatHistory.title') }}</span>
              <button
                class="history-panel__item-resume history-panel__detail-resume"
                :class="{ loading: resumingId === selectedSession.id }"
                @click="resumeSession($event, selectedSession)"
              >{{ $t('chatHistory.continueChat') }}</button>
              <button class="history-panel__close" @click="close" :aria-label="$t('common.close')">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                  <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
              </button>
            </div>

            <div class="history-panel__body">
              <div v-if="loadingMessages" class="history-panel__loading">
                <NSpin size="small" />
              </div>
              <div v-else class="history-panel__messages">
                <MessageBubble
                  v-for="msg in sessionMessages"
                  :key="msg.id"
                  :message="msg"
                  :portrait-url="msg.sender_id ? characterPortraitMap?.[msg.sender_id] : undefined"
                  :character-id="msg.sender_id"
                  :character-name-map="characterNameMap"
                  :user-character-map="userCharacterMap"
                />
                <div v-if="sessionMessages.length === 0" class="history-panel__empty">{{ $t('chatHistory.noMessages') }}</div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* === 遮罩层 === */
.history-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  z-index: 200;
  backdrop-filter: blur(2px);
}

/* === 面板 === */
.history-panel {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 380px;
  max-width: 100vw;
  display: flex;
  flex-direction: column;
  background: var(--bg-deep);
  border-left: 1px solid rgba(0,0,0,0.06);
  outline: none;
  overflow: hidden;
}

/* === 标题栏 === */
.history-panel__header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 12px 12px 16px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.history-panel__title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-display);
  flex: 1;
}

.history-panel__back,
.history-panel__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.history-panel__back:hover,
.history-panel__close:hover {
  color: var(--text-primary);
  background: var(--bg-input);
}

/* === 可滚动内容区（详情视图 / loading） === */
.history-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0 12px;
}

/* === 列表视图 === */
.history-panel__loading {
  display: flex;
  justify-content: center;
  padding: 32px;
}

/* === 类型标签 === */
.history-panel__type-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 3px;
  margin-right: 4px;
  vertical-align: 1px;
  line-height: 1.4;
}

.history-panel__type-tag--event {
  background: rgba(255, 180, 0, 0.15);
  color: var(--accent);
}

.history-panel__type-tag--chat {
  background: rgba(100, 160, 255, 0.12);
  color: var(--text-muted);
}

/* === 会话列表项（button 元素，无需角色问题） === */
.history-panel__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border: none;
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s;
  border-radius: 6px;
  margin: 0 6px;
  width: calc(100% - 12px);
  box-sizing: border-box;
}

.history-panel__item:hover {
  background: var(--bg-input);
}

.history-panel__item:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

.history-panel__item-actions {
  display: none;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  margin-left: auto;
}

.history-panel__item:hover .history-panel__item-actions {
  display: flex;
}

.history-panel__item-resume {
  display: flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.history-panel__item-resume:hover {
  background: var(--accent);
  color: var(--bg-deep);
}

.history-panel__item-resume.loading {
  opacity: 0.4;
  pointer-events: none;
}

.history-panel__detail-resume {
  display: flex;
  flex-shrink: 0;
}

.history-panel__item-delete {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
}

.history-panel__item-delete:hover {
  color: #e05a5a;
  background: rgba(224, 90, 90, 0.1);
}

.history-panel__item-delete.loading {
  opacity: 0.4;
  pointer-events: none;
}

.history-panel__item-clear-memory {
  display: flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(0,0,0,0.08);
  background: none;
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.history-panel__item-clear-memory:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.history-panel__item-clear-memory.loading,
.history-panel__item-clear-memory:disabled {
  opacity: 0.4;
  pointer-events: none;
}

.history-panel__item-clear-memory.cleared {
  opacity: 0.5;
  cursor: default;
}

.history-panel__item-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.history-panel__item-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.history-panel__item-title {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}

.history-panel__item-time {
  font-size: 11px;
  color: var(--text-muted);
  display: block;
}

/* === 空状态 / 消息列表 === */
.history-panel__empty {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 32px;
}

.history-panel__messages {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}

/* === 进入/离开动画 === */
.history-fade-enter-active,
.history-fade-leave-active {
  transition: opacity 0.2s ease;
}
.history-fade-enter-active .history-panel,
.history-fade-leave-active .history-panel {
  transition: transform 0.2s ease;
}
.history-fade-enter-from,
.history-fade-leave-to {
  opacity: 0;
}
.history-fade-enter-from .history-panel,
.history-fade-leave-to .history-panel {
  transform: translateX(24px);
}

/* === 主题 === */
[data-theme="ink"] .history-panel {
  background: var(--bg-deep);
  border-left-color: rgba(20, 212, 168, 0.12);
}

[data-theme="breeze"] .history-panel {
  background: #f4f6fb;
  border-left-color: rgba(0, 0, 0, 0.07);
}

</style>
