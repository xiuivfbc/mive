import { onUnmounted } from 'vue'

/**
 * 监听鼠标移动，将位置写入 CSS 变量 --mx / --my（px 单位），
 * 使用 requestAnimationFrame 节流。
 */
export function useMouseGlow() {
  let rafId: number | null = null
  let latestX = 0
  let latestY = 0

  function onMouseMove(e: MouseEvent) {
    latestX = e.clientX
    latestY = e.clientY
    if (rafId !== null) return
    rafId = requestAnimationFrame(() => {
      document.documentElement.style.setProperty('--mx', latestX + 'px')
      document.documentElement.style.setProperty('--my', latestY + 'px')
      rafId = null
    })
  }

  function cleanup() {
    document.removeEventListener('mousemove', onMouseMove)
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  document.addEventListener('mousemove', onMouseMove)
  onUnmounted(cleanup)

  return { cleanup }
}
