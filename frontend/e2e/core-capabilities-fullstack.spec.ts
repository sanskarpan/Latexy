/** Real browser + Next auth + FastAPI + PostgreSQL; no mocked API calls. */
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Requires explicitly started isolated local services')
test.setTimeout(240_000)

const CORE_KEYS = ['b01', 'c01', 'c05', 'compile', 'b10', 'resume_builder'] as const

function isolatedDatabase() {
  const connectionString = (process.env.DATABASE_URL ?? '').replace('postgresql+asyncpg:', 'postgresql:')
  const url = new URL(connectionString)
  if (!['localhost', '127.0.0.1', '::1'].includes(url.hostname) || !url.pathname.endsWith('_test')) {
    throw new Error('Core capability acceptance only runs against a loopback *_test database')
  }
  if (process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('Core capability acceptance must not have live model/email providers or remote workers')
  }
  return new Pool({ connectionString })
}

async function signup(context: BrowserContext, frontend: string) {
  const email = `test_core_capability_${randomUUID()}@example.test`
  const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
    headers: { Origin: frontend },
    data: { name: 'Synthetic core capability acceptance', email, password: `Synthetic-${randomUUID()}!` },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  const result = await response.json() as { user: { id: string }; token: string }
  expect(result.user.id).toBeTruthy()
  expect(result.token).toBeTruthy()
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
    headers,
    data: { enabled },
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
) {
  const path = scope === 'matrix' ? '/admin/entitlements/matrix' : '/admin/entitlements/roles'
  const data = scope === 'matrix'
    ? { plan_family: 'free', feature_key: key, enabled }
    : { role: 'user', feature_key: key, enabled }
  const response = await context.request.patch(`${backend}${path}`, { headers, data })
  expect(response.status(), await response.text()).toBe(200)
}

async function toggleGlobalInAdmin(page: Page, key: string, label: string, enabled: boolean) {
  await page.getByRole('searchbox', { name: 'Search capabilities' }).fill(key)
  const control = page.getByRole('switch', { name: `${label} global kill-switch`, exact: true })
  await expect(control).toBeVisible()
  if ((await control.getAttribute('aria-checked')) === String(enabled)) return
  const changed = page.waitForResponse((response) =>
    response.url().endsWith(`/admin/entitlements/kill-switch/${key}`) && response.request().method() === 'PATCH',
  )
  await control.click()
  expect((await changed).status()).toBe(200)
  await expect(control).toHaveAttribute('aria-checked', String(enabled))
}

test('core creation, source edits and compilation can be paused without losing existing-source recovery', async ({ browser }, testInfo) => {
  const database = isolatedDatabase()
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5181'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://127.0.0.1:8030'
  const adminContext = await browser.newContext({ baseURL: frontend })
  const actorContext = await browser.newContext({ baseURL: frontend, viewport: { width: 1440, height: 1000 } })
  await actorContext.addInitScript(() => {
    localStorage.setItem('latexy_onboarding_completed', 'true')
    localStorage.setItem('latexy_auto_compile', 'false')
  })

  const createdUsers: string[] = []
  const globals = await database.query(
    'SELECT key, enabled, updated_at FROM feature_flags WHERE key = ANY($1::text[])',
    [CORE_KEYS],
  )
  const matrix = await database.query(
    'SELECT plan_family, feature_key, enabled, updated_at FROM plan_features WHERE plan_family = $1 AND feature_key = ANY($2::text[])',
    ['free', CORE_KEYS],
  )
  const roles = await database.query(
    'SELECT role, feature_key, enabled, updated_at FROM role_features WHERE role = $1 AND feature_key = ANY($2::text[])',
    ['user', CORE_KEYS],
  )
  let admin: Awaited<ReturnType<typeof signup>> | undefined

  try {
    admin = await signup(adminContext, frontend)
    createdUsers.push(admin.id)
    const actor = await signup(actorContext, frontend)
    createdUsers.push(actor.id)
    await database.query("UPDATE users SET role = 'admin', email_verified = true WHERE id = $1", [admin.id])
    await database.query('UPDATE users SET email_verified = true WHERE id = $1', [actor.id])

    // Establish a known allow state for the actor's free/user scope so earlier
    // test state cannot masquerade as one of the global switches under test.
    for (const key of CORE_KEYS) {
      await setCell(adminContext, backend, admin.headers, 'matrix', key, true)
      await setCell(adminContext, backend, admin.headers, 'roles', key, true)
      await setGlobal(adminContext, backend, admin.headers, key, true)
    }

    const source = '\\documentclass{article}\\begin{document}Saved source.\\end{document}'
    expect(source.length).toBeLessThan(100) // The editor's automatic first-load compile stays idle.
    const created = await actorContext.request.post(`${backend}/resumes/`, {
      headers: actor.headers,
      data: { title: 'Existing core-capability source', latex_content: source },
    })
    expect(created.status(), await created.text()).toBe(201)
    const resume = await created.json() as { id: string; latex_content: string }
    // Main opens the visual editor by default. This scenario exercises saved
    // source recovery and Monaco/CodeMirror controls in an explicit source mode.
    await actorContext.addInitScript((resumeId: string) => {
      localStorage.setItem(`latexy_editor_mode_${resumeId}`, 'source')
    }, resume.id)

    const adminPage = await adminContext.newPage()
    await adminPage.goto('/admin')
    await expect(adminPage.getByRole('heading', { name: 'Capability inventory' })).toBeVisible({ timeout: 45_000 })
    const actorPage = await actorContext.newPage()
    await actorPage.goto('/workspace/new')
    await expect(actorPage.getByRole('button', { name: 'Start from Blank', exact: true })).toBeVisible({ timeout: 45_000 })
    await actorPage.goto(`/workspace/${resume.id}/edit`)
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true }).first()).toBeEnabled({ timeout: 45_000 })
    await expect(actorPage.getByRole('button', { name: 'Compile', exact: true }).first()).toBeVisible({ timeout: 45_000 })

    // An initial caller-supplied source is a content write too. Granting new
    // document creation alone must not override an editing denial.
    await toggleGlobalInAdmin(adminPage, 'c01', 'Source and content editing', false)
    const deniedInitialSource = await actorContext.request.post(`${backend}/resumes/`, {
      headers: actor.headers,
      data: { title: 'Denied initial source', latex_content: source },
    })
    expect(deniedInitialSource.status(), await deniedInitialSource.text()).toBe(403)
    await actorPage.goto('/workspace/new')
    await actorPage.reload()
    await expect(actorPage.getByRole('button', { name: 'Start from Blank', exact: true })).toHaveCount(0)
    await expect(actorPage.getByRole('button', { name: 'Create Resume', exact: true })).toHaveCount(0)
    await toggleGlobalInAdmin(adminPage, 'c01', 'Source and content editing', true)

    // Use the real admin inventory switches; requests travel through the
    // running Next app and FastAPI, and all API denials come from backend gates.
    await toggleGlobalInAdmin(adminPage, 'b01', 'New resume creation', false)
    await toggleGlobalInAdmin(adminPage, 'c01', 'Source and content editing', false)
    await toggleGlobalInAdmin(adminPage, 'c05', 'New compilation jobs', false)

    const actorPageConfig = actorPage.waitForResponse((response) =>
      response.url().endsWith('/config/entitlements') && response.status() === 200,
    )
    await actorPage.goto('/workspace/new')
    await actorPage.reload()
    await actorPageConfig
    await expect(actorPage.getByRole('button', { name: 'Start from Blank', exact: true })).toHaveCount(0)
    await expect(actorPage.getByRole('button', { name: 'Create Resume', exact: true })).toHaveCount(0)
    await actorPage.setViewportSize({ width: 390, height: 844 })
    await actorPage.reload()
    await expect(actorPage.getByRole('button', { name: 'Start from Blank', exact: true })).toHaveCount(0)
    await expect(actorPage.getByRole('button', { name: 'Create Resume', exact: true })).toHaveCount(0)

    const deniedCreate = await actorContext.request.post(`${backend}/resumes/`, {
      headers: actor.headers,
      data: { title: 'Blocked new source', latex_content: source },
    })
    expect(deniedCreate.status()).toBe(403)
    expect(await deniedCreate.text()).toContain('feature_disabled')

    const beforeJobs = await database.query(
      'SELECT (SELECT count(*)::int FROM compilations WHERE user_id = $1::uuid) AS compilations, (SELECT count(*)::int FROM job_finalizations WHERE user_id = $1::uuid) AS finalizations',
      [actor.id],
    )
    const deniedEdit = await actorContext.request.put(`${backend}/resumes/${resume.id}`, {
      headers: actor.headers,
      data: {
        latex_content: '\\documentclass{article}\\begin{document}Edited.\\end{document}',
        expected_latex_content: resume.latex_content,
      },
    })
    expect(deniedEdit.status()).toBe(403)
    expect(await deniedEdit.text()).toContain('feature_disabled')
    const deniedCompile = await actorContext.request.post(`${backend}/jobs/submit`, {
      headers: actor.headers,
      data: { job_type: 'latex_compilation', latex_content: resume.latex_content, resume_id: resume.id },
    })
    expect(deniedCompile.status()).toBe(403)
    expect(await deniedCompile.text()).toContain('feature_disabled')
    const afterJobs = await database.query(
      'SELECT (SELECT count(*)::int FROM compilations WHERE user_id = $1::uuid) AS compilations, (SELECT count(*)::int FROM job_finalizations WHERE user_id = $1::uuid) AS finalizations',
      [actor.id],
    )
    expect(afterJobs.rows[0]).toEqual(beforeJobs.rows[0])

    const recovered = await actorContext.request.get(`${backend}/resumes/${resume.id}`, { headers: actor.headers })
    expect(recovered.status()).toBe(200)
    expect((await recovered.json()).latex_content).toBe(source)

    await actorPage.goto(`/workspace/${resume.id}/edit`)
    await expect(actorPage.locator('.cm-editor, .monaco-editor').first()).toBeVisible({ timeout: 45_000 })
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
    await expect(actorPage.getByRole('button', { name: 'Compile', exact: true })).toHaveCount(0)
    await actorPage.screenshot({ path: testInfo.outputPath('core-capabilities-mobile-off.png'), fullPage: true })

    await actorPage.setViewportSize({ width: 1440, height: 1000 })
    await actorPage.reload()
    await expect(actorPage.locator('.monaco-editor').first()).toBeVisible({ timeout: 45_000 })
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
    await expect(actorPage.getByRole('button', { name: 'Compile', exact: true })).toHaveCount(0)
    await actorPage.screenshot({ path: testInfo.outputPath('core-capabilities-desktop-off.png'), fullPage: true })

    // Re-enable core admissions, then pause only visual editing. The existing
    // source remains readable and editable in the regular LaTeX editor.
    await toggleGlobalInAdmin(adminPage, 'b01', 'New resume creation', true)
    await toggleGlobalInAdmin(adminPage, 'c01', 'Source and content editing', true)
    await toggleGlobalInAdmin(adminPage, 'c05', 'New compilation jobs', true)
    await actorPage.reload()
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true }).first()).toBeVisible({ timeout: 45_000 })
    await expect(actorPage.getByRole('button', { name: 'Compile', exact: true }).first()).toBeVisible({ timeout: 45_000 })
    await actorPage.goto('/workspace/new')
    await expect(actorPage.getByRole('button', { name: 'Start from Blank', exact: true })).toBeVisible({ timeout: 45_000 })
    const restoredCreation = await actorContext.request.post(`${backend}/resumes/`, {
      headers: actor.headers,
      data: { title: 'Creation restored after capability ON', latex_content: source },
    })
    expect(restoredCreation.status(), await restoredCreation.text()).toBe(201)
    await setGlobal(adminContext, backend, admin.headers, 'b10', false)
    await actorPage.goto(`/workspace/${resume.id}/edit`)
    await actorPage.reload()
    await expect(actorPage.locator('.monaco-editor').first()).toBeVisible({ timeout: 45_000 })
    const sourceStillReadable = await actorContext.request.get(`${backend}/resumes/${resume.id}`, { headers: actor.headers })
    expect(sourceStillReadable.status()).toBe(200)
    expect((await sourceStillReadable.json()).latex_content).toBe(source)
    const sourceEditWithVisualModePaused = await actorContext.request.put(`${backend}/resumes/${resume.id}`, {
      headers: actor.headers,
      data: {
        latex_content: '\\documentclass{article}\\begin{document}Edited with source mode.\\end{document}',
        expected_latex_content: source,
      },
    })
    expect(sourceEditWithVisualModePaused.status(), await sourceEditWithVisualModePaused.text()).toBe(200)
    expect((await actorContext.request.get(`${backend}/resumes/${resume.id}`, { headers: actor.headers })).status()).toBe(200)
    await actorPage.screenshot({ path: testInfo.outputPath('core-capabilities-b10-off.png'), fullPage: true })
  } finally {
    if (admin) {
      for (const row of globals.rows) await setGlobal(adminContext, backend, admin.headers, row.key, row.enabled).catch(() => {})
      for (const row of matrix.rows) await setCell(adminContext, backend, admin.headers, 'matrix', row.feature_key, row.enabled).catch(() => {})
      for (const row of roles.rows) await setCell(adminContext, backend, admin.headers, 'roles', row.feature_key, row.enabled).catch(() => {})
    }
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
      await database.query('DELETE FROM session WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM account WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM users WHERE id = ANY($1::uuid[])', [createdUsers])
    }
    await adminContext.close()
    await actorContext.close()
    await database.end()
  }
})
