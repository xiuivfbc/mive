import { ref, computed, type Ref } from 'vue'
import { addElement, updateElement, deleteElement } from '@/api/worlds'
import { ELEMENT_CATEGORIES, normalizeCategory } from '@/types/world'
import type { WorldDoc, Element } from '@/types/world'

const isCharacterElement = (category: string) =>
  category === 'characters' || category.includes('人物') || category.includes('角色')

export function useElementCrud(worldId: string, world: Ref<WorldDoc | null>) {
  const selectedCategory = ref<string | null>(null)
  const showElementModal = ref(false)
  const editingElement = ref<Element | null>(null)

  const elementCategories = [...ELEMENT_CATEGORIES]

  const filteredElements = computed(() => {
    if (!world.value) return []
    const nonCharElements = world.value.elements.filter((e) => !isCharacterElement(e.category))
    if (selectedCategory.value) {
      return nonCharElements.filter((e) => normalizeCategory(e.category) === selectedCategory.value)
    }
    return nonCharElements
  })

  function openAddElement() {
    editingElement.value = null
    showElementModal.value = true
  }

  function openEditElement(el: Element) {
    editingElement.value = el
    showElementModal.value = true
  }

  async function handleElementSave(data: { name: string; category: string; brief: string; detail: string }) {
    if (!world.value) return
    if (editingElement.value) {
      const updated = await updateElement(worldId, editingElement.value.id, data)
      const idx = world.value.elements.findIndex((e) => e.id === editingElement.value!.id)
      if (idx !== -1) world.value.elements[idx] = updated
    } else {
      const created = await addElement(worldId, data)
      world.value.elements.push(created)
    }
    showElementModal.value = false
  }

  async function handleDeleteElement(el: Element) {
    if (!world.value) return
    await deleteElement(worldId, el.id)
    world.value.elements = world.value.elements.filter((e) => e.id !== el.id)
  }

  return {
    selectedCategory,
    showElementModal,
    editingElement,
    elementCategories,
    filteredElements,
    openAddElement,
    openEditElement,
    handleElementSave,
    handleDeleteElement,
  }
}
