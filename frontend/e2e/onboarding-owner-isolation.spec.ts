import { expect, test, type Page, type Request as PlaywrightRequest, type Route } from '@playwright/test'

type Owner = 'A' | 'B'
const ownerId = (owner: Owner) => `onboarding-owner-${owner.toLowerCase()}`
const ownerToken = (owner: Owner, rotated = false) => `onboarding-token-${owner.toLowerCase()}${rotated ? '-rotated' : ''}`

type FixtureOptions = {
  initialOwner: Owner
  onboarded: Record<Owner, boolean>
  sequence?: Partial<Record<Owner, boolean[]>>
  holdInitialMe?: Owner
}

type FixtureState = {
  owner: { current: Owner }
  origins: { app: string; api: string; apiFeatureFlags: string }
  tokens: Record<Owner, string>
  patches: Array<{ owner: Owner; authorization: string | undefined; body: Record<string, unknown> }>
  responseOwners: { me: Owner[]; session: Owner[] }
  meAdmissions: Owner[]
  heldMeRegistrations: Owner[]
  heldMeReadIds: string[]
  stopHoldingMe: () => void
  blockedUnknownRequests: Array<{ method: string; path: string; origin: string; resourceType: string }>
  pageErrors: string[]
  releaseHeldMe: (owner: Owner) => void
}

function meResponse(owner: Owner, hasOnboarded: boolean) {
  return {
    id: ownerId(owner),
    email: `${ownerId(owner)}@example.invalid`,
    plan: 'free',
    role: 'user',
    preferences: { has_onboarded: hasOnboarded },
  }
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
}

async function installFixture(page: Page, options: FixtureOptions): Promise<FixtureState> {
  const state: FixtureState = {
    owner: { current: options.initialOwner },
    origins: { app: '', api: '', apiFeatureFlags: '' },
    tokens: { A: ownerToken('A'), B: ownerToken('B') },
    patches: [],
    responseOwners: { me: [], session: [] },
    meAdmissions: [],
    heldMeRegistrations: [],
    heldMeReadIds: [],
    stopHoldingMe: () => {},
    blockedUnknownRequests: [],
    pageErrors: [],
    releaseHeldMe: () => {},
  }
  const pendingMe = new Map<Owner, Array<() => void>>()
  const meCounts: Record<Owner, number> = { A: 0, B: 0 }
  let holdingInitialMe = true
  const baseUrl = new URL(test.info().project.use.baseURL as string)
  const baseOrigin = baseUrl.origin
  const apiUrl = process.env.PLAYWRIGHT_API_URL
    ?? process.env.PLAYWRIGHT_BACKEND_URL
    ?? `http://127.0.0.1:${Number(baseUrl.port || 5182) + 2000}`
  const apiBaseUrl = new URL(apiUrl, baseUrl)
  const apiOrigin = apiBaseUrl.origin
  const apiBasePath = apiBaseUrl.pathname.replace(/\/+$/, '')
  const normalizeApiPath = (pathname: string) => {
    if (!apiBasePath) return pathname
    if (pathname === apiBasePath) return '/'
    return pathname.startsWith(`${apiBasePath}/`) ? pathname.slice(apiBasePath.length) : null
  }
  state.origins = {
    app: baseOrigin,
    api: apiOrigin,
    apiFeatureFlags: new URL(`${apiBasePath}/config/feature-flags`, `${apiOrigin}/`).href,
  }

  const recordBlocked = (request: PlaywrightRequest) => {
    const url = new URL(request.url())
    state.blockedUnknownRequests.push({ method: request.method(), path: url.pathname, origin: url.origin, resourceType: request.resourceType() })
  }

  await page.addInitScript(() => {
    // Clear only once per browser context. Reloads must preserve the scoped
    // completion/replay keys so cross-navigation leakage is actually tested.
    const initialized = '__onboarding_acceptance_storage_initialized'
    if (!sessionStorage.getItem(initialized)) {
      localStorage.removeItem('latexy_onboarding_completed')
      localStorage.removeItem('latexy_onboarding_completed:onboarding-owner-a')
      localStorage.removeItem('latexy_onboarding_completed:onboarding-owner-b')
      localStorage.removeItem('latexy_onboarding_replay:onboarding-owner-a')
      localStorage.removeItem('latexy_onboarding_replay:onboarding-owner-b')
      sessionStorage.setItem(initialized, 'true')
    }
    const state = window as Window & {
      __onboardingAcceptanceReads?: { me: string[]; meReadIds: string[]; session: string[]; sessionTokens: string[] }
    }
    state.__onboardingAcceptanceReads = { me: [], meReadIds: [], session: [], sessionTokens: [] }
    const markBodyRead = (response: Response, marker: 'me' | 'session') => {
      let counted = false
      const mark = () => {
        if (counted) return
        counted = true
        const reads = state.__onboardingAcceptanceReads
        if (!reads) return
        reads[marker].push(response.headers.get('x-onboarding-owner') ?? '')
        if (marker === 'me') reads.meReadIds.push(response.headers.get('x-onboarding-me-read-id') ?? '')
        if (marker === 'session') reads.sessionTokens.push(response.headers.get('x-onboarding-session-token') ?? '')
      }
      const originalJson = response.json.bind(response)
      response.json = async () => { const body = await originalJson(); mark(); return body }
      const originalText = response.text.bind(response)
      response.text = async () => { const body = await originalText(); mark(); return body }
      const originalClone = response.clone.bind(response)
      response.clone = () => {
        const clone = originalClone()
        markBodyRead(clone, marker)
        return clone
      }
    }
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init)
      const request = input instanceof Request ? input : new Request(input, init)
      const pathname = new URL(request.url).pathname
      const marker = pathname === '/me' ? 'me' : pathname === '/api/auth/get-session' ? 'session' : null
      if (request.method !== 'GET' || !marker) return response
      markBodyRead(response, marker)
      return response
    }
  })
  page.on('pageerror', (error) => state.pageErrors.push(error.message))

  // Fail closed before explicit synthetic routes. Only same-origin non-API GET
  // documents/assets may continue; external/API/non-GET traffic is recorded.
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin === baseOrigin && request.method() === 'GET' && !url.pathname.startsWith('/api/')) {
      await route.continue()
      return
    }
    recordBlocked(request)
    await route.abort()
  })

  await page.route((url) => url.origin === baseOrigin && url.pathname === '/api/auth/get-session', async (route) => {
    const request = route.request()
    if (request.method() !== 'GET') {
      recordBlocked(request)
      await route.abort()
      return
    }
    const owner = state.owner.current
    state.responseOwners.session.push(owner)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: {
        'x-onboarding-owner': owner,
        'x-onboarding-session-token': state.tokens[owner],
        'access-control-expose-headers': 'x-onboarding-owner, x-onboarding-session-token',
      },
      body: JSON.stringify({
        session: { id: `onboarding-session-${owner.toLowerCase()}`, userId: ownerId(owner), token: state.tokens[owner], expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: ownerId(owner), email: `${ownerId(owner)}@example.invalid`, name: ownerId(owner) },
      }),
    })
  })

  const backendPaths = new Set([
    '/me', '/me/preferences', '/resumes/', '/jobs/', '/resumes/stats',
    '/subscription/plans', '/config/feature-flags', '/config/entitlements',
    '/tenants/resolve-host', '/settings/notifications',
    '/github/status', '/zotero/status', '/mendeley/status', '/dropbox/status', '/google-drive/status',
    '/templates', '/templates/', '/templates/categories',
  ])
  await page.route((url) => url.origin === apiOrigin && backendPaths.has(normalizeApiPath(url.pathname) ?? ''), async (route: Route) => {
    const request = route.request()
    const path = normalizeApiPath(new URL(request.url()).pathname) ?? ''
    const allowedMethod = path === '/me/preferences' ? 'PATCH' : 'GET'
    if (request.method() !== allowedMethod) {
      recordBlocked(request)
      await route.abort()
      return
    }
    if (path === '/me' && request.method() === 'GET') {
      const authorization = request.headers().authorization
      const owner = authorization === `Bearer ${state.tokens.A}` ? 'A' : authorization === `Bearer ${state.tokens.B}` ? 'B' : null
      expect(owner).not.toBeNull()
      const resolvedOwner = owner as Owner
      state.meAdmissions.push(resolvedOwner)
      const count = meCounts[resolvedOwner]++
      const sequence = options.sequence?.[resolvedOwner] ?? [options.onboarded[resolvedOwner]]
      const heldInitialEpoch = options.holdInitialMe === resolvedOwner && holdingInitialMe
      const hasOnboarded = sequence[heldInitialEpoch ? 0 : Math.min(count, sequence.length - 1)]
      state.responseOwners.me.push(resolvedOwner)
      const waiters = pendingMe.get(resolvedOwner) ?? []
      const readId = `${resolvedOwner}:${count}`
      if (heldInitialEpoch) {
        pendingMe.set(resolvedOwner, waiters)
        state.heldMeRegistrations.push(resolvedOwner)
        state.heldMeReadIds.push(readId)
        await new Promise<void>((resolve) => waiters.push(resolve))
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: {
          'x-onboarding-owner': resolvedOwner,
          'x-onboarding-me-read-id': readId,
          'access-control-expose-headers': 'x-onboarding-owner, x-onboarding-me-read-id',
        },
        body: JSON.stringify(meResponse(resolvedOwner, hasOnboarded)),
      })
      return
    }
    if (path === '/me/preferences') {
      const authorization = request.headers().authorization
      const owner = authorization === `Bearer ${state.tokens.A}` ? 'A' : authorization === `Bearer ${state.tokens.B}` ? 'B' : null
      expect(owner).not.toBeNull()
      state.patches.push({ owner: owner as Owner, authorization, body: (request.postDataJSON() ?? {}) as Record<string, unknown> })
      // Keep the synthetic server preference independent for replay tests; the
      // request payload is captured without making a real account mutation.
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(meResponse(owner as Owner, true)) })
      return
    }
    const bodies: Record<string, unknown> = {
      '/resumes/': { resumes: [], total: 0, page: 1, limit: 20, pages: 0 },
      '/jobs/': { jobs: [] },
      '/resumes/stats': { total_resumes: 0, total_templates: 0, last_updated: null, avg_ats_score: null, best_ats_score: null, optimized_count: 0 },
      '/subscription/plans': { success: true, plans: { free: { compilations: 10, optimizations: 3 } } },
      '/config/feature-flags': {}, '/config/entitlements': { features: {} },
      '/tenants/resolve-host': { tenant: null },
      '/settings/notifications': { job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false, tracker_updates: true, comment_mentions: true },
      '/github/status': { connected: false }, '/zotero/status': { connected: false },
      '/mendeley/status': { connected: false }, '/dropbox/status': { connected: false }, '/google-drive/status': { connected: false },
      '/templates': [], '/templates/': [], '/templates/categories': [],
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bodies[path] ?? {}) })
  })
  state.releaseHeldMe = (owner) => {
    holdingInitialMe = false
    const waiters = pendingMe.get(owner) ?? []
    pendingMe.delete(owner)
    waiters.splice(0).forEach((release) => release())
  }
  state.stopHoldingMe = () => { holdingInitialMe = false }
  await page.route((url) => url.origin === baseOrigin && (url.pathname === '/templates' || url.pathname === '/templates/'), async (route) => {
    const request = route.request()
    const headers = request.headers()
    const navigation = request.resourceType() === 'document' || headers.rsc === '1' || headers['next-router-prefetch'] === '1' || headers.accept?.includes('text/x-component')
    if (request.method() === 'GET' && navigation) return route.continue()
    recordBlocked(request)
    return route.abort()
  })
  await page.route((url) => url.origin === baseOrigin && url.pathname === '/api/auth/passkey/list-user-passkeys', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    recordBlocked(route.request())
    await route.abort()
  })
  await page.route((url) => url.origin === baseOrigin && url.pathname === '/api/referral', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ available: false }) })
      return
    }
    recordBlocked(route.request())
    await route.abort()
  })
  await page.route((url) => url.origin === apiOrigin && normalizeApiPath(url.pathname) === '/telemetry/frontend', async (route) => {
    if (route.request().method() === 'POST') {
      await route.abort()
      return
    }
    recordBlocked(route.request())
    await route.abort()
  })
  const playwrightPort = Number(process.env.PLAYWRIGHT_PORT || baseUrl.port || 5181)
  const websocketBase = process.env.NEXT_PUBLIC_WS_URL
    ?? (process.env.PLAYWRIGHT_REQUIRE_BACKEND
      ? 'ws://localhost:8030'
      : `ws://127.0.0.1:${playwrightPort + 1000}`)
  const websocketBaseUrl = new URL(websocketBase, baseUrl)
  const apiWebSocketOrigin = websocketBaseUrl.origin
  const apiWebSocketPath = `${websocketBaseUrl.pathname.replace(/\/+$/, '')}/ws/jobs`
  await page.routeWebSocket(() => true, (socket) => {
    const url = new URL(socket.url())
    if (url.origin === apiWebSocketOrigin && url.pathname === apiWebSocketPath) {
      socket.close()
      return
    }
    state.blockedUnknownRequests.push({ method: 'WEBSOCKET', path: url.pathname, origin: url.origin, resourceType: 'websocket' })
    socket.close()
  })
  return state
}

async function waitForSessionOwner(page: Page, owner: Owner) {
  await expect(page.getByRole('button', { name: 'Open account menu', exact: true })).toContainText(ownerId(owner))
  await expect.poll(() => page.evaluate(() => (window as Window & { __onboardingAcceptanceReads?: { me: string[]; session: string[]; sessionTokens: string[] } }).__onboardingAcceptanceReads?.session ?? [])).toContain(owner)
}

async function waitForMeOwner(page: Page, owner: Owner) {
  await expect.poll(() => page.evaluate(() => (window as Window & { __onboardingAcceptanceReads?: { me: string[]; session: string[]; sessionTokens: string[] } }).__onboardingAcceptanceReads?.me ?? [])).toContain(owner)
  await settle(page)
}

async function switchOwner(page: Page, state: FixtureState, owner: Owner) {
  state.stopHoldingMe()
  state.owner.current = owner
  await page.evaluate(() => {
    const value = JSON.stringify({ event: 'session', data: { trigger: 'onboarding-acceptance' } })
    localStorage.setItem('better-auth.message', value)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: value }))
  })
  await waitForSessionOwner(page, owner)
}

async function assertClean(state: FixtureState, label: string) {
  expect(state.pageErrors, `${label}: page errors`).toEqual([])
  expect(state.blockedUnknownRequests, `${label}: blocked unknown requests`).toEqual([])
}

// Production-asset synthetic QA only; real service-worker lifecycle is outside
// this fixture. Playwright's serviceWorkers:block makes register() resolve
// undefined, while the production Workbox bundle expects a registration shape.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const registration = {
      installing: null,
      waiting: null,
      active: null,
      scope: new URL('/', window.location.href).href,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      update: async () => registration,
      unregister: async () => true,
    }
    const serviceWorker = {
      controller: null,
      register: async () => registration,
      getRegistration: async () => registration,
      getRegistrations: async () => [registration],
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: serviceWorker,
    })
  })
})

test.describe('onboarding owner-isolation acceptance', () => {
  test('B false displays the tour after session and /me bodies are consumed', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'B', onboarded: { A: true, B: false } })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')
    await waitForMeOwner(page, 'B')
    await expect(page.getByRole('dialog', { name: 'Welcome to Latexy' })).toBeVisible()
    await assertClean(state, 'B false')
  })

  test('B true suppresses the tour without a preseeded local flag', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'B', onboarded: { A: false, B: true } })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')
    await waitForMeOwner(page, 'B')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_onboarding_completed'))).toBeNull()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_onboarding_completed:onboarding-owner-b'))).toBe('true')
    await assertClean(state, 'B true')
  })

  test('A completion does not suppress B false', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'A', onboarded: { A: false, B: false } })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'A')
    await waitForMeOwner(page, 'A')
    await expect(page.getByRole('dialog', { name: 'Welcome to Latexy' })).toBeVisible()
    await page.getByRole('button', { name: 'Skip', exact: true }).first().click()
    await expect.poll(() => state.patches.length).toBe(1)
    expect(state.patches[0]).toMatchObject({ owner: 'A', authorization: `Bearer ${ownerToken('A')}`, body: { has_onboarded: true } })
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_onboarding_completed:onboarding-owner-a'))).toBe('true')
    state.owner.current = 'B'
    await page.reload({ waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')
    await waitForMeOwner(page, 'B')
    await expect(page.getByRole('dialog', { name: 'Welcome to Latexy' })).toBeVisible()
    await assertClean(state, 'A completion then B false')
  })

  test('held server-true reconciliation does not flash the tour', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'B', onboarded: { A: false, B: true }, holdInitialMe: 'B' })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')
    // Header, theme and onboarding each reconcile /me. Hold all three so the
    // control cannot accidentally hold only the unrelated theme request.
    await expect.poll(() => state.heldMeRegistrations.filter((owner) => owner === 'B').length).toBe(3)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    state.releaseHeldMe('B')
    await waitForMeOwner(page, 'B')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await assertClean(state, 'held B true')
  })

  test('ABA owner transition ignores the held old A body', async ({ page }) => {
    const state = await installFixture(page, {
      initialOwner: 'A',
      onboarded: { A: false, B: false },
      sequence: { A: [false, true], B: [false] },
      holdInitialMe: 'A',
    })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'A')
    await expect.poll(() => state.heldMeRegistrations.filter((owner) => owner === 'A').length).toBe(3)
    await switchOwner(page, state, 'B')
    await waitForMeOwner(page, 'B')
    await switchOwner(page, state, 'A')
    await waitForMeOwner(page, 'A')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    state.releaseHeldMe('A')
    for (const readId of state.heldMeReadIds) {
      await expect.poll(() => page.evaluate(() => (window as Window & { __onboardingAcceptanceReads?: { meReadIds: string[] } }).__onboardingAcceptanceReads?.meReadIds ?? [])).toContain(readId)
    }
    await settle(page)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await assertClean(state, 'ABA stale A body')
  })

  test('Settings Replay Tour survives stale server true on Workspace', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'B', onboarded: { A: false, B: true } })
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')
    await waitForMeOwner(page, 'B')
    const settingsBMeReads = await page.evaluate(() => (
      (window as Window & { __onboardingAcceptanceReads?: { me: string[]; session: string[]; sessionTokens: string[] } }).__onboardingAcceptanceReads?.me
        .filter((owner) => owner === 'B').length ?? 0
    ))
    await page.getByRole('button', { name: 'Replay product tour' }).click()
    await expect.poll(() => state.patches.some((patch) => patch.owner === 'B' && patch.body.has_onboarded === false)).toBe(true)
    await page.waitForURL('**/workspace')
    await waitForSessionOwner(page, 'B')
    await expect.poll(() => page.evaluate(() => (
      (window as Window & { __onboardingAcceptanceReads?: { me: string[]; session: string[]; sessionTokens: string[] } }).__onboardingAcceptanceReads?.me
        .filter((owner) => owner === 'B').length ?? 0
    ))).toBeGreaterThan(settingsBMeReads)
    await settle(page)
    await expect(page.getByRole('dialog', { name: 'Welcome to Latexy' })).toBeVisible()
    await assertClean(state, 'Settings replay')
  })

  test('same-owner token refresh preserves the visible tour without another /me read', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'B', onboarded: { A: false, B: false } })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')
    await waitForMeOwner(page, 'B')
    await expect(page.getByRole('dialog', { name: 'Welcome to Latexy' })).toBeVisible()
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    const currentStep = page.getByRole('dialog', { name: 'How Latexy works', exact: true })
    await expect(currentStep.getByText('2 / 4', { exact: true })).toBeVisible()
    const meResponsesBefore = state.responseOwners.me.length
    state.tokens.B = ownerToken('B', true)
    await page.evaluate(() => {
      const value = JSON.stringify({ event: 'session', data: { trigger: 'token-refresh' } })
      localStorage.setItem('better-auth.message', value)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: value }))
    })
    await expect.poll(() => page.evaluate(() => (window as Window & { __onboardingAcceptanceReads?: { me: string[]; session: string[]; sessionTokens: string[] } }).__onboardingAcceptanceReads?.sessionTokens ?? [])).toContain(ownerToken('B', true))
    await settle(page)
    await expect.poll(() => state.responseOwners.me.length).toBe(meResponsesBefore)
    await expect(currentStep.getByText('2 / 4', { exact: true })).toBeVisible()
    await expect(currentStep).toBeVisible()
    await page.getByRole('button', { name: 'Skip', exact: true }).click()
    await expect.poll(() => state.patches.some((patch) => patch.authorization === `Bearer ${ownerToken('B', true)}`)).toBe(true)
    await assertClean(state, 'same-owner token refresh')
  })

  test('fixture rejects external lookalikes and wrong methods without synthetic success', async ({ page }) => {
    const state = await installFixture(page, { initialOwner: 'B', onboarded: { A: false, B: true } })
    await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
    await waitForSessionOwner(page, 'B')

    const attempts = await page.evaluate(async ({ appOrigin, apiFeatureFlags }) => {
      const requests: Array<{ url: string; method: string }> = [
        { url: 'https://onboarding-fixture.invalid/api/auth/get-session', method: 'GET' },
        { url: 'https://onboarding-fixture.invalid/me', method: 'GET' },
        { url: `${appOrigin}/api/auth/get-session`, method: 'POST' },
        { url: `${appOrigin}/api/referral`, method: 'POST' },
        { url: apiFeatureFlags, method: 'POST' },
      ]
      return Promise.all(requests.map(async ({ url, method }) => {
        try {
          const response = await fetch(url, { method })
          return { url, method, fulfilled: true, status: response.status }
        } catch {
          return { url, method, fulfilled: false }
        }
      }))
    }, { appOrigin: state.origins.app, apiFeatureFlags: state.origins.apiFeatureFlags })

    const externalWebSocketOutcome = await page.evaluate(() => new Promise<string>((resolve) => {
      const socket = new WebSocket('wss://onboarding-fixture.invalid/ws/jobs')
      const timer = window.setTimeout(() => resolve('timeout'), 3_000)
      const finish = (outcome: string) => {
        window.clearTimeout(timer)
        resolve(outcome)
      }
      socket.addEventListener('close', () => finish('closed'), { once: true })
      socket.addEventListener('error', () => finish('error'), { once: true })
    }))

    expect(attempts.map(({ fulfilled }) => fulfilled)).toEqual([false, false, false, false, false])
    expect(['closed', 'error']).toContain(externalWebSocketOutcome)
    const expectedBlocked = [
      { method: 'GET', origin: 'https://onboarding-fixture.invalid', path: '/api/auth/get-session' },
      { method: 'GET', origin: 'https://onboarding-fixture.invalid', path: '/me' },
      { method: 'POST', origin: state.origins.app, path: '/api/auth/get-session' },
      { method: 'POST', origin: state.origins.app, path: '/api/referral' },
      { method: 'POST', origin: state.origins.api, path: new URL(state.origins.apiFeatureFlags).pathname },
      { method: 'WEBSOCKET', origin: 'wss://onboarding-fixture.invalid', path: '/ws/jobs' },
    ]
    for (const expected of expectedBlocked) {
      await expect.poll(() => state.blockedUnknownRequests).toContainEqual(expect.objectContaining(expected))
    }
    expect(state.pageErrors).toEqual([])
  })
})
