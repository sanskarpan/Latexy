/** Real auth, REST, PostgreSQL and relay; no mocked document or permission API. */
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Requires explicitly started isolated services')
test.setTimeout(360_000)

test('preserves recovery against empty relay, accepts clean peer state, and refreshes pre-sync title recovery', async ({ browser }, info) => {
  const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '13427'}`
  const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://localhost:19427'
  const connectionString = (process.env.DATABASE_URL ?? '').replace('postgresql+asyncpg:', 'postgresql:')
  const url = new URL(connectionString)
  if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) || !url.pathname.endsWith('_test') ||
    process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('Recovery acceptance requires isolated loopback test services without live providers')
  }
  const db = new Pool({ connectionString })
  const contexts: BrowserContext[] = []
  let userId: string | undefined
  let adminId: string | undefined
  let adminHeaders: { Authorization: string } | undefined
  let priorF04: boolean | undefined
  let releaseTicket: (() => void) | undefined
  const evidence: unknown[] = []
  const source = (page: Page) => page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue() as string | undefined)
  async function ready(page: Page) {
    await expect.poll(() => source(page), { timeout: 60_000 }).not.toBeUndefined()
  }
  async function readRecovery(page: Page, resumeId: string) {
    return page.evaluate(async ({ ownerId, resumeId }) => {
      const db = await new Promise<IDBDatabase>((resolve, reject) => {
        const req = indexedDB.open('latexy-offline', 3); req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error)
      })
      try {
        return await new Promise<any>((resolve, reject) => {
          const req = db.transaction('drafts').objectStore('drafts').get(JSON.stringify([ownerId, resumeId]))
          req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error)
        })
      } finally { db.close() }
    }, { ownerId: userId!, resumeId })
  }
  try {
    const context = await browser.newContext({ baseURL: frontend }); contexts.push(context)
    const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
      timeout: 120_000, headers: { Origin: frontend },
      data: { name: 'Synthetic recovery owner', email: `test_recovery_${randomUUID()}@example.test`, password: `Synthetic-${randomUUID()}!` },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
    const account = await response.json(); userId = account.user.id
    await db.query("UPDATE users SET email_verified=true, subscription_plan='pro', subscription_status='active' WHERE id=$1", [userId])
    const headers = { Authorization: `Bearer ${account.token}` }
    const ownerState = await context.storageState()
    const adminResponse = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
      timeout: 120_000, headers: { Origin: frontend },
      data: { name: 'Synthetic controls admin', email: `test_controls_${randomUUID()}@example.test`, password: `Synthetic-${randomUUID()}!` },
    })
    expect(adminResponse.ok(), await adminResponse.text()).toBeTruthy()
    const admin = await adminResponse.json(); adminId = admin.user.id
    adminHeaders = { Authorization: `Bearer ${admin.token}` }
    await db.query("UPDATE users SET role='admin', email_verified=true WHERE id=$1", [adminId])
    priorF04 = (await db.query("SELECT enabled FROM feature_flags WHERE key='f04'")).rows[0].enabled
    const enabled = await context.request.patch(`${backend}/admin/entitlements/kill-switch/f04`, { headers: adminHeaders, data: { enabled: true } })
    expect(enabled.status(), await enabled.text()).toBe(200)
    // Signup changed this context's cookies. Restore only the ordinary owner
    // session before any UI acceptance, never run editor as the controls admin.
    await context.clearCookies()
    await context.addCookies(ownerState.cookies)
    const state = await context.storageState()
    async function newPeer() {
      const peer = await browser.newContext({ baseURL: frontend, storageState: state }); contexts.push(peer)
      await peer.addInitScript(() => { localStorage.setItem('latexy_onboarding_completed', 'true'); localStorage.setItem('latexy_auto_compile', 'false') })
      return peer
    }
    await context.addInitScript(() => { localStorage.setItem('latexy_onboarding_completed', 'true'); localStorage.setItem('latexy_auto_compile', 'false') })
    async function create(title: string, source: string) {
      const result = await context.request.post(`${backend}/resumes/`, { headers, data: { title, latex_content: source } })
      expect(result.status(), await result.text()).toBe(201)
      return (await result.json()).id as string
    }
    async function open(peer: BrowserContext, id: string, waitForSync = true) {
      const page = await peer.newPage()
      let synced = false
      page.on('websocket', socket => {
        if (!new URL(socket.url()).pathname.startsWith('/ws/collab/')) return
        socket.on('framereceived', frame => {
          if (typeof frame.payload !== 'string' && frame.payload[0] === 0 && frame.payload[1] === 1) synced = true
        })
      })
      await page.addInitScript(resumeId => localStorage.setItem(`latexy_editor_mode_${resumeId}`, 'source'), id)
      await page.goto(`/workspace/${id}/edit`); await ready(page)
      if (waitForSync) await expect.poll(() => synced).toBe(true)
      return page
    }
    // SQL has advanced to P, while a persisted divergent L was based on A.
    const emptyId = await create('Recovery title', 'P')
    const recoveryPage = await context.newPage(); await recoveryPage.goto('/')
    await recoveryPage.evaluate(async ({ ownerId, resumeId }) => {
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const req = indexedDB.open('latexy-offline', 3)
        req.onupgradeneeded = () => {
          if (!req.result.objectStoreNames.contains('drafts')) {
            const store = req.result.createObjectStore('drafts', { keyPath: 'key' })
            store.createIndex('by-status', 'syncStatus'); store.createIndex('by-owner', 'ownerId')
          }
          if (!req.result.objectStoreNames.contains('compiled-pdfs')) {
            const store = req.result.createObjectStore('compiled-pdfs', { keyPath: 'key' })
            store.createIndex('by-owner', 'ownerId'); store.createIndex('by-accessed', 'lastAccessedAt')
          }
        }
        req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error)
      })
      await new Promise<void>((resolve, reject) => {
        const tx = database.transaction('drafts', 'readwrite')
        tx.objectStore('drafts').put({ key: JSON.stringify([ownerId, resumeId]), ownerId, resumeId,
          title: 'Recovered T1', latexContent: 'L', expectedLatexContent: 'A', collaborationPaused: true,
          syncStatus: 'conflict', savedAt: new Date() })
        tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error)
      }); database.close()
      localStorage.setItem(`latexy_editor_mode_${resumeId}`, 'source')
    }, { ownerId: userId!, resumeId: emptyId })
    await recoveryPage.goto(`/workspace/${emptyId}/edit`); await ready(recoveryPage)
    await expect(recoveryPage.getByRole('status').filter({ hasText: 'Live sync is paused' })).toBeVisible()
    expect(await source(recoveryPage)).toBe('L')
    const clean = await open(await newPeer(), emptyId)
    await expect.poll(() => source(clean)).toBe('P')
    await expect(clean.getByRole('status').filter({ hasText: 'Live sync is paused' })).toHaveCount(0)
    const attemptedSave = recoveryPage.waitForResponse(r => new URL(r.url()).pathname === `/resumes/${emptyId}` && r.request().method() === 'PUT')
    await recoveryPage.getByRole('button', { name: 'Save', exact: true }).click()
    expect((await attemptedSave).status()).toBe(409)
    expect((await db.query('SELECT latex_content FROM resumes WHERE id=$1', [emptyId])).rows[0].latex_content).toBe('P')
    expect(await source(clean)).toBe('P')
    evidence.push({ phase: 'empty-relay-recovery', recoveredSource: 'L', cleanPeerSource: 'P', staleSave: 409 })
    // Rejoining equal source must retain a title-only recovery until SQL
    // acknowledges T1. Hold autosave's 2500ms window while checking this race.
    await recoveryPage.clock.install(); await clean.clock.install()
    await recoveryPage.clock.pauseAt(new Date(Date.now() + 1000)); await clean.clock.pauseAt(new Date(Date.now() + 1000))
    const matchedSql = await context.request.put(`${backend}/resumes/${emptyId}`, {
      headers, data: { title: 'Recovery title', latex_content: 'L', expected_latex_content: 'P' },
    })
    expect(matchedSql.status(), await matchedSql.text()).toBe(200)
    await clean.evaluate(() => { const editor = (window as any).__latexyMonacoEditor; editor.executeEdits('acceptance', [{ range: editor.getModel().getFullModelRange(), text: 'L' }]) })
    for (let frame = 0; frame < 10; frame++) {
      await clean.clock.runFor(100); await recoveryPage.clock.runFor(100)
      if (await recoveryPage.getByRole('status').filter({ hasText: 'Live sync is paused' }).count() === 0) break
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    await expect(recoveryPage.getByRole('status').filter({ hasText: 'Live sync is paused' })).toHaveCount(0)
    expect((await readRecovery(recoveryPage, emptyId))?.title).toBe('Recovered T1')
    expect((await db.query('SELECT title FROM resumes WHERE id=$1', [emptyId])).rows[0].title).toBe('Recovery title')
    await recoveryPage.clock.resume(); await clean.clock.resume(); await clean.close()
    await recoveryPage.reload(); await ready(recoveryPage)
    await expect(recoveryPage.getByPlaceholder('Untitled', { exact: true })).toHaveValue('Recovered T1')
    await recoveryPage.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(async () => (await db.query('SELECT title FROM resumes WHERE id=$1', [emptyId])).rows[0].title).toBe('Recovered T1')
    await expect.poll(() => readRecovery(recoveryPage, emptyId)).toBeUndefined()
    evidence.push({ phase: 'title-only-rebind-reload', recoveredTitle: 'Recovered T1', clearedOnlyAfterAcknowledgment: true })
    await recoveryPage.close(); await clean.close()

    // Clean join must receive a peer's unsaved CRDT edits, not pause on stale SQL.
    const cleanId = await create('Clean peer test', 'A')
    const writer = await open(context, cleanId)
    await writer.clock.install(); await writer.clock.pauseAt(new Date(Date.now() + 1000))
    await writer.evaluate(() => { const editor = (window as any).__latexyMonacoEditor; editor.executeEdits('acceptance', [{ range: editor.getModel().getFullModelRange(), text: 'A + peer unsaved' }]) })
    await writer.clock.runFor(100)
    const joiner = await open(await newPeer(), cleanId)
    await expect.poll(() => source(joiner)).toBe('A + peer unsaved')
    await expect(joiner.getByRole('status').filter({ hasText: 'Live sync is paused' })).toHaveCount(0)
    await writer.clock.resume()
    await writer.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(async () => (await db.query('SELECT latex_content FROM resumes WHERE id=$1', [cleanId])).rows[0].latex_content).toBe('A + peer unsaved')
    await joiner.reload(); await ready(joiner)
    await expect.poll(() => source(joiner)).toBe('A + peer unsaved')
    evidence.push({ phase: 'clean-join-and-reload', source: 'A + peer unsaved', paused: false })
    await writer.close(); await joiner.close()

    // Keep the initial real ticket request pending while edits and title save.
    const titleId = await create('T0', 'Initial')
    const delayed = await newPeer()
    let ticketHeld = false
    const ticketGate = new Promise<void>(resolve => { releaseTicket = resolve })
    await delayed.route('**/ws/ticket', async route => {
      const payload = route.request().postDataJSON()
      if (payload?.purpose === 'collab' && payload?.resume_id === titleId) {
        ticketHeld = true; await ticketGate
      }
      await route.continue().catch(() => {})
    })
    const titlePage = await open(delayed, titleId, false)
    await expect.poll(() => ticketHeld).toBe(true)
    await titlePage.evaluate(() => { const editor = (window as any).__latexyMonacoEditor; editor.executeEdits('acceptance', [{ range: editor.getModel().getFullModelRange(), text: 'Local before sync' }]) })
    await titlePage.getByPlaceholder('Untitled', { exact: true }).fill('T1')
    await expect.poll(async () => (await db.query('SELECT title FROM resumes WHERE id=$1', [titleId])).rows[0].title).toBe('T1')
    await expect.poll(async () => (await readRecovery(titlePage, titleId))?.title).toBe('T1')
    await expect.poll(async () => (await readRecovery(titlePage, titleId))?.latexContent).toBe('Local before sync')
    await titlePage.reload(); await ready(titlePage)
    await expect(titlePage.getByPlaceholder('Untitled', { exact: true })).toHaveValue('T1')
    expect(await source(titlePage)).toBe('Local before sync')
    evidence.push({ phase: 'pre-sync-title-reload', title: 'T1', source: 'Local before sync', autosavedBeforeInitialTicket: true })
    releaseTicket?.(); releaseTicket = undefined
    await info.attach('initial-sync-evidence', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' })
  } finally {
    releaseTicket?.()
    if (adminHeaders && priorF04 !== undefined && contexts[0]) {
      await contexts[0].request.patch(`${backend}/admin/entitlements/kill-switch/f04`, { headers: adminHeaders, data: { enabled: priorF04 } })
    }
    for (const context of contexts) await context.close()
    if (userId) await db.query('DELETE FROM users WHERE id=$1', [userId])
    if (adminId) await db.query('DELETE FROM users WHERE id=$1', [adminId])
    await db.end()
  }
})
