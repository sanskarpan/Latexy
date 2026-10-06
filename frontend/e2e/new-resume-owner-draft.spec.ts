import { expect, test } from '@playwright/test'

const OWNER_A = 'new-resume-owner-a'
const OWNER_B = 'new-resume-owner-b'
const TOKEN_A = 'new-resume-token-a'
const TOKEN_B = 'new-resume-token-b'
const CREATED_A_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const CREATED_B_ID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'

const EMPTY_TEMPLATES = JSON.stringify([])
type MockOptions = { deferFirstCreate?: boolean; rejectFirstCreate?: boolean; failNextSession?: boolean }

function sessionFor(owner: string) {
  const token = owner === OWNER_A ? TOKEN_A : TOKEN_B
  return {
    session: { id: `session-${owner}`, userId: owner, token, expiresAt: '2099-01-01T00:00:00Z' },
    user: { id: owner, email: `${owner}@example.invalid`, name: owner },
  }
}

async function watchPageErrors(page: import('@playwright/test').Page) {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => {
    const state = window as Window & {
      __latexyResumeBodyReads?: string[]
      __latexySessionBodyReads?: string[]
    }
    state.__latexyResumeBodyReads = []
    state.__latexySessionBodyReads = []
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init)
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
      const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      const path = new URL(rawUrl, window.location.href).pathname
      const isResumeCreate = method === 'POST' && path === '/resumes/'
      const isSessionRead = method === 'GET' && path === '/api/auth/get-session'
      if (!isResumeCreate && !isSessionRead) return response

      const originalJson = response.json.bind(response)
      const originalText = response.text.bind(response)
      response.json = async () => {
        const body = await originalJson()
        if (isResumeCreate) state.__latexyResumeBodyReads?.push('json')
        if (isSessionRead) state.__latexySessionBodyReads?.push('json')
        return body
      }
      response.text = async () => {
        const body = await originalText()
        if (isResumeCreate) state.__latexyResumeBodyReads?.push('text')
        if (isSessionRead) state.__latexySessionBodyReads?.push('text')
        return body
      }
      return response
    }
  })
  return errors
}

async function expectResumeBodyRead(page: import('@playwright/test').Page, index: number, method: 'json' | 'text') {
  await expect.poll(() => page.evaluate(() =>
    (window as Window & { __latexyResumeBodyReads?: string[] }).__latexyResumeBodyReads?.length ?? 0,
  )).toBeGreaterThan(index)
  await expect.poll(() => page.evaluate((readIndex) =>
    (window as Window & { __latexyResumeBodyReads?: string[] }).__latexyResumeBodyReads?.[readIndex], index,
  )).toBe(method)
}

async function expectSessionBodyRead(page: import('@playwright/test').Page, index: number) {
  await expect.poll(() => page.evaluate(() =>
    (window as Window & { __latexySessionBodyReads?: string[] }).__latexySessionBodyReads?.length ?? 0,
  )).toBeGreaterThan(index)
}

async function settleAsyncHandler(page: import('@playwright/test').Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
}

async function mockNewResumeDependencies(
  page: import('@playwright/test').Page,
  owner: { current: string },
  options: MockOptions = {},
) {
  const sessionOwners: string[] = []
  const meAuthHeaders: string[] = []
  let createdBody: Record<string, unknown> | null = null
  let createdAuth: string | undefined
  let deferNextCreate = options.deferFirstCreate ?? false
  let rejectNextCreate = options.rejectFirstCreate ?? false
  let failNextSession = options.failNextSession ?? false
  const createStartedResolvers: Array<() => void> = []
  const deferredCreateResolvers: Array<() => void> = []

  await page.route('**/api/auth/get-session', (route) => {
    sessionOwners.push(owner.current)
    if (failNextSession) {
      failNextSession = false
      return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'temporary session outage' }) })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(sessionFor(owner.current)),
    })
  })
  await page.route((url) => url.pathname === '/templates' || url.pathname === '/templates/', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: EMPTY_TEMPLATES })
  )
  await page.route((url) => url.pathname === '/templates/categories', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: EMPTY_TEMPLATES })
  )
  await page.route((url) => url.pathname === '/config/feature-flags', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  )
  await page.route((url) => url.pathname === '/me', (route) => {
    meAuthHeaders.push(route.request().headers().authorization ?? '')
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: owner.current, role: 'user' }),
    })
  })
  await page.route((url) => url.pathname === '/config/entitlements', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: {} }) })
  )
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tenant: null }) })
  )
  await page.route((url) => url.pathname === '/resumes/', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const requestOwner = owner.current
    const requestAuth = route.request().headers().authorization
    const requestBody = route.request().postDataJSON() as Record<string, unknown>
    createdAuth = requestAuth
    createdBody = requestBody
    createStartedResolvers.shift()?.()
    if (deferNextCreate) {
      deferNextCreate = false
      await new Promise<void>((resolve) => deferredCreateResolvers.push(resolve))
    }
    if (rejectNextCreate) {
      rejectNextCreate = false
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'deferred create failure' }) })
      return
    }
    await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
        id: requestOwner === OWNER_A ? CREATED_A_ID : CREATED_B_ID,
        user_id: requestOwner,
        title: requestBody.title,
        latex_content: requestBody.latex_content,
        is_template: false,
      }),
    })
  })
  await page.route('**/ws/**', (route) => route.abort())

  return {
    sessionOwners,
    meAuthHeaders,
    failNextSession: () => { failNextSession = true },
    waitForCreateStarted: () => new Promise<void>((resolve) => createStartedResolvers.push(resolve)),
    releaseCreate: () => deferredCreateResolvers.shift()?.(),
    getCreated: () => ({ body: createdBody, auth: createdAuth }),
  }
}

test.describe('New Resume owner/draft boundary', () => {
  test('clears an A draft after an in-place A→B refresh, then permits a fresh B import/create', async ({ page }) => {
    const pageErrors = await watchPageErrors(page)
    const owner = { current: OWNER_A }
    const fixture = await mockNewResumeDependencies(page, owner)
    const notifyOwner = async (nextOwner: string) => {
      const previousSessionCount = fixture.sessionOwners.length
      const expectedAuth = `Bearer ${nextOwner === OWNER_A ? TOKEN_A : TOKEN_B}`
      const previousAuthCount = fixture.meAuthHeaders.filter((value) => value === expectedAuth).length
      owner.current = nextOwner
      await page.evaluate(() => {
        const message = JSON.stringify({ event: 'session', data: { trigger: 'test-owner-switch' } })
        localStorage.setItem('better-auth.message', message)
        window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
      })
      await expect.poll(() => fixture.sessionOwners.length).toBeGreaterThan(previousSessionCount)
      await page.getByRole('button', { name: 'Open account menu' }).click()
      await expect(page.getByRole('menu', { name: 'Account menu' })).toContainText(`${nextOwner}@example.invalid`)
      await page.keyboard.press('Escape')
      await expect.poll(() => fixture.meAuthHeaders.filter((value) => value === expectedAuth).length).toBeGreaterThan(previousAuthCount)
    }

    await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
    const title = page.locator('input[placeholder*="Senior Backend"]')
    await expect(title).toBeVisible()
    await title.fill('Owner A private draft')
    await page.getByRole('heading', { name: 'Import File' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'owner-a.tex',
      mimeType: 'application/x-tex',
      buffer: Buffer.from('\\documentclass{article}\\begin{document}Owner A private content\\end{document}'),
    })
    await expect(page.getByText('LaTeX file loaded')).toBeVisible()

    await notifyOwner(OWNER_B)

    await expect(title).toHaveValue('')
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toHaveCount(0)

    await notifyOwner(OWNER_A)
    await expect(title).toHaveValue('')
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toHaveCount(0)
    await notifyOwner(OWNER_B)
    await expect(title).toHaveValue('')
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toHaveCount(0)

    await title.fill('Owner B fresh draft')
    await page.getByRole('heading', { name: 'Import File' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'owner-b.tex',
      mimeType: 'application/x-tex',
      buffer: Buffer.from('\\documentclass{article}\\begin{document}Owner B fresh content\\end{document}'),
    })
    await expect(page.getByText('LaTeX file loaded')).toBeVisible()

    const createResponse = page.waitForResponse((response) => response.url().endsWith('/resumes/') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Create Resume' }).click()
    const completedCreateResponse = await createResponse
    await completedCreateResponse.finished()
    await expectResumeBodyRead(page, 0, 'json')
    await settleAsyncHandler(page)
    await expect(page).toHaveURL(new RegExp(`/workspace/${CREATED_B_ID}/edit$`))
    await expect.poll(() => fixture.getCreated().body).not.toBeNull()
    const created = fixture.getCreated()
    expect(created.auth).toBe(`Bearer ${TOKEN_B}`)
    expect(created.body).toMatchObject({
      title: 'Owner B fresh draft',
      latex_content: '\\documentclass{article}\\begin{document}Owner B fresh content\\end{document}',
    })
    expect(pageErrors).toEqual([])
  })

  test('same-owner refresh retains the draft while a reload clears it', async ({ page }) => {
    const pageErrors = await watchPageErrors(page)
    const owner = { current: OWNER_A }
    const fixture = await mockNewResumeDependencies(page, owner)

    await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
    const title = page.locator('input[placeholder*="Senior Backend"]')
    await title.fill('Same owner draft')
    await page.getByRole('heading', { name: 'Import File' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'same-owner.tex',
      mimeType: 'application/x-tex',
      buffer: Buffer.from('\\documentclass{article}\\begin{document}Same owner\\end{document}'),
    })
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()

    const previousSessionCount = fixture.sessionOwners.length
    const previousSessionBodyReadCount = await page.evaluate(() =>
      (window as Window & { __latexySessionBodyReads?: string[] }).__latexySessionBodyReads?.length ?? 0,
    )
    const refreshResponse = page.waitForResponse((response) =>
      response.url().includes('/api/auth/get-session') && response.status() === 200,
    )
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-same-owner-refresh' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => fixture.sessionOwners.length).toBeGreaterThan(previousSessionCount)
    const completedRefreshResponse = await refreshResponse
    await completedRefreshResponse.finished()
    await expectSessionBodyRead(page, previousSessionBodyReadCount)
    await settleAsyncHandler(page)
    await expect(title).toHaveValue('Same owner draft')
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.locator('input[placeholder*="Senior Backend"]')).toHaveValue('')
    await expect(page.getByText('LaTeX file loaded')).toHaveCount(0)
    expect(pageErrors).toEqual([])
  })

  for (const deferredOutcome of ['success', 'rejection'] as const) {
    test(`suppresses a deferred A ${deferredOutcome} after an owner switch and allows B to create`, async ({ page }) => {
    const pageErrors = await watchPageErrors(page)
    const owner = { current: OWNER_A }
    const fixture = await mockNewResumeDependencies(page, owner, {
      deferFirstCreate: true,
      rejectFirstCreate: deferredOutcome === 'rejection',
    })

    await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
    const title = page.locator('input[placeholder*="Senior Backend"]')
    await expect(title).toBeVisible()
    await title.fill('Owner A deferred draft')
    await page.getByRole('heading', { name: 'Import File' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'owner-a-deferred.tex',
      mimeType: 'application/x-tex',
      buffer: Buffer.from('\\documentclass{article}\\begin{document}Owner A deferred content\\end{document}'),
    })
    await expect(page.getByText('LaTeX file loaded')).toBeVisible()

    const oldCreateResponse = page.waitForResponse((response) =>
      response.url().endsWith('/resumes/') &&
      response.request().method() === 'POST' &&
      response.status() === (deferredOutcome === 'rejection' ? 503 : 201),
    )
    const oldCreateStarted = fixture.waitForCreateStarted()
    await page.getByRole('button', { name: 'Create Resume' }).click()
    await oldCreateStarted

    owner.current = OWNER_B
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-deferred-owner-switch' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => fixture.sessionOwners.filter((value) => value === OWNER_B).length).toBeGreaterThan(0)
    await page.getByRole('button', { name: 'Open account menu' }).click()
    await expect(page.getByRole('menu', { name: 'Account menu' })).toContainText(`${OWNER_B}@example.invalid`)
    await page.keyboard.press('Escape')
    await expect(title).toHaveValue('')

    fixture.releaseCreate()
    const completedOldCreateResponse = await oldCreateResponse
    await completedOldCreateResponse.finished()
    await expectResumeBodyRead(page, 0, deferredOutcome === 'rejection' ? 'text' : 'json')
    await settleAsyncHandler(page)
    await expect(page).toHaveURL(/\/workspace\/new$/)
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Resume created from import' })).toHaveCount(0)
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Failed to create resume' })).toHaveCount(0)

    await title.fill('Owner B recovery draft')
    await page.getByRole('heading', { name: 'Import File' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'owner-b-recovery.tex',
      mimeType: 'application/x-tex',
      buffer: Buffer.from('\\documentclass{article}\\begin{document}Owner B recovery content\\end{document}'),
    })
    await expect(page.getByText('LaTeX file loaded')).toBeVisible()
    const newCreateResponse = page.waitForResponse((response) => response.url().endsWith('/resumes/') && response.request().method() === 'POST')
    const newCreateStarted = fixture.waitForCreateStarted()
    await page.getByRole('button', { name: 'Create Resume' }).click()
    await newCreateStarted
    const completedNewCreateResponse = await newCreateResponse
    await completedNewCreateResponse.finished()
    await expectResumeBodyRead(page, 1, 'json')
    await settleAsyncHandler(page)
    await expect(page).toHaveURL(new RegExp(`/workspace/${CREATED_B_ID}/edit$`))
    await expect.poll(() => fixture.getCreated().body).not.toBeNull()
    expect(fixture.getCreated()).toMatchObject({
      auth: `Bearer ${TOKEN_B}`,
      body: {
        title: 'Owner B recovery draft',
        latex_content: '\\documentclass{article}\\begin{document}Owner B recovery content\\end{document}',
      },
    })
    expect(pageErrors).toEqual([])
    })
  }

  test('retains a same-owner draft through a transient session error and recovery', async ({ page }) => {
    const pageErrors = await watchPageErrors(page)
    const owner = { current: OWNER_A }
    const fixture = await mockNewResumeDependencies(page, owner)

    await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
    const title = page.locator('input[placeholder*="Senior Backend"]')
    await expect(title).toBeVisible()
    await title.fill('Same owner outage draft')
    await page.getByRole('heading', { name: 'Import File' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'same-owner-outage.tex',
      mimeType: 'application/x-tex',
      buffer: Buffer.from('\\documentclass{article}\\begin{document}Same owner outage content\\end{document}'),
    })
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()

    fixture.failNextSession()
    const previousFailedSessionBodyReadCount = await page.evaluate(() =>
      (window as Window & { __latexySessionBodyReads?: string[] }).__latexySessionBodyReads?.length ?? 0,
    )
    const failedSessionResponse = page.waitForResponse((response) => response.url().includes('/api/auth/get-session') && response.status() === 503)
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-same-owner-error' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    const completedFailedSessionResponse = await failedSessionResponse
    await completedFailedSessionResponse.finished()
    await expectSessionBodyRead(page, previousFailedSessionBodyReadCount)
    await settleAsyncHandler(page)
    await expect(title).toHaveValue('Same owner outage draft')
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()

    const previousRecoveredSessionBodyReadCount = await page.evaluate(() =>
      (window as Window & { __latexySessionBodyReads?: string[] }).__latexySessionBodyReads?.length ?? 0,
    )
    const recoveredSessionResponse = page.waitForResponse((response) => response.url().includes('/api/auth/get-session') && response.status() === 200)
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-same-owner-recovery' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    const completedRecoveredSessionResponse = await recoveredSessionResponse
    await completedRecoveredSessionResponse.finished()
    await expectSessionBodyRead(page, previousRecoveredSessionBodyReadCount)
    await settleAsyncHandler(page)
    await expect(title).toHaveValue('Same owner outage draft')
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()
    expect(pageErrors).toEqual([])
  })
})
