import { ref, computed, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  fetchCharacterMemories,
  createCharacterMemory,
  updateCharacterMemory,
  deleteCharacterMemory,
  type CharacterMemory,
  type CreateMemoryRequest,
  type UpdateMemoryRequest,
} from '@/api/memories'
import { listEventIndex } from '@/api/events'
import type { Character } from '@/types/character'

export function useCharacterMemories(
  worldId: string,
  characterId: Ref<string | null>,
  messageApi: { success: (msg: string) => void; error: (msg: string) => void },
  allCharacters?: Ref<{ id: string; name: string; tier?: string | null }[]>,
) {
  const { t } = useI18n()

  const shortTermMemories = ref<CharacterMemory[]>([])
  const longTermMemories = ref<CharacterMemory[]>([])
  const memoriesLoading = ref(false)
  const eventNameOptions = ref<{ label: string; value: string }[]>([])

  // New memory form
  const creatingMemory = ref(false)
  const createForm = ref<CreateMemoryRequest>({
    memory_type: 'short_term',
    content: '',
    memory_category: null,
    short_term_reflection: null,
    perspective_detail: null,
    reflection: null,
    event_name: null,
    involved_characters: null,
  })

  // Edit memory form
  const editingMemoryId = ref<string | null>(null)
  const editForm = ref<UpdateMemoryRequest>({})
  const editSaving = ref(false)
  const createSaving = ref(false)

  const categoryOptions = computed(() => [
    { label: t('character.memoryCategoryTrivial'), value: 'trivial' },
    { label: t('character.memoryCategoryPrivate'), value: 'private' },
    { label: t('character.memoryCategoryMajor'), value: 'major' },
  ])

  const characterOptions = computed(() => {
    if (!allCharacters?.value) return []
    return allCharacters.value.map(c => ({ label: c.name, value: c.id, tier: c.tier ?? undefined }))
  })

  // Reset state when character changes
  watch(characterId, () => {
    shortTermMemories.value = []
    longTermMemories.value = []
    resetCreateForm()
    editingMemoryId.value = null
  })

  async function loadMemories() {
    const cId = characterId.value
    if (!cId) return
    memoriesLoading.value = true
    try {
      const resp = await fetchCharacterMemories(worldId, cId)
      shortTermMemories.value = resp.short_term
      longTermMemories.value = resp.long_term
    } catch (e) {
      console.error('[useCharacterMemories] loadMemories failed:', e)
      messageApi.error(t('character.memoryLoadFailed'))
    } finally {
      memoriesLoading.value = false
    }
  }

  async function loadEventNames() {
    try {
      const events = await listEventIndex(worldId)
      eventNameOptions.value = events
        .filter((e) => e.event_name)
        .map((e) => ({ label: e.event_name, value: e.event_name }))
    } catch (e) {
      console.error('[useCharacterMemories] loadEventNames failed:', e)
    }
  }

  function resetCreateForm() {
    creatingMemory.value = false
    createForm.value = {
      memory_type: 'short_term',
      content: '',
      memory_category: null,
      short_term_reflection: null,
      perspective_detail: null,
      reflection: null,
      event_name: null,
      involved_characters: null,
    }
  }

  function startCreate(memoryType: 'short_term' | 'long_term') {
    creatingMemory.value = true
    editingMemoryId.value = null
    createForm.value = {
      memory_type: memoryType,
      content: '',
      memory_category: null,
      short_term_reflection: null,
      perspective_detail: null,
      reflection: null,
      event_name: null,
      involved_characters: null,
    }
  }

  async function saveNewMemory() {
    const cId = characterId.value
    if (!cId) return
    const isShort = createForm.value.memory_type === 'short_term'
    if (isShort && !createForm.value.content.trim()) return
    if (!isShort && !createForm.value.event_name?.trim()) return
    if (!isShort && !createForm.value.perspective_detail?.trim()) return
    createSaving.value = true
    try {
      const data: CreateMemoryRequest = {
        memory_type: createForm.value.memory_type,
        content: isShort ? createForm.value.content.trim() : '',
      }
      if (createForm.value.memory_category) data.memory_category = createForm.value.memory_category
      if (createForm.value.short_term_reflection) data.short_term_reflection = createForm.value.short_term_reflection
      if (createForm.value.perspective_detail) data.perspective_detail = createForm.value.perspective_detail
      if (createForm.value.reflection) data.reflection = createForm.value.reflection
      if (createForm.value.event_name) data.event_name = createForm.value.event_name
      if (createForm.value.involved_characters?.length) data.involved_characters = createForm.value.involved_characters

      const created = await createCharacterMemory(worldId, cId, data)
      if (data.memory_type === 'short_term') {
        shortTermMemories.value.unshift(created)
      } else {
        longTermMemories.value.unshift(created)
      }
      creatingMemory.value = false
      messageApi.success(t('character.memorySaved'))
    } catch {
      messageApi.error(t('character.memorySaveFailed'))
    } finally {
      createSaving.value = false
    }
  }

  function startEditMemory(mem: CharacterMemory) {
    creatingMemory.value = false
    editingMemoryId.value = mem.id
    editForm.value = {
      content: mem.content,
      memory_category: mem.memory_category ?? null,
      short_term_reflection: mem.short_term_reflection ?? null,
      perspective_detail: mem.perspective_detail ?? null,
      reflection: mem.reflection ?? null,
      event_name: mem.event_name ?? null,
      involved_characters: mem.involved_characters ?? null,
    }
  }

  function cancelEditMemory() {
    editingMemoryId.value = null
    editForm.value = {}
  }

  async function saveEditMemory(mem: CharacterMemory) {
    const cId = characterId.value
    if (!cId) return
    editSaving.value = true
    try {
      const isShort = mem.memory_type === 'short_term'
      const data: UpdateMemoryRequest = {}
      if (isShort && editForm.value.content !== mem.content) data.content = editForm.value.content
      if (isShort && editForm.value.memory_category !== mem.memory_category) data.memory_category = editForm.value.memory_category
      if (isShort && editForm.value.short_term_reflection !== mem.short_term_reflection) data.short_term_reflection = editForm.value.short_term_reflection
      if (!isShort && editForm.value.perspective_detail !== mem.perspective_detail) data.perspective_detail = editForm.value.perspective_detail
      if (!isShort && editForm.value.reflection !== mem.reflection) data.reflection = editForm.value.reflection
      if (!isShort && editForm.value.event_name !== mem.event_name) data.event_name = editForm.value.event_name
      if (!isShort && JSON.stringify(editForm.value.involved_characters ?? null) !== JSON.stringify(mem.involved_characters ?? null)) {
        data.involved_characters = editForm.value.involved_characters ?? []
      }

      const updated = await updateCharacterMemory(worldId, cId, mem.id, data)
      let idx = shortTermMemories.value.findIndex((m) => m.id === mem.id)
      if (idx !== -1) {
        shortTermMemories.value[idx] = updated
      } else {
        idx = longTermMemories.value.findIndex((m) => m.id === mem.id)
        if (idx !== -1) longTermMemories.value[idx] = updated
      }
      editingMemoryId.value = null
      editForm.value = {}
      messageApi.success(t('character.memorySaved'))
    } catch {
      messageApi.error(t('character.memorySaveFailed'))
    } finally {
      editSaving.value = false
    }
  }

  async function onDeleteMemory(memoryId: string) {
    const cId = characterId.value
    if (!cId) return
    try {
      await deleteCharacterMemory(worldId, cId, memoryId)
      shortTermMemories.value = shortTermMemories.value.filter((m) => m.id !== memoryId)
      longTermMemories.value = longTermMemories.value.filter((m) => m.id !== memoryId)
      if (editingMemoryId.value === memoryId) {
        editingMemoryId.value = null
        editForm.value = {}
      }
      messageApi.success(t('character.memoryDeleted'))
    } catch {
      messageApi.error(t('character.memoryDeleteFailed'))
    }
  }

  return {
    shortTermMemories,
    longTermMemories,
    memoriesLoading,
    eventNameOptions,
    creatingMemory,
    createForm,
    editingMemoryId,
    editForm,
    editSaving,
    createSaving,
    categoryOptions,
    characterOptions,
    loadMemories,
    loadEventNames,
    resetCreateForm,
    startCreate,
    saveNewMemory,
    startEditMemory,
    cancelEditMemory,
    saveEditMemory,
    onDeleteMemory,
  }
}
