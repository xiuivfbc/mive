import { ref, computed, nextTick, type Ref } from 'vue'
import { listMessages, sendMessage } from '@/api/messages'
import { discardEvent, rewindToEvent, trimStreamMessages } from '@/api/events'
import { useCursorPagination } from '@/composables/useCursorPagination'
import { useEventStream } from '@/composables/useEventStream'
import { useChatQueue } from '@/composables/useChatQueue'
import { useFakeStreaming } from '@/composables/useFakeStreaming'
import { useChatSession } from '@/composables/useChatSession'
import { parseApiError } from '@/utils/apiError'
import { flushChatMemories } from '@/api/memories'
import type { Message, SseEventInjectedPayload, QueueItem, SendMessageResponse } from '@/types/message'
import type { Participant } from '@/types/chatSession'
import type { useI18n } from 'vue-i18n'
import type { useMessage } from 'naive-ui'

export interface UseChatOrchestrationOptions {
  worldId: Ref<string>
  /** Ref to the MessageList component instance for scrollToBottom */
  messageListRef: Ref<{ scrollToBottom: () => void } | null>
  /** i18n translation function */
  t: ReturnType<typeof useI18n>['t']
  /** Naive UI message API */
  messageApi: ReturnType<typeof useMessage>
  /** Restore participant state from a persisted session */
  restoreSessionParticipants: (
    rawParticipants: Array<string | Participant> | null | undefined,
    mode: 'auto' | 'edit' | 'include' | null | undefined,
  ) => void
  /** Reset participant state to defaults */
  resetParticipants: () => void
  /** Update participants from server response */
  applyServerParticipants: (
    serverParticipants: Participant[],
    serverMode: 'auto' | 'edit' | 'include',
  ) => void
  /** Current user role character id */
  chatUserRole: Ref<string | null>
}

export function useChatOrchestration(options: UseChatOrchestrationOptions) {
  const {
    worldId,
    messageListRef,
    t,
    messageApi,
    restoreSessionParticipants,
    resetParticipants,
    applyServerParticipants,
    chatUserRole,
  } = options

  // ---- Internal state ----
  const sending = ref(false)
  const isFakeStreaming = ref(false)
  const currentSessionId = ref<string | null>(null)
  const sessionStarted = ref(false)
  const eventStarted = ref(false)
  const enrichMode = ref(false)
  const lastRawInput = ref('')
  const memoriesEnabled = ref(false)
  const actionDescriptions = ref(false)
  const showNarration = ref(false)
  const elementRerank = ref(false)
  const elementInjectionEnabled = ref(false)
  const elementInjectionIds = ref<string[]>([])
  const constraintText = ref('')

  const canUseRerank = computed(() => true)

  function toggleElementRerank() {
    elementRerank.value = !elementRerank.value
  }

  function scrollToBottom() {
    messageListRef.value?.scrollToBottom()
  }

  // ---- Composed composables ----
  const {
    isStreaming,
    currentEventTitle,
    currentEventId,
    currentCardMessageId,
    currentParticipants,
    currentSessionMessageIds,
    inject,
    pause,
    resume,
    stop,
    discardBuffer,
  } = useEventStream(worldId)

  const {
    sendCounter,
    streamMessages,
    cancelStreaming,
    invalidateStreaming,
    flushPending,
  } = useFakeStreaming(isFakeStreaming)

  const {
    items: messages,
    hasMore,
    loading,
    loadInitial,
    loadMore,
    append,
  } = useCursorPagination<Message>({
    fetchFn: async (params) => {
      if (!currentSessionId.value) {
        return { items: [], has_more: false }
      }
      const res = await listMessages(worldId.value, {
        ...params,
        session_id: currentSessionId.value,
      })
      return { items: [...res.messages].reverse(), has_more: res.has_more }
    },
    limit: 50,
    getSequenceFn: (msg) => msg.sequence ?? undefined,
  })

  const {
    restoreQueue,
    enqueue: enqueueItem,
    remove: removeQueueItem,
    processNext: processNextInQueue,
    clearFailed,
    clearAll: clearAllQueue,
    displayItems: queueDisplayItems,
    markProcessing,
    clearProcessing,
    isProcessing,
  } = useChatQueue({
    worldId,
    sessionId: currentSessionId,
    async onProcess(item: QueueItem): Promise<SendMessageResponse> {
      const optimisticId = `opt-queue-${item.id}`
      const optimisticMsg: Message = {
        id: optimisticId,
        world_id: worldId.value,
        type: 'user',
        sender_type: 'user',
        sender_id: item.userRole,
        sender_name: null,
        content: item.content,
        real_time: null,
        is_key_message: false,
        user_participated: true,
        created_at: null,
        sequence: Number.MAX_SAFE_INTEGER,
      }
      append(optimisticMsg)
      await nextTick()
      scrollToBottom()

      return await sendMessage(
        worldId.value,
        item.content,
        item.participantMode,
        item.participants,
        currentSessionId.value,
        memoriesEnabled.value,
        actionDescriptions.value,
        elementRerank.value,
        item.idempotencyKey,
        showNarration.value,
        item.userRole,
        elementInjectionIds.value,
        constraintText.value,
      )
    },
    async onSuccess(item: QueueItem, res: SendMessageResponse) {
      try {
        if (res.session_id) currentSessionId.value = res.session_id
        if (!sessionStarted.value) sessionStarted.value = true

        applyServerParticipants(res.participants, res.participant_mode)

        const optimisticId = `opt-queue-${item.id}`
        messages.value = messages.value.map(m => m.id === optimisticId ? res.user_message : m)

        const existingIds = new Set(messages.value.map((m) => m.id))
        const narrationToShow = (res.narration && !existingIds.has(res.narration.id)) ? res.narration : null
        const newResponses = res.responses.filter((r) => !existingIds.has(r.id))
        const allItems: Message[] = [
          ...(narrationToShow ? [narrationToShow] : []),
          ...newResponses,
        ]

        await streamMessages(
          allItems,
          (msg) => append(msg),
          scrollToBottom,
        )

        if (res.error) {
          messageApi.error('角色回复生成失败')
        }
      } catch (e) {
        isFakeStreaming.value = false
        throw e
      }
    },
    onFailure(item: QueueItem, error: string, errorResponse?: { session_id?: string | null }, errorObj?: unknown) {
      const errorMsg = errorObj ? parseApiError(errorObj, t) : `消息发送失败: ${error}`
      messageApi.error(errorMsg)
      if (errorResponse?.session_id) currentSessionId.value = errorResponse.session_id
      const optId = `opt-queue-${item.id}`
      const failedIdx = messages.value.findIndex((m) => m.id === optId)
      if (failedIdx !== -1) {
        messages.value[failedIdx] = { ...messages.value[failedIdx], status: 'failed' }
      }
    },
  })

  const {
    resetEventState,
    resetAllState,
    restoreSession,
  } = useChatSession({
    restoreSessionParticipants,
    resetParticipants,
    sessionStarted,
    eventStarted,
    eventMode: ref(false), // eventMode is UI-only, kept in ChatPage
    enrichMode,
    lastRawInput,
    showInterruptMenu: ref(false), // showInterruptMenu is UI-only, kept in ChatPage
    showRewindPicker: ref(false), // showRewindPicker is UI-only, kept in ChatPage
    currentEventTitle,
    actionDescriptions,
  })

  // ---- Derived state ----
  const currentTimelineEventId = computed(() => {
    const eventMsgs = sortedMessages.value.filter((m) => m.type === 'event')
    return eventMsgs.at(-1)?.id ?? null
  })

  const rewindableEvents = computed(() =>
    sortedMessages.value.filter(
      (m) => m.type === 'event' && m.id !== currentCardMessageId.value,
    ),
  )

  const sortedMessages = computed(() => {
    const seen = new Set<string>()
    return messages.value
      .filter((m) => {
        if (seen.has(m.id)) return false
        seen.add(m.id)
        return true
      })
      .map((m, i) => ({ m, i }))
      .sort(({ m: a, i: ai }, { m: b, i: bi }) => {
        if (a.sequence != null && b.sequence != null && a.sequence !== b.sequence) {
          return a.sequence - b.sequence
        }
        const ta = new Date(a.created_at ?? 0).getTime()
        const tb = new Date(b.created_at ?? 0).getTime()
        if (!isNaN(ta) && !isNaN(tb) && ta !== tb) return ta - tb
        return ai - bi
      })
      .map(({ m }) => m)
  })

  // ---- Handlers ----

  async function handleSend(content: string, participantMode: 'auto' | 'edit' | 'include' = 'auto', participants: Participant[] | null = null) {
    if (sending.value || isFakeStreaming.value || isProcessing.value) {
      enqueueItem(content, participantMode, participants, chatUserRole.value)
      return
    }

    flushPending()

    const currentSend = ++sendCounter.value
    sending.value = true
    const sentSessionId = currentSessionId.value

    markProcessing(content, participantMode, participants, chatUserRole.value)

    const optimisticId = `opt-${currentSend}-${Date.now()}`
    const optimisticMsg: Message = {
      id: optimisticId,
      world_id: worldId.value,
      type: 'user',
      sender_type: 'user',
      sender_id: chatUserRole.value,
      sender_name: null,
      content,
      real_time: null,
      is_key_message: false,
      user_participated: true,
      created_at: null,
      sequence: Number.MAX_SAFE_INTEGER,
    }
    append(optimisticMsg)
    await nextTick()
    scrollToBottom()

    try {
      const idempotencyKey = `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const res = await sendMessage(
        worldId.value,
        content,
        participantMode,
        participants,
        currentSessionId.value,
        memoriesEnabled.value,
        actionDescriptions.value,
        elementRerank.value,
        idempotencyKey,
        showNarration.value,
        chatUserRole.value,
      )

      if (currentSessionId.value !== sentSessionId) {
        messages.value = messages.value.filter(m => m.id !== optimisticId)
        clearProcessing()
        return
      }

      messages.value = messages.value.map(m => m.id === optimisticId ? res.user_message : m)

      if (res.session_id) currentSessionId.value = res.session_id
      if (!sessionStarted.value) sessionStarted.value = true
      if (res.memory_flush_triggered) {
        console.log('[ChatPage] memory flush triggered for session', res.session_id)
      }

      applyServerParticipants(res.participants, res.participant_mode)

      const existingIds = new Set(messages.value.map((m) => m.id))
      const newResponses = res.responses.filter((r) => !existingIds.has(r.id))

      sending.value = false

      const narrationToShow = (res.narration && !existingIds.has(res.narration.id)) ? res.narration : null
      const allItems: Message[] = [
        ...(narrationToShow ? [narrationToShow] : []),
        ...newResponses,
      ]

      await streamMessages(
        allItems,
        (msg) => append(msg),
        scrollToBottom,
      )

      if (res.error) {
        messageApi.error('角色回复生成失败')
      }

      clearProcessing()
      await processNextInQueue()
    } catch (e) {
      const idx = messages.value.findIndex((m) => m.id === optimisticId)
      if (idx !== -1) {
        messages.value[idx] = { ...messages.value[idx], status: 'failed' }
      }
      clearProcessing()
      messageApi.error(parseApiError(e, t))
      await processNextInQueue()
    } finally {
      if (sendCounter.value === currentSend) {
        sending.value = false
        isFakeStreaming.value = false
      }
    }
  }

  function buildEventMessage(payload: SseEventInjectedPayload): Message {
    return {
      id: payload.event_id,
      world_id: worldId.value,
      type: 'event',
      sender_type: 'system',
      sender_id: null,
      sender_name: null,
      content: JSON.stringify({
        title: payload.title,
        description: payload.description,
        participants: payload.participants,
      }),
      real_time: null,
      is_key_message: false,
      user_participated: false,
      created_at: new Date().toISOString(),
      sequence: payload.card_message_sequence ?? null,
    }
  }

  async function handleEventInject(rawInput: string) {
    lastRawInput.value = rawInput
    eventStarted.value = true
    await inject(rawInput, {
      onEventInjected(payload) {
        if (payload.session_id) {
          currentSessionId.value = payload.session_id
        }
        append(buildEventMessage(payload))
        nextTick(scrollToBottom)
      },
      onSpeakerTurn(msg) {
        append(msg)
        nextTick(scrollToBottom)
      },
      onNarratorTurn(msg) {
        append(msg)
        nextTick(scrollToBottom)
      },
      onMemoryUpdating() {},
      onDone() {
        eventStarted.value = false
      },
      onError(errMsg) {
        messageApi.error(`事件处理失败: ${errMsg}`)
        eventStarted.value = false
      },
    }, { sessionId: currentSessionId.value, memoriesEnabled: memoriesEnabled.value, actionDescriptions: actionDescriptions.value, showNarration: showNarration.value, elementRerank: elementRerank.value })
  }

  async function handleInputInterrupt() {
    if (isStreaming.value) {
      await pause()
    } else if (isFakeStreaming.value) {
      cancelStreaming()
    }
  }

  async function handleGoOn() {
    await resume()
  }

  async function handleEnrich() {
    const bufferedIds = discardBuffer()
    if (bufferedIds.length > 0) await trimStreamMessages(worldId.value, bufferedIds)
    await stop()
    eventStarted.value = false
    enrichMode.value = true
  }

  async function handleEnrichSubmit(additionalContext: string) {
    enrichMode.value = false
    const enrichedInput = lastRawInput.value + '\n\n[用户补充]: ' + additionalContext
    await inject(enrichedInput, {
      onEventInjected(payload) {
        if (payload.session_id) {
          currentSessionId.value = payload.session_id
        }
        currentEventTitle.value = payload.title
        append(buildEventMessage(payload))
        nextTick(scrollToBottom)
      },
      onSpeakerTurn(msg) {
        append(msg)
        nextTick(scrollToBottom)
      },
      onNarratorTurn(msg) {
        append(msg)
        nextTick(scrollToBottom)
      },
      onMemoryUpdating() {},
      onDone() {
        eventStarted.value = false
      },
      onError(errMsg) {
        messageApi.error(`事件丰富失败: ${errMsg}`)
        eventStarted.value = false
      },
    }, { sessionId: currentSessionId.value, memoriesEnabled: memoriesEnabled.value, actionDescriptions: actionDescriptions.value, showNarration: showNarration.value, elementRerank: elementRerank.value })
  }

  async function handleEndHere() {
    const bufferedIds = discardBuffer()
    if (bufferedIds.length > 0) await trimStreamMessages(worldId.value, bufferedIds)
    await stop()
    eventStarted.value = false
  }

  async function handleRewindSelect(cardMessageId: string) {
    await stop(true)
    eventStarted.value = false
    try {
      const result = await rewindToEvent(worldId.value, cardMessageId)
      const toRemove = new Set(result.deleted_message_ids)
      messages.value = messages.value.filter((m) => !toRemove.has(m.id))
    } catch (e) {
      messageApi.error(parseApiError(e, t))
    }
  }

  async function handleDiscard() {
    await stop(true)
    eventStarted.value = false
    if (!currentEventId.value) return
    try {
      await discardEvent(worldId.value, currentEventId.value, currentSessionMessageIds.value)
      const idsToRemove = new Set([...currentSessionMessageIds.value, currentEventId.value])
      messages.value = messages.value.filter((m) => !idsToRemove.has(m.id))
      currentEventTitle.value = null
    } catch (e) {
      messageApi.error(parseApiError(e, t))
    }
  }

  function handleResume(sessionId: string, sessionMessages: Message[], rawParticipants: Array<string | Participant> | null | undefined, participantMode: 'auto' | 'edit' | 'include' | null | undefined, hasParticipants: boolean, sessionElementInjectionIds?: string[] | null, sessionConstraints?: string) {
    invalidateStreaming()
    sending.value = false
    isFakeStreaming.value = false
    if (isStreaming.value) {
      stop(true).catch(() => {})
    }
    messages.value = [...sessionMessages]
    hasMore.value = false
    currentSessionId.value = sessionId
    clearAllQueue()
    resetEventState()
    restoreSession(rawParticipants, participantMode, hasParticipants)
    elementInjectionIds.value = sessionElementInjectionIds ?? []
    constraintText.value = sessionConstraints ?? ''
    actionDescriptions.value = false
    nextTick(scrollToBottom)
  }

  function startNewSession() {
    invalidateStreaming()
    sending.value = false
    isFakeStreaming.value = false
    if (isStreaming.value) {
      stop(true).catch(() => {})
    }
    messages.value = []
    hasMore.value = false
    currentSessionId.value = null
    resetAllState()
    clearAllQueue()
  }

  function init() {
    restoreQueue()
  }

  function beforeUnmount() {
    if (memoriesEnabled.value && worldId.value && currentSessionId.value) {
      flushChatMemories(worldId.value, currentSessionId.value)
    }
  }

  return {
    // Reactive state
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
    canUseRerank,

    // Actions
    handleSend,
    handleEventInject,
    handleInputInterrupt,
    handleGoOn,
    handleEnrich,
    handleEnrichSubmit,
    handleEndHere,
    handleRewindSelect,
    handleDiscard,
    handleResume,
    startNewSession,
    loadMore,
    toggleElementRerank,
    removeQueueItem,

    // Lifecycle
    init,
    beforeUnmount,
  }
}
