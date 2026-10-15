import { expect, test, type Page, type Request } from './quality-test'
import { fulfillQualityJson, qualityOrigins, QUALITY_PLANS } from './mock-api'
import {
  candidatePrefetchUrl, classifySignOutPageErrors, connectionPolicyUnrestricted, installSignOutProvenance,
  type NavigationLedger, type ObservedPageError, type SignOutNavigation,
} from '../helpers/webkit-signout-provenance'

const authenticatedSession = {
  user: { id: 'mobile-account-owner', email: 'mobile@example.com', name: 'Mobile Owner' },
  session: { id: 'mobile-session', userId: 'mobile-account-owner', token: 'mobile-session-token' },
}

const diagnosticsByPage = new WeakMap<Page, {
  pageErrors: string[]
  pageErrorDetails: ObservedPageError[]
  browserRequestUrls: string[]
  runId: string
  storageKey: string
  getSignOutNavigation: () => SignOutNavigation | null
  authTimeline: string[]
  unmockedApiRequests: string[]
  unexpectedAuthRequests: Map<Request, string>
  getSessionReads: () => number
  getGuestSessionReads: () => number
}>()

async function mockHeaderDependencies(
  page: Page,
  options: { authenticated: boolean; role?: string; billing?: boolean; features?: Record<string, boolean> },
) {
  const pageErrors: string[] = []
  const pageErrorDetails: ObservedPageError[] = []
  const browserRequestUrls: string[] = []
  const runId = crypto.randomUUID()
  const storageKey = `latexy-signout-provenance:${runId}`
  let signOutNavigation: SignOutNavigation | null = null
  let platformPolicyUnrestricted = false
  const authTimeline: string[] = []
  const unmockedApiRequests: string[] = []
  const unexpectedAuthRequests = new Map<Request, string>()
  const mockedAuthRequests = new WeakSet<Request>()
  let authenticated = options.authenticated
  let sessionReads = 0
  let guestSessionReads = 0
  const { appOrigin, backendOrigin } = qualityOrigins()
  await page.addInitScript(installSignOutProvenance, { storageKey, runId })
  const startedAt = Date.now()
  const timeline = (event: string, method: string, path: string, status?: number) => {
    const elapsedMs = Date.now() - startedAt
    authTimeline.push(`${event} +${elapsedMs}ms ${method} ${path}${status === undefined ? '' : ` -> ${status}`}`)
  }

  page.on('pageerror', error => {
    pageErrors.push(error.message)
    pageErrorDetails.push({ name: error.name, message: error.message, stack: error.stack ?? '', url: page.url(), observedAt: Date.now() })
    const path = error.message.match(/\/api\/auth\/[A-Za-z0-9/_-]+/)?.[0] ?? '(path unavailable)'
    timeline('PAGEERROR', '-', path)
  })
  page.on('request', request => {
    const url = new URL(request.url())
    const candidate = candidatePrefetchUrl(request.url(), appOrigin)
    if (candidate) {
      if (browserRequestUrls.length < 128) browserRequestUrls.push(candidate)
      timeline('RSC_REQUEST', request.method(), `${url.pathname}${url.search}`)
    }
    if (signOutNavigation && signOutNavigation.postSucceededAt !== null
      && signOutNavigation.replacementStartedAt === null && request.isNavigationRequest()
      && request.frame() === page.mainFrame() && url.href === `${appOrigin}/`) {
      signOutNavigation.replacementStartedAt = Date.now()
    }
    if (url.origin !== appOrigin || !url.pathname.startsWith('/api/auth/')) return
    unexpectedAuthRequests.set(request, `${request.method()} ${url.pathname} (pending)`)
    timeline('REQUEST', request.method(), url.pathname)
  })
  page.on('response', response => {
    const request = response.request()
    const url = new URL(request.url())
    if (request.isNavigationRequest() && request.frame() === page.mainFrame() && url.href === `${appOrigin}/platform`) {
      platformPolicyUnrestricted = connectionPolicyUnrestricted(response.headers()['content-security-policy'] ?? '')
    }
    if (candidatePrefetchUrl(request.url(), appOrigin)) timeline('RSC_RESPONSE', request.method(), `${url.pathname}${url.search}`, response.status())
    if (url.origin !== appOrigin || !url.pathname.startsWith('/api/auth/')) return
    timeline('RESPONSE', request.method(), url.pathname, response.status())
    if (signOutNavigation && url.pathname === '/api/auth/sign-out'
      && request.method() === 'POST' && response.status() === 200) signOutNavigation.postSucceededAt = Date.now()
    if (!unexpectedAuthRequests.has(request)) return
    if (mockedAuthRequests.has(request)) {
      unexpectedAuthRequests.delete(request)
      return
    }
    unexpectedAuthRequests.set(request, `${request.method()} ${url.pathname} -> ${response.status()}`)
  })
  page.on('requestfailed', request => {
    const url = new URL(request.url())
    if (candidatePrefetchUrl(request.url(), appOrigin)) timeline('RSC_REQUEST_FAILED', request.method(), `${url.pathname}${url.search} (${request.failure()?.errorText ?? 'unknown'})`)
    if (url.origin !== appOrigin || !url.pathname.startsWith('/api/auth/')) return
    timeline('REQUEST_FAILED', request.method(), url.pathname)
    if (!unexpectedAuthRequests.has(request)) return
    if (mockedAuthRequests.has(request)) {
      unexpectedAuthRequests.delete(request)
      return
    }
    unexpectedAuthRequests.set(request, `${request.method()} ${url.pathname} -> failed`)
  })
  page.on('framenavigated', frame => {
    if (frame !== page.mainFrame()) return
    const url = new URL(frame.url())
    timeline('DOCUMENT', 'GET', `${url.origin}${url.pathname}`)
    if (signOutNavigation && signOutNavigation.replacementStartedAt !== null
      && signOutNavigation.replacementCommittedAt === null && url.href === `${appOrigin}/`) {
      signOutNavigation.replacementCommittedAt = Date.now()
    }
  })

  // Fail and record any backend request this header-focused fixture did not
  // intentionally mock. The app must not silently depend on a live service.
  await page.route(url => url.origin === backendOrigin, route => {
    unmockedApiRequests.push(`${route.request().method()} ${route.request().url()}`)
    return fulfillQualityJson(route, {}, 501)
  })
  await page.route(url => url.origin === appOrigin && url.pathname === '/api/auth/get-session', async route => {
    mockedAuthRequests.add(route.request())
    const isGuest = !authenticated
    await fulfillQualityJson(route, isGuest ? { user: null, session: null } : authenticatedSession)
    sessionReads += 1
    if (isGuest) guestSessionReads += 1
  })
  await page.route(url => url.origin === backendOrigin && url.pathname === '/telemetry/frontend', route =>
    fulfillQualityJson(route, null, 204),
  )
  await page.route(url => url.origin === backendOrigin && url.pathname === '/tenants/resolve-host', route =>
    fulfillQualityJson(route, { tenant: null }),
  )
  await page.route(url => url.origin === backendOrigin && url.pathname === '/portfolio/resolve-domain', route =>
    fulfillQualityJson(route, { profile: null }),
  )
  await page.route(url => url.origin === backendOrigin && url.pathname === '/me', route =>
    fulfillQualityJson(route, { id: 'mobile-account-owner', email: 'mobile@example.com', role: options.role ?? 'user' }),
  )
  // Tests must explicitly grant optional entry points. Missing capabilities
  // stay denied while account recovery and sign-out remain reachable.
  await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', route =>
    fulfillQualityJson(route, { features: options.features ?? {} }),
  )
  await page.route(url => url.origin === backendOrigin && url.pathname === '/config/feature-flags', route =>
    fulfillQualityJson(route, { billing: options.billing ?? true }),
  )
  // Sign-out lands on the homepage, which loads its public pricing catalog.
  await page.route(url => url.origin === backendOrigin && url.pathname === '/subscription/plans', route =>
    fulfillQualityJson(route, QUALITY_PLANS),
  )

  const diagnostics = {
    pageErrors,
    pageErrorDetails,
    browserRequestUrls,
    runId,
    storageKey,
    getSignOutNavigation() { return signOutNavigation },
    async beginSignOutNavigation() {
      const intent = await page.evaluate(() => {
        const control = (window as Window & { __latexySignOutProvenance?: { arm(): { documentId: string; intentAt: number } } }).__latexySignOutProvenance
        if (!control) throw new Error('Sign-out provenance is unavailable')
        return control.arm()
      })
      signOutNavigation = { ...intent, connectionPolicyUnrestricted: platformPolicyUnrestricted,
        postSucceededAt: null, replacementStartedAt: null, replacementCommittedAt: null }
    },
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
  test.afterEach(async ({ page, browserName }, testInfo) => {
    // Finish in-flight mock responses before Playwright closes the page. Do not
    // ignore handler errors: they belong in the test result and diagnostics.
    await page.unrouteAll({ behavior: 'wait' })
    const diagnostics = diagnosticsByPage.get(page)
    if (!diagnostics) return
    const ledger = await page.evaluate(key => {
      const raw = sessionStorage.getItem(key)
      return raw ? JSON.parse(raw) as NavigationLedger : null
    }, diagnostics.storageKey)
    const classification = classifySignOutPageErrors({
      browserName, appOrigin: qualityOrigins().appOrigin, runId: diagnostics.runId,
      ledger, navigation: diagnostics.getSignOutNavigation(), errors: diagnostics.pageErrorDetails,
      browserRequestUrls: diagnostics.browserRequestUrls,
    })

    await testInfo.attach('mobile-account-navigation-diagnostics.json', {
      body: Buffer.from(JSON.stringify({
        pageErrors: diagnostics.pageErrors,
        pageErrorDetails: diagnostics.pageErrorDetails,
        ledger,
        classification,
        signOutNavigation: diagnostics.getSignOutNavigation(),
        browserRequestUrls: diagnostics.browserRequestUrls,
        authTimeline: diagnostics.authTimeline,
        unmockedApiRequests: diagnostics.unmockedApiRequests,
        unexpectedAuthRequests: [...diagnostics.unexpectedAuthRequests.values()],
        sessionReads: diagnostics.getSessionReads(),
        guestSessionReads: diagnostics.getGuestSessionReads(),
      }, null, 2)),
      contentType: 'application/json',
    })
    // Raw errors remain attached. Only positively proven upstream refusals
    // are classified; genuine window/rejection/CSP errors always fail.
    expect(ledger?.version).toBe(1)
    expect(ledger?.runId).toBe(diagnostics.runId)
    expect(ledger?.overflow).toBe(false)
    expect(ledger?.documents.length ?? 0).toBeGreaterThan(0)
    expect(ledger?.documents.flatMap(doc => doc.windowErrors) ?? []).toEqual([])
    expect(classification.unclassified).toEqual([])
    expect(diagnostics.unmockedApiRequests).toEqual([])
    expect([...diagnostics.unexpectedAuthRequests.values()]).toEqual([])
  })

  test('authenticated users can reach account controls, use the keyboard trap, and sign out', async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: true, features: { a09: true } })
    let signOutCalls = 0
    const { appOrigin } = qualityOrigins()
    const signOutMethods: string[] = []
    await page.route(url => url.origin === appOrigin && url.pathname === '/api/auth/sign-out', route => {
      fixture.markMockedAuthRequest(route.request())
      signOutCalls += 1
      signOutMethods.push(route.request().method())
      fixture.setAuthenticated(false)
      return fulfillQualityJson(route, {})
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
    await fixture.beginSignOutNavigation()
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
    const signOutDocument = await page.evaluate(({ storageKey, documentId }) => {
      const raw = sessionStorage.getItem(storageKey)
      const ledger = raw ? JSON.parse(raw) as NavigationLedger : null
      return ledger?.documents.find(doc => doc.id === documentId) ?? null
    }, { storageKey: fixture.storageKey, documentId: fixture.getSignOutNavigation()!.documentId })
    expect(signOutDocument).not.toBeNull()
    // Transient-menu destinations must not enqueue speculative /byok or /terms
    // work before sign-out, either. Keep the strict error classifier unchanged.
    expect(signOutDocument?.fetches).toEqual([])
    expect(signOutCalls).toBe(1)
  })

  test('guests see login actions without authenticated account controls', async ({ page }) => {
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: false, features: { a09: true, b04: true } })
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()

    await expect(page.getByRole('link', { name: 'Log In', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Try Free', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Templates', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'AI Providers', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Sign Out', exact: true })).toHaveCount(0)
  })

  test('account links still navigate on click without speculative route loads', async ({ page }) => {
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: true, features: { a09: true } })
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    await page.getByRole('link', { name: 'Terms', exact: true }).click()
    await expect(page).toHaveURL(/\/terms$/)
    await expect(page.getByRole('heading', { name: 'Terms of Service', level: 1 })).toBeVisible()
    await page.waitForLoadState('networkidle')
    const prefetches = await page.evaluate(storageKey => {
      const raw = sessionStorage.getItem(storageKey)
      const ledger = raw ? JSON.parse(raw) as NavigationLedger : null
      return ledger?.documents.flatMap(doc => doc.fetches) ?? null
    }, fixture.storageKey)
    expect(prefetches).toEqual([])
  })

  test('guests with Studio disabled retain login but no optional Studio or template entry points', async ({ page }) => {
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: false })
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()

    await expect(page.getByRole('link', { name: 'Log In', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Try Free', exact: true })).toHaveCount(0)
    await expect(page.locator('a[href="/try"]')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Templates', exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Sign Out', exact: true })).toHaveCount(0)
  })

  test('non-admin accounts do not gain admin or disabled billing links', async ({ page }) => {
    await page.setViewportSize({ width: 627, height: 780 })
    const fixture = await mockHeaderDependencies(page, { authenticated: true, role: 'user', billing: false })
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await waitForHeaderSession(page, fixture)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()

    await expect(page.getByRole('link', { name: 'Settings', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'AI Providers', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Sign Out', exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Studio', exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Admin', exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Billing', exact: true })).toHaveCount(0)
  })
})
