/** Real browser + Next auth + FastAPI + PostgreSQL. No API route interception. */
import { expect, test, type BrowserContext } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Requires explicitly started isolated local services')
test.setTimeout(240_000)

function isolatedDatabase() {
  const connectionString = (process.env.DATABASE_URL ?? '').replace('postgresql+asyncpg:', 'postgresql:')
  const url = new URL(connectionString)
  if (!['localhost', '127.0.0.1', '::1'].includes(url.hostname) || !url.pathname.endsWith('_test')) {
    throw new Error('Capability acceptance only runs against a loopback *_test database')
  }
  if (process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('Capability acceptance must not have live model/email providers or remote workers')
  }
  return new Pool({ connectionString })
}

async function signup(context: BrowserContext, frontend: string) {
  const email = `test_capability_${randomUUID()}@example.test`
  const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
    headers: { Origin: frontend },
    data: { name: 'Synthetic capability acceptance', email, password: `Synthetic-${randomUUID()}!` },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const result = await response.json() as { user: { id: string }; token: string }
  expect(result.user.id).toBeTruthy()
  expect(result.token).toBeTruthy()
  await context.addInitScript(() => {
    localStorage.setItem('latexy_onboarding_completed', 'true')
    localStorage.setItem('latexy_auto_compile', 'false')
  })
  return { id: result.user.id, headers: { Authorization: `Bearer ${result.token}` } }
}

test('real role toggles hide desktop/mobile controls and block API while owner data and admin recovery survive', async ({ browser }, testInfo) => {
  const database = isolatedDatabase()
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5180'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://127.0.0.1:8030'
  const adminContext = await browser.newContext({ baseURL: frontend })
  const actorContext = await browser.newContext({ baseURL: frontend })
  const guestContext = await browser.newContext({ baseURL: frontend, viewport: { width: 390, height: 844 } })
  await guestContext.addInitScript(() => { localStorage.setItem('latexy_auto_compile', 'false') })
  const createdUsers: string[] = []
  const oldRoles = await database.query('SELECT role, feature_key, enabled FROM role_features WHERE feature_key = ANY($1::text[])', [['b03', 'a09']])
  try {
    const admin = await signup(adminContext, frontend); createdUsers.push(admin.id)
    const actor = await signup(actorContext, frontend); createdUsers.push(actor.id)
    await database.query("UPDATE users SET role = 'admin', email_verified = true WHERE id = $1", [admin.id])
    await database.query("UPDATE users SET email_verified = true WHERE id = $1", [actor.id])
    const adminPage = await adminContext.newPage()
    const actorPage = await actorContext.newPage()
    await adminPage.goto('/admin')
    await expect(adminPage.getByRole('heading', { name: 'Capability inventory' })).toBeVisible({ timeout: 45_000 })
    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('b03')
    await adminPage.getByRole('button', { name: 'Account roles' }).click()
    const created = await actorContext.request.post(`${backend}/resumes/`, {
      headers: actor.headers,
      data: { title: 'Synthetic saved source', latex_content: '\\documentclass{article}\\begin{document}Existing source remains.\\end{document}' },
    })
    expect(created.ok(), await created.text()).toBeTruthy()
    const resume = await created.json() as { id: string; latex_content: string }
    for (const role of ['user', 'support', 'admin']) {
      await database.query('UPDATE users SET role = $1 WHERE id = $2', [role, actor.id])
      await actorPage.setViewportSize(role === 'support' ? { width: 390, height: 844 } : { width: 1440, height: 1000 })
      const control = adminPage.getByRole('switch', { name: `Cross-document search for role ${role}`, exact: true })
      await expect(control).toHaveAttribute('aria-checked', 'true')
      await actorPage.goto('/workspace')
      await expect(actorPage.getByRole('button', { name: 'Search resume content', exact: true })).toBeVisible({ timeout: 45_000 })
      const update = adminPage.waitForResponse((response) => response.url().endsWith('/admin/entitlements/roles') && response.request().method() === 'PATCH')
      await control.click()
      expect((await update).status()).toBe(200)
      await expect(control).toHaveAttribute('aria-checked', 'false')
      const denied = await actorContext.request.get(`${backend}/resumes/search?q=existing`, { headers: actor.headers })
      expect(denied.status()).toBe(403)
      expect(await denied.text()).toContain('feature_disabled')
      const disabledMap = actorPage.waitForResponse(
        (response) => response.url().endsWith('/config/entitlements') && response.status() === 200,
        { timeout: 45_000 },
      )
      // The user case proves another tab's admin edit reaches an already-open
      // browser through bounded visibility/polling refresh, without navigating
      // or reloading. Bring it forward as a real user returning to the tab would.
      if (role === 'user') await actorPage.bringToFront()
      else await actorPage.reload()
      expect((await (await disabledMap).json()).features.b03).toBe(false)
      await expect(actorPage.getByRole('heading', { name: /Resume library/i })).toBeVisible({ timeout: 45_000 })
      await expect(actorPage.getByRole('button', { name: 'Search resume content', exact: true })).toHaveCount(0)
      const stored = await actorContext.request.get(`${backend}/resumes/${resume.id}`, { headers: actor.headers })
      expect(stored.status()).toBe(200)
      expect((await stored.json()).latex_content).toBe(resume.latex_content)
      if (role === 'admin') {
        expect((await actorContext.request.get(`${backend}/admin/entitlements`, { headers: actor.headers })).status()).toBe(200)
      }
      await actorPage.screenshot({ path: testInfo.outputPath(`real-${role}-off.png`), fullPage: true })
      const restore = adminPage.waitForResponse((response) => response.url().endsWith('/admin/entitlements/roles') && response.request().method() === 'PATCH')
      await control.click(); expect((await restore).status()).toBe(200)
      await expect(control).toHaveAttribute('aria-checked', 'true')
      expect((await actorContext.request.get(`${backend}/resumes/search?q=existing`, { headers: actor.headers })).status()).toBe(200)
      await actorPage.reload()
      await expect(actorPage.getByRole('button', { name: 'Search resume content', exact: true })).toBeVisible({ timeout: 45_000 })
    }
    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('a09')
    const anonymousSwitch = adminPage.getByRole('switch', { name: 'Anonymous Resume Studio for role anonymous', exact: true })
    await expect(anonymousSwitch).toHaveAttribute('aria-checked', 'true')
    const guestOff = adminPage.waitForResponse((response) => response.url().endsWith('/admin/entitlements/roles') && response.request().method() === 'PATCH')
    await anonymousSwitch.click(); expect((await guestOff).status()).toBe(200)
    const guestPage = await guestContext.newPage()
    await guestPage.goto('/try')
    await expect(guestPage.locator('.monaco-editor').first()).toBeVisible({ timeout: 45_000 })
    await expect(guestPage.getByRole('button', { name: /recompile/i })).toHaveCount(0)
    await expect(guestPage.locator('button[aria-label="Auto-compile on change"]')).toHaveCount(0)
    await expect(guestPage.locator('[aria-label="Source and PDF synchronization"]')).toHaveCount(0)
    const guestDenied = await guestContext.request.post(`${backend}/jobs/submit`, {
      data: { job_type: 'latex_compilation', latex_content: 'Synthetic source' },
    })
    expect(guestDenied.status()).toBe(403)
    expect(await guestDenied.text()).toContain('feature_disabled')
    await guestPage.screenshot({ path: testInfo.outputPath('real-anonymous-off.png'), fullPage: true })
    const guestOn = adminPage.waitForResponse((response) => response.url().endsWith('/admin/entitlements/roles') && response.request().method() === 'PATCH')
    await anonymousSwitch.click(); expect((await guestOn).status()).toBe(200)
    await guestPage.reload()
    await expect(guestPage.getByRole('button', { name: /recompile/i })).toBeVisible({ timeout: 45_000 })
    await expect(guestPage.getByRole('button', { name: 'Auto-compile on change', exact: true })).toBeVisible()
    await adminPage.screenshot({ path: testInfo.outputPath('real-admin-role-controls.png'), fullPage: true })
  } finally {
    for (const row of oldRoles.rows) await database.query('UPDATE role_features SET enabled = $1 WHERE role = $2 AND feature_key = $3', [row.enabled, row.role, row.feature_key])
    if (createdUsers.length) {
      await database.query('DELETE FROM session WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM account WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM users WHERE id = ANY($1::uuid[])', [createdUsers])
    }
    await adminContext.close(); await actorContext.close(); await guestContext.close(); await database.end()
  }
})
