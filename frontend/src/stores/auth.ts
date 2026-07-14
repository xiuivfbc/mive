import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useLocale } from '@/composables/useLocale'

interface AuthUser {
  id: string
  username: string
  avatarUrl?: string | null
  isAdmin?: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)

  async function initialize() {
    const { apiClient } = await import('@/api/client')
    const response = await apiClient.get('/auth/me')
    const data = response.data
    user.value = {
      id: data.id,
      username: data.username,
      avatarUrl: data.avatar_url,
      isAdmin: data.is_admin ?? false,
    }
    if (data.preferred_language) {
      const { setLocale, supportedLocales } = useLocale()
      const validLocale = supportedLocales.find(l => l.id === data.preferred_language)
      if (validLocale) setLocale(validLocale.id, { skipSync: true })
    }
  }

  return { user, initialize }
})
