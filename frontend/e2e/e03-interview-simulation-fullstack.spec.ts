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
    throw new Error('E03 acceptance only runs against a loopback *_test database')
  }
  if (process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('E03 acceptance must not have live model/email providers or remote workers')
  }
  return new Pool({ connectionString })
}

async function signup(context: BrowserContext, frontend: string, name: string) {
  const email = `test_e03_${randomUUID()}@example.test`
  const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
    headers: { Origin: frontend },
    data: { name, email, password: `Synthetic-${randomUUID()}!` },
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

async function setGlobalSwitch(page: Page, label: string, enabled: boolean) {
  const control = page.getByRole('switch', { name: label, exact: true })
  await expect(control).toBeVisible()
  if ((await control.getAttribute('aria-checked')) !== String(enabled)) {
    const response = page.waitForResponse(candidate => candidate.url().includes('/admin/entitlements/kill-switch/')
      && candidate.request().method() === 'PATCH')
    await control.click()
    expect((await response).status()).toBe(200)
  }
  await expect(control).toHaveAttribute('aria-checked', String(enabled))
}

async function openInterviewPrep(page: Page, resumeId: string, question: string) {
  await page.goto(`/workspace/${resumeId}/edit`)
  await expect(page.getByRole('button', { name: /^More$/i })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: /^More$/i }).click()
  await page.getByRole('menuitem', { name: 'Interview Prep', exact: true }).click()
  await expect(page.getByText(question, { exact: true })).toBeVisible({ timeout: 45_000 })
}

test('E03 global OFF/ON and E02 sibling OFF preserve saved prep, enforce owner scope, and recover', async ({ browser }, testInfo) => {
  const database = isolatedDatabase()
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5180'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://127.0.0.1:8030'
  const adminContext = await browser.newContext({ baseURL: frontend })
  const actorContext = await browser.newContext({ baseURL: frontend })
  const otherContext = await browser.newContext({ baseURL: frontend })
  const createdUsers: string[] = []
  let oldSwitchRows: Array<{ key: string; enabled: boolean; updated_at: Date }> = []
  let prepId: string | null = null

  try {
    const oldSwitches = await database.query(
      'SELECT key, enabled, updated_at FROM feature_flags WHERE key = ANY($1::text[])',
      [['e02', 'e03']],
    )
    expect(oldSwitches.rows.map(row => row.key).sort()).toEqual(['e02', 'e03'])
    oldSwitchRows = oldSwitches.rows

    const admin = await signup(adminContext, frontend, 'Synthetic E03 control admin'); createdUsers.push(admin.id)
    const actor = await signup(actorContext, frontend, 'Synthetic E03 owner'); createdUsers.push(actor.id)
    const other = await signup(otherContext, frontend, 'Synthetic E03 other owner'); createdUsers.push(other.id)
    await database.query("UPDATE users SET role = 'admin', email_verified = true WHERE id = $1", [admin.id])
    await database.query("UPDATE users SET role = 'user', email_verified = true WHERE id = ANY($1::uuid[])", [[actor.id, other.id]])

    const created = await actorContext.request.post(`${backend}/resumes/`, {
      headers: actor.headers,
      data: {
        title: 'Synthetic E03 saved prep source',
        latex_content: '\\documentclass{article}\\begin{document}Synthetic engineer.\\end{document}',
      },
    })
    expect(created.ok(), await created.text()).toBeTruthy()
    const resume = await created.json() as { id: string }
    const question = 'Describe a reliability improvement you led in a synthetic project.'
    const questions = [{
      category: 'behavioral',
      question,
      what_interviewer_assesses: 'Ownership and evidence',
      ideal_response_outline: ['Context', 'Action', 'Measured result'],
    }]
    prepId = randomUUID()
    await database.query(
      'INSERT INTO interview_prep (id, user_id, resume_id, questions, created_at, updated_at) '
      + 'VALUES ($1, $2, $3, $4::jsonb, now(), now())',
      [prepId, actor.id, resume.id, JSON.stringify(questions)],
    )

    const adminPage = await adminContext.newPage()
    const actorPage = await actorContext.newPage()
    await adminPage.goto('/admin')
    await expect(adminPage.getByRole('heading', { name: 'Capability inventory' })).toBeVisible({ timeout: 45_000 })

    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('e03')
    await setGlobalSwitch(adminPage, 'Text interview simulation global kill-switch', true)
    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('e02')
    await setGlobalSwitch(adminPage, 'Interview prep global kill-switch', true)
    await openInterviewPrep(actorPage, resume.id, question)
    await expect(actorPage.getByText('Text interview simulation', { exact: true })).toBeVisible()
    await expect(actorPage.getByRole('button', { name: /Start Coach session/ })).toBeVisible()

    // Ordinary second account cannot use the first owner's saved session.
    const payload = {
      mode: 'coach',
      answers: [{ question_index: 0, answer: 'I led a synthetic retry redesign and measured fewer failed jobs.' }],
    }
    const foreign = await otherContext.request.post(`${backend}/interview-prep/${prepId}/simulate`, {
      headers: other.headers,
      data: payload,
    })
    expect(foreign.status()).toBe(404)

    await actorPage.getByRole('button', { name: /Start Coach session/ }).click()
    await actorPage.getByRole('textbox', { name: 'Answer to question 1' }).fill(payload.answers[0].answer)
    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('e03')
    await setGlobalSwitch(adminPage, 'Text interview simulation global kill-switch', false)
    const e03OffSnapshot = actorPage.waitForResponse(response => new URL(response.url()).pathname === '/config/entitlements'
      && response.status() === 200)
    await actorPage.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await e03OffSnapshot
    await expect(actorPage.getByText('Coach mode', { exact: true }).locator('xpath=../../p')).toHaveText(question)
    await expect(actorPage.getByRole('button', { name: 'Finish session' })).toHaveCount(0)
    await expect(actorPage.getByRole('textbox', { name: 'Answer to question 1' })).toHaveValue(payload.answers[0].answer)
    await expect(actorPage.getByText(/Your current answer is still here/)).toBeVisible()
    const denied = await actorContext.request.post(`${backend}/interview-prep/${prepId}/simulate`, {
      headers: actor.headers,
      data: payload,
    })
    expect(denied.status()).toBe(403)
    expect(await denied.text()).toContain('e03')
    const readable = await actorContext.request.get(`${backend}/interview-prep/${prepId}`, { headers: actor.headers })
    expect(readable.status()).toBe(200)
    expect((await readable.json()).questions).toEqual(questions)

    // Re-enabled E03 restores the UI and API gate. With model keys deliberately
    // absent, the real API reaches its normal provider-unavailable boundary.
    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('e03')
    await setGlobalSwitch(adminPage, 'Text interview simulation global kill-switch', true)
    const e03OnSnapshot = actorPage.waitForResponse(response => new URL(response.url()).pathname === '/config/entitlements'
      && response.status() === 200)
    await actorPage.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await e03OnSnapshot
    await expect(actorPage.getByRole('button', { name: 'Finish session' })).toBeVisible()
    await expect(actorPage.getByRole('textbox', { name: 'Answer to question 1' })).toHaveValue(payload.answers[0].answer)
    const evaluation = actorPage.waitForResponse(response => new URL(response.url()).pathname === `/interview-prep/${prepId}/simulate`
      && response.request().method() === 'POST')
    await actorPage.getByRole('button', { name: 'Finish session' }).click()
    const unavailable = await evaluation
    expect(unavailable.status()).toBe(503)
    expect(await unavailable.text()).toContain('temporarily unavailable')
    await expect(actorPage.getByRole('alert')).toContainText('temporarily unavailable')
    await expect(actorPage.getByRole('textbox', { name: 'Answer to question 1' })).toHaveValue(payload.answers[0].answer)

    // E02 generation OFF does not block the existing E03 operation. It becomes
    // a provider-unavailable result (503), not a capability denial (403).
    await adminPage.getByRole('searchbox', { name: 'Search capabilities' }).fill('e02')
    await setGlobalSwitch(adminPage, 'Interview prep global kill-switch', false)
    const e02OffSnapshot = actorPage.waitForResponse(response => new URL(response.url()).pathname === '/config/entitlements'
      && response.status() === 200)
    await actorPage.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await e02OffSnapshot
    await expect(actorPage.getByRole('button', { name: 'Finish session' })).toBeVisible()
    await expect(actorPage.getByRole('button', { name: 'New', exact: true })).toHaveCount(0)
    const siblingAllowed = await actorContext.request.post(`${backend}/interview-prep/${prepId}/simulate`, {
      headers: actor.headers,
      data: payload,
    })
    expect(siblingAllowed.status()).toBe(503)
    expect(await siblingAllowed.text()).toContain('temporarily unavailable')

    const afterEvaluation = await actorContext.request.get(
      `${backend}/interview-prep/${prepId}`, { headers: actor.headers },
    )
    expect(afterEvaluation.status()).toBe(200)
    expect((await afterEvaluation.json()).questions).toEqual(questions)

    const deleted = await actorContext.request.delete(`${backend}/interview-prep/${prepId}`, { headers: actor.headers })
    expect(deleted.status()).toBe(204)
    const gone = await actorContext.request.get(`${backend}/interview-prep/${prepId}`, { headers: actor.headers })
    expect(gone.status()).toBe(404)
    await actorPage.screenshot({ path: testInfo.outputPath('e03-e02-off-saved-prep.png'), fullPage: true })
  } finally {
    for (const row of oldSwitchRows) {
      await database.query(
        'UPDATE feature_flags SET enabled = $1, updated_at = $2 WHERE key = $3',
        [row.enabled, row.updated_at, row.key],
      )
    }
    if (createdUsers.length) {
      await database.query('DELETE FROM interview_prep WHERE user_id = ANY($1::uuid[])', [createdUsers])
      await database.query('DELETE FROM resumes WHERE user_id = ANY($1::uuid[])', [createdUsers])
      await database.query('DELETE FROM session WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM account WHERE "userId" = ANY($1::text[])', [createdUsers])
      await database.query('DELETE FROM users WHERE id = ANY($1::uuid[])', [createdUsers])
    }
    await adminContext.close()
    await actorContext.close()
    await otherContext.close()
    await database.end()
  }
})
