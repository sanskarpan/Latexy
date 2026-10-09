import { expect, test, type Page } from '@playwright/test'

const SESSION = {
  a: {
    session: { id: 'provider-action-session-a', userId: 'provider-action-owner-a', token: 'provider-action-token-a' },
    user: { id: 'provider-action-owner-a', email: 'owner-a@example.invalid', name: 'Alice' },
  },
  b: {
    session: { id: 'provider-action-session-b', userId: 'provider-action-owner-b', token: 'provider-action-token-b' },
    user: { id: 'provider-action-owner-b', email: 'owner-b@example.invalid', name: 'Bob' },
  },
} as const

type Owner = keyof typeof SESSION
type FixtureOptions = { retryA?: boolean; holdDisconnectA?: boolean; holdGitHubA?: boolean }

function gate() {
  let release!: () => void
  let markStarted!: () => void
  const wait = new Promise<void>((resolve) => { release = resolve })
  const started = new Promise<void>((resolve) => { markStarted = resolve })
  return { wait, started, release, markStarted }
}

type Fixture = {
  owner: { current: Owner }
  pageErrors: string[]
  googleStatusOwners: Owner[]
  disconnectOwners: Owner[]
  githubCompletions: Owner[]
  authErrors: string[]
  waitForRetryA: Promise<void>
  releaseRetryA: () => void
  armRetryA: () => void
  waitForDisconnectA: Promise<void>
  releaseDisconnectA: () => void
  waitForGitHubA: Promise<void>
  releaseGitHubA: () => void
}

function bodyLabelHeaders(label: string) {
  return {
    'x-test-body-label': label,
    'access-control-expose-headers': 'x-test-body-label',
  }
}

function ownerFromAuthorization(authorization: string | null | undefined): Owner | null {
  if (authorization === `Bearer ${SESSION.a.session.token}`) return 'a'
  if (authorization === `Bearer ${SESSION.b.session.token}`) return 'b'
  return null
}

async function installSettingsFixture(page: Page, options: FixtureOptions = {}): Promise<Fixture> {
  const owner = { current: 'a' as Owner }
  const pageErrors: string[] = []
  const googleStatusOwners: Owner[] = []
  const disconnectOwners: Owner[] = []
  const githubCompletions: Owner[] = []
  const authErrors: string[] = []
  const retryGate = gate()
  const disconnectGate = gate()
  const githubGate = gate()
  let retryArmed = false
  let aStatusCount = 0
  let bStatusCount = 0
  let aDisconnectCount = 0
  let aGitHubCount = 0
  let bGitHubCount = 0

  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.addInitScript(() => {
    const markResponseBodyRead = (response: Response) => {
      const label = response.headers.get('x-test-body-label')
      if (!label) return
      const reads = (window as typeof window & { __providerActionBodyReads?: string[] }).__providerActionBodyReads ??= []
      if (!reads.includes(label)) reads.push(label)
    }
    const responseJson = Response.prototype.json
    Response.prototype.json = async function (...args) {
      const value = await responseJson.apply(this, args)
      markResponseBodyRead(this)
      return value
    }
    const responseText = Response.prototype.text
    Response.prototype.text = async function (...args) {
      const value = await responseText.apply(this, args)
      markResponseBodyRead(this)
      return value
    }
    const markBodyRead = (response: Response) => {
      const label = response.headers.get('x-test-body-label')
      if (!label) return
      let marked = false
      const mark = () => {
        if (marked) return
        marked = true
        const reads = (window as typeof window & { __providerActionBodyReads?: string[] }).__providerActionBodyReads ??= []
        reads.push(label)
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
        markBodyRead(clone)
        return clone
      }
    }
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      const requestUrl = typeof args[0] === 'string'
        ? args[0]
        : args[0] instanceof Request
          ? args[0].url
          : args[0].toString()
      if (requestUrl.includes('/google-drive/status') || requestUrl.includes('/google-drive/disconnect') || requestUrl.includes('/github/complete')) {
        markBodyRead(response)
      }
      return response
    }
  })

  // Only the local app shell and explicitly mocked endpoints are reachable.
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url())
    const baseOrigin = new URL(test.info().project.use.baseURL!).origin
    if (route.request().method() === 'GET' && url.origin === baseOrigin && !url.pathname.startsWith('/api/')) {
      return route.continue()
    }
    return route.abort()
  })
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(SESSION[owner.current]),
  }))
  await page.route('**/api/auth/passkey/list-user-passkeys', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route((url) => url.pathname === '/me' || url.pathname === '/me/preferences', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: SESSION[owner.current].user.id,
      email: SESSION[owner.current].user.email,
      role: 'user',
      plan: 'free',
      preferences: { has_onboarded: true, spell_dictionary: [] },
    }),
  }))
  await page.route('**/settings/notifications', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false, tracker_updates: true, comment_mentions: true }),
  }))
  await page.route('**/api/referral', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ available: false, scope: 'test', message: 'Unavailable in diagnostic', share_code: null, your_attribution: null, referral_summary: { total: 0, captured: 0, qualified: 0, reversed: 0 }, reward_summary: { issued: 0, pending: 0, reversed: 0, issued_extension_days: 0 }, policy_configured: false }),
  }))
  await page.route((url) => url.pathname === '/config/feature-flags', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/config/entitlements', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: {} }) }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tenant: null }) }))
  await page.route('**/ws/**', (route) => route.abort())

  await page.route('**/github/status', async (route) => {
    const current = ownerFromAuthorization(await route.request().headerValue('authorization'))
    if (!current) {
      authErrors.push(`github/status missing or invalid bearer (${owner.current} active)`)
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'invalid synthetic bearer' }) })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false, username: null, public_import: false, private_sync: false, owner: current }),
    })
  })
  await page.route('**/github/complete', async (route) => {
    const current = ownerFromAuthorization(await route.request().headerValue('authorization'))
    if (!current) {
      authErrors.push(`github/complete missing or invalid bearer (${owner.current} active)`)
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'invalid synthetic bearer' }) })
      return
    }
    githubCompletions.push(current)
    aGitHubCount += current === 'a' ? 1 : 0
    bGitHubCount += current === 'b' ? 1 : 0
    if (options.holdGitHubA && current === 'a' && aGitHubCount === 1) {
      githubGate.markStarted()
      await githubGate.wait
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: bodyLabelHeaders(`github-complete-${current}-${current === 'a' ? aGitHubCount : bGitHubCount}`),
      body: JSON.stringify({ success: true, message: `synthetic ${current} completion` }),
    })
  })

  await page.route('**/google-drive/status', async (route) => {
    const current = ownerFromAuthorization(await route.request().headerValue('authorization'))
    if (!current) {
      authErrors.push(`google-drive/status missing or invalid bearer (${owner.current} active)`)
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'invalid synthetic bearer' }) })
      return
    }
    googleStatusOwners.push(current)
    if (current === 'a') aStatusCount += 1
    else bStatusCount += 1
    const statusNumber = current === 'a' ? aStatusCount : bStatusCount
    const label = `drive-status-${current}-${statusNumber}`
    if (options.retryA && current === 'a' && statusNumber === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        headers: bodyLabelHeaders(label),
        body: JSON.stringify({ error: { message: 'Synthetic Drive status failure' } }),
      })
      return
    }
    if (options.retryA && current === 'a' && retryArmed) {
      retryArmed = false
      retryGate.markStarted()
      await retryGate.wait
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: bodyLabelHeaders('drive-status-a-retry'),
        body: JSON.stringify({ connected: true, scope: 'drive.file' }),
      })
      return
    }
    const connected = !options.retryA
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: bodyLabelHeaders(label),
      body: JSON.stringify({ connected, scope: connected ? 'drive.file' : null }),
    })
  })
  for (const provider of ['zotero', 'mendeley', 'dropbox']) {
    await page.route(`**/${provider}/status`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false }),
    }))
  }
  await page.route('**/google-drive/disconnect', async (route) => {
    const current = ownerFromAuthorization(await route.request().headerValue('authorization'))
    if (!current) {
      authErrors.push(`google-drive/disconnect missing or invalid bearer (${owner.current} active)`)
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'invalid synthetic bearer' }) })
      return
    }
    disconnectOwners.push(current)
    if (current === 'a') aDisconnectCount += 1
    const label = `drive-disconnect-${current}-${current === 'a' ? aDisconnectCount : disconnectOwners.length}`
    if (options.holdDisconnectA && current === 'a' && aDisconnectCount === 1) {
      disconnectGate.markStarted()
      await disconnectGate.wait
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: bodyLabelHeaders(label),
      body: JSON.stringify({ success: true, message: 'synthetic disconnect success' }),
    })
  })

  return {
    owner,
    pageErrors,
    googleStatusOwners,
    disconnectOwners,
    githubCompletions,
    authErrors,
    waitForRetryA: retryGate.started,
    releaseRetryA: retryGate.release,
    armRetryA: () => { retryArmed = true },
    waitForDisconnectA: disconnectGate.started,
    releaseDisconnectA: disconnectGate.release,
    waitForGitHubA: githubGate.started,
    releaseGitHubA: githubGate.release,
  }
}

async function bodyReads(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as typeof window & { __providerActionBodyReads?: string[] }).__providerActionBodyReads ?? [])
}

async function refreshSession(page: Page, fixture: Fixture, next: Owner) {
  fixture.owner.current = next
  const response = page.waitForResponse((item) => item.url().includes('/api/auth/get-session') && item.status() === 200)
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'provider-action-owner-switch' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await (await response).finished()
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 100)))))
}

test.describe('Settings provider action owner isolation in a real browser', () => {
  test('held Drive retry success for A cannot overwrite B after an account switch', async ({ page }) => {
    const fixture = await installSettingsFixture(page, { retryA: true })
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Google Drive export' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
    await expect.poll(() => bodyReads(page)).toContain('drive-status-a-1')

    fixture.armRetryA()
    await page.getByRole('button', { name: 'Retry' }).click()
    await fixture.waitForRetryA
    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page)).toContain('drive-status-b-1')
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toBeDisabled()

    fixture.releaseRetryA()
    await expect.poll(() => bodyReads(page)).toContain('drive-status-a-retry')
    await settle(page)
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toHaveCount(0)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('held Drive disconnect A→B cannot overwrite B after the response body is consumed', async ({ page }) => {
    const fixture = await installSettingsFixture(page, { holdDisconnectA: true })
    page.on('dialog', (dialog) => dialog.accept())
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page)).toContain('drive-status-a-1')

    await page.getByRole('button', { name: 'Disconnect Google Drive', exact: true }).click()
    await fixture.waitForDisconnectA
    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page)).toContain('drive-status-b-1')
    await settle(page)
    await expect(page.getByText('Google Drive connected', { exact: true })).toBeVisible()

    fixture.releaseDisconnectA()
    await expect.poll(() => bodyReads(page)).toContain('drive-disconnect-a-1')
    await settle(page)
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toHaveCount(0)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('held Drive disconnect A→B→A cannot overwrite A after its fresh status read', async ({ page }) => {
    const fixture = await installSettingsFixture(page, { holdDisconnectA: true })
    page.on('dialog', (dialog) => dialog.accept())
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page)).toContain('drive-status-a-1')

    await page.getByRole('button', { name: 'Disconnect Google Drive', exact: true }).click()
    await fixture.waitForDisconnectA
    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page)).toContain('drive-status-b-1')
    await settle(page)
    await expect(page.getByText('Google Drive connected', { exact: true })).toBeVisible()
    await refreshSession(page, fixture, 'a')
    await expect.poll(() => bodyReads(page)).toContain('drive-status-a-2')
    await settle(page)
    await expect(page.getByText('Google Drive connected', { exact: true })).toBeVisible()

    fixture.releaseDisconnectA()
    await expect.poll(() => bodyReads(page)).toContain('drive-disconnect-a-1')
    await settle(page)
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toHaveCount(0)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('same-owner Drive disconnect applies its synthetic success', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    page.on('dialog', (dialog) => dialog.accept())
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Disconnect Google Drive', exact: true }).click()
    await expect.poll(() => bodyReads(page)).toContain('drive-disconnect-a-1')
    await settle(page)
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Connect Google Drive(?: \(Unavailable\))?$/ })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Disconnect Google Drive', exact: true })).toHaveCount(0)
    expect(fixture.disconnectOwners).toEqual(['a'])
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('same-owner GitHub callback dispatches once with the fixture owner token', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    await page.goto('/settings?github=complete&ticket=test-ticket', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toBeVisible()
    await expect.poll(() => bodyReads(page)).toContain('github-complete-a-1')
    expect(fixture.githubCompletions).toEqual(['a'])
    expect(fixture.authErrors).toEqual([])
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('held GitHub completion for A does not report success or change location after switching to B', async ({ page }) => {
    const fixture = await installSettingsFixture(page, { holdGitHubA: true })
    await page.goto('/settings?github=complete&ticket=test-ticket', { waitUntil: 'domcontentloaded' })
    await fixture.waitForGitHubA
    const originalOrigin = new URL(page.url()).origin

    await refreshSession(page, fixture, 'b')
    await expect.poll(() => bodyReads(page)).toContain('drive-status-b-1')
    fixture.releaseGitHubA()
    await expect.poll(() => bodyReads(page)).toContain('github-complete-a-1')
    await settle(page)
    await expect(page.getByText('GitHub account connected successfully!', { exact: true })).toHaveCount(0)
    expect(fixture.githubCompletions).toEqual(['a'])
    expect(fixture.authErrors).toEqual([])
    expect(new URL(page.url()).origin).toBe(originalOrigin)
    expect(new URL(page.url()).pathname).toBe('/settings')
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })
})
