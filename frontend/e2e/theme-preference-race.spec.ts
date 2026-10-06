import { expect, test, type Page } from '@playwright/test'

const OWNER_A = 'theme-race-owner-a'
const OWNER_B = 'theme-race-owner-b'
const TOKEN_A = 'theme-race-token-a'
const TOKEN_B = 'theme-race-token-b'

type Owner = 'A' | 'B'

function sessionFor(owner: Owner) {
  const userId = owner === 'A' ? OWNER_A : OWNER_B
  const token = owner === 'A' ? TOKEN_A : TOKEN_B
  return {
    session: {
      id: `theme-race-session-${owner.toLowerCase()}`,
      userId,
      token,
      expiresAt: '2099-01-01T00:00:00Z',
    },
    user: { id: userId, email: userId + '@example.invalid', name: userId },
  }
}

function meResponse(owner: Owner, theme: 'light' | 'dark') {
  const userId = owner === 'A' ? OWNER_A : OWNER_B
  return {
    id: userId,
    role: 'user',
    preferences: { theme },
  }
}

async function settleClient(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
}

async function mockThemeDependencies(
  page: Page,
  activeOwner: { current: Owner } = { current: 'A' },
  options: { authenticated?: boolean } = {},
) {
  const pendingMe: Array<{
    owner: Owner
    settled: boolean
    release: (theme: 'light' | 'dark') => Promise<void>
  }> = []
  const sessionOwners: Owner[] = []
  const meAuthHeaders: string[] = []
  const preferencePatches: Array<Record<string, unknown>> = []

  await page.addInitScript(() => {
    const state = window as Window & { __latexyMeBodyReads?: number }
    state.__latexyMeBodyReads = 0
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init)
      const request = input instanceof Request ? input : new Request(input, init)
      const path = new URL(request.url, window.location.href).pathname
      if (request.method.toUpperCase() !== 'GET' || path !== '/me') return response
      let bodyRead = false
      const markBodyRead = () => {
        if (bodyRead) return
        bodyRead = true
        state.__latexyMeBodyReads = (state.__latexyMeBodyReads ?? 0) + 1
      }
      const originalJson = response.json.bind(response)
      const originalText = response.text.bind(response)
      response.json = async () => {
        try {
          return await originalJson()
        } finally {
          markBodyRead()
        }
      }
      response.text = async () => {
        try {
          return await originalText()
        } finally {
          markBodyRead()
        }
      }
      return response
    }
  })

  await page.route('**/api/auth/get-session', (route) => {
    sessionOwners.push(activeOwner.current)
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(options.authenticated === false ? { session: null, user: null } : sessionFor(activeOwner.current)),
    })
  })
  await page.route((url) => url.pathname === '/config/feature-flags', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }))
  await page.route((url) => url.pathname === '/config/entitlements', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ features: {} }),
  }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ tenant: null }),
  }))
  await page.route((url) => url.pathname === '/me', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback()

    const token = route.request().headers().authorization
    meAuthHeaders.push(token ?? '')
    const owner: Owner = token === `Bearer ${TOKEN_B}` ? 'B' : 'A'
    let resolve!: () => void
    const pending = {
      owner,
      settled: false,
      release: async (theme: 'light' | 'dark') => {
        pending.settled = true
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(meResponse(owner, theme)),
        })
        resolve()
      },
    }
    await new Promise<void>((resolvePending) => {
      pendingMe.push(pending)
      resolve = resolvePending
    })
  })
  await page.route((url) => url.pathname === '/me/preferences', async (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    preferencePatches.push(body)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...meResponse(activeOwner.current, body.theme === 'dark' ? 'dark' : 'light'), preferences: body }),
    })
  })
  await page.route('**/ws/**', (route) => route.abort())

  return {
    pendingMeCount: () => pendingMe.filter((entry) => !entry.settled).length,
    pendingRequests: () => pendingMe.filter((entry) => !entry.settled),
    sessionOwners,
    meAuthHeaders,
    releasePendingMe: async (theme: 'light' | 'dark') => {
      const batch = pendingMe.filter((entry) => !entry.settled)
      await Promise.all(batch.map((entry) => entry.release(theme)))
    },
    releaseEntries: async (entries: Array<{ release: (theme: 'light' | 'dark') => Promise<void> }>, theme: 'light' | 'dark') => {
      await Promise.all(entries.map((entry) => entry.release(theme)))
    },
    preferencePatches,
  }
}

async function meBodyReadCount(page: Page) {
  return page.evaluate(() => (window as Window & { __latexyMeBodyReads?: number }).__latexyMeBodyReads ?? 0)
}

async function releaseMeAndWait(
  page: Page,
  fixture: Awaited<ReturnType<typeof mockThemeDependencies>>,
  entries: Array<{ release: (theme: 'light' | 'dark') => Promise<void> }>,
  theme: 'light' | 'dark',
) {
  const expectedBodyReads = await meBodyReadCount(page) + entries.length
  await fixture.releaseEntries(entries, theme)
  await expect.poll(() => meBodyReadCount(page)).toBeGreaterThanOrEqual(expectedBodyReads)
  await settleClient(page)
}

async function openAccessibility(page: Page) {
  await page.goto('/accessibility', { waitUntil: 'domcontentloaded' })
  const toggle = page.getByRole('button', { name: 'Toggle light or dark mode' }).first()
  await expect(toggle).toBeVisible()
  await expect(toggle).toBeEnabled()
  return toggle
}

async function expectInitialRequests(fixture: Awaited<ReturnType<typeof mockThemeDependencies>>) {
  // ThemeProvider and GlobalHeader both call GET /me for the authenticated user.
  await expect.poll(() => fixture.pendingMeCount()).toBeGreaterThanOrEqual(2)
}

async function notifyOwner(
  page: Page,
  fixture: Awaited<ReturnType<typeof mockThemeDependencies>>,
  activeOwner: { current: Owner },
  nextOwner: Owner,
) {
  const previousSessionReads = fixture.sessionOwners.length
  activeOwner.current = nextOwner
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'theme-race-owner-switch' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(() => fixture.sessionOwners.length).toBeGreaterThan(previousSessionReads)
}

test.describe('ThemeProvider preference synchronization', () => {
  test('ordinary account preference load applies the server theme', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const fixture = await mockThemeDependencies(page)
    await openAccessibility(page)
    await expectInitialRequests(fixture)

    await releaseMeAndWait(page, fixture, fixture.pendingRequests(), 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    expect(pageErrors).toEqual([])
  })

  test('same-owner toggle remains selected and persists its preference', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const fixture = await mockThemeDependencies(page)
    const toggle = await openAccessibility(page)
    await expectInitialRequests(fixture)

    await releaseMeAndWait(page, fixture, fixture.pendingRequests(), 'light')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')

    const patchResponse = page.waitForResponse((response) =>
      response.url().endsWith('/me/preferences') && response.request().method() === 'PATCH',
    )
    await toggle.click()
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    const completedPatch = await patchResponse
    await completedPatch.finished()
    await expect.poll(() => fixture.preferencePatches.length).toBeGreaterThan(0)
    expect(fixture.preferencePatches[fixture.preferencePatches.length - 1]).toEqual({ theme: 'dark' })
    await settleClient(page)
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    expect(pageErrors).toEqual([])
  })

  test('newer same-owner toggle choices supersede a pending preference response', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const fixture = await mockThemeDependencies(page)
    const toggle = await openAccessibility(page)
    await expectInitialRequests(fixture)

    const initialMode = await page.locator('html').getAttribute('data-mode')
    expect(initialMode).toMatch(/^(light|dark)$/)
    const firstChoice = initialMode === 'dark' ? 'light' : 'dark'

    const firstPatchResponse = page.waitForResponse((response) =>
      response.url().endsWith('/me/preferences') && response.request().method() === 'PATCH',
    )
    await toggle.click()
    await expect(page.locator('html')).toHaveAttribute('data-mode', firstChoice)
    const firstCompletedPatch = await firstPatchResponse
    await firstCompletedPatch.finished()

    const secondPatchResponse = page.waitForResponse((response) =>
      response.url().endsWith('/me/preferences') && response.request().method() === 'PATCH',
    )
    await toggle.click()
    await expect(page.locator('html')).toHaveAttribute('data-mode', initialMode!)
    const secondCompletedPatch = await secondPatchResponse
    await secondCompletedPatch.finished()

    await releaseMeAndWait(page, fixture, fixture.pendingRequests(), firstChoice as 'light' | 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', initialMode!)
    expect(fixture.preferencePatches.map((body) => body.theme)).toEqual([firstChoice, initialMode])
    expect(pageErrors).toEqual([])
  })

  test('ignores stale A→B→A preference responses across owner epochs', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.addInitScript(() => {
      document.cookie = 'latexy-theme=light; path=/'
    })
    const activeOwner = { current: 'A' as Owner }
    const fixture = await mockThemeDependencies(page, activeOwner)
    await openAccessibility(page)
    await expectInitialRequests(fixture)
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')

    const firstA = fixture.pendingRequests().filter((entry) => entry.owner === 'A')
    expect(firstA.length).toBeGreaterThanOrEqual(2)
    await notifyOwner(page, fixture, activeOwner, 'B')
    await expect.poll(() => fixture.pendingRequests().filter((entry) => entry.owner === 'B').length).toBeGreaterThanOrEqual(2)
    const firstB = fixture.pendingRequests().filter((entry) => entry.owner === 'B')

    await notifyOwner(page, fixture, activeOwner, 'A')
    await expect.poll(() => fixture.pendingRequests().filter((entry) => entry.owner === 'A' && !firstA.includes(entry)).length).toBeGreaterThanOrEqual(2)
    const secondA = fixture.pendingRequests().filter((entry) => entry.owner === 'A' && !firstA.includes(entry))

    await releaseMeAndWait(page, fixture, firstB, 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')
    await releaseMeAndWait(page, fixture, firstA, 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'light')
    await releaseMeAndWait(page, fixture, secondA, 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy-theme:acct:theme-race-owner-a'))).toBe('dark')
    await expect.poll(() => page.evaluate(() => document.cookie.match(/(?:^|; )latexy-theme=([^;]+)/)?.[1])).toBe('dark')
    expect(fixture.meAuthHeaders).toContain(`Bearer ${TOKEN_B}`)
    expect(fixture.meAuthHeaders).toContain(`Bearer ${TOKEN_A}`)
    expect(pageErrors).toEqual([])
  })

  test('ignores a pending preference response after a same-owner toggle', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const fixture = await mockThemeDependencies(page)
    const toggle = await openAccessibility(page)
    await expectInitialRequests(fixture)

    const initialMode = await page.locator('html').getAttribute('data-mode')
    expect(initialMode).toMatch(/^(light|dark)$/)
    const selectedMode = initialMode === 'dark' ? 'light' : 'dark'
    const patchResponse = page.waitForResponse((response) =>
      response.url().endsWith('/me/preferences') && response.request().method() === 'PATCH',
    )
    await toggle.click()
    await expect(page.locator('html')).toHaveAttribute('data-mode', selectedMode)
    const completedPatch = await patchResponse
    await completedPatch.finished()
    await expect.poll(() => fixture.preferencePatches.length).toBeGreaterThan(0)

    const selectedCache = await page.evaluate(() => ({
      cache: localStorage.getItem('latexy-theme:acct:theme-race-owner-a'),
      cookie: document.cookie.match(/(?:^|; )latexy-theme=([^;]+)/)?.[1] ?? null,
    }))
    await releaseMeAndWait(page, fixture, fixture.pendingRequests(), initialMode as 'light' | 'dark')
    await expect(page.locator('html')).toHaveAttribute('data-mode', selectedMode)
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy-theme:acct:theme-race-owner-a'))).toBe(selectedCache.cache)
    await expect.poll(() => page.evaluate(() => document.cookie.match(/(?:^|; )latexy-theme=([^;]+)/)?.[1] ?? null)).toBe(selectedCache.cookie)
    expect(fixture.preferencePatches[fixture.preferencePatches.length - 1]).toEqual({ theme: selectedMode })
    expect(pageErrors).toEqual([])
  })

  test('anonymous bootstrap keeps its cookie theme without account preference fetches', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await page.addInitScript(() => {
      document.cookie = 'latexy-theme=dark; path=/'
    })
    const fixture = await mockThemeDependencies(page, { current: 'A' }, { authenticated: false })
    await openAccessibility(page)

    await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark')
    await expect.poll(() => fixture.pendingMeCount()).toBe(0)
    expect(await meBodyReadCount(page)).toBe(0)
    expect(pageErrors).toEqual([])
  })
})
