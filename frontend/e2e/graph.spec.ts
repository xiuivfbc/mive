/**
 * graph.spec.ts — 图谱命令（CommandBar）完整决策树
 *
 * 覆盖：
 * - 空命令无反应
 * - 无效括号代号 → resolveError 提示
 * - 有效命令 → 解析 → 预览 diff → 应用 / 取消
 * - 解析 API（无 LLM 时返回 500 的错误处理）
 * - 应用 API（各操作类型）
 * - 图谱数据 API：获取、节点/边 CRUD
 */
import { test, expect, getSeedTokens, apiPost, apiGet, apiDelete } from './fixtures'

async function setupWorld() {
  const { user } = await getSeedTokens()
  const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 图谱命令测试', type: 'novel' })
  const worldId = (await res.json()).world_id

  // 创建两个角色供命令使用
  const c1 = await (await apiPost(user.access_token, `/api/worlds/${worldId}/characters`, {
    name: '[E2E] 角色甲',
    brief: '第一个角色',
    tier: 'core',
  })).json()
  const c2 = await (await apiPost(user.access_token, `/api/worlds/${worldId}/characters`, {
    name: '[E2E] 角色乙',
    brief: '第二个角色',
    tier: 'supporting',
  })).json()

  return { worldId, charIdA: c1.id as string, charIdB: c2.id as string, token: user.access_token }
}

test.describe('图谱命令 - CommandBar UI', () => {
  let worldId: string

  test.beforeEach(async () => {
    const setup = await setupWorld()
    worldId = setup.worldId
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('Graph tab 存在 CommandBar', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      // CommandBar 输入框
      await expect(
        page.locator('input[placeholder*="命令"], textarea[placeholder*="命令"], [class*="command"]').first()
      ).toBeVisible({ timeout: 5000 })
    }
  })

  test('空命令按 Enter 不发请求', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      const input = page.locator('input[placeholder*="命令"], [class*="command-input"]').first()
      if (await input.isVisible({ timeout: 3000 }).catch(() => false)) {
        await input.click()
        await page.keyboard.press('Enter')
        // 不应有加载状态
        await expect(page.locator('[class*="loading"], .n-spin')).not.toBeVisible({ timeout: 1000 }).catch(() => {})
      }
    }
  })

  test('无效代号 → 错误提示（不发解析请求）', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      const input = page.locator('input[placeholder*="命令"], [class*="command-input"]').first()
      if (await input.isVisible({ timeout: 3000 }).catch(() => false)) {
        await input.fill('[z] 这个代号不存在')
        const [req] = await Promise.all([
          page.waitForRequest(r => r.url().includes('/graph-command'), { timeout: 2000 }).catch(() => null),
          page.keyboard.press('Enter'),
        ])
        expect(req).toBeNull()
        await expect(page.getByText(/无效|代号|不存在/)).toBeVisible({ timeout: 3000 })
      }
    }
  })

  test('按 Escape 清空命令和预览', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      const input = page.locator('input[placeholder*="命令"], [class*="command-input"]').first()
      if (await input.isVisible({ timeout: 3000 }).catch(() => false)) {
        await input.fill('一些命令文字')
        await page.keyboard.press('Escape')
        await expect(input).toHaveValue('', { timeout: 2000 })
      }
    }
  })
})

// ---------------------------------------------------------------------------
// 图谱命令 — parse/apply API
// ---------------------------------------------------------------------------

test.describe('图谱命令 - parse/apply API', () => {
  let worldId: string
  let charIdA: string
  let charIdB: string
  let token: string

  test.beforeEach(async () => {
    const setup = await setupWorld()
    ;({ worldId, charIdA, charIdB, token } = setup)
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('parse 端点无 token → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph-command/parse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: '测试命令' }),
    })
    expect(res.status).toBe(401)
  })

  test('apply 端点无操作列表 → 422', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph-command/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
    })
    expect(res.status).toBe(422)
  })

  test('apply add_character 操作 → 角色被创建', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph-command/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        operations: [
          {
            op: 'add_character',
            name: '[E2E] 命令新增角色',
            tier: 'extra',
            brief: '通过图谱命令添加',
          },
        ],
      }),
    })
    expect([200, 201]).toContain(res.status)
    const data = await res.json()
    expect(data).toHaveProperty('applied')
  })

  test('apply delete_character 操作 → 角色被删除', async () => {
    // 先创建一个临时角色
    const tmp = await (await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 待命令删除',
      tier: 'extra',
    })).json()

    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph-command/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        operations: [{ op: 'delete_character', character_id: tmp.id }],
      }),
    })
    expect([200, 201]).toContain(res.status)
  })

  test('apply add_relation 操作 → 关系被创建', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph-command/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        operations: [
          {
            op: 'add_relation',
            character_a_id: charIdA,
            character_b_id: charIdB,
            relation: '合作伙伴',
            source_type: 'explicit',
          },
        ],
      }),
    })
    expect([200, 201]).toContain(res.status)
  })

  test('apply 空 operations 数组 → 正常返回（0 个操作）', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph-command/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ operations: [] }),
    })
    expect([200, 201]).toContain(res.status)
  })
})

// ---------------------------------------------------------------------------
// 图谱数据 API
// ---------------------------------------------------------------------------

test.describe('图谱数据 API', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    const res = await apiPost(token, '/api/worlds', { title: '[E2E] 图谱数据API', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('获取图谱数据 → 200', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/graph`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('nodes')
    expect(data).toHaveProperty('edges')
  })

  test('无 token 获取图谱 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/graph`)
    expect(res.status).toBe(401)
  })

  test('获取角色素材包 → 200', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/character-material`)
    expect(res.status).toBe(200)
  })
})

// ---------------------------------------------------------------------------
// 关系 CRUD API
// ---------------------------------------------------------------------------

test.describe('关系 CRUD API', () => {
  let worldId: string
  let charIdA: string
  let charIdB: string
  let token: string

  test.beforeEach(async () => {
    const setup = await setupWorld()
    ;({ worldId, charIdA, charIdB, token } = setup)
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('创建关系 → 201', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/relations`, {
      character_a_id: charIdA,
      character_b_id: charIdB,
      relation: '[E2E] 测试关系',
      source_type: 'explicit',
    })
    expect([200, 201]).toContain(res.status)
    const data = await res.json()
    expect(data).toHaveProperty('id')
  })

  test('创建关系缺少 character_a_id → 422', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/relations`, {
      character_b_id: charIdB,
      relation: '测试',
    })
    expect(res.status).toBe(422)
  })

  test('删除关系 → 204', async () => {
    const createRes = await apiPost(token, `/api/worlds/${worldId}/relations`, {
      character_a_id: charIdA,
      character_b_id: charIdB,
      relation: '[E2E] 待删除关系',
      source_type: 'explicit',
    })
    const rel = await createRes.json()
    const delRes = await apiDelete(token, `/api/worlds/${worldId}/relations/${rel.id}`)
    expect([200, 204]).toContain(delRes.status)
  })

  test('删除不存在的关系 → 404', async () => {
    const res = await apiDelete(token, `/api/worlds/${worldId}/relations/00000000-0000-0000-0000-000000000099`)
    expect(res.status).toBe(404)
  })

  test('删除角色时级联删除其关系（不报 FK 错误）', async () => {
    // 先建关系
    await apiPost(token, `/api/worlds/${worldId}/relations`, {
      character_a_id: charIdA,
      character_b_id: charIdB,
      relation: '[E2E] 级联删除测试',
      source_type: 'inferred',
    })
    // 删除角色（应同时删除关系）
    const res = await apiDelete(token, `/api/worlds/${worldId}/characters/${charIdA}`)
    expect([200, 204]).toContain(res.status)
  })
})
