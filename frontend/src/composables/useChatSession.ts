import { ref, type Ref } from 'vue'
import type { Participant } from '@/types/chatSession'

export interface UseChatSessionOptions {
  /** Restore participant state from a persisted session */
  restoreSessionParticipants: (
    rawParticipants: Array<string | Participant> | null | undefined,
    mode: 'auto' | 'edit' | 'include' | null | undefined,
  ) => void
  /** Reset participant state to defaults */
  resetParticipants: () => void
  /** Session-scoped flags that need resetting */
  sessionStarted: Ref<boolean>
  eventStarted: Ref<boolean>
  eventMode: Ref<boolean>
  enrichMode: Ref<boolean>
  lastRawInput: Ref<string>
  showInterruptMenu: Ref<boolean>
  showRewindPicker: Ref<boolean>
  currentEventTitle: Ref<string | null>
  actionDescriptions: Ref<boolean>
}

export function useChatSession(options: UseChatSessionOptions) {
  const {
    restoreSessionParticipants,
    resetParticipants,
    sessionStarted,
    eventStarted,
    eventMode,
    enrichMode,
    lastRawInput,
    showInterruptMenu,
    showRewindPicker,
    currentEventTitle,
    actionDescriptions,
  } = options

  /** Reset all event-related UI state (eventMode 保留，由用户手动切换) */
  function resetEventState() {
    eventStarted.value = false
    enrichMode.value = false
    lastRawInput.value = ''
    showInterruptMenu.value = false
    showRewindPicker.value = false
    currentEventTitle.value = null
  }

  /** Reset all session + event + participant state (shared by startNewSession and handleResume) */
  function resetAllState() {
    sessionStarted.value = false
    resetParticipants()
    resetEventState()
    actionDescriptions.value = false
  }

  /** Restore participant state from a persisted ChatSession */
  function restoreSession(rawParticipants: Array<string | Participant> | null | undefined, mode: 'auto' | 'edit' | 'include' | null | undefined, hasParticipants: boolean) {
    restoreSessionParticipants(rawParticipants, mode)
    sessionStarted.value = hasParticipants
  }

  return {
    resetEventState,
    resetAllState,
    restoreSession,
  }
}
