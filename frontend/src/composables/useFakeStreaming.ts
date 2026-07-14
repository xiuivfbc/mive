import { ref, nextTick, type Ref } from 'vue'

// Chinese reading speed ~5 chars/sec; clamp between 1200ms and 7000ms
export function readingDelay(content: string): number {
  return Math.max(1200, Math.min(7000, (content.length / 5) * 1000))
}

export function useFakeStreaming(isFakeStreaming: Ref<boolean>) {
  const sendCounter = ref(0)

  /** Active flush function — calling it aborts streaming and immediately appends remaining items */
  let flushFn: (() => void) | null = null

  /**
   * Run fake-streaming for a batch of messages.
   * Messages appear one-by-one with reading-delay pauses.
   *
   * @param items       Array of { content, msg } pairs to stream
   * @param append      Function to append a message to the list
   * @param scrollToBottom  Scroll callback after each chunk
   * @param onFirstDelay    Delay before the first item (default 400ms)
   */
  async function streamMessages<T extends { content: string }>(
    items: T[],
    append: (msg: T) => void,
    scrollToBottom: () => void,
    onFirstDelay = 400,
  ): Promise<void> {
    const currentSend = sendCounter.value
    let remainingItems = [...items]
    let aborted = false

    isFakeStreaming.value = true

    flushFn = () => {
      aborted = true
      isFakeStreaming.value = false
      for (const item of remainingItems) append(item)
      flushFn = null
      nextTick(() => scrollToBottom())
    }

    for (let i = 0; i < items.length; i++) {
      if (aborted || sendCounter.value !== currentSend) break
      const delay = i === 0 ? onFirstDelay : readingDelay(items[i - 1].content)
      await new Promise<void>((resolve) => setTimeout(resolve, delay))
      if (aborted || sendCounter.value !== currentSend) break
      append(items[i])
      remainingItems = items.slice(i + 1)
      await nextTick()
      scrollToBottom()
    }

    if (!aborted && sendCounter.value === currentSend) {
      flushFn = null
      isFakeStreaming.value = false
    }
  }

  /**
   * Abort any active fake-streaming and immediately flush remaining items.
   * If no streaming is active, just resets the isFakeStreaming flag.
   */
  function cancelStreaming() {
    if (flushFn) {
      flushFn()
    } else {
      isFakeStreaming.value = false
    }
  }

  /**
   * Bump the send counter to invalidate any in-flight streaming loop.
   * Does NOT flush remaining items — they are silently dropped.
   * Used when resuming/starting sessions where we don't care about orphaned items.
   */
  function invalidateStreaming() {
    sendCounter.value++
    isFakeStreaming.value = false
    flushFn = null
  }

  /**
   * Flush any pending fake-streaming closure (used before starting a new send
   * to ensure previously un-displayed messages are not lost).
   */
  function flushPending() {
    if (flushFn) flushFn()
  }

  return {
    sendCounter,
    streamMessages,
    cancelStreaming,
    invalidateStreaming,
    flushPending,
    readingDelay,
  }
}
