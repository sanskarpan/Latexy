import { expect, test, type Page, type Request } from './quality-test'

const authenticatedSession = {
  user: { id: 'mobile-account-owner', email: 'mobile@example.com', name: 'Mobile Owner' },
  session: { id: 'mobile-session', userId: 'mobile-account-owner', token: 'mobile-session-token' },
}

const diagnosticsByPage = new WeakMap<Page, {
  pageErrors: string[]
  authTimeline: string[]
  unmockedApiRequests: string[]
  unexpectedAuthRequests: Map<Request, string>
  getSessionReads: () => number
  getGuestSessionReads: () => number
}>()

async function mockHeaderDependencies(
  page: Page,
  options: { authenticated: boolean; role?: string; billing?: boolean },
) {
  const pageErrors: string[] = []
  const authTimeline: string[] = []
  const unmockedApiRequests: string[] = []
  const unexpectedAuthRequests = new Map<Request, string>()
  const mockedAuthRequests = new WeakSet<Request>()
  let authenticated = options.authenticated
  let sessionReads = 0
  let guestSessionReads = 0
  const qualityPort = Number.parseInt(process.env.PLAYWRIGHT_QUALITY_PORT ?? '5182', 10)
  const backendUrl = process.env.PLAYWRIGHT_API_URL
    ?? process.env.PLAYWRIGHT_BACKEND_URL
    ?? `http://127.0.0.1:${qualityPort + 2000}`
  const backendOrigin = new URL(backendUrl).origin
  const appOrigin = new URL(`http://localhost:${qualityPort}`).origin
  const startedAt = Date.now()
  const timeline = (event: string, method: string, path: string, status?: number) => {
    const elapsedMs = Date.now() - startedAt
    authTimeline.push(`${event} +${elapsedMs}ms ${method} ${path}${status === undefined ? '' : ` -> ${status}`}`)
  }

  page.on('pageerror', error => {
    pageErrors.push(error.message)
    const path = error.message.match(/\/api\/auth\/[A-Za-z0-9/_-]+/)?.[0] ?? '(path unavailable)'
    timeline('PAGEERROR', '-', path)
  })
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.origin !== appOrigin || !url.pathname.startsWith('/api/auth/')) return
    unexpectedAuthRequests.set(request, `${request.method()} ${url.pathname} (pending)`)
    timeline('REQUEST', request.method(), url.pathname)
  })
  page.on('response', response => {
    const request = response.request()
    const url = new URL(request.url())
    if (url.origin !== appOrigin || !url.pathname.startsWith('/api/auth/')) return
    timeline('RESPONSE', request.method(), url.pathname, response.status())
    if (!unexpectedAuthRequests.has(request)) return
    if (mockedAuthRequests.has(request)) {
      unexpectedAuthRequests.delete(request)
      return
    }
    unexpectedAuthRequests.set(request, `${request.method()} ${url.pathname} -> ${response.status()}`)
  })
  page.on('requestfailed', request => {
    const url = new URL(request.url())
    if (url.origin !== appOrigin || !url.pathname.startsWith('/api/auth/')) return
    timeline('REQUEST_FAILED', request.method(), url.pathname)
    if (!unexpectedAuthRequests.has(request)) return
    if (mockedAuthRequests.has(request)) {
      unexpectedAuthRequests.delete(request)
      return
    }
    unexpectedAuthRequests.set(request, `${request.method()} ${url.pathname} -> failed`)
  })

  // Fail and record any backend request this header-focused fixture did not
  // intentionally mock. The app must not silently depend on a live service.
  await page.route(url => url.origin === backendOrigin, route => {
    unmockedApiRequests.push(`${route.request().method()} ${route.request().url()}`)
    return route.fulfill({ status: 501, contentType: 'application/json', body: '{}' })
  })
  await page.route(url => url.origin === appOrigin && url.pathname === '/api/auth/get-session', async route => {
    mockedAuthRequests.add(route.request())
    const isGuest = !authenticated
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(isGuest ? { user: null, session: null } : authenticatedSession),
    })
    sessionReads += 1
    if (isGuest) guestSessionReads += 1
  })
  await page.route(url => url.origin === backendOrigin && url.pathname === '/telemetry/frontend', route =>
    route.fulfill({ status: 204, body: '' }),
  )
  await page.route(url => url.origin === backendOrigin && url.pathname === '/tenants/resolve-host', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ tenant: null }),
  }))
  await page.route(url => url.origin === backendOrigin && url.pathname === '/portfolio/resolve-domain', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ profile: null }),
  }))
  await page.route(url => url.pathname === '/me', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: 'mobile-account-owner', email: 'mobile@example.com', role: options.role ?? 'user' }),
  }))
  await page.route(url => url.pathname === '/config/entitlements', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ features: {} }),
  }))
  await page.route(url => url.pathname === '/config/feature-flags', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ billing: options.billing ?? true }),
  }))

  const diagnostics = {
    pageErrors,
    authTimeline,
    unmockedApiRequests,
    unexpectedAuthRequests,
    getSessionReads() {
      return sessionReads
    },
    getGuestSessionReads() {
      return guestSessionReads
    },
    setAuthenticated(value: boolean) {
      authenticated = value
    },
    markMockedAuthRequest(request: Request) {
      mockedAuthRequests.add(request)
    },
  }
  diagnosticsByPage.set(page, diagnostics)
  return diagnostics
}

async function waitForHeaderSession(page: Page, fixture: Awaited<ReturnType<typeof mockHeaderDependencies>>) {
  await expect.poll(() => fixture.getSessionReads()).toBeGreaterThan(0)
  // The header starts with a neutral session while Better Auth resolves. Let
  // that response and its hydration effects settle before opening the panel.
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
}

async function expectGuestAccountNavigation(page: Page) {
  await expect(page.getByRole('button', { name: 'Open navigation menu' })).toBeVisible()
  await page.getByRole('button', { name: 'Open navigation menu' }).click()
  await expect(page.getByRole('link', { name: 'Log In', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Try Free', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign Out', exact: true })).toHaveCount(0)
}

test.describe('mobile account navigation', () => {
  test.afterEach(async ({ page }, testInfo) => {
    const diagnostics = diagnosticsByPage.get(page)
    if (!diagnostics) return

    await testInfo.attach('mobile-account-navigation-diagnostics.json', {
      body: Buffer.from(JSON.stringify({
        pageErrors: diagnostics.pageErrors,
        authTimeline: diagnostics.authTimeline,
        unmockedApiRequests: diagnostics.unmockedApiRequests,
        unexpectedAuthRequests: [...diagnostics.unexpectedAuthRequests.values()],
        sessionReads: diagnostics.getSessionReads(),
        guestSessionReads: diagnostics.getGuestSessionReads(),
      }, null, 2)),
      contentType: 'application/json',
    })
    expect(diagnostics.pageErrors).toEqual([])
    expect(diagnostics.unmockedApiRequests).toEqual([])
    expect([...diagnostics.unexpectedAuthRequests.values()]).toEqual([])
  })

  test('authenticated users can reach account controls, use the keyboard trap, and sign out', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: true })
    let signOutCalls = 0
    const qualityPort = Number.parseInt(process.env.PLAYWRIGHT_QUALITY_PORT ?? '5182', 10)
    const appOrigin = new URL(`http://localhost:${qualityPort}`).origin
    const signOutMethods: string[] = []
    await page.route(url => url.origin === appOrigin && url.pathname === '/api/auth/sign-out', route => {
      fixture.markMockedAuthRequest(route.request())
      signOutCalls += 1
      signOutMethods.push(route.request().method())
      fixture.setAuthenticated(false)
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })

    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    const menuButton = page.getByRole('button', { name: 'Open navigation menu' })
    await expect(menuButton).toBeVisible()
    await menuButton.click()

    const settings = page.getByRole('link', { name: 'Settings', exact: true })
    const providers = page.getByRole('link', { name: 'AI Providers', exact: true })
    const signOut = page.getByRole('button', { name: 'Sign Out', exact: true })
    await expect(page.getByText('mobile@example.com')).toBeVisible()
    await expect(settings).toHaveAttribute('href', '/settings')
    await expect(providers).toHaveAttribute('href', '/byok')
    await expect(signOut).toBeVisible()

    const firstItem = page.getByRole('link', { name: 'Dashboard', exact: true })
    await expect(firstItem).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(signOut).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(firstItem).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0)
    await expect(menuButton).toBeFocused()

    await menuButton.click()
    await page.getByRole('button', { name: 'Sign Out', exact: true }).click()
    await expect.poll(() => signOutCalls).toBe(1)
    expect(signOutMethods).toEqual(['POST'])
    await expect(page).toHaveURL(/\/$/, { timeout: 90_000 })
    await expect.poll(() => fixture.getGuestSessionReads()).toBeGreaterThan(0)
    await waitForHeaderSession(page, fixture)
    await expectGuestAccountNavigation(page)
    // The session mock's response count precedes hydration and startup
    // prefetches. Do not interrupt that first guest document with our own
    // persistence reload, which can surface Firefox NS_BINDING_ABORTED.
    await page.waitForLoadState('networkidle')
    // A full reload proves the mock sign-out changed the backing session view;
    // independently verify the new document's session and guest controls.
    const guestSessionReadsBeforeReload = fixture.getGuestSessionReads()
    await page.reload({ waitUntil: 'networkidle' })
    await expect.poll(() => fixture.getGuestSessionReads()).toBeGreaterThan(guestSessionReadsBeforeReload)
    await waitForHeaderSession(page, fixture)
    await expectGuestAccountNavigation(page)
    expect(signOutCalls).toBe(1)
  })

  test('guests see login actions without authenticated account controls', async ({ page }) => {
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: false })
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()

    await expect(page.getByRole('link', { name: 'Log In', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Try Free', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'AI Providers', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Sign Out', exact: true })).toHaveCount(0)
  })

  test('non-admin accounts do not gain admin or disabled billing links', async ({ page }) => {
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: true, role: 'user', billing: false })
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()

    await expect(page.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Billing', exact: true })).toHaveCount(0)
  })
})
