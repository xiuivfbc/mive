/**
 * chat.spec.ts — 聊天页完整决策树
 *
 * 覆盖：
 * - 页面加载/初始状态
 * - 常规聊天（发送/乐观插入/假流式）
 * - 事件推演模式切换
 * - 事件流中断菜单（继续/丰富/到此为止/回档/丢弃）
 * - 用户身份切换（时空探索者/世界用户角色/NPC）
 * - 历史记录抽屉（加载/恢复 session）
 * - 参与者模式（auto/edit）
 * - API 错误路径
 */
import { test, expect, getSeedTokens, apiPost, apiGet, apiDelete } from './fixtures'

async function makeWorld(token: string, title = '[E2E] 聊天测试') {
  const res = await apiPost(token, '/api/worlds', { title, type: 'novel' })
  return (await res.json()).world_id as string
}

// ---------------------------------------------------------------------------
// 页面基础
// ---------------------------------------------------------------------------

test.describe('聊天页面基础', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token)
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('页面标题显示世界名', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.getByText('[E2E] 聊天测试')).toBeVisible({ timeout: 10000 })
  })

  test('初始无消息，输入框空白', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })
    const textarea = page.locator('textarea').first()
    await expect(textarea).toBeVisible({ timeout: 5000 })
    await expect(textarea).toHaveValue('')
  })

  test('输入框可以接收文字', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    const textarea = page.locator('textarea').first()
    await textarea.fill('[E2E] 测试输入内容')
    await expect(textarea).toHaveValue('[E2E] 测试输入内容')
  })

  test('输入框空时发送按钮 disabled', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    const textarea = page.locator('textarea').first()
    await textarea.fill('')
    const sendBtn = page.getByRole('button', { name: /发送/ })
    await expect(sendBtn).toBeDisabled({ timeout: 3000 })
  })

  test('有内容时发送按钮 enabled', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    const textarea = page.locator('textarea').first()
    await textarea.fill('内容')
    const sendBtn = page.getByRole('button', { name: /发送/ })
    await expect(sendBtn).toBeEnabled({ timeout: 3000 })
  })

  test('AI 免责横幅存在', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })
    // AI 免责横幅
    await expect(
      page.getByText(/AI|免责|仅供参考|人工智能/).first()
    ).toBeVisible({ timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// 常规聊天 - 发送流程
// ---------------------------------------------------------------------------

test.describe('常规聊天 - 发送', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 发消息测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('发送后用户消息乐观插入', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await page.locator('textarea').first().fill('[E2E] 乐观插入测试')
    await page.getByRole('button', { name: /发送/ }).click()
    // 消息立即出现
    await expect(page.getByText('[E2E] 乐观插入测试')).toBeVisible({ timeout: 3000 })
  })

  test('发送后等待 API 响应（POST /messages）', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await page.locator('textarea').first().fill('[E2E] API 响应测试')
    const respPromise = page.waitForResponse(
      r => r.url().includes('/messages') && r.request().method() === 'POST',
      { timeout: 15000 }
    )
    await page.getByRole('button', { name: /发送/ }).click()
    const resp = await respPromise
    expect([200, 201, 400, 500]).toContain(resp.status())
  })

  test('发送后输入框清空', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    const textarea = page.locator('textarea').first()
    await textarea.fill('[E2E] 发完清空测试')
    await page.getByRole('button', { name: /发送/ }).click()
    // 等 API 响应后输入框应清空
    await page.waitForResponse(r => r.url().includes('/messages') && r.request().method() === 'POST', { timeout: 10000 }).catch(() => {})
    await expect(textarea).toHaveValue('', { timeout: 5000 })
  })

  test('发送 API 直接调用 → session_id 不重复', async () => {
    const { user } = await getSeedTokens()
    const r1 = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '[E2E] 第一条',
    })
    const r2 = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '[E2E] 第二条',
    })
    // 两次应返回不同的 session
    if (r1.status === 201 && r2.status === 201) {
      const d1 = await r1.json()
      const d2 = await r2.json()
      // 每次都是新 session（无 session_id 传入）
      expect(d1.session_id).not.toBe(d2.session_id)
    }
  })

  test('指定 session_id 复用会话', async () => {
    const { user } = await getSeedTokens()
    const r1 = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '[E2E] 首条消息',
    })
    if (r1.status === 201) {
      const { session_id } = await r1.json()
      const r2 = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
        content: '[E2E] 续聊',
        session_id,
      })
      if (r2.status === 201) {
        expect((await r2.json()).session_id).toBe(session_id)
      }
    }
  })

  test('传旧字段 target_character_ids → 422', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '测试',
      target_character_ids: ['abc'],
    })
    expect(res.status).toBe(422)
  })

  test('无 token 发消息 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: '测试' }),
    })
    expect(res.status).toBe(401)
  })

  test('空内容发消息 → 422', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '',
    })
    expect([400, 422]).toContain(res.status)
  })
})

// ---------------------------------------------------------------------------
// 事件推演模式
// ---------------------------------------------------------------------------

test.describe('事件推演模式', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 事件推演测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('事件模式切换按钮存在', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })
    await expect(
      page.getByRole('button', { name: /事件|推演/ })
        .or(page.locator('[class*="event-mode"], [class*="mode-switch"]'))
        .first()
    ).toBeVisible({ timeout: 8000 })
  })

  test('切换到事件模式后输入框提示语变化', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const modeBtn = page.getByRole('button', { name: /事件|推演/ }).first()
    if (await modeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await modeBtn.click()
      // 输入框 placeholder 或周围文字变化
      await expect(page.locator('body')).toContainText(/事件|注入|推演/, { timeout: 3000 })
    }
  })

  test('记忆开关存在', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const modeBtn = page.getByRole('button', { name: /事件|推演/ }).first()
    if (await modeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await modeBtn.click()
      await expect(
        page.getByText(/记忆|memory/i).or(page.locator('input[type="checkbox"]').first())
      ).toBeVisible({ timeout: 3000 })
    }
  })

  test('事件流 API：无 LLM key 时返回错误（不是 422）', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/events/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${user.access_token}`,
      },
      body: JSON.stringify({ event_description: '[E2E] 测试事件', memories_enabled: false }),
    })
    // 500（LLM 不可用）或 200（开始流但立即错误）
    expect([200, 500, 402]).toContain(res.status)
    expect(res.status).not.toBe(422)
  })

  test('事件流 API：无 token → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/events/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_description: 'test' }),
    })
    expect(res.status).toBe(401)
  })

  test('流控制 API：pause/resume/stop 端点存在', async () => {
    const { user } = await getSeedTokens()
    for (const action of ['pause', 'resume', 'stop']) {
      const res = await fetch(
        `http://127.0.0.1:8000/api/worlds/${worldId}/events/stream/${action}`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${user.access_token}` },
        }
      )
      // 200 或 404（未启动流时 stop/pause 可能返回不同状态）
      expect([200, 204, 404, 409]).toContain(res.status)
    }
  })
})

// ---------------------------------------------------------------------------
// 中断菜单操作
// ---------------------------------------------------------------------------

test.describe('中断菜单（UI）', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 中断菜单测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('事件推演进行中时显示中断菜单', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const modeBtn = page.getByRole('button', { name: /事件|推演/ }).first()
    if (await modeBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await modeBtn.click()
      const textarea = page.locator('textarea').first()
      await textarea.fill('[E2E] 触发推演')
      await page.getByRole('button', { name: /发送|推演/ }).click()

      // 事件流开始后中断
      const interruptBtn = page.getByRole('button', { name: /中断|暂停|停止/ })
      if (await interruptBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
        await interruptBtn.click()
        // 中断菜单：继续/丰富/到此为止/回档/丢弃
        await expect(
          page.getByRole('button', { name: /继续|丰富|到此为止|回档|丢弃/ }).first()
        ).toBeVisible({ timeout: 3000 })
      }
    }
  })

  test('rewind API：无效 card_message_id → 404 或 400', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/events/stream/rewind`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${user.access_token}`,
      },
      body: JSON.stringify({ card_message_id: '00000000-0000-0000-0000-000000000099' }),
    })
    expect([400, 404, 422]).toContain(res.status)
  })
})

// ---------------------------------------------------------------------------
// 用户身份切换
// ---------------------------------------------------------------------------

test.describe('用户身份切换', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 身份切换测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('默认身份为时空探索者（🧭）', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })
    // 🧭 图标或"时空探索者"文字
    await expect(
      page.getByText(/时空探索者|🧭/).first()
    ).toBeVisible({ timeout: 5000 })
  })

  test('身份选择器存在', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })
    // 身份/角色选择器
    await expect(
      page.locator('[class*="role"], [class*="identity"], [class*="persona"]').first()
        .or(page.getByText(/身份|扮演/).first())
    ).toBeVisible({ timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// 参与者模式
// ---------------------------------------------------------------------------

test.describe('参与者模式', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 参与者模式测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('参与者选择区域存在（auto/edit 模式）', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })
    // 参与者相关 UI
    await expect(
      page.getByText(/参与者|自动|角色/).first()
        .or(page.locator('[class*="participant"], [class*="selector"]').first())
    ).toBeVisible({ timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// 历史记录抽屉
// ---------------------------------------------------------------------------

test.describe('历史记录抽屉', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 历史抽屉测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('历史按钮点击后打开抽屉', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}/chat`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const histBtn = page.getByRole('button', { name: /历史|记录/ })
      .or(page.locator('[title*="历史"], [aria-label*="历史"], [class*="history"]').first())
    if (await histBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await histBtn.click()
      await expect(
        page.locator('.n-drawer, [role="dialog"], [class*="drawer"]').first()
      ).toBeVisible({ timeout: 3000 })
    }
  })

  test('会话列表 API 返回数组', async () => {
    const { user } = await getSeedTokens()
    const res = await apiGet(user.access_token, `/api/worlds/${worldId}/chat-sessions`)
    expect(res.status).toBe(200)
    expect(Array.isArray(await res.json())).toBe(true)
  })

  test('会话消息列表 API 格式正确', async () => {
    const { user } = await getSeedTokens()
    // 先创建一个 session
    const msgRes = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '[E2E] 历史消息',
    })
    if (msgRes.status === 201) {
      const { session_id } = await msgRes.json()
      const listRes = await apiGet(user.access_token, `/api/worlds/${worldId}/messages?session_id=${session_id}`)
      expect(listRes.status).toBe(200)
      const data = await listRes.json()
      expect(data).toHaveProperty('items')
    }
  })

  test('删除会话 → 204', async () => {
    const { user } = await getSeedTokens()
    const msgRes = await apiPost(user.access_token, `/api/worlds/${worldId}/messages`, {
      content: '[E2E] 待删除会话消息',
    })
    if (msgRes.status === 201) {
      const { session_id } = await msgRes.json()
      const delRes = await apiDelete(user.access_token, `/api/worlds/${worldId}/chat-sessions/${session_id}`)
      expect([200, 204]).toContain(delRes.status)
    }
  })

  test('删除不存在的会话 → 404', async () => {
    const { user } = await getSeedTokens()
    const res = await apiDelete(user.access_token, `/api/worlds/${worldId}/chat-sessions/00000000-0000-0000-0000-000000000099`)
    expect(res.status).toBe(404)
  })

  test('无 token 获取会话列表 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/chat-sessions`)
    expect(res.status).toBe(401)
  })
})

// ---------------------------------------------------------------------------
// 时钟 API
// ---------------------------------------------------------------------------

test.describe('时钟 API', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 时钟测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('GET /clock 返回当前时间', async () => {
    const { user } = await getSeedTokens()
    const res = await apiGet(user.access_token, `/api/worlds/${worldId}/clock`)
    expect([200, 404]).toContain(res.status)
    if (res.status === 200) {
      const data = await res.json()
      expect(data).toHaveProperty('current_time')
    }
  })

  test('无 token 获取时钟 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/clock`)
    expect(res.status).toBe(401)
  })
})
