import { expect, test, type Page, type Route } from '@playwright/test'

const RESUME_ID = '72a54ec4-858c-48e0-a6f8-2209293d9897'

async function prepareReconnect(
  page: Page,
  legacy = false,
  onSubmit?: (route: Route, submissionIndex: number) => Promise<void>,
  controlOnline = false,
): Promise<string[]> {
  const submissions: string[] = []
  if (controlOnline) {
    await page.addInitScript(() => {
      let online = true
      Object.defineProperty(navigator, 'onLine', {
        configurable: true,
        get: () => online,
      })
      ;(window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline = (value) => {
        online = value
        window.dispatchEvent(new Event(value ? 'online' : 'offline'))
      }
    })
  }
  await page.addInitScript(({ legacy, resumeId }) => {
    const state = window as Window & { __queueSeed?: Promise<void> }
    state.__queueSeed = new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('latexy-compile-queue', legacy ? 1 : 2)
      request.onupgradeneeded = () => {
        const store = request.result.createObjectStore('compile-queue', { keyPath: 'id' })
        if (!legacy) store.createIndex('by-owner', 'ownerId')
        store.put({
          id: 'private-a', ...(legacy ? {} : { ownerId: 'owner-a' }),
          resumeId, latexContent: 'Private account A queue source', queuedAt: new Date(),
        })
        if (!legacy) store.put({
          id: 'private-b', ownerId: 'owner-b', resumeId,
          latexContent: 'Current account B queue source', queuedAt: new Date(),
        })
      }
      request.onsuccess = () => { request.result.close(); resolve() }
      request.onerror = () => reject(request.error)
    })
  }, { legacy, resumeId: RESUME_ID })
  await page.route('**/api/auth/get-session', async route => {
    await page.evaluate(() => (window as Window & { __queueSeed?: Promise<void> }).__queueSeed)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      session: { token: 'reconnect-owner-b-token' }, user: { id: 'owner-b', name: 'Owner B', email: 'owner-b@example.invalid' },
    }) })
  })
  await page.route(url => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      id: RESUME_ID, user_id: 'owner-b', title: 'Reconnect fixture',
      latex_content: '\\documentclass{article}\\begin{document}Current owner B.\\end{document}',
      metadata: {}, document_type: 'resume', created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-04T00:00:00Z',
    }),
  }))
  await page.route(url => url.pathname === '/jobs/submit', async route => {
    const submissionIndex = submissions.push(route.request().postDataJSON().latex_content as string) - 1
    if (onSubmit) {
      await onSubmit(route, submissionIndex)
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'owned-reconnect-job', message: 'Started' }) })
  })
  await page.route(url => url.pathname.includes('/checkpoints'), route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(url => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route(url => url.pathname === '/ats/quick-score' || url.pathname === '/config/feature-flags' || url.pathname.startsWith('/analytics') || url.pathname.endsWith('/status') || url.pathname === '/me', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close())
  return submissions
}

async function prepareDraftReconnect(page: Page, onUpdate: (route: Route, updateIndex: number) => Promise<void>): Promise<string[]> {
  const updates: string[] = []
  await page.addInitScript(({ resumeId }) => {
    const state = window as Window & { __draftSeed?: Promise<void> }
    state.__draftSeed = new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('latexy-offline', 3)
      request.onupgradeneeded = () => {
        const db = request.result
        const drafts = db.objectStoreNames.contains('drafts')
          ? request.transaction!.objectStore('drafts')
          : db.createObjectStore('drafts', { keyPath: 'key' })
        if (!drafts.indexNames.contains('by-status')) drafts.createIndex('by-status', 'syncStatus')
        if (!drafts.indexNames.contains('by-owner')) drafts.createIndex('by-owner', 'ownerId')
        if (!db.objectStoreNames.contains('compiled-pdfs')) {
          const pdfs = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
          pdfs.createIndex('by-owner', 'ownerId')
          pdfs.createIndex('by-accessed', 'lastAccessedAt')
        }
        drafts.put({
          key: JSON.stringify(['owner-b', resumeId]), ownerId: 'owner-b', resumeId,
          title: 'Draft B', latexContent: 'Draft B local source',
          expectedLatexContent: 'Server source before draft', savedAt: new Date(1), syncStatus: 'pending',
        })
      }
      request.onsuccess = () => { request.result.close(); resolve() }
      request.onerror = () => reject(request.error)
    })
  }, { resumeId: RESUME_ID })
  await page.addInitScript(() => {
    let online = true
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online })
    ;(window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline = (value) => {
      online = value
      window.dispatchEvent(new Event(value ? 'online' : 'offline'))
    }
  })
  await page.route('**/api/auth/get-session', async route => {
    await page.evaluate(() => (window as Window & { __draftSeed?: Promise<void> }).__draftSeed)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      session: { token: 'reconnect-owner-b-token' }, user: { id: 'owner-b', name: 'Owner B', email: 'owner-b@example.invalid' },
    }) })
  })
  await page.route(url => url.pathname === `/resumes/${RESUME_ID}`, async route => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify({
          id: RESUME_ID, user_id: 'owner-b', title: 'Reconnect fixture', latex_content: 'Server source before draft',
          metadata: {}, document_type: 'resume', created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-04T00:00:00Z',
        }),
      })
      return
    }
    updates.push(route.request().postDataJSON().latex_content as string)
    await onUpdate(route, updates.length - 1)
  })
  await page.route(url => url.pathname === '/jobs/submit', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'unused-job', message: 'Started' }) }))
  await page.route(url => url.pathname.includes('/checkpoints'), route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(url => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route(url => url.pathname === '/ats/quick-score' || url.pathname === '/config/feature-flags' || url.pathname.startsWith('/analytics') || url.pathname.endsWith('/status') || url.pathname === '/me', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close())
  return updates
}

async function offlineDraftRows(page: Page) {
  return page.evaluate(() => new Promise<Array<{ key: string; ownerId: string; resumeId: string; title: string; latexContent: string; savedAt: Date }>>((resolve, reject) => {
    const request = indexedDB.open('latexy-offline')
    request.onsuccess = () => {
      const db = request.result
      const tx = db.transaction('drafts', 'readonly')
      const read = tx.objectStore('drafts').getAll()
      tx.oncomplete = () => { resolve(read.result); db.close() }
      tx.onerror = () => { reject(tx.error); db.close() }
    }
    request.onerror = () => reject(request.error)
  }))
}

async function queueRows(page: Page) {
  return page.evaluate(() => new Promise<{ version: number; rows: Array<{ id: string; ownerId?: string; latexContent: string }> }>((resolve, reject) => {
    const request = indexedDB.open('latexy-compile-queue')
    request.onsuccess = () => {
      const db = request.result
      const tx = db.transaction('compile-queue', 'readonly')
      const read = tx.objectStore('compile-queue').getAll()
      tx.oncomplete = () => { resolve({ version: db.version, rows: read.result }); db.close() }
      tx.onerror = () => { reject(tx.error); db.close() }
    }
    request.onerror = () => reject(request.error)
  }))
}

test('reconnect submits only the current account’s queued source', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the production editor bundle')
  const submissions = await prepareReconnect(page)
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => submissions).toEqual(['Current account B queue source'])
  await expect.poll(async () => (await queueRows(page)).rows.map(row => row.id)).toEqual(['private-a'])
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))
  expect(submissions).toEqual(['Current account B queue source'])
  expect((await queueRows(page)).rows[0]).toMatchObject({ ownerId: 'owner-a', latexContent: 'Private account A queue source' })
})

test('reconnect upgrades but never assigns or submits legacy unowned work', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the production editor bundle')
  const submissions = await prepareReconnect(page, true)
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect.poll(async () => (await queueRows(page)).version).toBe(2)
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))
  expect(submissions).toEqual([])
  expect((await queueRows(page)).rows).toEqual([expect.objectContaining({ id: 'private-a', latexContent: 'Private account A queue source' })])
})

test('reconnect does not submit the same queued compile twice across a connectivity flap', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the production editor bundle')

  let firstRequestStarted!: () => void
  const firstStarted = new Promise<void>(resolve => { firstRequestStarted = resolve })
  let secondRequestStarted!: () => void
  const secondStarted = new Promise<void>(resolve => { secondRequestStarted = resolve })
  let releaseFirst!: () => void
  const firstResponse = new Promise<void>(resolve => { releaseFirst = resolve })
  const requestStartedAt: number[] = []
  const submissions = await prepareReconnect(page, false, async (route, submissionIndex) => {
    requestStartedAt.push(Date.now())
    if (submissionIndex === 0) {
      firstRequestStarted()
      await firstResponse
    } else {
      secondRequestStarted()
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: `owned-reconnect-job-${submissionIndex}`, message: 'Started' }) })
  }, true)

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor', { exact: true })).toBeVisible({ timeout: 30_000 })
  await firstStarted

  await page.evaluate(() => (window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline?.(false))
  await expect(page.getByText(/You're offline/)).toBeVisible({ timeout: 5_000 })
  await page.evaluate(() => (window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline?.(true))
  await expect(page.getByText(/You're offline/)).toBeHidden({ timeout: 5_000 })

  let duplicateObserved = false
  try {
    await Promise.race([
      secondStarted.then(() => { duplicateObserved = true }),
      page.waitForTimeout(1_500),
    ])
    console.log(`reconnect flap POST count=${submissions.length}, first-to-second-ms=${requestStartedAt[1] === undefined ? 'none' : requestStartedAt[1] - requestStartedAt[0]}`)
    expect(duplicateObserved).toBe(false)
  } finally {
    releaseFirst()
  }
  await expect.poll(async () => (await queueRows(page)).rows.map(row => row.id)).toEqual(['private-a'])
  expect(submissions).toEqual(['Current account B queue source'])
})

test('reconnect does not submit the same draft revision twice across a connectivity flap', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the production editor bundle')
  let firstRequestStarted!: () => void
  const firstStarted = new Promise<void>(resolve => { firstRequestStarted = resolve })
  let secondRequestStarted!: () => void
  const secondStarted = new Promise<void>(resolve => { secondRequestStarted = resolve })
  let releaseFirst!: () => void
  const firstResponse = new Promise<void>(resolve => { releaseFirst = resolve })
  const updates = await prepareDraftReconnect(page, async (route, updateIndex) => {
    if (updateIndex === 0) {
      firstRequestStarted()
      await firstResponse
    } else {
      secondRequestStarted()
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, user_id: 'owner-b', title: 'Draft B', latex_content: 'Draft B local source' }) })
  })
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor', { exact: true })).toBeVisible({ timeout: 30_000 })
  await firstStarted
  await page.evaluate(() => (window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline?.(false))
  await expect(page.getByText(/You're offline/)).toBeVisible({ timeout: 5_000 })
  await page.evaluate(() => (window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline?.(true))
  await expect(page.getByText(/You're offline/)).toBeHidden({ timeout: 5_000 })
  let duplicateObserved = false
  try {
    await Promise.race([secondStarted.then(() => { duplicateObserved = true }), page.waitForTimeout(1_500)])
    expect(duplicateObserved).toBe(false)
  } finally {
    releaseFirst()
  }
  await expect.poll(async () => (await offlineDraftRows(page)).length).toBe(0)
  expect(updates).toEqual(['Draft B local source'])
})

test('reconnect acknowledgement preserves a newer draft revision saved in flight', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the production editor bundle')
  let firstRequestStarted!: () => void
  const firstStarted = new Promise<void>(resolve => { firstRequestStarted = resolve })
  let releaseFirst!: () => void
  const firstResponse = new Promise<void>(resolve => { releaseFirst = resolve })
  const updates = await prepareDraftReconnect(page, async (route, updateIndex) => {
    expect(updateIndex).toBe(0)
    firstRequestStarted()
    await firstResponse
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, user_id: 'owner-b', title: 'Draft B', latex_content: 'Draft B local source' }) })
  })
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor', { exact: true })).toBeVisible({ timeout: 30_000 })
  await firstStarted

  await page.evaluate(({ resumeId }) => new Promise<void>((resolve, reject) => {
    const request = indexedDB.open('latexy-offline')
    request.onsuccess = () => {
      const db = request.result
      const tx = db.transaction('drafts', 'readwrite')
      const store = tx.objectStore('drafts')
      store.put({
        key: JSON.stringify(['owner-b', resumeId]), ownerId: 'owner-b', resumeId,
        title: 'Draft B newer', latexContent: 'Draft B newer local source',
        expectedLatexContent: 'Server source before draft', savedAt: new Date(2), syncStatus: 'pending',
      })
      store.put({
        key: JSON.stringify(['owner-a', 'private-resume']), ownerId: 'owner-a', resumeId: 'private-resume',
        title: 'Private A', latexContent: 'Private A source', savedAt: new Date(3), syncStatus: 'pending',
      })
      tx.oncomplete = () => { db.close(); resolve() }
      tx.onerror = () => { db.close(); reject(tx.error) }
    }
    request.onerror = () => reject(request.error)
  }), { resumeId: RESUME_ID })

  releaseFirst()
  await expect.poll(async () => (await offlineDraftRows(page)).map(row => ({
    ownerId: row.ownerId,
    resumeId: row.resumeId,
    title: row.title,
    latexContent: row.latexContent,
    savedAt: row.savedAt instanceof Date ? row.savedAt.getTime() : null,
  }))).toEqual(expect.arrayContaining([
    { ownerId: 'owner-b', resumeId: RESUME_ID, title: 'Draft B newer', latexContent: 'Draft B newer local source', savedAt: 2 },
    { ownerId: 'owner-a', resumeId: 'private-resume', title: 'Private A', latexContent: 'Private A source', savedAt: 3 },
  ]))
  expect(updates).toEqual(['Draft B local source'])
})

test('a failed queued compile remains retryable on a later reconnect', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires the production editor bundle')
  let firstRequestFinished!: () => void
  const firstFinished = new Promise<void>(resolve => { firstRequestFinished = resolve })
  let secondRequestStarted!: () => void
  const secondStarted = new Promise<void>(resolve => { secondRequestStarted = resolve })
  const submissions = await prepareReconnect(page, false, async (route, submissionIndex) => {
    if (submissionIndex === 0) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary compile outage' }) })
      firstRequestFinished()
      return
    }
    secondRequestStarted()
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'retry-job', message: 'Started' }) })
  }, true)
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor', { exact: true })).toBeVisible({ timeout: 30_000 })
  await firstFinished
  await expect.poll(() => submissions.length).toBe(1)
  await page.evaluate(() => (window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline?.(false))
  await expect(page.getByText(/You're offline/)).toBeVisible({ timeout: 5_000 })
  await page.evaluate(() => (window as Window & { __setTestOnline?: (value: boolean) => void }).__setTestOnline?.(true))
  await expect(page.getByText(/You're offline/)).toBeHidden({ timeout: 5_000 })
  await secondStarted
  await expect.poll(async () => (await queueRows(page)).rows.map(row => row.id)).toEqual(['private-a'])
  expect(submissions).toEqual(['Current account B queue source', 'Current account B queue source'])
})
