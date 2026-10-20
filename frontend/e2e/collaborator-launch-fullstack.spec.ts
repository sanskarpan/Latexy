/** Real browser sessions + Next auth + API + disposable PostgreSQL/Redis. */
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { postSignupWithRateLimitRetry } from './helpers/signup-retry'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Requires explicitly started isolated services')
test.setTimeout(360_000)
test.use({ actionTimeout: 60_000 })

/** Freeze autosave scheduling without replacing Monaco's real performance entries. */
async function installAutosaveClock(page: Page) {
  await page.evaluate(() => {
    const methods = ['mark', 'measure', 'getEntries', 'getEntriesByName', 'getEntriesByType', 'clearMarks', 'clearMeasures'] as const
    ;(window as any).__acceptancePerformanceEntries = Object.fromEntries(
      methods.map(name => [name, performance[name].bind(performance)]),
    )
  })
  await page.clock.install()
  await page.evaluate(() => {
    // Playwright's fake performance entry methods return empty arrays. Monaco
    // reads the real measure after keyboard input; keep its original bound APIs.
    Object.assign(performance, (window as any).__acceptancePerformanceEntries)
    delete (window as any).__acceptancePerformanceEntries
  })
}

test('native entries remain real while scheduling remains frozen', async ({ page, browser }) => {
  test.setTimeout(15_000)
  // Counterfactual: the unmodified fake clock cannot supply Monaco's entries.
  // Playwright clocks are context-scoped, so isolate the counterfactual.
  const baselineContext = await browser.newContext()
  const baseline = await baselineContext.newPage()
  await baseline.clock.install()
  expect(await baseline.evaluate(() => {
    performance.mark('start'); performance.mark('end'); performance.measure('input', 'start', 'end')
    return performance.getEntriesByName('input').length
  })).toBe(0)
  await baselineContext.close()
  await page.goto('about:blank')
  await installAutosaveClock(page)
  await page.clock.pauseAt(new Date(Date.now() + 1000))
  await page.evaluate(() => {
    ;(window as any).saved = false
    performance.mark('typing/start')
    setTimeout(() => {
      performance.mark('typing/end')
      performance.measure('typing', 'typing/start', 'typing/end')
      ;(window as any).measured = performance.getEntriesByName('typing')[0].duration
    }, 50)
    setTimeout(() => { (window as any).saved = true }, 2500)
  })
  await page.clock.runFor(100)
  const before = await page.evaluate(() => ({ saved: (window as any).saved, measured: (window as any).measured, count: performance.getEntriesByName('typing').length }))
  expect(before.saved).toBe(false)
  expect(before.count).toBe(1)
  expect(before.measured).toBeGreaterThanOrEqual(0)
  expect(await page.evaluate(() => { try { performance.measure('invalid', 'does-not-exist'); return false } catch { return true } })).toBe(true)
  await page.clock.runFor(2400)
  expect(await page.evaluate(() => (window as any).saved)).toBe(true)
})

test('F04 role recovery, cross-account controls, live session revocation and recovery', async ({ browser }, info) => {
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '13427'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://localhost:19427'
  const connectionString = (process.env.DATABASE_URL ?? '').replace('postgresql+asyncpg:', 'postgresql:')
  const dbUrl = new URL(connectionString)
  if (!['localhost', '127.0.0.1', '::1'].includes(dbUrl.hostname) || !dbUrl.pathname.endsWith('_test')) {
    throw new Error('Collaborator acceptance requires loopback disposable *_test PostgreSQL')
  }
  if (process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('Synthetic local-only acceptance cannot use live providers')
  }
  const db = new Pool({ connectionString })
  const contexts: BrowserContext[] = []
  const users: string[] = []
  const evidence: Record<string, unknown>[] = []
  async function signup(name: string) {
    const context = await browser.newContext({ baseURL: frontend }); contexts.push(context)
    const email = `test_collab_${randomUUID()}@example.test`
    const options = {
      timeout: 120_000,
      headers: { Origin: frontend }, data: { name, email, password: `Synthetic-${randomUUID()}!` },
    }
    const response = await postSignupWithRateLimitRetry(context.request, `${frontend}/api/auth/sign-up/email`, options)
    expect(response.ok(), await response.text()).toBeTruthy()
    const body = await response.json() as { user: { id: string }; token: string }
    users.push(body.user.id)
    await db.query("UPDATE users SET email_verified=true, subscription_plan='pro', subscription_status='active' WHERE id=$1", [body.user.id])
    await context.addInitScript(() => {
      localStorage.setItem('latexy_onboarding_completed', 'true')
      localStorage.setItem('latexy_auto_compile', 'false')
    })
    return { context, id: body.user.id, email, headers: { Authorization: `Bearer ${body.token}` } }
  }
  function observeInitialSync(page: Page) {
    const state = { synced: false }
    page.on('websocket', socket => {
      if (!new URL(socket.url()).pathname.startsWith('/ws/collab/')) return
      socket.on('framereceived', frame => {
        if (typeof frame.payload === 'string') return
        // lib0 MSG_SYNC(0), SYNC_STEP2(1): this is the real provider socket.
        if (frame.payload[0] === 0 && frame.payload[1] === 1) state.synced = true
      })
    })
    return state
  }
  let prior: Array<{ key: string; enabled: boolean }> = []
  try {
    prior = (await db.query("SELECT key,enabled FROM feature_flags WHERE key IN ('f04','collaboration')")).rows
    expect(prior).toHaveLength(2)
    const owner = await signup('Synthetic collaborator owner')
    const actor = await signup('Synthetic invited collaborator')
    const stranger = await signup('Synthetic unrelated account')
    const admin = await signup('Synthetic controls admin')
    await db.query("UPDATE users SET role='admin' WHERE id=$1", [admin.id])
    async function toggle(enabled: boolean) {
      const response = await admin.context.request.patch(`${backend}/admin/entitlements/kill-switch/f04`, {
        headers: admin.headers, data: { enabled },
      })
      expect(response.status(), await response.text()).toBe(200)
    }
    await toggle(true)
    const created = await owner.context.request.post(`${backend}/resumes/`, {
      headers: owner.headers, data: { title: 'Synthetic collaborator launch acceptance', latex_content: 'Synthetic source identity' },
    })
    expect(created.status(), await created.text()).toBe(201)
    const resumeId = (await created.json()).id as string
    const persistedSource = async () => (await db.query('SELECT latex_content FROM resumes WHERE id=$1', [resumeId])).rows[0].latex_content as string
    const ownerPage = await owner.context.newPage()
    const ownerSync = observeInitialSync(ownerPage)
    await ownerPage.addInitScript(id => localStorage.setItem(`latexy_editor_mode_${id}`, 'source'), resumeId)
    await ownerPage.goto(`/workspace/${resumeId}/edit`)
    await ownerPage.getByTitle('Collaborators', { exact: true }).click()
    await expect(ownerPage.getByRole('heading', { name: 'Collaborators', exact: true })).toBeVisible()
    await ownerPage.getByPlaceholder('colleague@example.com').fill(actor.email)
    const invited = ownerPage.waitForResponse(r => r.url().endsWith(`/resumes/${resumeId}/collaborators`) && r.request().method() === 'POST')
    await ownerPage.getByRole('button', { name: 'Invite', exact: true }).click()
    expect((await invited).status()).toBe(201)
    const row = ownerPage.getByText(actor.email, { exact: true }).locator('xpath=../..')
    await expect(row.getByRole('combobox')).toHaveValue('editor')
    const route = `${backend}/resumes/${resumeId}/collaborators/${actor.id}`
    const foreign = await stranger.context.request.patch(route, { headers: stranger.headers, data: { role: 'viewer' } })
    expect(foreign.status()).toBe(404)
    const self = await actor.context.request.patch(route, { headers: actor.headers, data: { role: 'viewer' } })
    expect(self.status()).toBe(404)
    const allowedWrite = await actor.context.request.put(`${backend}/resumes/${resumeId}`, {
      headers: actor.headers, data: { latex_content: 'Synthetic source identity', expected_latex_content: 'Synthetic source identity' },
    })
    expect(allowedWrite.status(), await allowedWrite.text()).toBe(200)
    const actorPage = await actor.context.newPage()
    const actorSync = observeInitialSync(actorPage)
    await actorPage.addInitScript(id => localStorage.setItem(`latexy_editor_mode_${id}`, 'source'), resumeId)
    await actorPage.goto(`/workspace/${resumeId}/edit`)
    await refreshActorAccess()
    await expect(actorPage.getByTitle('Collaborators', { exact: true })).toBeVisible()
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
    async function refreshActorAccess() {
      const retry = actorPage.getByRole('button', { name: 'Retry feature access', exact: true })
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const snapshot = actorPage.waitForResponse(r => new URL(r.url()).pathname === '/config/entitlements' && r.status() === 200, { timeout: 30_000 })
        if (attempt && await retry.isVisible()) await retry.click()
        else await actorPage.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
        try {
          await snapshot
          await expect(retry).toHaveCount(0)
          return
        } catch (error) {
          if (attempt === 1) throw error
        }
      }
    }
    async function openActorSocket() {
      const ticketResponse = await actor.context.request.post(`${backend}/ws/ticket`, {
        headers: actor.headers, data: { purpose: 'collab', resume_id: resumeId },
      })
      expect(ticketResponse.status()).toBe(200)
      const { ticket } = await ticketResponse.json()
      await actorPage.evaluate(async url => {
        const socket = new WebSocket(url)
        socket.binaryType = 'arraybuffer'
        const observation = { code: 0, notices: [] as string[] }
        Object.assign(window, { acceptanceSocket: socket, acceptanceObservation: observation })
        socket.onclose = event => { observation.code = event.code }
        socket.onmessage = event => {
          if (event.data instanceof ArrayBuffer) observation.notices.push(new TextDecoder().decode(event.data))
        }
        await new Promise<void>((resolve, reject) => { socket.onopen = () => resolve(); socket.onerror = () => reject(new Error('Socket failed')) })
      }, `${backend.replace(/^http/, 'ws')}/ws/collab/${resumeId}?ticket=${encodeURIComponent(ticket)}`)
    }
    await openActorSocket()
    await expect.poll(() => ownerSync.synced && actorSync.synced).toBe(true)
    // Real peer awareness confirms async collaboration initialization has completed.
    await expect(ownerPage.getByText('Currently editing', { exact: true })).toBeVisible()
    await expect(ownerPage.getByText('Synthetic invited collaborator', { exact: true })).toHaveCount(2)
    const unsavedMarker = `UNSAVED_${randomUUID().replace(/-/g, '')}`
    // Freeze only the short edit/checkpoint window in both browser pages.
    // This holds their 2500ms autosave debounces while real keyboard/CRDT and
    // database operations continue. Resume before UI/socket polling.
    await installAutosaveClock(ownerPage)
    await installAutosaveClock(actorPage)
    await ownerPage.clock.pauseAt(new Date(Date.now() + 1000))
    await actorPage.clock.pauseAt(new Date(Date.now() + 1000))
    try {
      const codeInput = actorPage.locator('.monaco-editor .view-lines').first()
      await codeInput.click({ force: true, position: { x: 100, y: 10 } })
      await actorPage.keyboard.press('Control+End')
      await actorPage.keyboard.insertText(`\n% ${unsavedMarker}`)
      await actorPage.clock.runFor(100)
      await ownerPage.clock.runFor(100)
      await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
      // A received Yjs update needs a render frame even while autosave is held.
      // Bound virtual advancement to 1000ms, below the 2500ms debounce.
      for (let frame = 0; frame < 100; frame += 1) {
        await ownerPage.clock.runFor(10)
        if ((await ownerPage.locator('.monaco-editor .view-lines').innerText()).includes(unsavedMarker)) break
        await new Promise(resolve => setTimeout(resolve, 150))
      }
      await expect(ownerPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
      const beforeTransition = await persistedSource()
      expect(beforeTransition).toBe('Synthetic source identity')
      expect(beforeTransition).not.toContain(unsavedMarker)
      evidence.push({ phase: 'distinct-unsaved-pre-transition', browserMarkerPresent: true, storedMarkerPresent: false, autosaveDebounceHeldMs: 2500 })
      const firstChange = await owner.context.request.patch(route, { headers: owner.headers, data: { role: 'commenter' } })
      expect(firstChange.status()).toBe(200)
      // Both browser autosaves remain held through the committed role change.
      expect(await persistedSource()).toBe('Synthetic source identity')
      evidence.push({ phase: 'distinct-unsaved-at-role-commit', rolePatch: 200, storedMarkerPresent: false })
    } finally {
      await actorPage.clock.resume()
      await ownerPage.clock.resume()
    }
    // Role changes must close a currently authorized editor session with the
    // retryable role-change code, so reconnect can receive its new role.
    await expect.poll(() => actorPage.evaluate(() => (window as unknown as { acceptanceObservation: { code: number } }).acceptanceObservation.code)).toBe(4005)
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText('Synthetic source identity')
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
    await actorPage.screenshot({ path: info.outputPath('unsaved-draft-after-downgrade.png'), fullPage: true })
    const firstRecovery = await owner.context.request.patch(route, { headers: owner.headers, data: { role: 'editor' } })
    expect(firstRecovery.status()).toBe(200)
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText('Synthetic source identity')
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
    // Refresh the owner panel after the independent session role changes.
    await ownerPage.keyboard.press('Escape')
    await ownerPage.getByTitle('Collaborators', { exact: true }).click()
    await expect(row.getByRole('combobox')).toHaveValue('editor')
    evidence.push({ phase: 'live-editor-role-change', closeCode: 4005 })
    await openActorSocket()
    expect(await actorPage.evaluate(() => (window as unknown as { acceptanceSocket: WebSocket }).acceptanceSocket.readyState)).toBe(1)
    await toggle(false)
    // Query-awareness is protocol frame 3 and carries no document update.
    // The established receive loop rechecks F04 before processing any frame.
    await actorPage.evaluate(() => {
      const socket = (window as unknown as { acceptanceSocket: WebSocket }).acceptanceSocket
      if (socket.readyState === WebSocket.OPEN) socket.send(new Uint8Array([3]))
    })
    await expect.poll(() => actorPage.evaluate(() => (window as unknown as { acceptanceObservation: { code: number } }).acceptanceObservation.code), { timeout: 20_000 }).toBe(4003)
    expect((await db.query('SELECT role FROM resume_collaborators WHERE resume_id=$1 AND user_id=$2', [resumeId, actor.id])).rows[0].role).toBe('editor')
    const forbiddenOffMarker = `FORBIDDEN_F04_${randomUUID()}`
    const preDeniedSource = await persistedSource()
    const disabledEditorWrite = await actor.context.request.put(`${backend}/resumes/${resumeId}`, {
      headers: actor.headers, data: { latex_content: `${preDeniedSource}\n% ${forbiddenOffMarker}`, expected_latex_content: preDeniedSource },
    })
    expect(disabledEditorWrite.status()).toBe(403)
    expect(await persistedSource()).not.toContain(forbiddenOffMarker)
    evidence.push({ phase: 'active-editor-socket-f04-off', observationSocketOpenBeforeDisable: true, closeCode: 4003, currentStoredRole: 'editor', restWrite: 403, forbiddenMarkerPersisted: false })
    const refreshed = ownerPage.waitForResponse(r => new URL(r.url()).pathname === '/config/entitlements' && r.status() === 200)
    await ownerPage.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await refreshActorAccess()
    await refreshed
    await expect(ownerPage.getByPlaceholder('colleague@example.com')).toHaveCount(0)
    await expect(ownerPage.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
    await expect(row.getByRole('combobox')).toBeEnabled()
    const downgraded = ownerPage.waitForResponse(r => r.url().endsWith(`/collaborators/${actor.id}`) && r.request().method() === 'PATCH')
    await row.getByRole('combobox').selectOption('commenter')
    expect((await downgraded).status()).toBe(200)
    await expect(row.getByRole('combobox')).toHaveValue('commenter')
    await row.getByRole('combobox').selectOption('viewer')
    await expect(row.getByRole('combobox')).toHaveValue('viewer')
    await expect(row.getByRole('combobox')).toBeDisabled()
    const deniedPromotion = await owner.context.request.patch(route, { headers: owner.headers, data: { role: 'commenter' } })
    expect(deniedPromotion.status()).toBe(403)
    expect(await deniedPromotion.text()).toContain('f04')
    const deniedInvite = await owner.context.request.post(`${backend}/resumes/${resumeId}/collaborators`, {
      headers: owner.headers, data: { email: stranger.email, role: 'viewer' },
    })
    expect(deniedInvite.status()).toBe(403)
    const deniedWrite = await actor.context.request.put(`${backend}/resumes/${resumeId}`, {
      headers: actor.headers, data: { latex_content: 'Forbidden viewer source', expected_latex_content: 'Synthetic source identity' },
    })
    expect(deniedWrite.status()).toBe(403)
    evidence.push({ phase: 'off', crossAccount: foreign.status(), selfRoleChange: self.status(), downgrade: 200, promotion: deniedPromotion.status(), invite: deniedInvite.status(), write: deniedWrite.status() })
    await ownerPage.screenshot({ path: info.outputPath('f04-off-owner-recovery.png'), fullPage: true })
    await toggle(true)
    await ownerPage.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await refreshActorAccess()
    await expect(ownerPage.getByPlaceholder('colleague@example.com')).toBeVisible()
    await expect(row.getByRole('combobox')).toBeEnabled()
    await openActorSocket()
    await expect.poll(() => actorPage.evaluate(() => (window as unknown as { acceptanceObservation: { notices: string[] } }).acceptanceObservation.notices.join(' '))).toContain('read_only')
    const viewerWrite = await actor.context.request.put(`${backend}/resumes/${resumeId}`, {
      headers: actor.headers, data: { latex_content: 'Forbidden viewer with enabled F04', expected_latex_content: 'Synthetic source identity' },
    })
    expect(viewerWrite.status()).toBe(403)
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await row.getByRole('combobox').selectOption('editor')
    await expect(row.getByRole('combobox')).toHaveValue('editor')
    await expect.poll(() => actorPage.evaluate(() => (window as unknown as { acceptanceObservation: { code: number } }).acceptanceObservation.code)).toBe(4005)
    await openActorSocket()
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
    const recoveredSource = await persistedSource()
    const recoveredWrite = await actor.context.request.put(`${backend}/resumes/${resumeId}`, {
      headers: actor.headers, data: { latex_content: recoveredSource, expected_latex_content: recoveredSource },
    })
    expect(recoveredWrite.status(), await recoveredWrite.text()).toBe(200)
    await row.getByTitle('Remove collaborator').click()
    await expect(ownerPage.getByText(actor.email, { exact: true })).toHaveCount(0)
    await expect.poll(() => actorPage.evaluate(() => (window as unknown as { acceptanceObservation: { code: number } }).acceptanceObservation.code)).toBe(4003)
    await expect(actorPage.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
    await expect(actorPage.locator('.monaco-editor .view-lines')).toContainText(unsavedMarker)
    await actorPage.screenshot({ path: info.outputPath('removed-collaborator-save-disabled.png'), fullPage: true })
    const revokedRead = await actor.context.request.get(`${backend}/resumes/${resumeId}`, { headers: actor.headers })
    expect(revokedRead.status()).toBe(404)
    evidence.push({ phase: 'recovered-and-revoked', write: recoveredWrite.status(), revokedRead: revokedRead.status(), promotionSocketClose: 4005, removalSocketClose: 4003, visibleSaveDisabled: true, distinctDraftPreserved: true })
    await info.attach('acceptance-evidence', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' })
  } finally {
    for (const context of contexts) await context.close()
    for (const row of prior) await db.query('UPDATE feature_flags SET enabled=$2 WHERE key=$1', [row.key, row.enabled])
    if (users.length) await db.query('DELETE FROM users WHERE id=ANY($1::uuid[])', [users])
    await db.end()
  }
})
