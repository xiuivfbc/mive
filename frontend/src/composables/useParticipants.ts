import { ref, computed, watch, type Ref } from 'vue'
import type { Character } from '@/types/character'
import type { Participant } from '@/types/chatSession'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from 'vue-i18n'

export interface UseParticipantsOptions {
  /** Reactive characters list */
  characters: Ref<Character[]>
  /** Reactive world user character id (world.value?.user_character_id) */
  worldUserCharacterId: Ref<string | null>
}

export function useParticipants(options: UseParticipantsOptions) {
  const { characters, worldUserCharacterId } = options

  const authStore = useAuthStore()
  const { t } = useI18n()

  /** Active participants: null = new session, array = active session */
  const chatParticipants = ref<Participant[] | null>(null)
  /** Participant selection mode */
  const chatParticipantMode = ref<'auto' | 'edit'>('auto')
  /** User identity: null = explorer, string = character_id */
  const chatUserRole = ref<string | null>(null)
  /** Track previously used role characters in this session */
  const previousUserRoles = ref<Set<string>>(new Set())

  // When user switches role, add the old role to participants so it stays in the list
  watch(chatUserRole, (newRole, oldRole) => {
    if (oldRole && oldRole !== newRole) {
      previousUserRoles.value.add(oldRole)
      if (chatParticipants.value) {
        const alreadyInList = chatParticipants.value.some((p) => p.id === oldRole)
        if (!alreadyInList) {
          const char = characters.value.find((c) => c.id === oldRole)
          if (char) {
            chatParticipants.value = [...chatParticipants.value, { id: char.id, name: char.name }]
          }
        }
      }
    }
  })

  /** The character the user is currently role-playing (or null) */
  const userRoleCharacter = computed(() =>
    characters.value.find((c) => c.id === chatUserRole.value) ?? null,
  )

  /** Display name for the user bubble */
  const userDisplayName = computed(() =>
    userRoleCharacter.value ? userRoleCharacter.value.name : t('chat.defaultRole'),
  )

  /** Avatar URL or emoji for the user bubble */
  const userAvatarUrl = computed(() => {
    if (!chatUserRole.value) return '\u{1F9ED}' // explorer compass emoji
    if (chatUserRole.value === worldUserCharacterId.value) return authStore.user?.avatarUrl ?? null
    return userRoleCharacter.value?.portrait_url ?? null
  })

  /** id -> {name, portrait_url} for per-message user role identity resolution */
  const userCharacterMap = computed<Record<string, { name: string; portrait_url: string | null }>>(
    () => {
      const map: Record<string, { name: string; portrait_url: string | null }> = {}
      for (const c of characters.value) {
        const isWorldUser = c.id === worldUserCharacterId.value
        map[c.id] = {
          name: c.name,
          portrait_url: isWorldUser
            ? (authStore.user?.avatarUrl ?? null)
            : (c.portrait_url ?? null),
        }
      }
      return map
    },
  )

  /** Update participants from server response */
  function applyServerParticipants(
    serverParticipants: Participant[],
    serverMode: 'auto' | 'edit' | 'include',
  ) {
    if (serverParticipants.length > 0) {
      chatParticipants.value = serverParticipants
      // 'include' is transient send-mode, normalize to 'auto' for idle state
      chatParticipantMode.value = serverMode === 'edit' ? 'edit' : 'auto'
    }
  }

  /**
   * Restore participants from a persisted session.
   * DB stores bare UUID strings (or legacy {id,name} objects), normalize to {id, name}.
   */
  function restoreSessionParticipants(
    rawParticipants: Array<string | Participant> | null | undefined,
    mode: 'auto' | 'edit' | 'include' | null | undefined,
  ) {
    chatParticipants.value =
      rawParticipants && rawParticipants.length > 0
        ? rawParticipants.map((p) =>
            typeof p === 'string'
              ? { id: p, name: characters.value.find((c) => c.id === p)?.name ?? '' }
              : {
                  id: p.id,
                  name: p.name || characters.value.find((c) => c.id === p.id)?.name || '',
                },
          )
        : null
    chatParticipantMode.value = mode === 'edit' ? 'edit' : 'auto'
    chatUserRole.value = null
    previousUserRoles.value = new Set()
  }

  /** Reset all participant state (for new session) */
  function resetParticipants() {
    chatParticipants.value = null
    chatParticipantMode.value = 'auto'
    chatUserRole.value = null
    previousUserRoles.value = new Set()
  }

  return {
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
  }
}
