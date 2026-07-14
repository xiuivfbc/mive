import { ref, computed, type Ref } from 'vue'
import { listCharacters } from '@/api/characters'
import type { Character } from '@/types/character'

export interface UseCharactersOptions {
  /** Reactive world ID */
  worldId: Ref<string>
}

export function useCharacters(options: UseCharactersOptions) {
  const { worldId } = options

  const characters = ref<Character[]>([])

  /** id -> portrait_url (only entries with a truthy portrait_url) */
  const characterPortraitMap = computed<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const c of characters.value) {
      if (c.portrait_url) map[c.id] = c.portrait_url
    }
    return map
  })

  /** id -> name */
  const characterNameMap = computed<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const c of characters.value) {
      map[c.id] = c.name
    }
    return map
  })

  /** Fetch characters from the API */
  async function loadCharacters() {
    characters.value = await listCharacters(worldId.value)
  }

  /** Add a character to the local list */
  function addCharacter(c: Character) {
    characters.value.push(c)
  }

  /** Remove a character by id */
  function removeCharacter(id: string) {
    characters.value = characters.value.filter((c) => c.id !== id)
  }

  /** Replace a character in-place by id */
  function updateCharacter(c: Character) {
    const idx = characters.value.findIndex((x) => x.id === c.id)
    if (idx !== -1) characters.value.splice(idx, 1, c)
  }

  /** Bulk-replace the entire characters array (e.g. from graph data) */
  function setCharacters(chars: Character[]) {
    characters.value = chars
  }

  return {
    characters,
    characterPortraitMap,
    characterNameMap,
    loadCharacters,
    addCharacter,
    removeCharacter,
    updateCharacter,
    setCharacters,
  }
}
