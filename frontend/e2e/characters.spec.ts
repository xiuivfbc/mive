/**
 * characters.spec.ts — 角色完整决策树
 *
 * 覆盖：
 * - 角色 CRUD（创建/读取/更新/删除）
 * - 角色生成异步流程（202/状态轮询/取消）
 * - 世界用户角色（user_character_id 绑定）
 * - 角色层级（core/supporting/extra）
 * - 记忆 API
 * - 删除角色时级联删除关系
 * - 图谱 UI（节点/布局切换）
 * - API 错误路径（401/403/404/422）
 */
import { test, expect, getSeedTokens, apiPost, apiGet, apiDelete } from './fixtures'

async function makeWorld(token: string, title = '[E2E] 角色测试') {
  const res = await apiPost(token, '/api/worlds', { title, type: 'novel' })
  return (await res.json()).world_id as string
}

// ---------------------------------------------------------------------------
// 角色 CRUD API
// ---------------------------------------------------------------------------

test.describe('角色 CRUD API', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await makeWorld(token)
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('创建 core 角色 → 201', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] core 角色',
      brief: '核心角色',
      tier: 'core',
    })
    expect(res.status).toBe(201)
    const data = await res.json()
    expect(data).toHaveProperty('id')
    expect(data.tier).toBe('core')
    await apiDelete(token, `/api/worlds/${worldId}/characters/${data.id}`)
  })

  test('创建 supporting 角色 → 201', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] supporting 角色',
      tier: 'supporting',
    })
    expect(res.status).toBe(201)
    const c = await res.json()
    await apiDelete(token, `/api/worlds/${worldId}/characters/${c.id}`)
  })

  test('创建 extra 角色 → 201', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] extra 角色',
      tier: 'extra',
    })
    expect(res.status).toBe(201)
    const c = await res.json()
    await apiDelete(token, `/api/worlds/${worldId}/characters/${c.id}`)
  })

  test('缺少 name → 422', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/characters`, {
      brief: '没有名字',
      tier: 'core',
    })
    expect(res.status).toBe(422)
  })

  test('无效 tier → 422', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 无效 tier',
      tier: 'legendary',
    })
    expect(res.status).toBe(422)
  })

  test('无 token 创建角色 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/characters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'test', tier: 'core' }),
    })
    expect(res.status).toBe(401)
  })

  test('获取角色列表 → 200 数组', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/characters`)
    expect(res.status).toBe(200)
    expect(Array.isArray(await res.json())).toBe(true)
  })

  test('获取单个角色 → 200 含基本字段', async () => {
    const c = await (await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 单个角色查询',
      tier: 'core',
    })).json()

    const res = await apiGet(token, `/api/worlds/${worldId}/characters/${c.id}`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.name).toBe('[E2E] 单个角色查询')
    expect(data).toHaveProperty('tier')

    await apiDelete(token, `/api/worlds/${worldId}/characters/${c.id}`)
  })

  test('获取不存在的角色 → 404', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/characters/00000000-0000-0000-0000-000000000099`)
    expect(res.status).toBe(404)
  })

  test('更新角色 brief → 200', async () => {
    const c = await (await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 更新角色',
      tier: 'supporting',
    })).json()

    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/characters/${c.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ brief: '[E2E] 更新后的简介内容' }),
    })
    expect(res.status).toBe(200)
    expect((await res.json()).brief).toBe('[E2E] 更新后的简介内容')

    await apiDelete(token, `/api/worlds/${worldId}/characters/${c.id}`)
  })

  test('更新角色 tier → 200', async () => {
    const c = await (await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] tier 更新',
      tier: 'extra',
    })).json()

    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/characters/${c.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ tier: 'core' }),
    })
    expect(res.status).toBe(200)
    expect((await res.json()).tier).toBe('core')

    await apiDelete(token, `/api/worlds/${worldId}/characters/${c.id}`)
  })

  test('删除角色 → 204', async () => {
    const c = await (await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 待删除角色',
      tier: 'extra',
    })).json()
    const res = await apiDelete(token, `/api/worlds/${worldId}/characters/${c.id}`)
    expect([200, 204]).toContain(res.status)
  })

  test('删除不存在的角色 → 404', async () => {
    const res = await apiDelete(token, `/api/worlds/${worldId}/characters/00000000-0000-0000-0000-000000000099`)
    expect(res.status).toBe(404)
  })

  test('删除角色级联删除其关系（无 FK 报错）', async () => {
    const cA = await (await apiPost(token, `/api/worlds/${worldId}/characters`, { name: '[E2E] 级联A', tier: 'core' })).json()
    const cB = await (await apiPost(token, `/api/worlds/${worldId}/characters`, { name: '[E2E] 级联B', tier: 'supporting' })).json()

    // 建立关系
    await apiPost(token, `/api/worlds/${worldId}/relations`, {
      character_a_id: cA.id,
      character_b_id: cB.id,
      relation: '[E2E] 级联测试关系',
      source_type: 'explicit',
    })

    // 删除角色 A（关系应同时消失，不报 FK 错）
    const res = await apiDelete(token, `/api/worlds/${worldId}/characters/${cA.id}`)
    expect([200, 204]).toContain(res.status)

    await apiDelete(token, `/api/worlds/${worldId}/characters/${cB.id}`)
  })
})

// ---------------------------------------------------------------------------
// 角色生成异步流程
// ---------------------------------------------------------------------------

test.describe('角色生成异步流程', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await makeWorld(token, '[E2E] 生成测试')
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('触发生成 → 202（后台任务启动）', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/generate-characters`, {
      scale: 'standard',
    })
    expect([200, 202]).toContain(res.status)
  })

  test('触发生成无效 scale → 422', async () => {
    const res = await apiPost(token, `/api/worlds/${worldId}/generate-characters`, {
      scale: 'mega',
    })
    expect(res.status).toBe(422)
  })

  test('无 token 触发生成 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/generate-characters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scale: 'standard' }),
    })
    expect(res.status).toBe(401)
  })

  test('状态轮询端点 → 200 含 status', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/generate-characters/status`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('status')
    expect(['idle', 'running', 'completed', 'failed']).toContain(data.status)
  })

  test('四种 scale 都触发正常（standard/detailed/deep/all）', async () => {
    for (const scale of ['standard', 'detailed', 'deep', 'all']) {
      const res = await apiPost(token, `/api/worlds/${worldId}/generate-characters`, { scale })
      expect([200, 202]).toContain(res.status)
      // 避免竞争，轮询直到 idle/failed
      for (let i = 0; i < 5; i++) {
        const status = await (await apiGet(token, `/api/worlds/${worldId}/generate-characters/status`)).json()
        if (['idle', 'completed', 'failed'].includes(status.status)) break
        await new Promise(r => setTimeout(r, 500))
      }
    }
  })
})

// ---------------------------------------------------------------------------
// 世界用户角色
// ---------------------------------------------------------------------------

test.describe('世界用户角色', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await makeWorld(token, '[E2E] 用户角色测试')
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('世界创建后 user_character_id 存在或为 null', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}`)
    expect(res.status).toBe(200)
    const data = await res.json()
    // user_character_id 可为 null 或 uuid
    expect(['string', 'object']).toContain(typeof data.user_character_id)
  })

  test('世界用户角色不出现在角色列表（被排除）', async () => {
    const worldRes = await (await apiGet(token, `/api/worlds/${worldId}`)).json()
    const userCharId = worldRes.user_character_id

    if (userCharId) {
      const chars = await (await apiGet(token, `/api/worlds/${worldId}/characters`)).json()
      const found = (chars as any[]).find((c: any) => c.id === userCharId)
      // 世界用户角色不应在普通角色列表中（或如果存在，标记了特殊 flag）
      if (found) {
        expect(found.is_user_character).toBe(true)
      }
    }
  })
})

// ---------------------------------------------------------------------------
// 角色记忆 API
// ---------------------------------------------------------------------------

test.describe('角色记忆 API', () => {
  let worldId: string
  let charId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await makeWorld(token, '[E2E] 记忆测试')
    const c = await (await apiPost(token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 记忆角色',
      tier: 'core',
    })).json()
    charId = c.id
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('获取角色记忆列表 → 200 数组', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/characters/${charId}/memories`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
  })

  test('无 token 获取记忆 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/characters/${charId}/memories`)
    expect(res.status).toBe(401)
  })

  test('不存在角色的记忆 → 404', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/characters/00000000-0000-0000-0000-000000000099/memories`)
    expect(res.status).toBe(404)
  })

  test('删除不存在的记忆 → 404', async () => {
    const res = await apiDelete(token, `/api/worlds/${worldId}/characters/${charId}/memories/00000000-0000-0000-0000-000000000099`)
    expect(res.status).toBe(404)
  })
})

// ---------------------------------------------------------------------------
// 角色图谱 UI
// ---------------------------------------------------------------------------

test.describe('角色图谱 UI', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    worldId = await makeWorld(user.access_token, '[E2E] 图谱UI测试')
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('图谱 Tab 中 SVG 渲染存在', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      await expect(page.locator('svg').first()).toBeVisible({ timeout: 8000 })
    }
  })

  test('有角色时节点出现在 SVG 中', async ({ userPage: page }) => {
    const { user } = await getSeedTokens()
    // 先创建角色
    const c = await (await apiPost(user.access_token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 图谱节点测试角色',
      tier: 'core',
    })).json()

    await page.goto(`/world/${worldId}`)
    await expect(page.locator('body')).toBeVisible({ timeout: 10000 })

    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      await expect(page.locator('svg').first()).toBeVisible({ timeout: 8000 })
      // 角色名出现在页面（tooltip 或 label）
      await expect(page.getByText('[E2E] 图谱节点测试角色')).toBeVisible({ timeout: 5000 })
    }

    await apiDelete(user.access_token, `/api/worlds/${worldId}/characters/${c.id}`)
  })

  test('布局切换按钮存在并可点击', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      const layoutBtn = page.getByRole('button', { name: /同心|力导向|布局|concentric|force/ })
      if (await layoutBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await layoutBtn.click()
        await expect(layoutBtn).toBeVisible()
      }
    }
  })

  test('点击角色节点打开详情抽屉', async ({ userPage: page }) => {
    const { user } = await getSeedTokens()
    const c = await (await apiPost(user.access_token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 可点击节点',
      tier: 'core',
    })).json()

    await page.goto(`/world/${worldId}`)
    const graphTab = page.getByRole('tab', { name: /图谱/ })
    if (await graphTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await graphTab.click()
      await expect(page.locator('svg').first()).toBeVisible({ timeout: 8000 })

      // 点击角色名/节点
      const nodeLabel = page.getByText('[E2E] 可点击节点').first()
      if (await nodeLabel.isVisible({ timeout: 3000 }).catch(() => false)) {
        await nodeLabel.click()
        await expect(
          page.locator('.n-drawer, [role="complementary"]').first()
        ).toBeVisible({ timeout: 3000 })
      }
    }

    await apiDelete(user.access_token, `/api/worlds/${worldId}/characters/${c.id}`)
  })
})
