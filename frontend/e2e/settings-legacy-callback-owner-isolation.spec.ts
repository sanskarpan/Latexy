import { expect, test, type BrowserContext, type Page, type Route } from '@playwright/test'

const SESSION = {
  a: {
    session: { id: 'legacy-callback-session-a', userId: 'legacy-callback-owner-a', token: 'legacy-callback-token-a', expiresAt: '2099-01-01T00:00:00.000Z' },
    user: { id: 'legacy-callback-owner-a', email: 'legacy-a@example.invalid', name: 'Alice' },
  },
  b: {
    session: { id: 'legacy-callback-session-b', userId: 'legacy-callback-owner-b', token: 'legacy-callback-token-b', expiresAt: '2099-01-01T00:00:00.000Z' },
    user: { id: 'legacy-callback-owner-b', email: 'legacy-b@example.invalid', name: 'Bob' },
  },
} as const

type Owner = keyof typeof SESSION
type Provider = 'github' | 'zotero' | 'mendeley' | 'dropbox' | 'google-drive'
type Outcome = 'success' | 'failure'

type FixtureOptions = {
  holdLegacyA?: boolean
  holdLegacyB?: boolean
  holdLegacyARevisit?: boolean
  holdInitialA?: boolean
  legacyAOutcome?: Outcome
  legacyACallNumber?: number
}

type Fixture = {
  owner: { current: Owner }
  appOrigin: string
  pageErrors: string[]
  authErrors: string[]
  unexpectedRequests: string[]
  webSocketAttempts: string[]
  providerRequests: Array<{ provider: Provider; owner: Owner; call: number; label: string; tokenVersion: 'initial-a' | 'rotated-a' | 'b' }>
  currentToken: { value: string }
  bodyReads: (page: Page) => string[]
  legacyAStarted: Promise<void>
  releaseLegacyA: () => void
  legacyBStarted: Promise<void>
  releaseLegacyB: () => void
  legacyARevisitStarted: Promise<void>
  releaseLegacyARevisit: () => void
  initialAStarted: Promise<void>
  releaseInitialA: () => void
}

function appBaseUrl(): URL {
  const baseURL = test.info().project.use.baseURL
  if (!baseURL) throw new Error('Playwright project must define baseURL')
  return new URL(baseURL)
}

function apiBaseUrl(appUrl: URL): URL {
  const configured = process.env.PLAYWRIGHT_API_URL
    ?? process.env.PLAYWRIGHT_BACKEND_URL
    ?? `http://127.0.0.1:${Number(appUrl.port) + 2000}`
  return new URL(configured, appUrl)
}

const ROTATED_TOKEN_A = 'legacy-callback-token-a-rotated'

function ownerFromAuthorization(value: string | null): Owner | null {
  if (value === `Bearer ${SESSION.a.session.token}` || value === `Bearer ${ROTATED_TOKEN_A}`) return 'a'
  if (value === `Bearer ${SESSION.b.session.token}`) return 'b'
  return null
}

function bodyLabelHeaders(label: string, appOrigin: string) {
  return {
    'x-test-body-label': label,
    'access-control-expose-headers': 'x-test-body-label',
    'access-control-allow-origin': appOrigin,
    'access-control-allow-credentials': 'true',
    'access-control-allow-headers': 'authorization, content-type, x-request-id, traceparent',
    'access-control-allow-methods': 'GET, OPTIONS',
    vary: 'Origin',
  }
}

function me(owner: Owner) {
  return {
    id: SESSION[owner].user.id,
    email: SESSION[owner].user.email,
    role: 'user',
    plan: 'free',
    preferences: { has_onboarded: true, spell_dictionary: [] },
  }
}

function statusBody(provider: Provider, owner: Owner, call: number, isLegacy = false) {
  const username = owner === 'b'
    ? 'BobGitHub'
    : isLegacy
      ? 'AliceLegacyGitHub'
      : call === 1
        ? 'AliceInitialGitHub'
        : call === 3
          ? 'AliceCurrentGitHub'
          : 'AliceRotatedGitHub'
  if (provider === 'github') {
    return { connected: true, username, public_import: true, private_sync: false }
  }
  if (provider === 'zotero') {
    return { connected: true, username: owner === 'b' ? 'BobZotero' : `AliceZotero${call}`, user_id: `zotero-${owner}-${call}` }
  }
  if (provider === 'mendeley') {
    return { connected: true, name: owner === 'b' ? 'Bob Mendeley' : `Alice Mendeley ${call}` }
  }
  if (provider === 'dropbox') {
    return { connected: true, display_name: owner === 'b' ? 'Bob Dropbox' : `Alice Dropbox ${call}`, account_id: `dropbox-${owner}-${call}` }
  }
  return { connected: true, scope: 'drive.file' }
}

async function fulfillJson(route: Route, payload: unknown, options: { status?: number; headers?: Record<string, string> } = {}) {
  await route.fulfill({
    status: options.status ?? 200,
    contentType: 'application/json',
    headers: options.headers ?? {},
    body: JSON.stringify(payload),
  })
}

async function installFixture(context: BrowserContext, page: Page, provider: Provider, options: FixtureOptions = {}): Promise<Fixture> {
  const appUrl = appBaseUrl()
  const apiUrl = apiBaseUrl(appUrl)
  const appOrigin = appUrl.origin
  const apiOrigin = apiUrl.origin
  const apiPrefix = apiUrl.pathname.replace(/\/+$/, '')
  const owner = { current: 'a' as Owner }
  const currentToken = { value: SESSION.a.session.token }
  const pageErrors: string[] = []
  const authErrors: string[] = []
  const unexpectedRequests: string[] = []
  const webSocketAttempts: string[] = []
  const providerRequests: Fixture['providerRequests'] = []
  const consumedBodyLabels = new Map<Page, string[]>()
  const counts = new Map<string, number>()
  let releaseLegacyA!: () => void
  let markLegacyAStarted!: () => void
  const legacyAStarted = new Promise<void>((resolve) => { markLegacyAStarted = resolve })
  const legacyARelease = new Promise<void>((resolve) => { releaseLegacyA = resolve })
  let releaseLegacyB!: () => void
  let markLegacyBStarted!: () => void
  const legacyBStarted = new Promise<void>((resolve) => { markLegacyBStarted = resolve })
  const legacyBRelease = new Promise<void>((resolve) => { releaseLegacyB = resolve })
  let releaseLegacyARevisit!: () => void
  let markLegacyARevisitStarted!: () => void
  const legacyARevisitStarted = new Promise<void>((resolve) => { markLegacyARevisitStarted = resolve })
  const legacyARevisitRelease = new Promise<void>((resolve) => { releaseLegacyARevisit = resolve })
  let releaseInitialA!: () => void
  let markInitialAStarted!: () => void
  const initialAStarted = new Promise<void>((resolve) => { markInitialAStarted = resolve })
  const initialARelease = new Promise<void>((resolve) => { releaseInitialA = resolve })

  context.on('page', (openedPage) => openedPage.on('pageerror', (error) => pageErrors.push(error.message)))
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await context.exposeBinding('__recordLegacyCallbackBodyRead', ({ page: sourcePage }, label: string) => {
    const labels = consumedBodyLabels.get(sourcePage) ?? []
    labels.push(label)
    consumedBodyLabels.set(sourcePage, labels)
  })

  await context.addInitScript(() => {
    // Production-asset test shim only: this does not exercise native SW/PWA lifecycle.
    const registration = {
      installing: null,
      waiting: null,
      active: null,
      // `window.open()` first creates an about:blank popup before it navigates.
      // Avoid throwing in that initial document so the callback observer is also installed.
      scope: window.location.protocol === 'about:' ? '' : `${window.location.origin}/`,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      update: async () => registration,
      unregister: async () => true,
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        controller: null,
        register: async () => registration,
        getRegistration: async () => registration,
        getRegistrations: async () => [registration],
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      },
    })
    const state = window as typeof window & { __recordLegacyCallbackBodyRead?: (label: string) => Promise<void> }
    const attachBodyRead = (response: Response): Response => {
      if (!response.headers.get('x-test-body-label')) return response
      let marked = false
      const mark = async () => {
        if (marked) return
        marked = true
        const label = response.headers.get('x-test-body-label')
        if (label && state.__recordLegacyCallbackBodyRead) await state.__recordLegacyCallbackBodyRead(label)
      }
      const originalJson = response.json.bind(response)
      response.json = async () => {
        const value = await originalJson()
        await mark()
        return value
      }
      const originalText = response.text.bind(response)
      response.text = async () => {
        const value = await originalText()
        await mark()
        return value
      }
      const originalArrayBuffer = response.arrayBuffer.bind(response)
      response.arrayBuffer = async () => {
        const value = await originalArrayBuffer()
        await mark()
        return value
      }
      const originalBlob = response.blob.bind(response)
      response.blob = async () => {
        const value = await originalBlob()
        await mark()
        return value
      }
      const originalClone = response.clone.bind(response)
      response.clone = () => attachBodyRead(originalClone())
      return response
    }
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (...args) => attachBodyRead(await originalFetch(...args))
  })

  const unexpected = async (route: Route, reason: string) => {
    const url = new URL(route.request().url())
    unexpectedRequests.push(`${route.request().method()} ${url.origin}${url.pathname} (${reason})`)
    await route.abort('blockedbyclient')
  }

  const referralStatus = {
    available: false,
    scope: 'synthetic-test',
    message: 'Referral status unavailable in this synthetic test.',
    share_code: null,
    your_attribution: null,
    referral_summary: { total: 0, captured: 0, qualified: 0, reversed: 0 },
    reward_summary: { issued: 0, pending: 0, reversed: 0, issued_extension_days: 0 },
    policy_configured: false,
  }

  await context.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method().toUpperCase()
    const pathname = url.pathname
    const apiPrefixMatches = Boolean(apiPrefix && (pathname === apiPrefix || pathname.startsWith(`${apiPrefix}/`)))
    const rootApiPath = [
      '/settings/notifications', '/github/status', '/zotero/status', '/mendeley/status',
      '/dropbox/status', '/google-drive/status', '/me', '/me/preferences',
      '/config/feature-flags', '/config/entitlements', '/tenants/resolve-host',
    ].includes(pathname)
    const sameOriginBackendRequest = apiOrigin === appOrigin
      && (apiPrefixMatches || (!apiPrefix && rootApiPath))
      && !pathname.startsWith('/api/auth/')
      && pathname !== '/api/referral'

    if (url.origin === appOrigin && !sameOriginBackendRequest) {
      if (pathname === '/__legacy-callback-test-opener' && method === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: `<!doctype html><button id="open" onclick="const provider=new URLSearchParams(location.search).get('callback')||'zotero';window.open('/settings?'+provider+'=connected','legacy-callback-test')">Open synthetic callback</button><script>window.__messages=[];addEventListener('message',event=>window.__messages.push({origin:event.origin,data:event.data}))</script>`,
        })
        return
      }
      if (pathname === '/api/auth/get-session' && method === 'GET') {
        const session = SESSION[owner.current]
        await fulfillJson(route, {
          ...session,
          session: { ...session.session, token: currentToken.value },
        })
        return
      }
      if (pathname === '/api/auth/passkey/list-user-passkeys' && method === 'GET') {
        await fulfillJson(route, [])
        return
      }
      if (pathname === '/api/referral' && method === 'GET') {
        await fulfillJson(route, referralStatus)
        return
      }
      if (pathname === '/api/referral' && method === 'POST') {
        // AuthSync's optional referral-cookie claim is contained entirely in this synthetic fixture.
        await fulfillJson(route, { claimed: false, message: 'Synthetic fixture: no referral cookie.' })
        return
      }
      if (method === 'GET' && !pathname.startsWith('/api/')) {
        await route.continue()
        return
      }
      await unexpected(route, 'unknown app API path or method')
      return
    }

    if (url.origin !== apiOrigin) {
      await unexpected(route, 'external origin')
      return
    }

    const apiPath = apiPrefix && (pathname === apiPrefix || pathname.startsWith(`${apiPrefix}/`))
      ? pathname.slice(apiPrefix.length) || '/'
      : pathname

    if (method === 'OPTIONS') {
      const telemetryPost = apiPath === '/telemetry/frontend'
      const knownRead = [
        '/settings/notifications', '/github/status', '/zotero/status', '/mendeley/status',
        '/dropbox/status', '/google-drive/status', '/me', '/me/preferences',
        '/config/feature-flags', '/config/entitlements', '/tenants/resolve-host',
      ].includes(apiPath)
      const providerStatus = ['github', 'zotero', 'mendeley', 'dropbox', 'google-drive']
        .some((name) => apiPath === `/${name}/status`)
      if (!knownRead && !providerStatus && !telemetryPost) {
        await unexpected(route, 'unknown API preflight')
        return
      }
      await route.fulfill({
        status: 204,
        headers: {
          'access-control-allow-origin': appOrigin,
          'access-control-allow-credentials': 'true',
          'access-control-allow-headers': 'authorization, content-type, x-request-id, traceparent',
          'access-control-allow-methods': telemetryPost ? 'POST, OPTIONS' : 'GET, OPTIONS',
          vary: 'Origin',
        },
      })
      return
    }

    if (apiPath === '/telemetry/frontend' && method === 'POST') {
      // Web-vitals/page-view telemetry is explicitly synthetic and never reaches a real service.
      await route.fulfill({ status: 204, headers: { 'access-control-allow-origin': appOrigin, 'access-control-allow-credentials': 'true' } })
      return
    }

    if (method !== 'GET') {
      await unexpected(route, 'API writes are not part of this callback test')
      return
    }

    if (apiPath === '/settings/notifications') {
      const current = ownerFromAuthorization(await request.headerValue('authorization'))
      if (!current) {
        authErrors.push('/settings/notifications missing synthetic bearer')
        await fulfillJson(route, { detail: 'Synthetic fixture requires a known bearer.' }, { status: 401, headers: bodyLabelHeaders('notifications-unauthorized', appOrigin) })
        return
      }
      await fulfillJson(route, { job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false, tracker_updates: true, comment_mentions: true }, { headers: bodyLabelHeaders('notifications', appOrigin) })
      return
    }
    if (apiPath === '/me' || apiPath === '/me/preferences') {
      const current = ownerFromAuthorization(await request.headerValue('authorization'))
      if (!current) {
        authErrors.push(`${apiPath} missing synthetic bearer`)
        await fulfillJson(route, { detail: 'Synthetic fixture requires a known bearer.' }, { status: 401, headers: bodyLabelHeaders('me-unauthorized', appOrigin) })
        return
      }
      await fulfillJson(route, me(current), { headers: bodyLabelHeaders(`me-${current}`, appOrigin) })
      return
    }
    if (apiPath === '/config/feature-flags') {
      await fulfillJson(route, {}, { headers: bodyLabelHeaders('feature-flags', appOrigin) })
      return
    }
    if (apiPath === '/config/entitlements') {
      await fulfillJson(route, { features: {} }, { headers: bodyLabelHeaders('entitlements', appOrigin) })
      return
    }
    if (apiPath === '/tenants/resolve-host') {
      await fulfillJson(route, { tenant: null }, { headers: bodyLabelHeaders('tenant', appOrigin) })
      return
    }
    const statusProvider = (['github', 'zotero', 'mendeley', 'dropbox', 'google-drive'] as const)
      .find((name) => apiPath === `/${name}/status`)
    if (statusProvider) {
      const current = ownerFromAuthorization(await request.headerValue('authorization'))
      if (!current) {
        authErrors.push(`${statusProvider}/status missing synthetic bearer`)
        await fulfillJson(route, { detail: 'Synthetic fixture requires a known bearer.' }, { status: 401, headers: bodyLabelHeaders(`${statusProvider}-unauthorized`, appOrigin) })
        return
      }
      if (statusProvider !== provider) {
        await fulfillJson(route, { connected: false }, { headers: bodyLabelHeaders(`status-${statusProvider}-${current}-disconnected`, appOrigin) })
        return
      }
      const key = `${statusProvider}:${current}`
      const call = (counts.get(key) ?? 0) + 1
      counts.set(key, call)
      const isLegacyARevisit = current === 'a' && call === 4 && options.holdLegacyARevisit
      const isLegacyRequest = call === (options.legacyACallNumber ?? 2) || isLegacyARevisit
      const isInitialA = current === 'a' && call === 1
      const label = isLegacyRequest
        ? `legacy-${statusProvider}-${current}${isLegacyARevisit ? '-revisit' : ''}`
        : `status-${statusProvider}-${current}-${call}`
      const authorization = await request.headerValue('authorization')
      const tokenVersion = current === 'b'
        ? 'b'
        : authorization === `Bearer ${ROTATED_TOKEN_A}`
          ? 'rotated-a'
          : 'initial-a'
      providerRequests.push({ provider: statusProvider, owner: current, call, label, tokenVersion })
      if (isInitialA) {
        markInitialAStarted()
        if (options.holdInitialA) await initialARelease
      }
      if (isLegacyRequest) {
        if (isLegacyARevisit) {
          markLegacyARevisitStarted()
          await legacyARevisitRelease
        } else if (current === 'a') {
          markLegacyAStarted()
          if (options.holdLegacyA) await legacyARelease
        } else {
          markLegacyBStarted()
          if (options.holdLegacyB) await legacyBRelease
        }
      }
      if (current === 'a' && isLegacyRequest && options.legacyAOutcome === 'failure') {
        await fulfillJson(route, { detail: 'Synthetic provider verification failed.' }, { status: 503, headers: bodyLabelHeaders(label, appOrigin) })
        return
      }
      await fulfillJson(route, statusBody(provider, current, call, isLegacyRequest), { headers: bodyLabelHeaders(label, appOrigin) })
      return
    }

    // Only the explicitly modeled read endpoints above may reach this point.
    await unexpected(route, 'unknown API endpoint')
  })

  context.routeWebSocket('**/*', (webSocket) => {
    const url = new URL(webSocket.url())
    webSocketAttempts.push(`${url.origin}${url.pathname}`)
    webSocket.close({ code: 1008, reason: 'No WebSocket is expected in this synthetic Settings test.' })
  })

  return {
    owner,
    appOrigin,
    pageErrors,
    authErrors,
    unexpectedRequests,
    webSocketAttempts,
    providerRequests,
    currentToken,
    bodyReads: (targetPage) => [...(consumedBodyLabels.get(targetPage) ?? [])],
    legacyAStarted,
    releaseLegacyA: () => releaseLegacyA(),
    legacyBStarted,
    releaseLegacyB: () => releaseLegacyB(),
    legacyARevisitStarted,
    releaseLegacyARevisit: () => releaseLegacyARevisit(),
    initialAStarted,
    releaseInitialA: () => releaseInitialA(),
  }
}

function bodyReads(page: Page, fixture: Fixture): string[] {
  return fixture.bodyReads(page)
}

async function refreshSession(page: Page, fixture: Fixture, next: Owner, token?: string) {
  fixture.owner.current = next
  fixture.currentToken.value = token ?? SESSION[next].session.token
  const response = page.waitForResponse((item) => new URL(item.url()).pathname === '/api/auth/get-session' && item.status() === 200)
  await page.evaluate((trigger) => {
    const message = JSON.stringify({ event: 'session', data: { trigger } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  }, `legacy-callback-owner-switch-${next}`)
  await (await response).finished()
}

async function flushEffects(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

async function assertFixtureClean(fixture: Fixture) {
  expect(fixture.authErrors).toEqual([])
  expect(fixture.unexpectedRequests).toEqual([])
  expect(fixture.webSocketAttempts).toEqual([])
  expect(fixture.pageErrors).toEqual([])
}

test.describe('legacy Settings provider callback owner isolation', () => {
  test('same-owner legacy GitHub success applies only after its status body is consumed', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { holdLegacyA: true })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await fixture.legacyAStarted
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    expect(fixture.providerRequests.map(({ owner, call, label }) => ({ owner, call, label }))).toEqual([
      { owner: 'a', call: 1, label: 'status-github-a-1' },
      { owner: 'a', call: 2, label: 'legacy-github-a' },
    ])
    await assertFixtureClean(fixture)
  })

  test('same-owner legacy GitHub verification failure remains actionable without a success notice', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { holdLegacyA: true, legacyAOutcome: 'failure' })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await fixture.legacyAStarted

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('GitHub account authorization completed, but the connection could not be verified. Refresh or try connecting again.', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)
    await assertFixtureClean(fixture)
  })

  test('settled legacy GitHub success notice is cleared after switching to B with no callback query', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github')
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(/\/settings$/)

    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-b-1')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toHaveCount(0)
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0, { timeout: 1_000 })
    await assertFixtureClean(fixture)
  })

  test('settled legacy GitHub verification error is cleared after switching to B with no callback query', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { legacyAOutcome: 'failure' })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText(/authorization completed, but the connection could not be verified/i)).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)
    await expect(page).toHaveURL(/\/settings$/)

    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-b-1')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText(/authorization completed, but the connection could not be verified/i)).toHaveCount(0, { timeout: 1_000 })
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0, { timeout: 1_000 })
    await assertFixtureClean(fixture)
  })

  test('held legacy A success cannot replace B after B status body consumption', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { holdLegacyA: true, holdLegacyB: true })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await fixture.legacyAStarted

    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-b-1')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toHaveCount(0)
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)

    // If the still-present callback query starts a B-owned verification, keep it
    // separate from the released A response and drain it only after these checks.
    await flushEffects(page)
    if (fixture.providerRequests.some(({ label }) => label === 'legacy-github-b')) {
      fixture.releaseLegacyB()
      await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-b')
      await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
      await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    } else {
      fixture.releaseLegacyB()
    }
    await assertFixtureClean(fixture)
  })

  test('held legacy A success cannot replace A after an A→B→A identity transition', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', {
      holdLegacyA: true,
      holdLegacyB: true,
      holdLegacyARevisit: true,
    })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await fixture.legacyAStarted

    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-b-1')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await refreshSession(page, fixture, 'a')
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-3')
    await expect(page.getByText('AliceCurrentGitHub', { exact: true })).toBeVisible()

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('AliceCurrentGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toHaveCount(0)
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)

    await flushEffects(page)
    const hasLegacyB = fixture.providerRequests.some(({ label }) => label === 'legacy-github-b')
    const hasLegacyARevisit = fixture.providerRequests.some(({ label }) => label === 'legacy-github-a-revisit')
    fixture.releaseLegacyB()
    if (hasLegacyB) await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-b')
    fixture.releaseLegacyARevisit()
    if (hasLegacyARevisit) {
      await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a-revisit')
      await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
      await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    }
    await assertFixtureClean(fixture)
  })

  test('deferred legacy A verification failure cannot replace B state or surface A error', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { holdLegacyA: true, holdLegacyB: true, legacyAOutcome: 'failure' })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toBeVisible()
    await fixture.legacyAStarted

    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-b-1')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText(/authorization completed, but the connection could not be verified/i)).toHaveCount(0)
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)

    await flushEffects(page)
    if (fixture.providerRequests.some(({ label }) => label === 'legacy-github-b')) {
      fixture.releaseLegacyB()
      await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-b')
      await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
      await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    } else {
      fixture.releaseLegacyB()
    }
    await assertFixtureClean(fixture)
  })

  test('a delayed initial GitHub status cannot overwrite a verified legacy callback', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { holdInitialA: true })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await fixture.initialAStarted
    await expect(fixture.legacyAStarted).resolves.toBeUndefined()

    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()

    fixture.releaseInitialA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toHaveCount(0)
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    await assertFixtureClean(fixture)
  })

  test('same-owner GitHub legacy callback succeeds after the session token rotates', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { legacyACallNumber: 4 })
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await expect(page.getByText('AliceInitialGitHub', { exact: true })).toBeVisible()

    await refreshSession(page, fixture, 'a', ROTATED_TOKEN_A)
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-2')
    await expect(page.getByText('AliceRotatedGitHub', { exact: true })).toBeVisible()

    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    expect(fixture.providerRequests.find(({ call }) => call === 4)).toMatchObject({
      provider: 'github',
      owner: 'a',
      tokenVersion: 'rotated-a',
    })
    await assertFixtureClean(fixture)
  })

  test('already-dispatched GitHub legacy verification survives same-owner token rotation without replay', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'github', { holdLegacyA: true })
    await page.goto('/settings?github=connected', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-1')
    await fixture.legacyAStarted

    await refreshSession(page, fixture, 'a', ROTATED_TOKEN_A)
    await expect.poll(() => bodyReads(page, fixture)).toContain('status-github-a-3')
    await expect(page.getByText('AliceCurrentGitHub', { exact: true })).toBeVisible()

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(page, fixture)).toContain('legacy-github-a')
    await expect(page.getByText('AliceLegacyGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    expect(fixture.providerRequests.filter(({ label }) => label === 'legacy-github-a')).toEqual([
      expect.objectContaining({ owner: 'a', call: 2, tokenVersion: 'initial-a' }),
    ])
    expect(fixture.providerRequests.some(({ call }) => call === 4)).toBe(false)
    await assertFixtureClean(fixture)
  })

  test('verified legacy Zotero popup callback posts same-origin notice and closes only after body consumption', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'zotero', { holdLegacyA: true })
    await page.goto('/__legacy-callback-test-opener?callback=zotero', { waitUntil: 'domcontentloaded' })
    const popupPromise = context.waitForEvent('page')
    await page.locator('#open').click()
    const popup = await popupPromise
    await popup.waitForURL(/\/settings(?:\?zotero=connected)?$/)
    await expect(popup.getByText('@AliceZotero1', { exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(popup, fixture)).toContain('status-zotero-a-1')
    await fixture.legacyAStarted
    await expect(popup.getByText('Zotero connected successfully!', { exact: true })).toHaveCount(0)

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-zotero-a')
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: Array<{ origin: string; data: unknown }> }).__messages ?? []))
      .toEqual([{ origin: fixture.appOrigin, data: { type: 'zotero:connected' } }])
    await expect.poll(() => popup.isClosed()).toBe(true)
    await assertFixtureClean(fixture)
  })

  test('already-dispatched Zotero popup callback survives same-owner token rotation without replay', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'zotero', { holdLegacyA: true })
    await page.goto('/__legacy-callback-test-opener?callback=zotero', { waitUntil: 'domcontentloaded' })
    const popupPromise = context.waitForEvent('page')
    await page.locator('#open').click()
    const popup = await popupPromise
    await popup.waitForURL(/\/settings(?:\?zotero=connected)?$/)
    await expect.poll(() => bodyReads(popup, fixture)).toContain('status-zotero-a-1')
    await fixture.legacyAStarted

    await refreshSession(popup, fixture, 'a', ROTATED_TOKEN_A)
    await expect.poll(() => bodyReads(popup, fixture)).toContain('status-zotero-a-3')
    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-zotero-a')
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: Array<{ origin: string; data: unknown }> }).__messages ?? []))
      .toEqual([{ origin: fixture.appOrigin, data: { type: 'zotero:connected' } }])
    await expect.poll(() => popup.isClosed()).toBe(true)
    expect(fixture.providerRequests.filter(({ label }) => label === 'legacy-zotero-a')).toEqual([
      expect.objectContaining({ owner: 'a', call: 2, tokenVersion: 'initial-a' }),
    ])
    expect(fixture.providerRequests.find(({ call, label }) => call === 3 && label === 'status-zotero-a-3'))
      .toMatchObject({ tokenVersion: 'rotated-a' })
    expect(fixture.providerRequests.some(({ call }) => call === 4)).toBe(false)
    await assertFixtureClean(fixture)
  })

  test('held Zotero popup callback from A has no effect after B status is consumed', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'zotero', { holdLegacyA: true, holdLegacyB: true })
    await page.goto('/__legacy-callback-test-opener?callback=zotero', { waitUntil: 'domcontentloaded' })
    const popupPromise = context.waitForEvent('page')
    await page.locator('#open').click()
    const popup = await popupPromise
    await popup.waitForURL(/\/settings(?:\?zotero=connected)?$/)
    await expect.poll(() => bodyReads(popup, fixture)).toContain('status-zotero-a-1')
    await fixture.legacyAStarted

    await refreshSession(popup, fixture, 'b')
    await expect.poll(() => bodyReads(popup, fixture)).toContain('status-zotero-b-1')
    await expect(popup.getByText('@BobZotero', { exact: true })).toBeVisible()

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-zotero-a')
    await expect(popup.getByText('@BobZotero', { exact: true })).toBeVisible()
    await expect(popup.getByText('@AliceZotero2', { exact: true })).toHaveCount(0)
    await expect(popup.getByText('Zotero connected successfully!', { exact: true })).toHaveCount(0)
    await expect(popup.getByText(/authorization completed, but the connection could not be verified/i)).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: unknown[] }).__messages ?? [])).toEqual([])
    expect(popup.isClosed()).toBe(false)

    // If the still-present callback query starts B's own verification, drain it
    // only after proving the released A body caused no message or popup close.
    await flushEffects(popup)
    if (fixture.providerRequests.some(({ label }) => label === 'legacy-zotero-b')) {
      fixture.releaseLegacyB()
      await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-zotero-b')
      await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: Array<{ origin: string; data: unknown }> }).__messages ?? []))
        .toEqual([{ origin: fixture.appOrigin, data: { type: 'zotero:connected' } }])
      await expect.poll(() => popup.isClosed()).toBe(true)
    } else {
      fixture.releaseLegacyB()
    }
    await assertFixtureClean(fixture)
  })

  test('failed legacy Zotero verification leaves popup open and sends no success notice', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'zotero', { holdLegacyA: true, legacyAOutcome: 'failure' })
    await page.goto('/__legacy-callback-test-opener?callback=zotero', { waitUntil: 'domcontentloaded' })
    const popupPromise = context.waitForEvent('page')
    await page.locator('#open').click()
    const popup = await popupPromise
    await popup.waitForURL(/\/settings(?:\?zotero=connected)?$/)
    await expect(popup.getByText('@AliceZotero1', { exact: true })).toBeVisible()
    await fixture.legacyAStarted
    fixture.releaseLegacyA()

    await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-zotero-a')
    await expect(popup.getByText(/authorization completed, but the connection could not be verified/i)).toBeVisible()
    await expect(popup.getByText('Zotero connected successfully!', { exact: true })).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: unknown[] }).__messages ?? [])).toEqual([])
    expect(popup.isClosed()).toBe(false)
    await expect(popup).toHaveURL(/\/settings$/)
    await assertFixtureClean(fixture)
  })

  test('verified legacy Mendeley popup callback posts same-origin notice and closes after body consumption', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'mendeley', { holdLegacyA: true })
    await page.goto('/__legacy-callback-test-opener?callback=mendeley', { waitUntil: 'domcontentloaded' })
    const popupPromise = context.waitForEvent('page')
    await page.locator('#open').click()
    const popup = await popupPromise
    await popup.waitForURL(/\/settings(?:\?mendeley=connected)?$/)
    await expect.poll(() => bodyReads(popup, fixture)).toContain('status-mendeley-a-1')
    await fixture.legacyAStarted

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-mendeley-a')
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: Array<{ origin: string; data: unknown }> }).__messages ?? []))
      .toEqual([{ origin: fixture.appOrigin, data: { type: 'mendeley:connected' } }])
    await expect.poll(() => popup.isClosed()).toBe(true)
    await assertFixtureClean(fixture)
  })

  test('failed legacy Mendeley verification keeps popup open without a success notice', async ({ page, context }) => {
    const fixture = await installFixture(context, page, 'mendeley', { holdLegacyA: true, legacyAOutcome: 'failure' })
    await page.goto('/__legacy-callback-test-opener?callback=mendeley', { waitUntil: 'domcontentloaded' })
    const popupPromise = context.waitForEvent('page')
    await page.locator('#open').click()
    const popup = await popupPromise
    await popup.waitForURL(/\/settings(?:\?mendeley=connected)?$/)
    await fixture.legacyAStarted

    fixture.releaseLegacyA()
    await expect.poll(() => bodyReads(popup, fixture)).toContain('legacy-mendeley-a')
    await expect(popup.getByText(/authorization completed, but the connection could not be verified/i)).toBeVisible()
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __messages?: unknown[] }).__messages ?? [])).toEqual([])
    expect(popup.isClosed()).toBe(false)
    await expect(popup).toHaveURL(/\/settings$/)
    await assertFixtureClean(fixture)
  })
})
