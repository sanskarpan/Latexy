/** Real browser + Next auth + FastAPI + PostgreSQL. No API route interception. */
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
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
  const email = 'test_capability_' + randomUUID() + '@example.test'
  const response = await context.request.post(frontend + '/api/auth/sign-up/email', {
    headers: { Origin: frontend },
    data: { name: 'Synthetic capability acceptance', email, password: 'Synthetic-' + randomUUID() + '!' },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const result = await response.json() as { user: { id: string }; token: string }
  expect(result.user.id).toBeTruthy()
  expect(result.token).toBeTruthy()
  await context.addInitScript(() => {
    localStorage.setItem('latexy_onboarding_completed', 'true')
    localStorage.setItem('latexy_auto_compile', 'false')
  })
  return { id: result.user.id, headers: { Authorization: 'Bearer ' + result.token } }
}

async function setAdminCapability(
  page: Page,
  feature: string,
  label: string,
  scope: 'global' | 'family' | 'sku' | 'role',
  enabled: boolean,
) {
  await page.getByRole('searchbox', { name: 'Search capabilities' }).fill(feature)
  if (scope === 'family') await page.getByRole('button', { name: 'Family defaults', exact: true }).click()
  if (scope === 'sku') await page.getByRole('button', { name: 'Individual plans', exact: true }).click()
  if (scope === 'role') await page.getByRole('button', { name: 'Account roles', exact: true }).click()
  const cell = scope === 'family' ? 'pro' : scope === 'sku' ? 'pro_annual' : 'user'
  const name = scope === 'global'
    ? label + ' global kill-switch'
    : label + ' for ' + (scope === 'role' ? 'role ' : '') + cell
  const control = page.getByRole('switch', { name, exact: true })
  await expect(control).toHaveAttribute('aria-checked', String(!enabled))
  const changed = page.waitForResponse((response) =>
    new URL(response.url()).pathname.startsWith('/admin/entitlements/')
      && response.request().method() === 'PATCH',
  )
  await control.click()
  const response = await changed
  expect(response.status(), await response.text()).toBe(200)
  await expect(control).toHaveAttribute('aria-checked', String(enabled))
}
test('real sharing child gates honor role, family, SKU and parent while ordinary owner recovery survives', async ({ browser }) => {
  const database = isolatedDatabase()
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5181'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://127.0.0.1:8030'
  const adminContext = await browser.newContext({ baseURL: frontend })
  const ownerContext = await browser.newContext({ baseURL: frontend })
  const unrelatedContext = await browser.newContext({ baseURL: frontend })
  const controlledKeys = ['collaboration', 'f01', 'f03', 'resume_builder', 'b01', 'c01']
  const globals = await database.query(
    'SELECT key, enabled, updated_at FROM feature_flags WHERE key = ANY($1::text[])',
    [controlledKeys],
  )
  const matrix = await database.query(
    'SELECT plan_family, feature_key, enabled, updated_at FROM plan_features WHERE plan_family = ANY($1::text[]) AND feature_key = ANY($2::text[])',
    [['pro', 'pro_annual'], controlledKeys],
  )
  const roles = await database.query(
    'SELECT role, feature_key, enabled, updated_at FROM role_features WHERE role = $1 AND feature_key = ANY($2::text[])',
    ['user', controlledKeys],
  )
  const createdUsers: string[] = []

  try {
    await database.query('UPDATE feature_flags SET enabled = TRUE WHERE key = ANY($1::text[])', [controlledKeys])
    await database.query(
      'UPDATE plan_features SET enabled = TRUE WHERE plan_family = ANY($1::text[]) AND feature_key = ANY($2::text[])',
      [['pro', 'pro_annual'], controlledKeys],
    )
    await database.query(
      'UPDATE role_features SET enabled = TRUE WHERE role = $1 AND feature_key = ANY($2::text[])',
      ['user', controlledKeys],
    )

    const admin = await signup(adminContext, frontend); createdUsers.push(admin.id)
    const owner = await signup(ownerContext, frontend); createdUsers.push(owner.id)
    const unrelated = await signup(unrelatedContext, frontend); createdUsers.push(unrelated.id)
    await database.query("UPDATE users SET role = 'admin', email_verified = TRUE WHERE id = $1", [admin.id])
    await database.query("UPDATE users SET role = 'user', subscription_plan = 'pro_annual', email_verified = TRUE WHERE id = $1", [owner.id])
    await database.query("UPDATE users SET role = 'user', email_verified = TRUE WHERE id = $1", [unrelated.id])

    const source = '\\documentclass{article}\\begin{document}Private owner source.\\end{document}'
    const created = await ownerContext.request.post(`${backend}/resumes/`, {
      headers: owner.headers,
      data: { title: 'Synthetic sharing controls', latex_content: source },
    })
    expect(created.status(), await created.text()).toBe(201)
    const resume = await created.json() as { id: string; latex_content: string }
    const initialShare = await ownerContext.request.post(`${backend}/resumes/${resume.id}/share`, {
      headers: owner.headers,
      data: { review_comments: true },
    })
    expect(initialShare.status(), await initialShare.text()).toBe(200)
    const shareToken = (await initialShare.json()).share_token as string

    const adminPage = await adminContext.newPage()
    await adminPage.goto('/admin')
    await expect(adminPage.getByRole('heading', { name: 'Capability inventory' })).toBeVisible({ timeout: 45_000 })

    const ownerPage = await ownerContext.newPage()
    await ownerPage.goto(`/workspace/${resume.id}/edit`)
    await ownerPage.getByRole('button', { name: 'Manage share link', exact: true }).click()
    await expect(ownerPage.getByRole('heading', { name: 'Share Resume' })).toBeVisible({ timeout: 45_000 })
    await expect(ownerPage.getByRole('button', { name: 'Revoke link', exact: true })).toBeVisible()

    // All requests use the same already-authenticated owner session. These
    // edits go through the real Admin UI; each next-share request must reread
    // the owner role and current family/SKU rather than reuse a browser grant.
    await setAdminCapability(adminPage, 'f01', 'Public share links', 'role', false)
    let denied = await ownerContext.request.post(`${backend}/resumes/${resume.id}/share`, { headers: owner.headers })
    expect(denied.status(), await denied.text()).toBe(403)
    await setAdminCapability(adminPage, 'f01', 'Public share links', 'role', true)

    await setAdminCapability(adminPage, 'f01', 'Public share links', 'family', false)
    const familyStateResponse = await adminContext.request.get(`${backend}/admin/entitlements`, { headers: admin.headers })
    expect(familyStateResponse.status()).toBe(200)
    const familyState = await familyStateResponse.json()
    expect(familyState.matrix.pro.f01).toBe(false)
    expect(familyState.matrix.pro_annual.f01).toBe(true)
    const familyEffectiveResponse = await ownerContext.request.get(
      `${backend}/config/entitlements?include_quotas=false`, { headers: owner.headers },
    )
    expect(familyEffectiveResponse.status()).toBe(200)
    expect((await familyEffectiveResponse.json()).features.f01).toBe(false)
    denied = await ownerContext.request.post(`${backend}/resumes/${resume.id}/share`, { headers: owner.headers })
    expect(denied.status(), await denied.text()).toBe(403)
    await setAdminCapability(adminPage, 'f01', 'Public share links', 'family', true)

    await setAdminCapability(adminPage, 'f01', 'Public share links', 'sku', false)
    denied = await ownerContext.request.post(`${backend}/resumes/${resume.id}/share`, { headers: owner.headers })
    expect(denied.status(), await denied.text()).toBe(403)
    await setAdminCapability(adminPage, 'f01', 'Public share links', 'sku', true)

    // Explicit F01 remains true while its collaboration parent is switched
    // off. The already-open browser refreshes on focus, shows recovery, and the
    // same public token can no longer mint a storage URL.
    await setAdminCapability(adminPage, 'collaboration', 'Collaboration & Comments', 'global', false)
    const controlState = await adminContext.request.get(`${backend}/admin/entitlements`, { headers: admin.headers })
    expect(controlState.status()).toBe(200)
    const stored = await controlState.json()
    expect(stored.kill_switches.collaboration).toBe(false)
    expect(stored.kill_switches.f01).toBe(true)
    const refresh = ownerPage.waitForResponse((response) =>
      new URL(response.url()).pathname === '/config/entitlements'
        && new URL(response.url()).searchParams.get('include_quotas') === 'false'
        && response.status() === 200,
      { timeout: 45_000 },
    )
    await ownerPage.bringToFront()
    const refreshedResponse = await refresh
    expect(refreshedResponse.status()).toBe(200)
    expect((await refreshedResponse.json()).features.f01).toBe(false)
    await expect(ownerPage.getByText(/Sharing changes are unavailable/)).toBeVisible({ timeout: 45_000 })
    const publicDenied = await unrelatedContext.request.get(`${backend}/share/${shareToken}`)
    expect(publicDenied.status()).toBe(404)
    denied = await ownerContext.request.post(`${backend}/resumes/${resume.id}/share`, { headers: owner.headers })
    expect(denied.status(), await denied.text()).toBe(403)

    const sourceStillOwned = await ownerContext.request.get(`${backend}/resumes/${resume.id}`, { headers: owner.headers })
    expect(sourceStillOwned.status()).toBe(200)
    expect((await sourceStillOwned.json()).latex_content).toBe(source)
    expect((await unrelatedContext.request.get(`${backend}/resumes/${resume.id}`, { headers: unrelated.headers })).status()).toBe(404)
    expect((await unrelatedContext.request.post(`${backend}/resumes/${resume.id}/share`, { headers: unrelated.headers })).status()).toBe(404)

    await ownerPage.getByRole('button', { name: 'Revoke link', exact: true }).click()
    const revoked = ownerPage.waitForResponse((response) =>
      new URL(response.url()).pathname === `/resumes/${resume.id}/share`
        && response.request().method() === 'DELETE',
    )
    await ownerPage.getByRole('button', { name: 'Revoke permanently', exact: true }).click()
    expect((await revoked).status()).toBe(204)
    await expect(ownerPage.getByText(/New sharing is currently unavailable/)).toBeVisible()
    expect((await ownerContext.request.get(`${backend}/resumes/${resume.id}`, { headers: owner.headers })).status()).toBe(200)

    await setAdminCapability(adminPage, 'collaboration', 'Collaboration & Comments', 'global', true)
    const restoredShare = await ownerContext.request.post(`${backend}/resumes/${resume.id}/share`, {
      headers: owner.headers,
    })
    expect(restoredShare.status(), await restoredShare.text()).toBe(200)
  } finally {
    if (createdUsers.length) {
      await database.query('DELETE FROM resumes WHERE user_id = ANY($1::uuid[])', [createdUsers])
      await database.query('DELETE FROM session WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM account WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM users WHERE id = ANY($1::uuid[])', [createdUsers])
    }
    for (const row of globals.rows) await database.query('UPDATE feature_flags SET enabled = $1, updated_at = $2 WHERE key = $3', [row.enabled, row.updated_at, row.key])
    for (const row of matrix.rows) await database.query('UPDATE plan_features SET enabled = $1, updated_at = $2 WHERE plan_family = $3 AND feature_key = $4', [row.enabled, row.updated_at, row.plan_family, row.feature_key])
    for (const row of roles.rows) await database.query('UPDATE role_features SET enabled = $1, updated_at = $2 WHERE role = $3 AND feature_key = $4', [row.enabled, row.updated_at, row.role, row.feature_key])
    await adminContext.close(); await ownerContext.close(); await unrelatedContext.close(); await database.end()
  }
})
