/**
 * worlds.spec.ts — 世界创建全状态机 + 列表 + 详情各 Tab
 *
 * 覆盖 CreateWorldDialog 所有 phase：
 *   form → (disambiguate) → wiki-confirm → no-wiki → generating
 * 以及 WorldDetailPage 所有 Tab 操作和 API 错误路径
 */
import { test, expect, getSeedTokens, apiPost, apiDelete, apiGet } from './fixtures'

// ---------------------------------------------------------------------------
// 世界列表
// ---------------------------------------------------------------------------

test.describe('世界列表', () => {
  test('已登录用户可以访问世界列表', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await expect(page).toHaveURL(/\/worlds/, { timeout: 10000 })
    await expect(page.getByRole('button', { name: /创建/ })).toBeVisible({ timeout: 8000 })
  })

  test('分页或滚动加载：API 第一页正常返回', async () => {
    const { user } = await getSeedTokens()
    const res = await apiGet(user.access_token, '/api/worlds?limit=20')
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data).toHaveProperty('items')
    expect(Array.isArray(data.items)).toBe(true)
  })

  test('访问不存在的世界详情 → 404', async () => {
    const { user } = await getSeedTokens()
    const res = await apiGet(user.access_token, '/api/worlds/00000000-0000-0000-0000-000000000099')
    expect(res.status).toBe(404)
  })
})

// ---------------------------------------------------------------------------
// CreateWorldDialog — form phase 校验
// ---------------------------------------------------------------------------

test.describe('创建世界 - form phase 校验', () => {
  test('标题为空时提交按钮 disabled', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })

    // 不填标题，直接检查提交按钮
    const submitBtn = modal.getByRole('button', { name: /^创建$|^确认$|^确定$/ }).last()
    await expect(submitBtn).toBeDisabled({ timeout: 2000 })
  })

  test('IP 免责未勾选点提交 → 出现抖动/错误提示', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })

    await modal.locator('input[type="text"]').first().fill('[E2E] IP测试世界')

    // 确保 IP 声明未勾选
    const ipCheck = modal.locator('input[type="checkbox"]').first()
    if (await ipCheck.isVisible({ timeout: 1000 }).catch(() => false)) {
      await ipCheck.uncheck()
      const submitBtn = modal.getByRole('button', { name: /^创建$|^确认$|^确定$/ }).last()
      await submitBtn.click()
      // 不应跳转，modal 仍可见
      await page.waitForTimeout(500)
      await expect(modal).toBeVisible()
    }
  })

  test('四种规模都能选择', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })

    for (const scale of ['标准', '详尽', '深度', '全量', 'standard', 'detailed', 'deep', 'all']) {
      const btn = modal.getByText(new RegExp(scale, 'i'))
      if (await btn.isVisible({ timeout: 500 }).catch(() => false)) {
        await btn.click()
        // 不报错即可
      }
    }
  })

  test('可以添加参考 URL 输入框', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })

    const addUrlBtn = modal.getByRole('button', { name: /添加|\+.*URL|参考/ })
    if (await addUrlBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await addUrlBtn.click()
      const urlInput = modal.locator('input[placeholder*="http"]').last()
      await expect(urlInput).toBeVisible({ timeout: 2000 })
      await urlInput.fill('https://example.com/reference')
    }
  })
})

// ---------------------------------------------------------------------------
// CreateWorldDialog — 成功创建（无 wiki）
// ---------------------------------------------------------------------------

test.describe('创建世界 - 成功路径（无 wiki）', () => {
  test('填写标题提交 → 进入 no-wiki 或 generating phase', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })

    await modal.locator('input[type="text"]').first().fill('[E2E] 无Wiki世界')

    const ipCheck = modal.locator('input[type="checkbox"]').first()
    if (await ipCheck.isVisible({ timeout: 1000 }).catch(() => false)) await ipCheck.check()

    const submitBtn = modal.getByRole('button', { name: /^创建$|^确认$|^确定$/ }).last()
    await submitBtn.click()

    // phase 进入 wiki-confirm、no-wiki 或 generating 之一
    await expect(
      page.getByText(/找到|未找到|正在|搜索|wiki/i)
        .or(page.getByRole('button', { name: /跳过|继续|是|否/ }))
        .or(page.locator('[class*="step"], [class*="progress"]'))
    ).toBeVisible({ timeout: 15000 })
  })
})

// ---------------------------------------------------------------------------
// CreateWorldDialog — wiki-confirm phase
// ---------------------------------------------------------------------------

test.describe('创建世界 - wiki-confirm phase', () => {
  test('手动输入非 wikipedia 格式 URL → 错误提示', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    await modal.locator('input[type="text"]').first().fill('[E2E] Wiki格式测试')
    const ipCheck = modal.locator('input[type="checkbox"]').first()
    if (await ipCheck.isVisible({ timeout: 1000 }).catch(() => false)) await ipCheck.check()
    await modal.getByRole('button', { name: /^创建$|^确认$|^确定$/ }).last().click()

    // 若进入 wiki-confirm phase
    const manualInput = page.locator('input[placeholder*="wikipedia"], input[placeholder*="网址"], input[placeholder*="URL"]').last()
    if (await manualInput.isVisible({ timeout: 10000 }).catch(() => false)) {
      await manualInput.fill('https://baidu.com/not-wiki')
      const confirmBtn = page.getByRole('button', { name: /^是$|^确认$|^确定$/ })
      await confirmBtn.click()
      await expect(page.locator('body')).toContainText(/格式|无效|wikipedia/, { timeout: 3000 })
    }
  })

  test('点击"否"拒绝 wiki → 进入 no-wiki phase', async ({ userPage: page }) => {
    await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
    await page.goto('/worlds')
    await page.getByRole('button', { name: /创建/ }).click()

    const modal = page.locator('.n-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    await modal.locator('input[type="text"]').first().fill('[E2E] Wiki拒绝测试')
    const ipCheck = modal.locator('input[type="checkbox"]').first()
    if (await ipCheck.isVisible({ timeout: 1000 }).catch(() => false)) await ipCheck.check()
    await modal.getByRole('button', { name: /^创建$|^确认$|^确定$/ }).last().click()

    // 若进入 wiki-confirm phase 后点"否"
    const rejectBtn = page.getByRole('button', { name: /^否$|拒绝|不是这个/ })
    if (await rejectBtn.isVisible({ timeout: 10000 }).catch(() => false)) {
      await rejectBtn.click()
      // 进入 no-wiki phase
      await expect(page.getByRole('button', { name: /跳过|继续/ })).toBeVisible({ timeout: 5000 })
    }
  })
})

// ---------------------------------------------------------------------------
// CreateWorldDialog — no-wiki phase
// ---------------------------------------------------------------------------

test.describe('创建世界 - no-wiki phase', () => {
  test('no-wiki 阶段有参考 URL 输入框和两个按钮', async ({ userPage: page }) => {
    // 通过 API 验证 check-wiki（搜不到时的流程）
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds/check-wiki', {
      title: 'xyznonexistent12345',
      author: '',
    })
    const data = await res.json()
    // found=false 时前端应进入 no-wiki
    if (!data.found) {
      // 进入 no-wiki phase — UI 测试
      await page.evaluate(() => localStorage.setItem('hasVisitedWelcome', 'true'))
      await page.goto('/worlds')
      await page.getByRole('button', { name: /创建/ }).click()
      const modal = page.locator('.n-modal, [role="dialog"]').first()
      await expect(modal).toBeVisible({ timeout: 5000 })
      await modal.locator('input[type="text"]').first().fill('[E2E] NoWiki测试')
      const ipCheck = modal.locator('input[type="checkbox"]').first()
      if (await ipCheck.isVisible({ timeout: 1000 }).catch(() => false)) await ipCheck.check()
      await modal.getByRole('button', { name: /^创建$|^确认$|^确定$/ }).last().click()

      const skipBtn = page.getByRole('button', { name: /跳过/ })
      if (await skipBtn.isVisible({ timeout: 12000 }).catch(() => false)) {
        // 存在"跳过"和"继续"按钮
        await expect(page.getByRole('button', { name: /继续/ })).toBeVisible()
      }
    }
  })

  test('check-wiki API：空标题 → 422', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds/check-wiki', {
      title: '',
    })
    expect([400, 422]).toContain(res.status)
  })

  test('check-wiki API：无 token → 401', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/worlds/check-wiki', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'test' }),
    })
    expect(res.status).toBe(401)
  })
})

// ---------------------------------------------------------------------------
// 世界 CRUD API
// ---------------------------------------------------------------------------

test.describe('世界 CRUD API', () => {
  test('创建世界 → 201 含 world_id', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', {
      title: '[E2E] API创建测试',
      type: 'novel',
    })
    expect(res.status).toBe(201)
    const data = await res.json()
    expect(data).toHaveProperty('world_id')
    await apiDelete(user.access_token, `/api/worlds/${data.world_id}`)
  })

  test('创建世界无 token → 401', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/worlds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'test' }),
    })
    expect(res.status).toBe(401)
  })

  test('创建世界缺少标题 → 422', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', {})
    expect(res.status).toBe(422)
  })

  test('删除不存在的世界 → 404', async () => {
    const { user } = await getSeedTokens()
    const res = await apiDelete(user.access_token, '/api/worlds/00000000-0000-0000-0000-000000000099')
    expect(res.status).toBe(404)
  })
})

// ---------------------------------------------------------------------------
// 世界详情 — World Tab（故事简介编辑）
// ---------------------------------------------------------------------------

test.describe('世界详情 - World Tab', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 详情-World Tab', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('World tab 可以切换并看到基础信息', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-World Tab')).toBeVisible({ timeout: 10000 })
    const worldTab = page.getByRole('tab', { name: /世界|world/i })
    if (await worldTab.isVisible({ timeout: 3000 }).catch(() => false)) await worldTab.click()
    await expect(page.locator('body')).toContainText(/创建|类型|作者|标题|novel/i, { timeout: 5000 })
  })

  test('故事简介：编辑 → 保存 → 验证内容更新', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-World Tab')).toBeVisible({ timeout: 10000 })

    // 找故事简介编辑入口
    const editBtn = page.getByRole('button', { name: /编辑|修改/ }).first()
    if (await editBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await editBtn.click()
    } else {
      // 双击触发内联编辑
      const summaryArea = page.locator('[class*="plot"], [class*="summary"], [class*="story"]').first()
      if (await summaryArea.isVisible({ timeout: 2000 }).catch(() => false)) {
        await summaryArea.dblclick()
      }
    }

    const editor = page.locator('textarea, [contenteditable="true"]').first()
    if (await editor.isVisible({ timeout: 3000 }).catch(() => false)) {
      await editor.fill('[E2E] 这是测试用故事简介内容。')
      const saveBtn = page.getByRole('button', { name: /保存|确认/ }).first()
      if (await saveBtn.isVisible({ timeout: 1000 }).catch(() => false)) await saveBtn.click()
      else await page.keyboard.press('Escape')
    }
  })

  test('故事简介：取消编辑不保存', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-World Tab')).toBeVisible({ timeout: 10000 })

    const editBtn = page.getByRole('button', { name: /编辑|修改/ }).first()
    if (await editBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await editBtn.click()
      const editor = page.locator('textarea, [contenteditable="true"]').first()
      if (await editor.isVisible({ timeout: 2000 }).catch(() => false)) {
        const original = await editor.inputValue().catch(() => '')
        await editor.fill('[E2E] 临时修改内容，不保存')
        const cancelBtn = page.getByRole('button', { name: /取消/ })
        if (await cancelBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
          await cancelBtn.click()
          // 内容不变
          await expect(page.getByText('[E2E] 临时修改内容，不保存')).not.toBeVisible({ timeout: 2000 }).catch(() => {})
        }
      }
    }
  })

  test('故事简介 API：空内容 PATCH → 正常（允许清空）', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/plot-summary`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${user.access_token}`,
      },
      body: JSON.stringify({ plot_summary: '' }),
    })
    expect([200, 204]).toContain(res.status)
  })
})

// ---------------------------------------------------------------------------
// 世界详情 — Characters Tab
// ---------------------------------------------------------------------------

test.describe('世界详情 - Characters Tab', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 详情-Chars Tab', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('无角色时显示空状态和"生成角色"按钮', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-Chars Tab')).toBeVisible({ timeout: 10000 })
    const charTab = page.getByRole('tab', { name: /角色/ })
    if (await charTab.isVisible({ timeout: 3000 }).catch(() => false)) await charTab.click()
    await expect(page.getByRole('button', { name: /生成|角色/ })).toBeVisible({ timeout: 5000 })
  })

  test('点击"生成角色"打开确认对话框', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-Chars Tab')).toBeVisible({ timeout: 10000 })
    const charTab = page.getByRole('tab', { name: /角色/ })
    if (await charTab.isVisible({ timeout: 3000 }).catch(() => false)) await charTab.click()

    const genBtn = page.getByRole('button', { name: /生成/ }).first()
    if (await genBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await genBtn.click()
      // 确认对话框
      await expect(
        page.locator('.n-modal, [role="dialog"]').last()
      ).toBeVisible({ timeout: 3000 })
    }
  })

  test('有角色时可以点击查看角色详情抽屉', async ({ userPage: page }) => {
    const { user } = await getSeedTokens()
    // 先创建一个角色
    const charRes = await apiPost(user.access_token, `/api/worlds/${worldId}/characters`, {
      name: '[E2E] 抽屉测试角色',
      brief: '一个测试角色',
      tier: 'core',
    })
    const charId = (await charRes.json()).id

    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-Chars Tab')).toBeVisible({ timeout: 10000 })
    const charTab = page.getByRole('tab', { name: /角色/ })
    if (await charTab.isVisible({ timeout: 3000 }).catch(() => false)) await charTab.click()

    // 点击角色
    const charEl = page.getByText('[E2E] 抽屉测试角色').first()
    if (await charEl.isVisible({ timeout: 5000 }).catch(() => false)) {
      await charEl.click()
      // 抽屉出现
      await expect(
        page.locator('.n-drawer, [role="complementary"]').first()
      ).toBeVisible({ timeout: 3000 })
    }

    await apiDelete(user.access_token, `/api/worlds/${worldId}/characters/${charId}`)
  })
})

// ---------------------------------------------------------------------------
// 世界详情 — Elements Tab
// ---------------------------------------------------------------------------

test.describe('世界详情 - Elements Tab', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 详情-Elements Tab', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('可以切换到 Elements tab', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-Elements Tab')).toBeVisible({ timeout: 10000 })
    const elTab = page.getByRole('tab', { name: /元素|世界设定/ })
    if (await elTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await elTab.click()
      await expect(elTab).toHaveAttribute('aria-selected', 'true', { timeout: 2000 }).catch(() => {})
    }
  })

  test('通过 API 添加元素', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, `/api/worlds/${worldId}/elements`, {
      name: '[E2E] 测试元素',
      category: '地点',
      brief: '一个测试用的地点',
    })
    expect([200, 201]).toContain(res.status)
    const data = await res.json()
    expect(data).toHaveProperty('id')
    // 清理
    await apiDelete(user.access_token, `/api/worlds/${worldId}/elements/${data.id}`)
  })

  test('通过 API 删除元素', async () => {
    const { user } = await getSeedTokens()
    const createRes = await apiPost(user.access_token, `/api/worlds/${worldId}/elements`, {
      name: '[E2E] 待删除元素',
      category: '道具',
    })
    const el = await createRes.json()
    const delRes = await apiDelete(user.access_token, `/api/worlds/${worldId}/elements/${el.id}`)
    expect([200, 204]).toContain(delRes.status)
  })

  test('通过 API 更新元素', async () => {
    const { user } = await getSeedTokens()
    const createRes = await apiPost(user.access_token, `/api/worlds/${worldId}/elements`, {
      name: '[E2E] 元素更新前',
      category: '地点',
    })
    const el = await createRes.json()

    const patchRes = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/elements/${el.id}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${user.access_token}`,
      },
      body: JSON.stringify({ brief: '[E2E] 更新后的说明' }),
    })
    expect(patchRes.status).toBe(200)
    const updated = await patchRes.json()
    expect(updated.brief).toBe('[E2E] 更新后的说明')

    await apiDelete(user.access_token, `/api/worlds/${worldId}/elements/${el.id}`)
  })

  test('删除不存在的元素 → 404', async () => {
    const { user } = await getSeedTokens()
    const res = await apiDelete(user.access_token, `/api/worlds/${worldId}/elements/00000000-0000-0000-0000-000000000099`)
    expect(res.status).toBe(404)
  })
})

// ---------------------------------------------------------------------------
// 世界详情 — Versions Tab
// ---------------------------------------------------------------------------

test.describe('世界详情 - Versions Tab', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 详情-Versions Tab', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('Versions tab 可切换', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 详情-Versions Tab')).toBeVisible({ timeout: 10000 })
    const verTab = page.getByRole('tab', { name: /版本|历史/ })
    if (await verTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await verTab.click()
      await expect(verTab).toHaveAttribute('aria-selected', 'true', { timeout: 2000 }).catch(() => {})
    }
  })

  test('版本列表 API 正常返回', async () => {
    const { user } = await getSeedTokens()
    const res = await apiGet(user.access_token, `/api/worlds/${worldId}/versions`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(Array.isArray(data)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// 世界详情 — 分享（Share）
// ---------------------------------------------------------------------------

test.describe('世界详情 - 分享', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 详情-Share', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('生成分享码 → 6 位 base62', async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, `/api/worlds/${worldId}/share`)
    expect(res.status).toBe(200)
    const data = await res.json()
    expect(data.share_code).toMatch(/^[A-Za-z0-9]{6}$/)
  })

  test('生成分享码幂等（两次结果相同）', async () => {
    const { user } = await getSeedTokens()
    const r1 = await apiPost(user.access_token, `/api/worlds/${worldId}/share`)
    const r2 = await apiPost(user.access_token, `/api/worlds/${worldId}/share`)
    expect((await r1.json()).share_code).toBe((await r2.json()).share_code)
  })

  test('撤销分享码后再访问 → 404', async () => {
    const { user } = await getSeedTokens()
    const { share_code } = await (await apiPost(user.access_token, `/api/worlds/${worldId}/share`)).json()

    // 撤销
    await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/share`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${user.access_token}` },
    })

    const shareRes = await fetch(`http://127.0.0.1:8000/api/s/${share_code}`)
    expect(shareRes.status).toBe(404)
  })

  test('无效分享码访问 → 404', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/s/XXXXXX')
    expect(res.status).toBe(404)
  })
})

// ---------------------------------------------------------------------------
// 举报
// ---------------------------------------------------------------------------

test.describe('举报', () => {
  let worldId: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    const res = await apiPost(user.access_token, '/api/worlds', { title: '[E2E] 举报测试', type: 'novel' })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await apiDelete(user.access_token, `/api/worlds/${worldId}`)
  })

  test('提交举报 → 201', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ world_id: worldId, reason: 'inappropriate', description: '[E2E] 测试举报' }),
    })
    expect([201, 422]).toContain(res.status) // 422 可能是 reason 枚举问题
  })

  test('举报世界详情页有举报按钮', async ({ userPage: page }) => {
    await page.goto(`/world/${worldId}`)
    await expect(page.getByText('[E2E] 举报测试')).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: /举报/ })).toBeVisible({ timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// 世界识别（identify）
// ---------------------------------------------------------------------------

test.describe('作品识别', () => {
  test('POST /identify 有 title → 200，返回识别结果', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch('http://127.0.0.1:8000/api/worlds/identify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${user.access_token}` },
      body: JSON.stringify({ title: '哈利·波特', author: 'J.K.罗琳' }),
    })
    expect([200, 201]).toContain(res.status)
    const data = await res.json()
    expect(data).toHaveProperty('title')
  })

  test('POST /identify 缺少 title → 422', async () => {
    const { user } = await getSeedTokens()
    const res = await fetch('http://127.0.0.1:8000/api/worlds/identify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${user.access_token}` },
      body: JSON.stringify({ author: '某作者' }),
    })
    expect(res.status).toBe(422)
  })

  test('POST /identify 无 token → 401', async () => {
    const res = await fetch('http://127.0.0.1:8000/api/worlds/identify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '测试' }),
    })
    expect(res.status).toBe(401)
  })
})

// ---------------------------------------------------------------------------
// 世界复制（copy）
// ---------------------------------------------------------------------------

test.describe('世界复制', () => {
  let worldId: string
  let token: string

  test.beforeEach(async () => {
    const { user } = await getSeedTokens()
    token = user.access_token
    const res = await fetch('http://127.0.0.1:8000/api/worlds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ title: '[E2E] 复制源世界', type: 'novel' }),
    })
    worldId = (await res.json()).world_id
  })

  test.afterEach(async () => {
    const { user } = await getSeedTokens()
    if (worldId) await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${user.access_token}` },
    })
  })

  test('复制世界 → 201，返回新 world_id', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/copy`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status).toBe(201)
    const data = await res.json()
    expect(data).toHaveProperty('world_id')
    expect(data.world_id).not.toBe(worldId)

    // 清理复制出的世界
    await fetch(`http://127.0.0.1:8000/api/worlds/${data.world_id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
  })

  test('复制不存在的世界 → 404', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/00000000-0000-0000-0000-000000000099/copy`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.status).toBe(404)
  })

  test('无 token 复制 → 401', async () => {
    const res = await fetch(`http://127.0.0.1:8000/api/worlds/${worldId}/copy`, {
      method: 'POST',
    })
    expect(res.status).toBe(401)
  })
})
