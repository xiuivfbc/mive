import { ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import { parseApiError } from '@/utils/apiError'

/**
 * Wraps an async function with consistent error handling.
 * On failure, shows a toast via naive-ui's useMessage and logs the error.
 *
 * Usage:
 *   const { data, error, loading, exec } = useApiCall()
 *   await exec(() => fetchSomething(id))
 */
export function useApiCall<T = unknown>() {
  const data: Ref<T | null> = ref(null) as Ref<T | null>
  const error: Ref<string | null> = ref(null)
  const loading = ref(false)

  let _t: ((key: string) => string) | null = null
  let _message: ReturnType<typeof useMessage> | null = null

  function ensureContext() {
    if (!_t) {
      try {
        const { t } = useI18n()
        _t = t
      } catch {
        // Outside setup — fall back to identity
        _t = (key: string) => key
      }
    }
    if (!_message) {
      try {
        _message = useMessage()
      } catch {
        // Outside setup — no toast
      }
    }
  }

  async function exec<R = T>(fn: () => Promise<R>): Promise<R | null> {
    ensureContext()
    loading.value = true
    error.value = null
    data.value = null
    try {
      const result = await fn()
      data.value = result as unknown as T
      return result
    } catch (e) {
      const msg = parseApiError(e, _t!)
      error.value = msg
      _message?.error(msg)
      return null
    } finally {
      loading.value = false
    }
  }

  return { data, error, loading, exec }
}
