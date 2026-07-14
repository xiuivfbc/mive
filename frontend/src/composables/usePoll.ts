import { onUnmounted } from 'vue'

/**
 * 通用轮询 composable。
 * fn 返回 true 时停止轮询；超时时调用 onTimeout 后停止。
 * 使用递归 setTimeout 替代 setInterval，避免异步回调下的竞态问题。
 */
export function usePoll() {
  let timer: ReturnType<typeof setTimeout> | null = null
  let elapsed = 0

  function stop() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    elapsed = 0
  }

  onUnmounted(stop)

  function start(
    fn: () => Promise<boolean>,
    intervalMs: number,
    timeoutMs: number,
    onTimeout?: () => void,
  ) {
    stop()

    async function tick() {
      elapsed += intervalMs
      if (elapsed >= timeoutMs) {
        timer = null
        onTimeout?.()
        return
      }
      try {
        const done = await fn()
        if (done) {
          timer = null
          return
        }
      } catch {
        // 轮询期间的瞬态网络错误忽略
      }
      timer = setTimeout(tick, intervalMs)
    }

    timer = setTimeout(tick, intervalMs)
  }

  return { start, stop }
}
