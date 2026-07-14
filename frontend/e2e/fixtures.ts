import { test as base, type Page } from '@playwright/test'
import path from 'path'

export const USER_AUTH = path.join(__dirname, '.auth/user.json')
export const ADMIN_AUTH = path.join(__dirname, '.auth/admin.json')

export const USER_EMAIL = 'e2e_user@local.test'
export const USER_PASSWORD = 'E2eTest123!'
export const ADMIN_EMAIL = 'e2e_admin@local.test'
export const ADMIN_PASSWORD = 'E2eAdmin123!'

/** 带普通用户登录态的 page fixture */
export const test = base.extend<{ userPage: Page; adminPage: Page }>({
  userPage: async ({ browser }, use) => {
    const ctx = await browser.newContext({ storageState: USER_AUTH })
    const page = await ctx.newPage()
    await use(page)
    await ctx.close()
  },
  adminPage: async ({ browser }, use) => {
    const ctx = await browser.newContext({ storageState: ADMIN_AUTH })
    const page = await ctx.newPage()
    await use(page)
    await ctx.close()
  },
})

export { expect } from '@playwright/test'

/** 直接调后端 API（带 token）。token 从 seed 端点取，测试内需要时可 await apiAs(token, ...) */
export async function apiPost(token: string, path: string, body?: unknown) {
  const res = await fetch(`http://127.0.0.1:8000${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: body ? JSON.stringify(body) : undefined,
  })
  return res
}

export async function apiGet(token: string, path: string) {
  return fetch(`http://127.0.0.1:8000${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function apiDelete(token: string, path: string) {
  return fetch(`http://127.0.0.1:8000${path}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
}

/** 从 seed 端点重新获取测试 token（每次测试前调用，保证 token 新鲜） */
export async function getSeedTokens() {
  const res = await fetch('http://127.0.0.1:8000/api/e2e/seed', { method: 'POST' })
  return res.json() as Promise<{
    user: { user_id: string; username: string; email: string; access_token: string; refresh_token: string }
    admin: { user_id: string; username: string; email: string; access_token: string; refresh_token: string }
    credentials: { user_email: string; user_password: string; admin_email: string; admin_password: string }
  }>
}
