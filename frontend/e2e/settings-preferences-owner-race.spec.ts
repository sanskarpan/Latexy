import { expect, test, type Page } from '@playwright/test'

const SESSION = {
  a: {
    session: { id: 'settings-preferences-session-a', userId: 'settings-preferences-owner-a', token: 'settings-preferences-token-a' },
    user: { id: 'settings-preferences-owner-a', email: 'owner-a@example.invalid', name: 'Alice' },
  },
  b: {
    session: { id: 'settings-preferences-session-b', userId: 'settings-preferences-owner-b', token: 'settings-preferences-token-b' },
    user: { id: 'settings-preferences-owner-b', email: 'owner-b@example.invalid', name: 'Bob' },
  },
} as const

type Owner = keyof typeof SESSION
type Mode = 'success' | 'error'

type Fixture = {
  owner: { current: Owner; sessionTokens: Record<Owner, string> }
  sessionOwners: Owner[]
  notificationOwners: Array<{ method: string; owner: Owner }>
  githubBSeen: () => boolean
  releaseDeferredA: () => void
  waitForDeferredA: Promise<void>
  releaseDeferredB: () => void
  waitForDeferredB: Promise<void>
  bodyReads: (page: Page) => Promise<string[]>
  failNextNotificationGet: (owner: Owner) => void
  pageErrors: string[]
}

function preferences(owner: Owner, mode: Mode) {
  return {
    job_completed: owner === 'b' ? false : mode === 'error',
    job_failed: true,
    share_viewed: false,
    weekly_digest: false,
    tracker_updates: true,
    comment_mentions: true,
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

async function installSettingsFixture(page: Page, mode: Mode, holdA = false, failInitialGetOwners: Owner[] = [], holdB = false): Promise<Fixture> {
  const owner = {
    current: 'a' as Owner,
    sessionTokens: { a: SESSION.a.session.token, b: SESSION.b.session.token },
  }
  const acceptedSessionTokens: Record<Owner, Set<string>> = {
    a: new Set([SESSION.a.session.token]),
    b: new Set([SESSION.b.session.token]),
  }
  const sessionOwners: Owner[] = []
  const notificationOwners: Array<{ method: string; owner: Owner }> = []
  const pageErrors: string[] = []
  let githubBSeen = false
  let markDeferredAStarted!: () => void
  const waitForDeferredA = new Promise<void>((resolve) => { markDeferredAStarted = resolve })
  let releaseDeferredA!: () => void
  const deferredA = new Promise<void>((resolve) => { releaseDeferredA = resolve })
  let deferredAStarted = false
  let markDeferredBStarted!: () => void
  const waitForDeferredB = new Promise<void>((resolve) => { markDeferredBStarted = resolve })
  let releaseDeferredB!: () => void
  const deferredB = new Promise<void>((resolve) => { releaseDeferredB = resolve })
  let deferredBStarted = false
  const failedGetOwners = new Set(failInitialGetOwners)
  const failNextGetOwners = new Set<Owner>()

  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.addInitScript(() => {
    const state = window as typeof window & { __settingsNotificationBodyReads?: string[] }
    state.__settingsNotificationBodyReads = []
    const markBodyRead = (response: Response, label: string) => {
      let marked = false
      const mark = () => {
        if (marked) return
        marked = true
        const owner = response.headers.get('x-test-owner') ?? 'unknown'
        state.__settingsNotificationBodyReads?.push(`${label}:${owner}`)
      }
      const originalJson = response.json.bind(response)
      response.json = async () => {
        const value = await originalJson()
        mark()
        return value
      }
      const originalText = response.text.bind(response)
      response.text = async () => {
        const value = await originalText()
        mark()
        return value
      }
      const originalClone = response.clone.bind(response)
      response.clone = () => {
        const clone = originalClone()
        markBodyRead(clone, label)
        return clone
      }
    }
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      const request = args[0] instanceof Request
        ? args[0]
        : new Request(args[0], args[1])
      if (new URL(request.url).pathname === '/settings/notifications') {
        markBodyRead(response, request.method.toLowerCase())
      }
      return response
    }
  })

  // Empty browser context: permit only the local app shell and explicitly
  // mocked routes below. Unexpected API/provider traffic fails closed.
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url())
    const baseOrigin = new URL(test.info().project.use.baseURL!).origin
    if (route.request().method() === 'GET' && url.origin === baseOrigin && !url.pathname.startsWith('/api/')) {
      return route.continue()
    }
    return route.abort()
  })

  await page.route('**/api/auth/get-session', async (route) => {
    const current = owner.current
    acceptedSessionTokens[current].add(owner.sessionTokens[current])
    sessionOwners.push(current)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...SESSION[current],
        session: { ...SESSION[current].session, token: owner.sessionTokens[current] },
      }),
    })
  })

  await page.route('**/settings/notifications', async (route) => {
    const authorization = await route.request().headerValue('authorization')
    const requestOwner = acceptedSessionTokens.a.has(authorization?.replace(/^Bearer /, '') ?? '')
      ? 'a'
      : acceptedSessionTokens.b.has(authorization?.replace(/^Bearer /, '') ?? '')
        ? 'b'
        : null
    if (requestOwner === null) throw new Error('Synthetic notification request missing an expected owner bearer')
    const method = route.request().method()
    notificationOwners.push({ method, owner: requestOwner })
    if (method === 'GET' && (failedGetOwners.delete(requestOwner) || failNextGetOwners.delete(requestOwner))) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        headers: { 'x-test-owner': requestOwner, 'access-control-expose-headers': 'x-test-owner' },
        body: JSON.stringify({ detail: 'Synthetic notification read failure' }),
      })
      return
    }
    if (method === 'PUT' && requestOwner === 'a' && holdA && !deferredAStarted) {
      deferredAStarted = true
      markDeferredAStarted()
      await deferredA
      if (mode === 'error') {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          headers: { 'x-test-owner': requestOwner, 'access-control-expose-headers': 'x-test-owner' },
          body: JSON.stringify({ detail: 'Synthetic A preference failure' }),
        })
        return
      }
    }
    if (method === 'PUT' && requestOwner === 'b' && holdB && !deferredBStarted) {
      deferredBStarted = true
      markDeferredBStarted()
      await deferredB
    }
    const responsePreferences = method === 'PUT'
      ? route.request().postDataJSON()
      : preferences(requestOwner, mode)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'x-test-owner': requestOwner, 'access-control-expose-headers': 'x-test-owner' },
      body: JSON.stringify(responsePreferences),
    })
  })

  await page.route('**/api/auth/passkey/list-user-passkeys', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }))
  await page.route((url) => url.pathname === '/me' || url.pathname === '/me/preferences', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(me(owner.current)),
  }))
  await page.route('**/github/status', async (route) => {
    const authorization = await route.request().headerValue('authorization')
    if (authorization === `Bearer ${SESSION.b.session.token}`) githubBSeen = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(authorization === `Bearer ${SESSION.b.session.token}`
        ? { connected: true, username: 'BobGitHub', public_import: true, private_sync: false }
        : { connected: false, username: null, public_import: false, private_sync: false }),
    })
  })
  for (const provider of ['zotero', 'mendeley', 'dropbox', 'google-drive']) {
    await page.route(`**/${provider}/status`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false }),
    }))
  }
  await page.route((url) => url.pathname === '/config/feature-flags', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{}',
  }))
  // A valid denied map keeps this owner-race fixture focused on preferences,
  // rather than introducing a separate transport-error Retry control.
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
  await page.route('**/api/referral', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ available: false, scope: 'test', message: 'Unavailable in diagnostic', share_code: null, your_attribution: null, referral_summary: { total: 0, captured: 0, qualified: 0, reversed: 0 }, reward_summary: { issued: 0, pending: 0, reversed: 0, issued_extension_days: 0 }, policy_configured: false }),
  }))
  await page.route('**/ws/**', (route) => route.abort())

  return {
    owner,
    sessionOwners,
    notificationOwners,
    githubBSeen: () => githubBSeen,
    releaseDeferredA,
    waitForDeferredA,
    releaseDeferredB,
    waitForDeferredB,
    bodyReads: (targetPage) => targetPage.evaluate(() => (window as typeof window & { __settingsNotificationBodyReads?: string[] }).__settingsNotificationBodyReads ?? []),
    failNextNotificationGet: (targetOwner) => { failNextGetOwners.add(targetOwner) },
    pageErrors,
  }
}

async function refreshSession(page: Page, trigger = 'diagnostic-owner-switch') {
  const response = page.waitForResponse((item) => item.url().includes('/api/auth/get-session') && item.status() === 200)
  await page.evaluate((refreshTrigger) => {
    const message = JSON.stringify({ event: 'session', data: { trigger: refreshTrigger } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  }, trigger)
  await (await response).finished()
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 100))))
  )
}

async function waitForInitialPreferences(page: Page, checked: boolean) {
  await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', String(checked))
}

async function navigateThroughAccountMenu(page: Page, destination: 'Dashboard' | 'Settings') {
  await page.getByRole('button', { name: 'Open account menu' }).click()
  await page.getByRole('menuitem', { name: destination, exact: true }).click()
  await page.waitForURL(new RegExp(`/${destination.toLowerCase()}`))
}

test.describe('settings notification preference owner race', () => {
  for (const mode of ['success', 'error'] as const) {
    test(`old A ${mode} cannot release B's pending save or show a stale notice`, async ({ page }) => {
      const fixture = await installSettingsFixture(page, mode, true, [], true)
      try {
        await page.goto('/settings', { waitUntil: 'domcontentloaded' })
        await waitForInitialPreferences(page, mode === 'error')
        await page.getByRole('switch', { name: 'Job completion emails' }).click()
        await fixture.waitForDeferredA

        fixture.owner.current = 'b'
        await refreshSession(page)
        await expect.poll(() => fixture.githubBSeen()).toBe(true)
        await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
        await expect.poll(() => fixture.bodyReads(page)).toContain('get:b')
        await waitForInitialPreferences(page, false)
        const toggle = page.getByRole('switch', { name: 'Job completion emails' })
        await expect(toggle).toBeEnabled()
        await toggle.click()
        await fixture.waitForDeferredB
        await expect(toggle).toBeDisabled()

        fixture.releaseDeferredA()
        await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
        await settle(page)
        await expect(toggle).toBeDisabled()
        await expect(toggle).toHaveAttribute('aria-checked', 'true')
        await expect(page.getByText('Saved', { exact: true })).toHaveCount(0)
        await expect(page.getByText('Synthetic A preference failure', { exact: false })).toHaveCount(0)

        fixture.releaseDeferredB()
        await expect.poll(() => fixture.bodyReads(page)).toContain('put:b')
        await expect(toggle).toBeEnabled()
        await expect(toggle).toHaveAttribute('aria-checked', 'true')
        await expect(page.getByText('Saved', { exact: true })).toBeVisible()
        expect(fixture.notificationOwners.filter((request) => request.method === 'PUT').map((request) => request.owner)).toEqual(['a', 'b'])
        expect(fixture.pageErrors).toEqual([])
      } finally {
        fixture.releaseDeferredA()
        fixture.releaseDeferredB()
      }
    })
  }

  test('ordinary preference success applies to the current owner', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')
    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()
    fixture.releaseDeferredA()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('ordinary preference failure reverts the current owner and shows an error', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'error', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, true)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')
    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()
    fixture.releaseDeferredA()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByText('Synthetic A preference failure', { exact: false })).toBeVisible()
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('fails closed on an initial preference read and retries without exposing defaults', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success', false, ['a'])
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Failed to load preferences.', { exact: true })).toBeVisible()
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveCount(0)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')

    await page.getByRole('button', { name: 'Retry notification preferences' }).click()
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.bodyReads(page).then((reads) => reads.filter((read) => read === 'get:a').length)).toBeGreaterThanOrEqual(2)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('keeps same-owner preferences visible across a refresh read failure and retry', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success')
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    fixture.failNextNotificationGet('a')
    fixture.owner.sessionTokens.a = 'settings-preferences-token-a-refresh-error'
    await refreshSession(page, 'diagnostic-same-owner-refresh-error')
    await expect(page.getByRole('alert').filter({ hasText: 'Failed to load preferences' })).toBeVisible()
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'false')

    await page.getByRole('button', { name: 'Retry notification preferences' }).click()
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('keeps an optimistic toggle when a same-owner refresh returns an older snapshot', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')

    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'true')

    // The refresh response still reports A's old server value (false), while
    // the optimistic A PUT remains in flight. It must not erase the draft.
    fixture.owner.sessionTokens.a = 'settings-preferences-token-a-refresh-optimistic'
    await refreshSession(page, 'diagnostic-same-owner-refresh-optimistic')
    await expect.poll(() => fixture.bodyReads(page).then((reads) => reads.filter((read) => read === 'get:a').length)).toBeGreaterThanOrEqual(2)
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'true')

    fixture.releaseDeferredA()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'true')
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('does not apply a pending PUT after the settings page unmounts', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()

    // Unmount the old SettingsContent, then mount a fresh page before the old
    // response is released. The body-read marker proves the app consumed the
    // deferred response rather than merely waiting for network completion.
    await navigateThroughAccountMenu(page, 'Dashboard')
    await navigateThroughAccountMenu(page, 'Settings')
    await waitForInitialPreferences(page, false)
    fixture.releaseDeferredA()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)

    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'false')
    await expect(page.getByText('Saved', { exact: true })).toHaveCount(0)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('ignores delayed A success after B preferences and identity are applied', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')
    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.sessionOwners).toContain('b')
    await expect.poll(() => fixture.githubBSeen()).toBe(true)
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:b')
    await waitForInitialPreferences(page, false)

    const putResponse = page.waitForResponse((response) => response.url().includes('/settings/notifications') && response.request().method() === 'PUT' && response.status() === 200)
    fixture.releaseDeferredA()
    await (await putResponse).finished()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)
    await expect.poll(() => fixture.pageErrors).toEqual([])
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'false')
    await expect(page.getByText('Saved', { exact: true })).toHaveCount(0)
  })

  test('fails closed while a new owner preference read is unavailable, then accepts the retry', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success')
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    fixture.failNextNotificationGet('b')

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.githubBSeen()).toBe(true)
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect(page.getByText('Failed to load preferences.', { exact: true })).toBeVisible()
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveCount(0)

    await page.getByRole('button', { name: 'Retry notification preferences' }).click()
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.bodyReads(page).then((reads) => reads.filter((read) => read === 'get:b').length)).toBeGreaterThanOrEqual(2)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('ignores delayed A failure after B preferences and identity are applied', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'error', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, true)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')
    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.sessionOwners).toContain('b')
    await expect.poll(() => fixture.githubBSeen()).toBe(true)
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:b')
    await waitForInitialPreferences(page, false)

    const putResponse = page.waitForResponse((response) => response.url().includes('/settings/notifications') && response.request().method() === 'PUT' && response.status() === 503)
    fixture.releaseDeferredA()
    await (await putResponse).finished()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)
    await expect.poll(() => fixture.pageErrors).toEqual([])
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'false')
    await expect(page.getByText('Synthetic A preference failure', { exact: false })).toHaveCount(0)
  })

  test('keeps the fresh A state across an A→B→A cycle before the first A PUT releases', async ({ page }) => {
    const fixture = await installSettingsFixture(page, 'success', true)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await waitForInitialPreferences(page, false)
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:a')
    await page.getByRole('switch', { name: 'Job completion emails' }).click()
    await expect(fixture.waitForDeferredA).resolves.toBeUndefined()

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.githubBSeen()).toBe(true)
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => fixture.bodyReads(page)).toContain('get:b')
    await waitForInitialPreferences(page, false)

    fixture.owner.current = 'a'
    await refreshSession(page)
    await expect.poll(() => fixture.sessionOwners[fixture.sessionOwners.length - 1]).toBe('a')
    await expect.poll(() => fixture.bodyReads(page).then((reads) => reads.filter((read) => read === 'get:a').length)).toBeGreaterThanOrEqual(2)
    await waitForInitialPreferences(page, false)

    const putResponse = page.waitForResponse((response) => response.url().includes('/settings/notifications') && response.request().method() === 'PUT' && response.status() === 200)
    fixture.releaseDeferredA()
    await (await putResponse).finished()
    await expect.poll(() => fixture.bodyReads(page)).toContain('put:a')
    await settle(page)
    await expect.poll(() => fixture.pageErrors).toEqual([])
    await expect(page.getByRole('switch', { name: 'Job completion emails' })).toHaveAttribute('aria-checked', 'false')
  })
})
