import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeef'
const SHORT_SOURCE = '\\documentclass{article}\\begin{document}Offline editor fixture.\\end{document}'
// Keep the fixture below the editor's auto-compile threshold so the test owns
// the sole job submission and can deterministically gate its PDF response.
const LONG_SOURCE = SHORT_SOURCE

async function mockEditor(page: Page, owner: string, source: string): Promise<void> {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session: { token: `token-${owner}` }, user: { id: owner, email: `${owner}@example.com`, name: owner } }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: RESUME_ID, user_id: owner, title: 'Offline editor fixture', latex_content: source, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', document_type: 'resume', metadata: {} }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname.includes('/checkpoints') || url.pathname.includes('/academic-cv-report') || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/jobs/submit', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'old-owner-job', message: 'Started' }) }))
  await page.route('**/ws/**', (route) => route.abort())
}

async function seedPdf(page: Page, owner: string): Promise<void> {
  await page.evaluate(async ({ owner, resumeId }) => {
    const request = indexedDB.open('latexy-offline', 3)
    await new Promise<void>((resolve, reject) => {
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains('drafts')) {
          const drafts = db.createObjectStore('drafts', { keyPath: 'key' })
          drafts.createIndex('by-status', 'syncStatus')
          drafts.createIndex('by-owner', 'ownerId')
        }
        if (!db.objectStoreNames.contains('compiled-pdfs')) {
          const pdfs = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
          pdfs.createIndex('by-owner', 'ownerId')
          pdfs.createIndex('by-accessed', 'lastAccessedAt')
        }
      }
      request.onsuccess = () => {
        const db = request.result
        const tx = db.transaction('compiled-pdfs', 'readwrite')
        tx.objectStore('compiled-pdfs').put({ key: JSON.stringify([owner, resumeId]), ownerId: owner, resumeId, title: 'Offline editor fixture', pdf: new Blob(['%PDF-1.4 delayed fixture'], { type: 'application/pdf' }), byteSize: 25, savedAt: Date.now(), lastAccessedAt: Date.now() })
        tx.oncomplete = () => resolve()
        tx.onerror = () => reject(tx.error)
      }
      request.onerror = () => reject(request.error)
    })
    localStorage.setItem('latexy:last-authenticated-owner', owner)
  }, { owner, resumeId: RESUME_ID })
}

test.describe('editor offline PDF ownership', () => {
  test('drops a delayed offline read after client-side editor unmount', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'editor ownership proof runs against the production editor bundle')
    await page.addInitScript(() => {
      const originalText = Blob.prototype.text
      const state = window as Window & {
        __offlinePdfReadStarted?: boolean
        __offlinePdfReadFinished?: boolean
        __releaseOfflinePdfRead?: () => void
      }
      state.__offlinePdfReadStarted = false
      state.__offlinePdfReadFinished = false
      let release!: () => void
      const gate = new Promise<void>((resolve) => { release = resolve })
      state.__releaseOfflinePdfRead = release
      Blob.prototype.text = async function () {
        state.__offlinePdfReadStarted = true
        await gate
        const result = await originalText.call(this)
        state.__offlinePdfReadFinished = true
        return result
      }
    })
    await mockEditor(page, 'owner-a', SHORT_SOURCE)
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await seedPdf(page, 'owner-a')
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
      window.dispatchEvent(new Event('offline'))
    })
    await expect.poll(() => page.evaluate(() => Boolean((window as Window & { __offlinePdfReadStarted?: boolean }).__offlinePdfReadStarted))).toBe(true)
    await page.evaluate(() => {
      const original = URL.createObjectURL
      sessionStorage.setItem('offline-pdf-object-kinds', '[]')
      URL.createObjectURL = (blob) => {
        const objects = JSON.parse(sessionStorage.getItem('offline-pdf-object-kinds') ?? '[]') as Array<{ type: string; size: number }>
        objects.push({ type: (blob as Blob).type, size: (blob as Blob).size })
        sessionStorage.setItem('offline-pdf-object-kinds', JSON.stringify(objects))
        return original.call(URL, blob)
      }
    })
    await context.setOffline(false)
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
      window.dispatchEvent(new Event('online'))
    })
    const navigation = page.waitForURL(new RegExp(`/workspace/${RESUME_ID}/cover-letter$`))
    await page.getByRole('link', { name: 'Cover Letter', exact: true }).evaluate((element) => (element as HTMLElement).click())
    await navigation
    await page.evaluate(() => (window as Window & { __releaseOfflinePdfRead?: () => void }).__releaseOfflinePdfRead?.())
    await expect.poll(() => page.evaluate(() => Boolean((window as Window & { __offlinePdfReadFinished?: boolean }).__offlinePdfReadFinished))).toBe(true)
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
    }))
    expect(await page.evaluate(() => (JSON.parse(sessionStorage.getItem('offline-pdf-object-kinds') ?? '[]') as Array<{ type: string; size: number }>).filter((object) => object.type === 'application/pdf'))).toEqual([])
  })

  test('drops a delayed completed-job PDF after the authenticated owner switches', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'editor ownership proof runs against the production editor bundle')
    let owner = 'owner-a'
    let sessionCalls = 0
    const sessionOwners: string[] = []
    let submitCount = 0
    let releaseDownload!: () => void
    const downloadGate = new Promise<void>((resolve) => { releaseDownload = resolve })
    await page.route('**/api/auth/get-session', (route) => {
      // The second response is the client-side account refresh triggered by
      // Better Auth's broadcast channel; no document replacement is involved.
      sessionCalls += 1
      sessionOwners.push(owner)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session: { token: `token-${owner}` }, user: { id: owner, email: `${owner}@example.com`, name: owner } }),
      })
    })
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: RESUME_ID, user_id: owner, title: 'Owner switch fixture', latex_content: LONG_SOURCE, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', document_type: 'resume', metadata: {} }),
    }))
    await page.route((url) => url.pathname === '/jobs/submit', (route) => {
      submitCount += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: submitCount === 1 ? 'old-owner-job' : 'new-owner-job', message: 'Started' }) })
    })
    await page.route((url) => url.pathname === '/ws/ticket', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ticket: 'owner-switch-test-ticket' }),
    }))
    await page.route((url) => url.pathname === '/download/old-owner-job', async (route) => {
      await downloadGate
      return route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.4 stale job') })
    })
    await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname.includes('/checkpoints') || url.pathname.includes('/academic-cv-report') || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string)
        if (message.type === 'ping') ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
        if (message.type === 'subscribe' && message.job_id === 'old-owner-job') {
          ws.send(JSON.stringify({ type: 'subscribed', job_id: message.job_id, replayed_count: 0 }))
          setTimeout(() => ws.send(JSON.stringify({ type: 'event', event: { event_id: 'old-owner-complete', job_id: 'old-owner-job', timestamp: Date.now() / 1000, sequence: 1, type: 'job.completed', pdf_job_id: 'old-owner-job', page_count: 1 } })), 50)
        }
      })
    })
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await page.evaluate(() => {
      const original = URL.createObjectURL
      ;(window as Window & { __offlinePdfObjectUrls?: number }).__offlinePdfObjectUrls = 0
      ;(window as Window & { __offlinePdfObjectKinds?: Array<{ type: string; size: number }> }).__offlinePdfObjectKinds = []
      URL.createObjectURL = (blob) => {
        ;(window as Window & { __offlinePdfObjectUrls?: number }).__offlinePdfObjectUrls = ((window as Window & { __offlinePdfObjectUrls?: number }).__offlinePdfObjectUrls ?? 0) + 1
        ;(window as Window & { __offlinePdfObjectKinds?: Array<{ type: string; size: number }> }).__offlinePdfObjectKinds?.push({ type: (blob as Blob).type, size: (blob as Blob).size })
        return original.call(URL, blob)
      }
    })
    const downloadRequest = page.waitForRequest('**/download/old-owner-job')
    await page.getByRole('button', { name: 'Compile', exact: true }).click()
    await downloadRequest
    owner = 'owner-b'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy:last-authenticated-owner'))).toBe('owner-b')
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    expect(sessionOwners).toContain('owner-b')
    releaseDownload()
    await page.waitForTimeout(500)
    expect(await page.evaluate(() => ((window as Window & { __offlinePdfObjectKinds?: Array<{ type: string; size: number }> }).__offlinePdfObjectKinds ?? []).filter((object) => object.type === 'application/pdf'))).toEqual([])
  })

  test('keeps a deferred same-owner PDF fetch alive across a title refresh', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'editor ownership proof runs against the production editor bundle')
    let submitCount = 0
    let downloadRequests = 0
    let releaseDownload!: () => void
    const downloadGate = new Promise<void>((resolve) => { releaseDownload = resolve })
    await page.route('**/api/auth/get-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session: { token: 'token-owner-a' }, user: { id: 'owner-a', email: 'owner-a@example.com', name: 'owner-a' } }),
    }))
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: RESUME_ID, user_id: 'owner-a', title: 'Same-owner fixture', latex_content: SHORT_SOURCE, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', document_type: 'resume', metadata: {} }),
    }))
    await page.route((url) => url.pathname === '/jobs/submit', (route) => {
      submitCount += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'same-owner-job', message: 'Started' }) })
    })
    await page.route((url) => url.pathname === '/ws/ticket', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ticket: 'same-owner-test-ticket' }),
    }))
    await page.route((url) => url.pathname === '/download/same-owner-job', async (route) => {
      downloadRequests += 1
      await downloadGate
      return route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.4 same owner') })
    })
    await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname.includes('/checkpoints') || url.pathname.includes('/academic-cv-report') || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string)
        if (message.type === 'ping') ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
        if (message.type === 'subscribe' && message.job_id === 'same-owner-job') {
          ws.send(JSON.stringify({ type: 'subscribed', job_id: message.job_id, replayed_count: 0 }))
          setTimeout(() => ws.send(JSON.stringify({ type: 'event', event: { event_id: 'same-owner-complete', job_id: 'same-owner-job', timestamp: Date.now() / 1000, sequence: 1, type: 'job.completed', pdf_job_id: 'same-owner-job', page_count: 1 } })), 50)
        }
      })
    })
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await page.evaluate(() => {
      const original = URL.createObjectURL
      ;(window as Window & { __offlinePdfObjectKinds?: Array<{ type: string; size: number }> }).__offlinePdfObjectKinds = []
      URL.createObjectURL = (blob) => {
        ;(window as Window & { __offlinePdfObjectKinds?: Array<{ type: string; size: number }> }).__offlinePdfObjectKinds?.push({ type: (blob as Blob).type, size: (blob as Blob).size })
        return original.call(URL, blob)
      }
    })
    const downloadRequest = page.waitForRequest('**/download/same-owner-job')
    await page.getByRole('button', { name: 'Compile', exact: true }).click()
    await downloadRequest
    await page.locator('input[placeholder="Untitled"]').fill('Updated same-owner title')
    releaseDownload()
    await expect.poll(async () => {
      const fallback = await page.getByRole('button', { name: 'Download to view', exact: true }).count()
      const renderedPages = await page.locator('[data-page-number]').count()
      return fallback + renderedPages
    }, { timeout: 12_000 }).toBeGreaterThan(0)
    expect(submitCount).toBe(1)
    expect(downloadRequests).toBe(1)
    expect(await page.evaluate(() => ((window as Window & { __offlinePdfObjectKinds?: Array<{ type: string; size: number }> }).__offlinePdfObjectKinds ?? []).filter((object) => object.type === 'application/pdf'))).toHaveLength(1)
  })
})
