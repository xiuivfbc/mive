import { ref, type Ref } from 'vue'

interface PaginationOptions<T> {
  fetchFn: (params: { before_sequence?: number; limit: number }) => Promise<{
    items: T[]
    has_more: boolean
  }>
  limit?: number
  getSequenceFn: (item: T) => number | null | undefined
}

export function useCursorPagination<T>(options: PaginationOptions<T>) {
  const items: Ref<T[]> = ref([]) as Ref<T[]>
  const hasMore = ref(true)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadInitial() {
    loading.value = true
    error.value = null
    try {
      const result = await options.fetchFn({ limit: options.limit ?? 50 })
      items.value = result.items
      hasMore.value = result.has_more
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function loadMore() {
    if (!hasMore.value || loading.value) return
    loading.value = true
    try {
      // items 按升序排列（最旧在前），向上翻页需要取最旧条目的 sequence 作为游标
      const oldest = items.value[0]
      const beforeSequence = oldest ? options.getSequenceFn(oldest) ?? undefined : undefined
      const result = await options.fetchFn({
        before_sequence: beforeSequence,
        limit: options.limit ?? 50,
      })
      // 旧消息插到头部，保持升序
      items.value.unshift(...result.items)
      hasMore.value = result.has_more
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  function prepend(item: T) {
    items.value.unshift(item)
  }

  function append(item: T) {
    items.value.push(item)
  }

  return { items, hasMore, loading, error, loadInitial, loadMore, prepend, append }
}
