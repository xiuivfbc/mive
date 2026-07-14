import { chromium } from '@playwright/test'
import path from 'path'

const BASE_URL = 'http://127.0.0.1:5173'
const API_URL = 'http://127.0.0.1:8000'

export const USER_AUTH = path.join(__dirname, '.auth/user.json')
export const ADMIN_AUTH = path.join(__dirname, '.auth/admin.json')

export default async function globalSetup() {
  // Seed test users via the E2E endpoint
  const res = await fetch(`${API_URL}/api/e2e/seed`, { method: 'POST' })
  if (!res.ok) throw new Error(`E2E seed failed: ${res.status} ${await res.text()}`)
  const { user, admin } = await res.json()

  const browser = await chromium.launch()

  for (const [data, authFile] of [
    [user, USER_AUTH],
    [admin, ADMIN_AUTH],
  ] as const) {
    const ctx = await browser.newContext()

    // Inject refresh token cookie so store.initialize() can restore auth
    await ctx.addCookies([
      {
        name: 'refresh_token',
        value: data.refresh_token,
        domain: '127.0.0.1',
        path: '/api/auth/refresh',
        httpOnly: true,
        sameSite: 'Lax',
        expires: Math.floor(Date.now() / 1000) + 7 * 24 * 3600,
      },
    ])

    const page = await ctx.newPage()
    // Mark welcome as visited so router goes straight to /worlds
    await page.goto(BASE_URL)
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    // Navigate to a protected page to trigger initialize() + token refresh
    await page.goto(`${BASE_URL}/worlds`)
    // Wait until auth completes — the world-list button or heading should appear
    await page.waitForSelector('button, h1, h2', { timeout: 15000 })

    await ctx.storageState({ path: authFile })
    await ctx.close()
  }

  await browser.close()
}
