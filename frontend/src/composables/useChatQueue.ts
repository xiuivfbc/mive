import { ref, computed, type Ref } from 'vue'
import type { QueueItem, QueuePersistData, SendMessageResponse } from '@/types/message'
import type { Participant } from '@/types/chatSession'

const MAX_RETRIES = 3
const STORAGE_PREFIX = 'mive_chat_queue'

function generateIdempotencyKey(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function getStorageKey(worldId: string): string {
  return `${STORAGE_PREFIX}:${worldId}`
}

function loadFromStorage(worldId: string): QueuePersistData | null {
  try {
    const raw = localStorage.getItem(getStorageKey(worldId))
    if (!raw) return null
    return JSON.parse(raw) as QueuePersistData
  } catch {
    return null
  }
}

function saveToStorage(worldId: string, data: QueuePersistData): void {
  try {
    localStorage.setItem(getStorageKey(worldId), JSON.stringify(data))
  } catch {
    // localStorage full or unavailable
  }
}

function clearStorage(worldId: string): void {
  try {
    localStorage.removeItem(getStorageKey(worldId))
  } catch {
    // ignore
  }
}

export interface UseChatQueueOptions {
  worldId: Ref<string>
  sessionId: Ref<string | null>
  onProcess: (item: QueueItem) => Promise<SendMessageResponse>
  onSuccess: (item: QueueItem, response: SendMessageResponse) => void | Promise<void>
  onFailure: (item: QueueItem, error: string, errorResponse?: { session_id?: string | null }, errorObj?: unknown) => void
}

export function useChatQueue(options: UseChatQueueOptions) {
  const { worldId, sessionId, onProcess, onSuccess, onFailure } = options

  const queue: Ref<QueueItem[]> = ref([])
  const processingItem: Ref<QueueItem | null> = ref(null)
  const isProcessing = ref(false)

  // Restore queue from localStorage on init
  function restoreQueue() {
    const data = loadFromStorage(worldId.value)
    if (!data) return

    // Only restore if worldId matches
    if (data.worldId !== worldId.value) return

    // Validate stored sessionId: if the caller has already set a different
    // sessionId (e.g. user navigated to a different session), skip restoring
    // the old sessionId to avoid clobbering the active session.
    if (data.sessionId && sessionId.value && data.sessionId !== sessionId.value) {
      // Stored session is stale — discard the persisted queue
      clearStorage(worldId.value)
      return
    }

    // Restore pending items (skip failed — they disappear on refresh per design)
    queue.value = data.pendingQueue
      .filter((item) => item.status !== 'failed')
      .map((item) => ({
        ...item,
        status: 'pending' as const,
      }))

    // If there was a processing item, re-queue it as pending
    // (since we can't know if the server processed it)
    if (data.processingItem) {
      queue.value.unshift({
        ...data.processingItem,
        status: 'pending' as const,
      })
    }

    // Update sessionId if stored one is more recent and current is null
    if (data.sessionId && !sessionId.value) {
      sessionId.value = data.sessionId
    }

    // Clear localStorage if queue is now empty
    if (queue.value.length === 0) {
      clearStorage(worldId.value)
    }
  }

  // Persist queue to localStorage
  function persistQueue() {
    const data: QueuePersistData = {
      worldId: worldId.value,
      sessionId: sessionId.value,
      pendingQueue: queue.value.filter((item) => item.status === 'pending'),
      processingItem: processingItem.value,
    }
    saveToStorage(worldId.value, data)
  }

  // Add a new item to the queue
  function enqueue(
    content: string,
    participantMode: 'auto' | 'edit' | 'include',
    participants: Participant[] | null,
    userRole: string | null,
  ): QueueItem {
    const item: QueueItem = {
      id: `q-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      idempotencyKey: generateIdempotencyKey(),
      content,
      senderType: 'user',
      participantMode,
      participants,
      userRole,
      status: 'pending',
      createdAt: Date.now(),
      retryCount: 0,
    }
    queue.value.push(item)
    persistQueue()
    return item
  }

  // Remove an item from the queue (user action)
  function remove(itemId: string) {
    queue.value = queue.value.filter((item) => item.id !== itemId)
    persistQueue()
  }

  // Process the next pending item in the queue
  async function processNext() {
    if (isProcessing.value) return

    const nextItem = queue.value.find((item) => item.status === 'pending')
    if (!nextItem) {
      clearStorage(worldId.value)
      return
    }

    isProcessing.value = true
    processingItem.value = nextItem
    nextItem.status = 'processing'
    persistQueue()

    try {
      const response = await onProcess(nextItem)

      // Check if the response indicates failure (0 replies + error)
      if (response.error && response.responses.length === 0) {
        // Complete failure - retry or mark as failed
        if (nextItem.retryCount < MAX_RETRIES) {
          nextItem.retryCount++
          nextItem.status = 'pending'
          processingItem.value = null
          isProcessing.value = false
          persistQueue()
          // Process next (will pick up this retried item or another)
          await processNext()
          return
        }

        // Max retries reached
        nextItem.status = 'failed'
        processingItem.value = null
        isProcessing.value = false
        onFailure(nextItem, response.error, { session_id: response.session_id })
        persistQueue()
        // Continue processing next items
        await processNext()
        return
      }

      // Success (partial or full) — await so fake streaming completes before next item
      await onSuccess(nextItem, response)

      // Remove from queue
      queue.value = queue.value.filter((item) => item.id !== nextItem.id)
      processingItem.value = null
      isProcessing.value = false
      persistQueue()

      // Process next item
      await processNext()
    } catch (e) {
      // Network error or other exception - retry or mark as failed
      const errorMsg = (e as Error).message || '发送失败'
      const status = (e as any)?.response?.status

      // 402 (payment required) / 403 (forbidden) — no point retrying
      if (status === 402 || status === 403) {
        nextItem.status = 'failed'
        processingItem.value = null
        isProcessing.value = false
        const errorData = (e as any)?.response?.data
        onFailure(nextItem, errorMsg, { session_id: errorData?.session_id }, e)
        persistQueue()
        await processNext()
        return
      }

      if (nextItem.retryCount < MAX_RETRIES) {
        nextItem.retryCount++
        nextItem.status = 'pending'
        processingItem.value = null
        isProcessing.value = false
        persistQueue()
        await processNext()
        return
      }

      // Max retries reached
      nextItem.status = 'failed'
      processingItem.value = null
      isProcessing.value = false
      const errorData = (e as any)?.response?.data
      onFailure(nextItem, errorMsg, { session_id: errorData?.session_id }, e)
      persistQueue()
      await processNext()
    }
  }

  // Clear failed items (called on page refresh or user action)
  function clearFailed() {
    queue.value = queue.value.filter((item) => item.status !== 'failed')
    persistQueue()
  }

  // Clear all queue items and processing state
  function clearAll() {
    queue.value = []
    processingItem.value = null
    isProcessing.value = false
    clearStorage(worldId.value)
  }

  // Register a directly-sent message as "processing" in the queue bar (display only,
  // not added to the persistent queue array). Used for the first message that bypasses
  // the queue but should still show a spinner in QueueBar.
  function markProcessing(
    content: string,
    participantMode: 'auto' | 'edit' | 'include',
    participants: Participant[] | null,
    userRole: string | null,
  ): QueueItem {
    const item: QueueItem = {
      id: `q-direct-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      idempotencyKey: '',
      content,
      senderType: 'user',
      participantMode,
      participants,
      userRole,
      status: 'processing',
      createdAt: Date.now(),
      retryCount: 0,
    }
    processingItem.value = item
    return item
  }

  // Clear the processing indicator set by markProcessing.
  function clearProcessing() {
    processingItem.value = null
  }

  // Get all items for display (processing + pending + failed) — reactive computed
  const displayItems = computed<QueueItem[]>(() => {
    const items: QueueItem[] = []
    if (processingItem.value) items.push(processingItem.value)
    items.push(...queue.value.filter((item) => item.status === 'pending'))
    items.push(...queue.value.filter((item) => item.status === 'failed'))
    return items
  })

  return {
    queue,
    processingItem,
    isProcessing,
    restoreQueue,
    enqueue,
    remove,
    processNext,
    clearFailed,
    clearAll,
    displayItems,
    markProcessing,
    clearProcessing,
  }
}
