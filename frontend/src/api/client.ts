import axios, { type InternalAxiosRequestConfig } from 'axios'

// ---------------------------------------------------------------------------
// Conditional caching (Last-Modified / If-Modified-Since / 304)
// ---------------------------------------------------------------------------

const lastModifiedMap = new Map<string, string>()
const CACHE_PREFIX = 'cache:'

/** Derive a stable cache key from request URL + baseURL (pathname + search). */
function cacheKey(url: string, baseURL?: string): string {
  try {
    const u = new URL(url, baseURL ?? window.location.origin)
    return u.pathname + u.search
  } catch {
    return url
  }
}

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------

const client = axios.create({
  baseURL: '/api',
  timeout: 0,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
  validateStatus: (s) => (s >= 200 && s < 300) || s === 304,
})

client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // Attach If-Modified-Since for GET requests
  if (config.method === 'get') {
    const key = cacheKey(config.url ?? '', config.baseURL)
    const ims = lastModifiedMap.get(key)
    if (ims) config.headers['If-Modified-Since'] = ims
  }
  return config
})

client.interceptors.response.use(
  (response) => {
    const key = cacheKey(response.config.url ?? '', response.config.baseURL)

    // 304 → restore data from localStorage cache
    if (response.status === 304) {
      const cached = localStorage.getItem(CACHE_PREFIX + key)
      if (cached) {
        response.data = JSON.parse(cached)
        response.status = 200
        return response
      }
      // Cache missing (localStorage cleared) → drop stale key, retry without If-Modified-Since
      lastModifiedMap.delete(key)
      if ((response.config as any)._cacheRetry) {
        // Already retried — avoid infinite loop (e.g. proxy returning 304 without IMS)
        return response
      }
      const config = { ...response.config, _cacheRetry: true }
      delete config.headers['If-Modified-Since']
      return client(config)
    }

    // 200 → store Last-Modified + response data for future 304s
    if (response.config.method === 'get') {
      const lm = response.headers['last-modified']
      if (lm) lastModifiedMap.set(key, lm)
      try {
        localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(response.data))
      } catch {
        // QuotaExceededError — silently ignore
      }
    }
    return response
  },
  async (error) => {
    const status = error.response?.status
    const data = error.response?.data
    console.error('[API Error]', status, data)
    const detail = data?.detail
    if (detail) {
      error.message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    }
    return Promise.reject(error)
  }
)

export { client as apiClient }
export default client
