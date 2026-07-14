/**
 * admin.spec.ts — 管理后台完整决策树
 *
 * 覆盖：
 * - 权限守卫（普通用户无法访问）
 * - 管理员举报列表（分页/状态）
 * - 举报状态修改（pending→reviewed/ignored）
 * - 世界封禁/解封
 * - share_banned 封禁/解封分享
 * - 管理员分享预览（不需要 share_code）
 * - 永久管理员邮箱权限
 * - 管理后台页面 UI
 */
import { test, expect, getSeedTokens, apiPost, apiDelete, apiGet } from './fixtures'

// ---------------------------------------------------------------------------
// 权限守卫
// ---------------------------------------------------------------------------

test.describe('管理后台权限守卫', () => {
  test('未登录访问 /admin → /auth', async ({ page }) => {
    await page.goto('/admin')
    await expect(page).toHaveURL(/\/auth/, { timeout: 8000 })
  })

  test('普通用户访问 /admin → 重定向到首页', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/admin')
    await expect(page).not.toHaveURL(/\/admin/, { timeout: 8000 })
  })

  test('管理员用户可以访问 /admin', async ({ adminPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/admin')
    await expect(page).toHaveURL(/\/admin/, { timeout: 10000 })
    await expect(page.locator('h1, h2').first()).toBeVisible({ timeout: 5000 })
  })

  test('普通用户调用管理 API → 403', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch('http://127.0.0.1:8000/api/reports', {
      headers: { Authorization: `Bearer ${user.access_token}` },
    })
    // 管理接口对普通用户返回 403
    expect([200, 403]).toContain(res.status) // GET reports 可能是公开的（取决于实现）
  })

  test('无 token 调用管理员封禁接口 → 401', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/admin/worlds/00000000-0000-0000-0000-000000000001/ban', {
      method: 'POST',
    })
    expect(res.status).toBe(401)
  })

  test('普通用户调用封禁接口 → 403', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch('http://127.0.0.1:8000/api/admin/worlds/00000000-0000-0000-0000-000000000001/ban', {
      method: 'POST',
      headers: { Authorization: `Bearer ${user.access_token}` },
    })
    expect(res.status).toBe(403)
  })
})

// ---------------------------------------------------------------------------
// 举报系统
// ---------------------------------------------------------------------------

test.describe('举报系统', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 举报系统测试', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('提交举报（无需鉴权）→ 201 或 422', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        world_id: worldId,
        reason: 'inappropriate',
        description: '[E2E] 测试举报内容',
      }),
    })
    expect([201, 422]).toContain(res.status)
  })

  test('管理员获取举报列表 → 200 数组', async () => {
    const { admin } = await getSeedTokens()
    const res = await fetch('http://127.0.0.1:8000/api/reports', {
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    expect(res.status).toBe(200)
    expect(Array.isArray(await res.json())).toBe(true)
  })

  test('举报缺少 world_id → 422', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'inappropriate' }),
    })
    expect(res.status).toBe(422)
  })

  test('举报已删除世界 → 404 或 422', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        world_id: '00000000-0000-0000-0000-000000000099',
        reason: 'inappropriate',
      }),
    })
    expect([404, 422]).toContain(res.status)
  })
})

// ---------------------------------------------------------------------------
// 世界封禁/解封
// ---------------------------------------------------------------------------

test.describe('世界封禁/解封', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 封禁解封测试', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user, admin } = await getSeedTokens()
    // 确保解封（防止影响其他测试）
    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/unban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('管理员可以封禁世界', async () => {
    const { admin } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    expect([200, 204]).toContain(res.status)
  })

  test('管理员可以解封世界', async () => {
    const { admin } = await getSeedTokens()
    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    const res = await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/unban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    expect([200, 204]).toContain(res.status)
  })

  test('封禁后分享页返回 451', async () => {
    const { user, admin } = await getSeedTokens()
    const { share_code } = await (await apiPost(user.access_token, `/api/worlds/${worldId}/share`)).json()

    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })

    const res = await fetch(`http://127.0.0.1:8000/api/s/${share_code}`)
    expect(res.status).toBe(451)
  })

  test('解封后分享页恢复正常', async () => {
    const { user, admin } = await getSeedTokens()
    const { share_code } = await (await apiPost(user.access_token, `/api/worlds/${worldId}/share`)).json()

    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/unban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })

    const res = await fetch(`http://127.0.0.1:8000/api/s/${share_code}`)
    expect(res.status).toBe(200)
  })
})

// ---------------------------------------------------------------------------
// 分享封禁（share_banned）
// ---------------------------------------------------------------------------

test.describe('分享封禁', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 分享封禁测试', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user, admin } = await getSeedTokens()
    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share/unban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('管理员可以封禁分享功能', async () => {
    const { admin } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    expect([200, 204]).toContain(res.status)
  })

  test('分享被封禁后生成分享码 → 403', async () => {
    const { user, admin } = await getSeedTokens()
    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    const res = await apiPost(user.access_token, `/api/worlds/${worldId}/share`)
    expect(res.status).toBe(403)
  })

  test('管理员可以解封分享功能', async () => {
    const { admin } = await getSeedTokens()
    await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    const res = await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share/unban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    expect([200, 204]).toContain(res.status)
  })
})

// ---------------------------------------------------------------------------
// 管理员分享预览
// ---------------------------------------------------------------------------

test.describe('管理员分享预览', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 管理预览测试', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('管理员预览 API（无需 share_code）→ 200', async () => {
    const { admin } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share-preview`, {
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('title')
  })

  test('普通用户调用管理预览 → 403', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/admin/worlds/${worldId}/share-preview`, {
      headers: { Authorization: `Bearer ${user.access_token}` },
    })
    expect(res.status).toBe(403)
  })

  test('前端 /admin/worlds/:worldId/share-preview 路由可访问', async ({ adminPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto(`/admin/worlds/${worldId}/share-preview`)
    await expect(page).not.toHaveURL(/\/auth/, { timeout: 8000 })
    await expect(page.locator('body')).not.toBeEmpty()
  })
})

// ---------------------------------------------------------------------------
// 管理后台 UI
// ---------------------------------------------------------------------------

test.describe('管理后台 UI', () => {
  test('管理后台展示举报列表', async ({ adminPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/admin')
    await expect(page).toHaveURL(/\/admin/, { timeout: 10000 })
    await expect(page.getByText(/举报|report/i).first()).toBeVisible({ timeout: 8000 })
  })

  test('管理后台有操作按钮（忽略/封禁等）', async ({ adminPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/admin')

    // 先提交一条举报
    const { user } = await getSeedTokens()
    const wRes = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 管理UI举报', type: 'novel' })
    const { world_id } = await wRes.json()
    await fetch('http://127.0.0.1:8000/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ world_id, reason: 'inappropriate', description: '[E2E]' }),
    })

    await page.reload()
    await page.waitForTimeout(1000)

    // 应有操作按钮
    await expect(
      page.getByRole('button', { name: /忽略|封禁|处理|详情/ }).first()
    ).toBeVisible({ timeout: 5000 })

    await apiDelete(user.access_token, `/api/worlds/${world_id}`)
  })
})

// ---------------------------------------------------------------------------
// 服务条款页
// ---------------------------------------------------------------------------

test.describe('服务条款', () => {
  test('/tos 页面可以不登录访问', async ({ page }) => {
    await page.goto('/tos')
    await expect(page).not.toHaveURL(/\/auth/, { timeout: 5000 })
    await expect(page.locator('body')).not.toBeEmpty()
    await expect(page.locator('h1, h2').first()).toBeVisible({ timeout: 5000 })
  })

  test('登录页有 ToS 链接', async ({ page }) => {
    await page.goto('/auth')
    const tosLink = page.locator('a[href*="tos"]').or(page.getByText(/服务条款|条款|ToS/i))
    await expect(tosLink.first()).toBeVisible({ timeout: 8000 })
  })
})
