import { createRouter, createWebHistory } from 'vue-router'
import { setBaseTitle } from '@/composables/useTabNotification'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: () => '/welcome',
    },
    {
      path: '/welcome',
      name: 'Welcome',
      component: () => import('@/views/WelcomePage.vue'),
      meta: { title: 'MIVE' },
    },
    {
      path: '/worlds',
      name: 'WorldList',
      component: () => import('@/views/WorldListPage.vue'),
      meta: { title: '世界列表' },
    },
    {
      path: '/world/:id',
      name: 'WorldDetail',
      component: () => import('@/views/WorldDetailPage.vue'),
      meta: { title: '世界详情' },
      props: true,
    },
    {
      path: '/world/:id/chat',
      name: 'Chat',
      component: () => import('@/views/ChatPage.vue'),
      meta: { title: '聊天' },
      props: true,
    },
    {
      path: '/tos',
      name: 'Tos',
      component: () => import('@/views/TosPage.vue'),
      meta: { title: '服务条款' },
    },
    {
      path: '/admin',
      name: 'Admin',
      component: () => import('@/views/AdminPage.vue'),
      meta: { title: '管理后台' },
    },
  ],
})

let _initialized = false
let _initPromise: Promise<void> | null = null

function ensureInitialized(): Promise<void> {
  if (_initialized) return Promise.resolve()
  if (_initPromise) return _initPromise
  _initPromise = (async () => {
    const { useAuthStore } = await import('@/stores/auth')
    const store = useAuthStore()
    try {
      await store.initialize()
      _initialized = true
    } catch {
      // Backend not reachable yet — let navigation proceed and retry on the next route.
      _initPromise = null
    }
  })()
  return _initPromise
}

router.beforeEach(async (to) => {
  // Update page title
  const title = to.meta.title as string | undefined
  if (title) {
    const fullTitle = `${title} - MIVE`
    setBaseTitle(fullTitle)
  }

  // Open-source single-admin deployment: no login gate. Still initialize the
  // auth store once so the nav bar can display the admin's username/avatar.
  await ensureInitialized()

  return true
})

export default router
