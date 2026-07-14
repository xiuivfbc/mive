/**
 * Tab notification composable:
 * - Plays a short chime sound on every notification (regardless of tab visibility)
 * - Flashes the document title with descriptive labels when the tab is hidden
 * - Stops flashing when the user returns to the tab
 */
import { ref } from 'vue'

let audioCtx: AudioContext | null = null
let flashTimer: ReturnType<typeof setInterval> | null = null
let baseTitle = document.title

interface NotificationSource {
  key: string
  label: string // e.g. '💬 新消息' or '✅ 角色生成成功'
}

// Active notification sources
const sources = ref<NotificationSource[]>([])
// Pending notifyOnce timers (key → timerId), cleared on tab return
const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>()

function getAudioCtx(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext()
  return audioCtx
}

/** Play a short pleasant chime (two-tone sine wave). */
function playChime() {
  try {
    const ctx = getAudioCtx()
    if (ctx.state === 'suspended') ctx.resume()

    const now = ctx.currentTime
    // First tone
    const osc1 = ctx.createOscillator()
    const gain1 = ctx.createGain()
    osc1.type = 'sine'
    osc1.frequency.setValueAtTime(880, now) // A5
    gain1.gain.setValueAtTime(0.15, now)
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.2)
    osc1.connect(gain1).connect(ctx.destination)
    osc1.start(now)
    osc1.stop(now + 0.2)

    // Second tone (higher)
    const osc2 = ctx.createOscillator()
    const gain2 = ctx.createGain()
    osc2.type = 'sine'
    osc2.frequency.setValueAtTime(1320, now + 0.12) // E6
    gain2.gain.setValueAtTime(0.12, now + 0.12)
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.35)
    osc2.connect(gain2).connect(ctx.destination)
    osc2.start(now + 0.12)
    osc2.stop(now + 0.35)
  } catch {
    // Audio API unavailable — silently ignore
  }
}

function startFlash() {
  if (flashTimer) return
  let idx = 0
  flashTimer = setInterval(() => {
    const list = sources.value
    if (list.length === 0) {
      stopFlash()
      return
    }
    if (idx % 2 === 0) {
      // Show the notification label (cycle through if multiple)
      const source = list[(idx / 2) % list.length]
      document.title = `${source.label} - ${baseTitle}`
    } else {
      document.title = baseTitle
    }
    idx++
  }, 1000)
}

function stopFlash() {
  if (flashTimer) {
    clearInterval(flashTimer)
    flashTimer = null
  }
  document.title = baseTitle
}

function onVisibilityChange() {
  if (!document.hidden) {
    // User returned — clear everything, cancel pending timers, restore normal title
    sources.value = []
    pendingTimers.forEach(t => clearTimeout(t))
    pendingTimers.clear()
    stopFlash()
  }
}

// Register global listener once
let listenerRegistered = false
function ensureListener() {
  if (listenerRegistered) return
  listenerRegistered = true
  document.addEventListener('visibilitychange', onVisibilityChange)
}

/**
 * Set the base title (call from router on navigation).
 */
export function setBaseTitle(title: string) {
  baseTitle = title
  if (!flashTimer) {
    if (sources.value.length > 0) {
      document.title = `${sources.value[0].label} - ${baseTitle}`
    } else {
      document.title = baseTitle
    }
  }
}

export function useTabNotification() {
  ensureListener()

  /**
   * Notify with a count badge (e.g. DM unread messages).
   * Flash continues until user returns to the tab OR count is set to 0.
   * @param key - unique source key (e.g. 'dm')
   * @param label - display text (e.g. '💬 新消息')
   * @param count - 0 to clear this source
   */
  function notify(key: string, label: string, count: number) {
    // Remove previous entry for this key
    sources.value = sources.value.filter(s => s.key !== key)

    if (count > 0) {
      sources.value.push({ key, label })
      playChime()
      if (document.hidden) startFlash()
    } else {
      if (sources.value.length === 0) stopFlash()
    }
  }

  /**
   * Notify once with a descriptive label (e.g. character generation done).
   * Sound plays once. Flash continues until user returns to the tab.
   * If tab is visible, shows briefly for 5 seconds then clears.
   * @param key - unique source key (e.g. 'generation')
   * @param label - display text (e.g. '✅ 角色生成成功')
   */
  function notifyOnce(key: string, label: string) {
    // Clear any pending timer for this key
    const existing = pendingTimers.get(key)
    if (existing) clearTimeout(existing)
    pendingTimers.delete(key)

    // Remove previous entry for this key
    sources.value = sources.value.filter(s => s.key !== key)
    sources.value.push({ key, label })

    playChime()
    if (document.hidden) {
      startFlash()
    } else {
      // Tab is visible — show briefly then clear
      document.title = `${label} - ${baseTitle}`
      const timer = setTimeout(() => {
        pendingTimers.delete(key)
        sources.value = sources.value.filter(s => s.key !== key)
        if (sources.value.length === 0) document.title = baseTitle
      }, 5000)
      pendingTimers.set(key, timer)
    }
  }

  return { notify, notifyOnce }
}
