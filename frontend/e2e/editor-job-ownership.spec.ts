import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174032'
const OWNER_A_SOURCE = '\\documentclass{article}\\begin{document}Owner A job source.\\end{document}'
const OWNER_B_SOURCE = '\\documentclass{article}\\begin{document}Owner B job source.\\end{document}'

async function mockJobEditor(page: Page, ownerRef: { current: string }): Promise<void> {
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: ownerRef.current,
      title: 'Job ownership fixture',
      latex_content: ownerRef.current === 'owner-a' ? OWNER_A_SOURCE : OWNER_B_SOURCE,
      document_type: 'resume',
      metadata: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route('**/dropbox/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"connected":false}' }))
  await page.route('**/github/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"private_sync":false}' }))
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"is_academic_cv":false,"detected_sections":[],"estimated_pages":1,"confidence":0}' }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}' }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())
}

async function switchOwner(page: Page, ownerRef: { current: string }, sessionCalls: () => number, owner: string): Promise<void> {
  ownerRef.current = owner
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(sessionCalls).toBeGreaterThan(1)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner B job source')
}

test.describe('editor job-start ownership', () => {
  test('does not attach a deferred compile response after an account switch', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'job ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let sessionCalls = 0
    let submitStarted = false
    let staleWsSubscriptions = 0
    let staleStateRequests = 0
    let staleResultRequests = 0
    let releaseSubmit!: () => void
    const submitGate = new Promise<void>((resolve) => { releaseSubmit = resolve })

    await page.route('**/api/auth/get-session', (route) => {
      sessionCalls += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { token: `token-${ownerRef.current}` }, user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current } }) })
    })
    await mockJobEditor(page, ownerRef)
    await page.route('**/ws/ticket', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"ticket":"job-ownership-ticket"}' }))
    await page.route((url) => url.pathname === '/jobs/stale-compile-job/state', (route) => {
      staleStateRequests += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"processing"}' })
    })
    await page.route((url) => url.pathname === '/jobs/stale-compile-job/result', (route) => {
      staleResultRequests += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"job_id":"stale-compile-job","success":true}' })
    })
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string) as { type?: string; job_id?: string }
        if (message.type === 'subscribe' && message.job_id === 'stale-compile-job') staleWsSubscriptions += 1
      })
    })
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      submitStarted = true
      await submitGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'stale-compile-job', message: 'Started' }) })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A job source')
    await page.getByRole('button', { name: 'Compile', exact: true }).click()
    await expect.poll(() => submitStarted).toBe(true)
    await switchOwner(page, ownerRef, () => sessionCalls, 'owner-b')

    const submitResponse = page.waitForResponse((response) => response.url().endsWith('/jobs/submit') && response.status() === 200)
    releaseSubmit()
    const response = await submitResponse
    await response.finished()
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
    }))
    await expect(page.getByText('Compilation started', { exact: true })).toHaveCount(0)
    expect(staleWsSubscriptions).toBe(0)
    expect(staleStateRequests).toBe(0)
    expect(staleResultRequests).toBe(0)
  })

  test('does not attach a deferred AI job response after an account switch', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'job ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let sessionCalls = 0
    let submitStarted = false
    let staleWsSubscriptions = 0
    let staleStateRequests = 0
    let staleResultRequests = 0
    let releaseSubmit!: () => void
    const submitGate = new Promise<void>((resolve) => { releaseSubmit = resolve })

    await page.route('**/api/auth/get-session', (route) => {
      sessionCalls += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { token: `token-${ownerRef.current}` }, user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current } }) })
    })
    await mockJobEditor(page, ownerRef)
    await page.route('**/ws/ticket', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"ticket":"job-ownership-ticket"}' }))
    await page.route((url) => url.pathname === '/jobs/stale-ai-job/state', (route) => {
      staleStateRequests += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"processing"}' })
    })
    await page.route((url) => url.pathname === '/jobs/stale-ai-job/result', (route) => {
      staleResultRequests += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{"job_id":"stale-ai-job","success":true}' })
    })
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string) as { type?: string; job_id?: string }
        if (message.type === 'subscribe' && message.job_id === 'stale-ai-job') staleWsSubscriptions += 1
      })
    })
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      submitStarted = true
      await submitGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'stale-ai-job', message: 'Started' }) })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'AI Optimize', exact: true })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A job source')
    await page.getByRole('button', { name: 'AI Optimize', exact: true }).click()
    await page.getByRole('button', { name: 'Optimize Resume', exact: true }).click()
    await expect.poll(() => submitStarted).toBe(true)
    await switchOwner(page, ownerRef, () => sessionCalls, 'owner-b')

    const submitResponse = page.waitForResponse((response) => response.url().endsWith('/jobs/submit') && response.status() === 200)
    releaseSubmit()
    const response = await submitResponse
    await response.finished()
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
    }))
    await expect(page.getByText('AI optimization started', { exact: true })).toHaveCount(0)
    expect(staleWsSubscriptions).toBe(0)
    expect(staleStateRequests).toBe(0)
    expect(staleResultRequests).toBe(0)
  })

  test('attaches a deferred compile response for the same owner', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'job ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let submitStarted = false
    let releaseSubmit!: () => void
    let wsSubscriptions = 0
    const submitGate = new Promise<void>((resolve) => { releaseSubmit = resolve })

    await page.route('**/api/auth/get-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session: { token: 'token-owner-a' }, user: { id: 'owner-a', email: 'owner-a@example.com', name: 'owner-a' } }),
    }))
    await mockJobEditor(page, ownerRef)
    await page.route('**/ws/ticket', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"ticket":"job-ownership-ticket"}' }))
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      submitStarted = true
      await submitGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'same-owner-compile-job', message: 'Started' }) })
    })
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string) as { type?: string; job_id?: string }
        if (message.type === 'subscribe' && message.job_id === 'same-owner-compile-job') {
          wsSubscriptions += 1
          ws.send(JSON.stringify({ type: 'subscribed', job_id: message.job_id, replayed_count: 0 }))
        }
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'Compile', exact: true }).click()
    await expect.poll(() => submitStarted).toBe(true)
    const submitResponse = page.waitForResponse((response) => response.url().endsWith('/jobs/submit') && response.status() === 200)
    releaseSubmit()
    const response = await submitResponse
    await response.finished()
    await expect(page.getByText('Compilation started', { exact: true })).toBeVisible()
    await expect.poll(() => wsSubscriptions).toBe(1)
  })

  test('does not subscribe a deferred deep-analysis job after an account switch', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'job ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let sessionCalls = 0
    let aiStarted = false
    let analysisStarted = false
    let releaseAnalysis!: () => void
    let staleSubscriptions = 0
    const analysisGate = new Promise<void>((resolve) => { releaseAnalysis = resolve })

    await page.route('**/api/auth/get-session', (route) => {
      sessionCalls += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session: { token: `token-${ownerRef.current}` }, user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current } }),
      })
    })
    await mockJobEditor(page, ownerRef)
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      aiStarted = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'deep-prerequisite-ai-job', message: 'Started' }) })
    })
    await page.route((url) => url.pathname === '/jobs/deep-prerequisite-ai-job/state', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"completed"}' }))
    await page.route((url) => url.pathname === '/jobs/deep-prerequisite-ai-job/result', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"job_id":"deep-prerequisite-ai-job","success":true,"result":{"job_id":"deep-prerequisite-ai-job","pdf_job_id":null,"ats_score":70,"changes_made":[]}}' }))
    await page.route((url) => url.pathname.endsWith('/ats/deep-analyze'), async (route) => {
      analysisStarted = true
      await analysisGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'stale-deep-analysis-job', uses_remaining: 2, message: 'Started' }) })
    })
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string) as { type?: string; job_id?: string }
        if (message.type !== 'subscribe' || !message.job_id) return
        if (message.job_id === 'stale-deep-analysis-job') staleSubscriptions += 1
        if (message.job_id === 'deep-prerequisite-ai-job') {
          ws.send(JSON.stringify({ type: 'subscribed', job_id: message.job_id, replayed_count: 0 }))
          ws.send(JSON.stringify({ type: 'event', stream_id: '9999999999999-0', event: { type: 'job.completed', event_id: 'deep-prerequisite-complete', job_id: message.job_id, timestamp: Date.now() / 1000, sequence: 1, pdf_job_id: null, ats_score: 70, ats_details: null, changes_made: [], compilation_time: 0, optimization_time: 0, tokens_used: 0, page_count: 1 } }))
        }
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'AI Optimize', exact: true })).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'AI Optimize', exact: true }).click()
    await page.getByRole('button', { name: 'Optimize Resume', exact: true }).click()
    await expect.poll(() => aiStarted).toBe(true)
    await expect(page.getByRole('button', { name: 'Deep AI Analysis', exact: true })).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'Deep AI Analysis', exact: true }).click()
    await expect.poll(() => analysisStarted).toBe(true)

    await switchOwner(page, ownerRef, () => sessionCalls, 'owner-b')
    const analysisResponse = page.waitForResponse((response) => response.url().endsWith('/ats/deep-analyze') && response.status() === 200)
    releaseAnalysis()
    const response = await analysisResponse
    await response.finished()
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
    }))

    expect(staleSubscriptions).toBe(0)
    await expect(page.getByRole('dialog', { name: 'Deep AI Analysis' })).toHaveCount(0)
  })

  test('does not refetch or cache a completed PDF under the next owner', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'job ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let sessionCalls = 0
    let submitCalls = 0
    let pdfDownloads = 0

    await page.addInitScript(() => {
      const originalCreateObjectURL = URL.createObjectURL.bind(URL)
      const calls = [] as string[]
      ;(window as typeof window & { __latexyObjectUrlCalls?: string[] }).__latexyObjectUrlCalls = calls
      URL.createObjectURL = (value: Blob | MediaSource) => {
        calls.push(value instanceof Blob ? value.type : 'media-source')
        return originalCreateObjectURL(value)
      }
    })
    await page.route('**/api/auth/get-session', (route) => {
      sessionCalls += 1
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: { token: `token-${ownerRef.current}` }, user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current } }) })
    })
    await mockJobEditor(page, ownerRef)
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      submitCalls += 1
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'completed-owner-a-job', message: 'Started' }) })
    })
    await page.route((url) => url.pathname === '/jobs/completed-owner-a-job/state', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"completed"}' }))
    await page.route((url) => url.pathname === '/jobs/completed-owner-a-job/result', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"job_id":"completed-owner-a-job","success":true,"result":{"job_id":"completed-owner-a-job","pdf_job_id":"completed-owner-a-pdf","ats_score":null,"changes_made":[]}}' }))
    await page.route((url) => url.pathname.endsWith('/download/completed-owner-a-pdf'), async (route) => {
      pdfDownloads += 1
      await route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.7\nowner-a\n%%EOF') })
    })
    await page.routeWebSocket('**/ws/jobs**', (ws) => {
      ws.onMessage((data) => {
        const message = JSON.parse(data as string) as { type?: string; job_id?: string }
        if (message.type !== 'subscribe' || message.job_id !== 'completed-owner-a-job') return
        ws.send(JSON.stringify({ type: 'subscribed', job_id: message.job_id, replayed_count: 0 }))
        ws.send(JSON.stringify({ type: 'event', stream_id: '9999999999999-0', event: { type: 'job.completed', event_id: 'completed-owner-a-event', job_id: message.job_id, timestamp: Date.now() / 1000, sequence: 1, pdf_job_id: 'completed-owner-a-pdf', ats_score: null, ats_details: null, changes_made: [], compilation_time: 0, optimization_time: 0, tokens_used: 0, page_count: 1 } }))
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'Compile', exact: true }).click()
    await expect.poll(() => submitCalls).toBe(1)
    await expect.poll(() => pdfDownloads).toBe(1)
    const pdfObjectUrlsBeforeSwitch = await page.evaluate(() => (window as typeof window & { __latexyObjectUrlCalls?: string[] }).__latexyObjectUrlCalls?.filter((type) => type === 'application/pdf').length ?? 0)
    expect(pdfObjectUrlsBeforeSwitch).toBe(1)

    await switchOwner(page, ownerRef, () => sessionCalls, 'owner-b')
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 100)))))

    expect(pdfDownloads).toBe(1)
    expect(await page.evaluate(() => (window as typeof window & { __latexyObjectUrlCalls?: string[] }).__latexyObjectUrlCalls?.filter((type) => type === 'application/pdf').length ?? 0)).toBe(pdfObjectUrlsBeforeSwitch)
    const ownerBKeys = await page.evaluate(async () => new Promise<string[]>((resolve) => {
      const request = indexedDB.open('latexy-offline', 3)
      request.onerror = () => resolve([])
      request.onsuccess = () => {
        const db = request.result
        if (!db.objectStoreNames.contains('compiled-pdfs')) { resolve([]); return }
        const read = db.transaction('compiled-pdfs', 'readonly').objectStore('compiled-pdfs').getAll()
        read.onerror = () => resolve([])
        read.onsuccess = () => resolve((read.result as Array<{ ownerId?: string; key?: string }>).filter((record) => record.ownerId === 'owner-b').map((record) => record.key ?? ''))
      }
    }))
    expect(ownerBKeys).toEqual([])
  })
})
