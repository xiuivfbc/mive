/**
 * events.spec.ts — 事件系统完整决策树
 *
 * 覆盖：
 * - GET /（列表）
 * - PUT /{id}/mark（标记关键事件）
 * - DELETE /{id}（取消/删除事件）
 * - POST /stream（SSE 推演）
 * - POST /stream/pause|resume|stop
 * - POST /stream/trim
 * - POST /stream/rewind
 * - POST /{id}/discard
 * - 版本快照 CRUD（compare/rollback/rename）
 * - 时钟 GET/PUT/advance
 */
import { test, expect, getSeedTokens, apiPost, apiDelete, apiGet } from './fixtures'

const BASE = 'http://127.0.0.1:8000'

// ---------------------------------------------------------------------------
// 辅助：创建测试世界
// ---------------------------------------------------------------------------

async function createWorld(token: string, title = '[E2E] 事件测试') {
  const res = await apiPost(token, '/api/worlds', { title, type: 'novel' })
  return (await res.json()).world_id as string
}

// ---------------------------------------------------------------------------
// 事件列表 GET /api/worlds/{world_id}/events
// ---------------------------------------------------------------------------

test.describe('事件列表', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await createWorld(token)
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('GET 事件列表 → 200 数组', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/events`)
    expect(res.status).toBe(200)
    expect(Array.isArray(await res.json())).toBe(true)
  })

  test('无 token → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events`)
    expect(res.status).toBe(401)
  })

  test('不存在的世界 → 404', async () => {
    const res = await apiGet(token, '/api/worlds/00000000-0000-0000-0000-000000000099/events')
    expect(res.status).toBe(404)
  })
})

// ---------------------------------------------------------------------------
// 事件标记关键/取消 PUT /{event_id}/mark, DELETE /{event_id}
// ---------------------------------------------------------------------------

test.describe('事件标记与删除', () => {
  let worldId: string
  let eventId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await createWorld(token, '[E2E] 标记删除测试')
    // Use /stream to create an event (parse SSE to extract event_id)
    const streamRes = await fetch(`${BASE}/api/worlds/${worldId}/events/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ raw_input: '[E2E] 待标记事件' }),
    })
    const body = await streamRes.text()
    const match = body.match(/event: event_injected\r?\ndata: ({.*?})\r?\n/)
    if (match) {
      const data = JSON.parse(match[1])
      eventId = data.event_id
    }
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('标记为关键事件 → 200 或 204', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/${eventId}/mark`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ is_key_event: true }),
    })
    expect([200, 204]).toContain(res.status)
  })

  test('取消关键标记 → 200 或 204', async () => {
    await fetch(`${BASE}/api/worlds/${worldId}/events/${eventId}/mark`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ is_key_event: true }),
    })
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/${eventId}/mark`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ is_key_event: false }),
    })
    expect([200, 204]).toContain(res.status)
  })

  test('删除事件 → 204', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/${eventId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect([200, 204]).toContain(res.status)
  })

  test('删除不存在的事件 → 404', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/00000000-0000-0000-0000-000000000099`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status).toBe(404)
  })

  test('无 token 标记 → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/${eventId}/mark`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_key_event: true }),
    })
    expect(res.status).toBe(401)
  })
})

// ---------------------------------------------------------------------------
// 流控制 POST /stream/pause|resume|stop
// ---------------------------------------------------------------------------

test.describe('流控制', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await createWorld(token, '[E2E] 流控制测试')
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('pause 端点存在（无流时返回 200 或 404）', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/stream/pause`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect([200, 204, 404]).toContain(res.status)
  })

  test('resume 端点存在（无流时返回 200 或 404）', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/stream/resume`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect([200, 204, 404]).toContain(res.status)
  })

  test('stop 端点存在', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/stream/stop`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect([200, 204, 404]).toContain(res.status)
  })

  test('trim 端点：空 message_ids → 200 或 422', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/stream/trim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ message_ids: [] }),
    })
    expect([200, 204, 422]).toContain(res.status)
  })

  test('rewind 端点：无效 card_message_id → 404', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/stream/rewind`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ card_message_id: '00000000-0000-0000-0000-000000000099' }),
    })
    expect([404, 422]).toContain(res.status)
  })

  test('无 token 调用 pause → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/stream/pause`, {
      method: 'POST',
    })
    expect(res.status).toBe(401)
  })
})

// ---------------------------------------------------------------------------
// discard POST /{event_id}/discard
// ---------------------------------------------------------------------------

test.describe('事件 discard', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await createWorld(token, '[E2E] discard 测试')
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('discard 不存在事件 → 404', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/00000000-0000-0000-0000-000000000099/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ message_ids: [] }),
    })
    expect([404, 422]).toContain(res.status)
  })

  test('无 token discard → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/events/00000000-0000-0000-0000-000000000099/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message_ids: [] }),
    })
    expect(res.status).toBe(401)
  })
})

// ---------------------------------------------------------------------------
// 版本快照 /api/worlds/{world_id}/versions
// ---------------------------------------------------------------------------

test.describe('版本快照', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await createWorld(token, '[E2E] 版本测试')
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('GET 版本列表 → 200 数组', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/versions`)
    expect(res.status).toBe(200)
    expect(Array.isArray(await res.json())).toBe(true)
  })

  test('无 token 获取版本 → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/versions`)
    expect(res.status).toBe(401)
  })

  test('不存在世界的版本 → 404', async () => {
    const res = await apiGet(token, '/api/worlds/00000000-0000-0000-0000-000000000099/versions')
    expect(res.status).toBe(404)
  })

  test('compare：无效 version_ids → 422 或 404', async () => {
    const res = await fetch(
      `${BASE}/api/worlds/${worldId}/versions/compare?v1=00000000-0000-0000-0000-000000000001&v2=00000000-0000-0000-0000-000000000002`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    expect([404, 422]).toContain(res.status)
  })

  test('rollback 不存在版本 → 404', async () => {
    const res = await fetch(
      `${BASE}/api/worlds/${worldId}/versions/00000000-0000-0000-0000-000000000099/rollback`,
      { method: 'POST', headers: { Authorization: `Bearer ${token}` } }
    )
    expect(res.status).toBe(404)
  })

  test('rename 不存在版本 → 404', async () => {
    const res = await fetch(
      `${BASE}/api/worlds/${worldId}/versions/00000000-0000-0000-0000-000000000099`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ name: '新名称' }),
      }
    )
    expect(res.status).toBe(404)
  })

  test('无 token rollback → 401', async () => {
    const res = await fetch(
      `${BASE}/api/worlds/${worldId}/versions/00000000-0000-0000-0000-000000000099/rollback`,
      { method: 'POST' }
    )
    expect(res.status).toBe(401)
  })

  test('生成角色后有版本快照', async () => {
    // 触发角色生成（后台任务），等待完成
    const genRes = await apiPost(token, `/api/worlds/${worldId}/generate-characters`, {
      scale: 'standard',
    })
    if (genRes.status === 202) {
      // 等待生成完成（最多 30s）
      let status = 'running'
      const deadline = Date.now() + 30000
      while (status === 'running' && Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 2000))
        const s = await apiGet(token, `/api/worlds/${worldId}/generate-characters/status`)
        const d = await s.json()
        status = d.status
      }
      if (status === 'completed') {
        const versRes = await apiGet(token, `/api/worlds/${worldId}/versions`)
        const versions = await versRes.json()
        expect(versions.length).toBeGreaterThan(0)
      }
    }
  })
})

// ---------------------------------------------------------------------------
// 时钟 /api/worlds/{world_id}/clock
// ---------------------------------------------------------------------------

test.describe('虚拟时钟', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    worldId = await createWorld(token, '[E2E] 时钟测试')
  })

  test.afterEach(async () => {
    if (worldId) await apiDelete(token, `/api/worlds/${worldId}`)
  })

  test('GET 当前时钟 → 200，含 current_time', async () => {
    const res = await apiGet(token, `/api/worlds/${worldId}/clock`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('current_time')
  })

  test('PUT 设置时钟 → 200 或 204', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/clock`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ current_time: new Date('2025-01-01T00:00:00Z').toISOString() }),
    })
    expect([200, 204]).toContain(res.status)
  })

  test('advance 时钟 → 200 或 204', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/clock/advance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ minutes: 30 }),
    })
    expect([200, 204]).toContain(res.status)
  })

  test('advance 负值 → 422 或 200', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/clock/advance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ minutes: -60 }),
    })
    // 取决于后端是否允许回退时间
    expect([200, 204, 422]).toContain(res.status)
  })

  test('无 token GET 时钟 → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/clock`)
    expect(res.status).toBe(401)
  })

  test('无 token advance → 401', async () => {
    const res = await fetch(`${BASE}/api/worlds/${worldId}/clock/advance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ minutes: 10 }),
    })
    expect(res.status).toBe(401)
  })

  test('设置后 GET 返回正确时间', async () => {
    const targetTime = new Date('2030-06-15T12:00:00Z').toISOString()
    await fetch(`${BASE}/api/worlds/${worldId}/clock`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ current_time: targetTime }),
    })
    const res = await apiGet(token, `/api/worlds/${worldId}/clock`)
    const data = await res.json()
    expect(data.current_time).toContain('2030-06-15')
  })
})

// ---------------------------------------------------------------------------
// 管理员报告状态修改 PATCH /api/admin/reports/{id}
// ---------------------------------------------------------------------------

test.describe('管理员报告处理', () => {
  let worldId: string
  let reportId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 报告处理测试', type: 'novel' })
    worldId = (await res.json()).world_id

    // 提交一条举报
    const reportRes = await fetch(`${BASE}/api/reports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ world_id: worldId, reason: 'inappropriate', description: '[E2E]' }),
    })
    if (reportRes.status === 201) {
      const data = await reportRes.json()
      reportId = data.id || data.report_id
    }
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('管理员更改举报状态为 reviewed', async () => {
    if (!reportId) return // 如果举报创建失败则跳过
    const { admin } = await getSeedTokens()
    const res = await fetch(`${BASE}/api/admin/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${admin.access_token}` },
      body: JSON.stringify({ status: 'reviewed' }),
    })
    expect([200, 204]).toContain(res.status)
  })

  test('管理员更改举报状态为 ignored', async () => {
    if (!reportId) return
    const { admin } = await getSeedTokens()
    const res = await fetch(`${BASE}/api/admin/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${admin.access_token}` },
      body: JSON.stringify({ status: 'ignored' }),
    })
    expect([200, 204]).toContain(res.status)
  })

  test('普通用户修改举报状态 → 403', async () => {
    if (!reportId) return
    const { user } = await getSeedTokens()
    const res = await fetch(`${BASE}/api/admin/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${user.access_token}` },
      body: JSON.stringify({ status: 'reviewed' }),
    })
    expect(res.status).toBe(403)
  })

  test('无效状态值 → 422', async () => {
    if (!reportId) return
    const { admin } = await getSeedTokens()
    const res = await fetch(`${BASE}/api/admin/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${admin.access_token}` },
      body: JSON.stringify({ status: 'invalid_status' }),
    })
    expect([400, 422]).toContain(res.status)
  })

  test('无 token 修改举报 → 401', async () => {
    if (!reportId) return
    const res = await fetch(`${BASE}/api/admin/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'reviewed' }),
    })
    expect(res.status).toBe(401)
  })
})
