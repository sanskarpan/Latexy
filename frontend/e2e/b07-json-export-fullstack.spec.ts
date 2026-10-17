/** Real browser + Next auth + FastAPI + PostgreSQL; no API route interception. */
import { readFileSync } from 'node:fs'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Requires explicitly started isolated local services')
test.setTimeout(240_000)

const CONTROLLED_KEYS = ['exports', 'h01', 'resume_builder', 'b07', 'b01', 'c01'] as const
const CONTROLLED_FAMILIES = ['pro', 'pro_annual'] as const

function isolatedDatabase() {
  const connectionString = (process.env.DATABASE_URL ?? '').replace('postgresql+asyncpg:', 'postgresql:')
  const url = new URL(connectionString)
  if (!['localhost', '127.0.0.1', '::1'].includes(url.hostname) || !url.pathname.endsWith('_test')) {
    throw new Error('B07 acceptance only runs against a loopback *_test database')
  }
  if (process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('B07 acceptance must not have live model/email providers or remote workers')
  }
  return new Pool({ connectionString })
}

async function signup(context: BrowserContext, frontend: string) {
  const email = `test_b07_export_${randomUUID()}@example.test`
  const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
    headers: { Origin: frontend },
    data: { name: 'Synthetic B07 export acceptance', email, password: `Synthetic-${randomUUID()}!` },
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

async function setGlobal(
  context: BrowserContext,
  backend: string,
  headers: Record<string, string>,
  key: string,
  enabled: boolean,
) {
  const response = await context.request.patch(`${backend}/admin/entitlements/kill-switch/${key}`, {
    headers, data: { enabled },
  })
  expect(response.status(), await response.text()).toBe(200)
}

async function setCell(
  context: BrowserContext,
  backend: string,
  headers: Record<string, string>,
  scope: 'matrix' | 'roles',
  key: string,
  enabled: boolean,
  target: string,
) {
  const path = scope === 'matrix' ? '/admin/entitlements/matrix' : '/admin/entitlements/roles'
  const data = scope === 'matrix'
    ? { plan_family: target, feature_key: key, enabled }
    : { role: target, feature_key: key, enabled }
  const response = await context.request.patch(`${backend}${path}`, { headers, data })
  expect(response.status(), await response.text()).toBe(200)
}

async function toggleB07InAdmin(page: Page, enabled: boolean) {
  await page.getByRole('searchbox', { name: 'Search capabilities' }).fill('b07')
  const control = page.getByRole('switch', {
    name: 'Structured resume interchange global kill-switch', exact: true,
  })
  await expect(control).toBeVisible()
  if ((await control.getAttribute('aria-checked')) !== String(enabled)) {
    const changed = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/admin/entitlements/kill-switch/b07'
        && response.request().method() === 'PATCH',
    )
    await control.click()
    const response = await changed
    expect(response.status(), await response.text()).toBe(200)
  }
  await expect(control).toHaveAttribute('aria-checked', String(enabled))
}

function exportJsonOption(page: Page) {
  return page.getByRole('button', { name: /JSON Resume format/ })
}

test('real B07 toggle denies raw, saved and builder JSON routes, preserves owner ACL, and recovers', async ({ browser }, testInfo) => {
  const database = isolatedDatabase()
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5181'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://127.0.0.1:8030'
  const adminContext = await browser.newContext({ baseURL: frontend })
  const ownerContext = await browser.newContext({ baseURL: frontend, viewport: { width: 1440, height: 1000 } })
  const otherContext = await browser.newContext({ baseURL: frontend })
  const globals = await database.query(
    'SELECT key, enabled, updated_at FROM feature_flags WHERE key = ANY($1::text[])', [CONTROLLED_KEYS],
  )
  const matrix = await database.query(
    'SELECT plan_family, feature_key, enabled, updated_at FROM plan_features WHERE plan_family = ANY($1::text[]) AND feature_key = ANY($2::text[])',
    [CONTROLLED_FAMILIES, CONTROLLED_KEYS],
  )
  const roles = await database.query(
    'SELECT role, feature_key, enabled, updated_at FROM role_features WHERE role = $1 AND feature_key = ANY($2::text[])',
    ['user', CONTROLLED_KEYS],
  )
  expect(globals.rows).toHaveLength(CONTROLLED_KEYS.length)
  expect(matrix.rows).toHaveLength(CONTROLLED_FAMILIES.length * CONTROLLED_KEYS.length)
  expect(roles.rows).toHaveLength(CONTROLLED_KEYS.length)

  const createdUsers: string[] = []
  let admin: Awaited<ReturnType<typeof signup>> | undefined
  let b07BaselineReady = false

  try {
    admin = await signup(adminContext, frontend); createdUsers.push(admin.id)
    const owner = await signup(ownerContext, frontend); createdUsers.push(owner.id)
    const other = await signup(otherContext, frontend); createdUsers.push(other.id)
    await database.query("UPDATE users SET role = 'admin', email_verified = TRUE WHERE id = $1", [admin.id])
    for (const account of [owner, other]) {
      await database.query(
        "UPDATE users SET role = 'user', subscription_plan = 'pro_annual', subscription_status = 'active', email_verified = TRUE WHERE id = $1",
        [account.id],
      )
    }

    // Give the synthetic pro_annual users a known allow baseline for B07/H01
    // and their parents, plus the two capabilities needed to create the source.
    for (const key of CONTROLLED_KEYS) {
      await setGlobal(adminContext, backend, admin.headers, key, true)
      for (const family of CONTROLLED_FAMILIES) {
        await setCell(adminContext, backend, admin.headers, 'matrix', key, true, family)
      }
      await setCell(adminContext, backend, admin.headers, 'roles', key, true, 'user')
    }
    b07BaselineReady = true

    const source = '\\documentclass{article}\\begin{document}Synthetic B07 export source.\\end{document}'
    const created = await ownerContext.request.post(`${backend}/resumes/`, {
      headers: owner.headers,
      data: { title: 'Synthetic B07 export owner', latex_content: source },
    })
    expect(created.status(), await created.text()).toBe(201)
    const resume = await created.json() as { id: string; latex_content: string }

    const enabled = await ownerContext.request.get(`${backend}/config/entitlements?include_quotas=false`, {
      headers: owner.headers,
    })
    expect(enabled.status(), await enabled.text()).toBe(200)
    expect((await enabled.json()).features).toMatchObject({ h01: true, b07: true })

    // Cross-owner denial is an ACL result while B07/H01 are enabled.
    const crossOwner = await otherContext.request.get(`${backend}/export/${resume.id}/json`, {
      headers: other.headers,
    })
    expect(crossOwner.status(), await crossOwner.text()).toBe(403)
    expect((await crossOwner.json()).detail).toBe('Access denied')

    const adminPage = await adminContext.newPage()
    await adminPage.goto('/admin')
    await expect(adminPage.getByRole('heading', { name: 'Capability inventory' })).toBeVisible({ timeout: 45_000 })
    const ownerPage = await ownerContext.newPage()
    await ownerPage.goto(`/workspace/${resume.id}/edit`)
    const exportButton = ownerPage.getByRole('button', { name: /^Export/ })
    await expect(exportButton).toBeVisible({ timeout: 45_000 })
    await exportButton.click()
    await expect(exportJsonOption(ownerPage)).toBeVisible()

    // The real Admin UI turns B07 off. H01 stays on, so this isolates the
    // JSON Resume child gate instead of masking it with the parent export gate.
    await toggleB07InAdmin(adminPage, false)
    const deniedConfigWait = ownerPage.waitForResponse((response) =>
      new URL(response.url()).pathname === '/config/entitlements'
        && new URL(response.url()).searchParams.get('include_quotas') === 'false'
        && response.status() === 200,
      { timeout: 45_000 },
    )
    await ownerPage.reload()
    const deniedConfig = await deniedConfigWait
    expect((await deniedConfig.json()).features).toMatchObject({ h01: true, b07: false })
    await ownerPage.getByRole('button', { name: /^Export/ }).click()
    await expect(exportJsonOption(ownerPage)).toHaveCount(0)

    const denied = [
      await ownerContext.request.post(`${backend}/export/content/json`, {
        headers: owner.headers, data: { latex_content: source },
      }),
      await ownerContext.request.get(`${backend}/export/${resume.id}/json`, { headers: owner.headers }),
      await ownerContext.request.get(`${backend}/export/builder/v1/${resume.id}/json`, { headers: owner.headers }),
    ]
    for (const response of denied) {
      const body = await response.text()
      expect(response.status(), body).toBe(403)
      expect(body).toContain('feature_disabled')
      expect(body).toContain('b07')
    }

    const ownerSource = await ownerContext.request.get(`${backend}/resumes/${resume.id}`, { headers: owner.headers })
    expect(ownerSource.status(), await ownerSource.text()).toBe(200)
    expect((await ownerSource.json()).latex_content).toBe(source)

    await toggleB07InAdmin(adminPage, true)
    const recoveredConfigWait = ownerPage.waitForResponse((response) =>
      new URL(response.url()).pathname === '/config/entitlements'
        && new URL(response.url()).searchParams.get('include_quotas') === 'false'
        && response.status() === 200,
      { timeout: 45_000 },
    )
    await ownerPage.reload()
    const recoveredConfig = await recoveredConfigWait
    expect((await recoveredConfig.json()).features).toMatchObject({ h01: true, b07: true })
    await ownerPage.getByRole('button', { name: /^Export/ }).click()
    await expect(exportJsonOption(ownerPage)).toBeVisible()

    const downloadWait = ownerPage.waitForEvent('download')
    await exportJsonOption(ownerPage).click()
    const download = await downloadWait
    expect(download.suggestedFilename()).toBe('resume.json')
    const path = await download.path()
    expect(path).toBeTruthy()
    const downloaded = JSON.parse(readFileSync(path!, 'utf8')) as Record<string, unknown>
    expect(downloaded).toHaveProperty('basics')

    const recovered = [
      await ownerContext.request.post(`${backend}/export/content/json`, {
        headers: owner.headers, data: { latex_content: source },
      }),
      await ownerContext.request.get(`${backend}/export/${resume.id}/json`, { headers: owner.headers }),
      await ownerContext.request.get(`${backend}/export/builder/v1/${resume.id}/json`, { headers: owner.headers }),
    ]
    for (const response of recovered) {
      expect(response.status(), await response.text()).toBe(200)
      expect(response.headers()['content-type']).toContain('application/json')
      expect(await response.json()).toHaveProperty('basics')
    }
    const stillCrossOwner = await otherContext.request.get(`${backend}/export/${resume.id}/json`, {
      headers: other.headers,
    })
    expect(stillCrossOwner.status(), await stillCrossOwner.text()).toBe(403)
    expect((await stillCrossOwner.json()).detail).toBe('Access denied')

    await ownerPage.screenshot({ path: testInfo.outputPath('b07-json-export-reenabled.png'), fullPage: true })
  } finally {
    // Restore exact saved policy values even if an assertion fails midway.
    try {
      if (admin && b07BaselineReady) {
        for (const row of globals.rows) await setGlobal(adminContext, backend, admin.headers, row.key, row.enabled)
        for (const row of matrix.rows) await setCell(adminContext, backend, admin.headers, 'matrix', row.feature_key, row.enabled, row.plan_family)
        for (const row of roles.rows) await setCell(adminContext, backend, admin.headers, 'roles', row.feature_key, row.enabled, row.role)
      }
    } finally {
      try {
        for (const row of globals.rows) {
          await database.query('UPDATE feature_flags SET enabled = $1, updated_at = $2 WHERE key = $3', [row.enabled, row.updated_at, row.key])
        }
        for (const row of matrix.rows) {
          await database.query('UPDATE plan_features SET enabled = $1, updated_at = $2 WHERE plan_family = $3 AND feature_key = $4', [row.enabled, row.updated_at, row.plan_family, row.feature_key])
        }
        for (const row of roles.rows) {
          await database.query('UPDATE role_features SET enabled = $1, updated_at = $2 WHERE role = $3 AND feature_key = $4', [row.enabled, row.updated_at, row.role, row.feature_key])
        }
        if (createdUsers.length) {
          await database.query('DELETE FROM resumes WHERE user_id = ANY($1::uuid[])', [createdUsers])
          await database.query('DELETE FROM session WHERE "userId" = ANY($1::text[])', [createdUsers])
          await database.query('DELETE FROM account WHERE "userId" = ANY($1::text[])', [createdUsers])
          await database.query('DELETE FROM users WHERE id = ANY($1::uuid[])', [createdUsers])
        }
      } finally {
        await adminContext.close(); await ownerContext.close(); await otherContext.close(); await database.end()
      }
    }
  }
})
