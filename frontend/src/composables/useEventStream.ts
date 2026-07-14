import { ref } from 'vue'
import type { Ref } from 'vue'
import { pauseStream, resumeStream, stopStream } from '@/api/events'
import { readingDelay } from '@/composables/useFakeStreaming'
import type { Message, SseEventInjectedPayload, SseNarratorTurnPayload, SseSpeakerTurnPayload } from '@/types/message'

export interface EventStreamCallbacks {
  onEventInjected: (payload: SseEventInjectedPayload) => void
  onSpeakerTurn: (msg: Message) => void
  onNarratorTurn: (msg: Message) => void
  onMemoryUpdating: () => void
  onDone: () => void
  onError: (message: string) => void
}

export interface InjectOptions {
  sessionId?: string | null
  memoriesEnabled?: boolean
  actionDescriptions?: boolean
  showNarration?: boolean
  elementRerank?: boolean
  elementInjectionIds?: string[] | null
  constraint?: string | null
}

interface PendingEntry {
  timer: ReturnType<typeof setTimeout>
  content: string
  fn: () => void
  id: string
}

interface BufferedEntry {
  content: string
  fn: () => void
  id: string
}

export function useEventStream(worldId: Ref<string>) {
  const isStreaming = ref(false)
  const currentEventTitle = ref<string | null>(null)
  const currentEventId = ref<string | null>(null)
  const currentCardMessageId = ref<string | null>(null)
  const currentSessionMessageIds = ref<string[]>([])
  const currentParticipants = ref<string[]>([])

  let abortController: AbortController | null = null
  let isPaused = false
  let nextDisplayTime = 0
  const pendingEntries: PendingEntry[] = []
  // 暂停后缓冲区：消息已到达前端但未显示，等待用户决策
  const displayBuffer: BufferedEntry[] = []

  // id 为空字符串表示非消息事件（memory_updating 等）
  function scheduleDisplay(content: string, fn: () => void, id = ''): void {
    if (isPaused) {
      displayBuffer.push({ content, fn, id })
      return
    }
    const now = Date.now()
    const delay = Math.max(0, nextDisplayTime - now)
    nextDisplayTime = Math.max(now, nextDisplayTime) + readingDelay(content)
    const entry: PendingEntry = { timer: null as unknown as ReturnType<typeof setTimeout>, content, fn, id }
    entry.timer = setTimeout(() => {
      const idx = pendingEntries.indexOf(entry)
      if (idx !== -1) pendingEntries.splice(idx, 1)
      fn()
    }, delay)
    pendingEntries.push(entry)
  }

  function clearPendingTimers(): void {
    for (const e of pendingEntries) clearTimeout(e.timer)
    pendingEntries.length = 0
    nextDisplayTime = 0
  }

  async function pause(): Promise<void> {
    isPaused = true
    // 把已排队但未显示的 entry 移入缓冲区
    for (const e of pendingEntries) {
      clearTimeout(e.timer)
      displayBuffer.push({ content: e.content, fn: e.fn, id: e.id })
    }
    pendingEntries.length = 0
    nextDisplayTime = 0
    await pauseStream(worldId.value)
  }

  async function resume(): Promise<void> {
    await resumeStream(worldId.value)
    isPaused = false
    nextDisplayTime = Date.now()
    const toFlush = [...displayBuffer]
    displayBuffer.length = 0
    for (const { content, fn, id } of toFlush) {
      scheduleDisplay(content, fn, id)
    }
  }

  // 丢弃缓冲区，返回其中的消息 ID 列表（供调用方告知后端删除）
  function discardBuffer(): string[] {
    const ids = displayBuffer.map(e => e.id).filter(Boolean)
    displayBuffer.length = 0
    return ids
  }

  // clearDisplay=true：同时清掉待显示队列（Discard / Rewind 使用，避免将被删除的消息闪现）
  async function stop(clearDisplay = false): Promise<void> {
    isPaused = false
    if (clearDisplay) {
      displayBuffer.length = 0
      clearPendingTimers()
    }
    await stopStream(worldId.value)
    abortController?.abort()
  }

  async function inject(
    rawInput: string,
    callbacks: EventStreamCallbacks,
    options: InjectOptions = {}
  ): Promise<void> {
    if (isStreaming.value) return

    abortController = new AbortController()
    isStreaming.value = true
    currentSessionMessageIds.value = []
    currentCardMessageId.value = null
    nextDisplayTime = Date.now()

    let streamError: string | null = null

    // Wrap onError to capture error
    const wrappedCallbacks: EventStreamCallbacks = {
      ...callbacks,
      onError(msg: string) {
        streamError = msg
        callbacks.onError(msg)
      },
    }

    try {
      const response = await fetch(`/api/worlds/${worldId.value}/events/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          raw_input: rawInput,
          session_id: options.sessionId ?? null,
          memories_enabled: options.memoriesEnabled ?? false,
          action_descriptions: options.actionDescriptions ?? false,
          show_narration: options.showNarration ?? false,
          element_rerank: options.elementRerank ?? false,
          element_injection_ids: options.elementInjectionIds ?? null,
          constraint: options.constraint ?? null,
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        const errMsg = `请求失败: ${response.status}`
        callbacks.onError(errMsg)
        throw new Error(errMsg)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''

        for (const rawEvent of events) {
          if (!rawEvent.trim()) continue
          parseSseEvent(rawEvent, wrappedCallbacks)
        }
      }

      // Check if error occurred during streaming
      if (streamError) {
        throw new Error(streamError)
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        // Error already reported via wrappedCallbacks.onError, don't duplicate
        throw err
      }
    } finally {
      isStreaming.value = false
      abortController = null
    }
  }

  function parseSseEvent(raw: string, callbacks: EventStreamCallbacks): void {
    const lines = raw.split('\n')
    let eventType = ''
    let dataStr = ''

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        dataStr = line.slice(6).trim()
      }
    }

    if (!eventType || !dataStr) return

    try {
      const data = JSON.parse(dataStr)
      switch (eventType) {
        case 'event_injected':
          currentEventTitle.value = data.title
          currentEventId.value = data.event_id
          currentParticipants.value = data.participants
          if (data.card_message_id) {
            currentCardMessageId.value = data.card_message_id
            currentSessionMessageIds.value.push(data.card_message_id)
          }
          callbacks.onEventInjected(data as SseEventInjectedPayload)
          break
        case 'speaker_turn': {
          const msg = ssePayloadToMessage(data)
          currentSessionMessageIds.value.push(msg.id)
          if (data.sender_name) currentParticipants.value = [...new Set([...currentParticipants.value, data.sender_name])]
          scheduleDisplay(msg.content, () => callbacks.onSpeakerTurn(msg), msg.id)
          break
        }
        case 'narrator_turn': {
          const msg = narratorPayloadToMessage(data as SseNarratorTurnPayload)
          currentSessionMessageIds.value.push(msg.id)
          scheduleDisplay(msg.content, () => callbacks.onNarratorTurn(msg), msg.id)
          break
        }
        case 'memory_updating':
          // 不经过缓冲区，立即执行（无视觉呈现，仅内部状态）
          callbacks.onMemoryUpdating()
          break
        case 'done':
          // 不经过缓冲区，立即执行（时钟刷新不依赖消息显示顺序）
          callbacks.onDone()
          break
        case 'error':
          callbacks.onError(data.message ?? '未知错误')
          break
      }
    } catch {
      // 忽略 JSON 解析失败的碎片
    }
  }

  function ssePayloadToMessage(payload: SseSpeakerTurnPayload): Message {
    return {
      id: payload.id,
      world_id: worldId.value,
      type: 'dialogue',
      sender_type: 'character',
      sender_id: payload.sender_id,
      sender_name: payload.sender_name,
      content: payload.content,
      real_time: null,
      is_key_message: false,
      user_participated: false,
      created_at: new Date().toISOString(),
      sequence: payload.sequence ?? null,
    }
  }

  function narratorPayloadToMessage(payload: SseNarratorTurnPayload): Message {
    return {
      id: payload.id,
      world_id: worldId.value,
      type: 'narration',
      sender_type: 'narrator',
      sender_id: null,
      sender_name: '旁白',
      content: payload.content,
      real_time: null,
      is_key_message: false,
      user_participated: false,
      created_at: new Date().toISOString(),
      sequence: payload.sequence ?? null,
    }
  }

  return {
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
  }
}
