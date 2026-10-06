import { expect, test, type Page } from '@playwright/test'

const SESSION = {
  a: {
    session: { id: 'settings-passkey-session-a', userId: 'settings-passkey-owner-a', token: 'settings-passkey-token-a' },
    user: { id: 'settings-passkey-owner-a', email: 'owner-a@example.invalid', name: 'Alice' },
  },
  b: {
    session: { id: 'settings-passkey-session-b', userId: 'settings-passkey-owner-b', token: 'settings-passkey-token-b' },
    user: { id: 'settings-passkey-owner-b', email: 'owner-b@example.invalid', name: 'Bob' },
  },
} as const

type Owner = keyof typeof SESSION

type FixtureOptions = {
  deferredAOutcome?: 'success' | 'error'
  distinguishAbaResponses?: boolean
}

type Fixture = {
  owner: { current: Owner }
  sessionOwners: Owner[]
  passkeyOwners: Owner[]
  githubBSeen: () => boolean
  releaseDeferredA: () => void
  waitForDeferredA: Promise<void>
  releaseDeferredTwoFactorA: () => void
  waitForTwoFactorAStarted: Promise<void>
  pageErrors: string[]
}

function passkeys(owner: Owner, name = owner === 'a' ? 'Owner A passkey' : 'Owner B passkey') {
  return [{
      id: `passkey-${owner}`,
      name,
      createdAt: '2026-10-06T00:00:00.000Z',
    }]
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

async function installSettingsFixture(page: Page, options: FixtureOptions = {}): Promise<Fixture> {
  const owner = { current: 'a' as Owner }
  const sessionOwners: Owner[] = []
  const passkeyOwners: Owner[] = []
  let githubBSeen = false
  const pageErrors: string[] = []
  let releaseDeferredA!: () => void
  const waitForDeferredA = new Promise<void>((resolve) => { releaseDeferredA = resolve })
  let markTwoFactorAStarted!: () => void
  const waitForTwoFactorAStarted = new Promise<void>((resolve) => { markTwoFactorAStarted = resolve })
  let releaseDeferredTwoFactorA!: () => void
  const waitForDeferredTwoFactorA = new Promise<void>((resolve) => { releaseDeferredTwoFactorA = resolve })
  let aRequestCount = 0
  let deferredTwoFactorAStarted = false

  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('response', (response) => {
    if (response.status() >= 500) console.log(`[diagnostic-http-${response.status()}] ${new URL(response.url()).pathname}`)
  })

  // Better Auth may parse either the original response or a clone. Mark both
  // paths only after JSON/text consumption, which is later than route.fulfill
  // and provides a real application body-read barrier.
  await page.addInitScript(() => {
    const markBodyRead = (response: Response, label: string) => {
      let marked = false
      const mark = () => {
        if (marked) return
        marked = true
        const reads = (window as typeof window & { __latexySecurityBodyReads?: string[] }).__latexySecurityBodyReads ??= []
        const owner = response.headers.get('x-test-owner') ?? 'unknown'
        reads.push(label === 'passkey' ? owner : `${label}:${owner}`)
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
      const requestUrl = typeof args[0] === 'string' ? args[0] : args[0] instanceof Request ? args[0].url : args[0].toString()
      if (requestUrl.includes('/api/auth/passkey/list-user-passkeys')) markBodyRead(response, 'passkey')
      if (requestUrl.includes('/api/auth/two-factor/enable')) markBodyRead(response, 'two-factor')
      return response
    }
  })
  // New empty browser contexts: permit only the local app shell and the
  // explicitly mocked API routes below. Any unexpected network/provider call
  // fails closed instead of making this ownership test pass accidentally.
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
    sessionOwners.push(current)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION[current]) })
  })

  await page.route('**/api/auth/two-factor/enable', async (route) => {
    const current = owner.current
    if (current === 'a' && !deferredTwoFactorAStarted) {
      deferredTwoFactorAStarted = true
      markTwoFactorAStarted()
      await waitForDeferredTwoFactorA
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'x-test-owner': current },
      body: JSON.stringify({
        totpURI: `otpauth://totp/Latexy:${current}@example.invalid?secret=${current.toUpperCase()}TESTSECRET`,
        backupCodes: [`${current}-backup-code-1`, `${current}-backup-code-2`],
      }),
    })
  })

  await page.route('**/api/auth/passkey/list-user-passkeys', async (route) => {
    const current = owner.current
    passkeyOwners.push(current)
    const requestA = current === 'a'
    const firstA = requestA && aRequestCount === 0
    if (requestA) aRequestCount += 1
    if (firstA) {
      await waitForDeferredA
    }
    const responseName = options.distinguishAbaResponses && requestA
      ? (aRequestCount === 1 ? 'Owner A stale passkey' : 'Owner A current passkey')
      : undefined
    if (firstA && options.deferredAOutcome === 'error') {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        headers: { 'x-test-owner': current },
        body: JSON.stringify({ error: { message: 'Synthetic passkey list failure' } }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'x-test-owner': current },
      body: JSON.stringify(passkeys(current, responseName)),
    })
  })

  await page.route((url) => url.pathname === '/me' || url.pathname === '/me/preferences', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(me(owner.current)) })
  })
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
  await page.route('**/github/status', async (route) => {
    const authorization = await route.request().headerValue('authorization')
    if (authorization === 'Bearer settings-passkey-token-b') githubBSeen = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(authorization === 'Bearer settings-passkey-token-b'
        ? { connected: true, username: 'BobGitHub', public_import: true, private_sync: false }
        : { connected: false, username: null, public_import: false, private_sync: false }),
    })
  })
  for (const provider of ['zotero', 'mendeley', 'dropbox', 'google-drive']) {
    await page.route(`**/${provider}/status`, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connected: false }) }))
  }
  await page.route((url) => url.pathname === '/config/feature-flags', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }))
  await page.route((url) => url.pathname === '/config/entitlements', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: {} }) }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ tenant: null }) }))
  await page.route('**/ws/**', (route) => route.abort())

  return { owner, sessionOwners, passkeyOwners, githubBSeen: () => githubBSeen, releaseDeferredA, waitForDeferredA, releaseDeferredTwoFactorA, waitForTwoFactorAStarted, pageErrors }
}

async function refreshSession(page: Page) {
  const response = page.waitForResponse((item) => item.url().includes('/api/auth/get-session') && item.status() === 200)
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'diagnostic-owner-switch' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await (await response).finished()
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 100))))
  )
}

async function passkeyBodyReads(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as typeof window & { __latexySecurityBodyReads?: string[] }).__latexySecurityBodyReads?.filter((value) => !value.startsWith('two-factor:')) ?? [])
}

async function securityBodyReads(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as typeof window & { __latexySecurityBodyReads?: string[] }).__latexySecurityBodyReads ?? [])
}

test.describe('settings passkey owner isolation', () => {
  test('ordinary passkey list loads for the current owner', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    fixture.releaseDeferredA()
    const passkeyResponse = page.waitForResponse((response) => response.url().includes('/api/auth/passkey/list-user-passkeys') && response.status() === 200)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await (await passkeyResponse).finished()
    await expect(page.getByRole('button', { name: 'Remove Owner A passkey' })).toBeVisible()
    await expect.poll(() => passkeyBodyReads(page)).toContain('a')
    await expect.poll(() => fixture.pageErrors).toEqual([])
    expect(fixture.passkeyOwners).toContain('a')
  })

  test('retains the current owner security state across a same-owner refresh', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    fixture.releaseDeferredA()
    const passkeyResponse = page.waitForResponse((response) => response.url().includes('/api/auth/passkey/list-user-passkeys') && response.status() === 200)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await (await passkeyResponse).finished()
    await expect(page.getByRole('button', { name: 'Remove Owner A passkey' })).toBeVisible()

    await page.getByLabel('Current password for two-factor setup').fill('same-owner-private-draft')
    await page.getByLabel('Passkey name').fill('same-owner-passkey-draft')
    await refreshSession(page)
    await settle(page)
    await expect(page.getByRole('button', { name: 'Remove Owner A passkey' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove Owner B passkey' })).toHaveCount(0)
    await expect(page.getByLabel('Current password for two-factor setup')).toHaveValue('same-owner-private-draft')
    await expect(page.getByLabel('Passkey name')).toHaveValue('same-owner-passkey-draft')
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('shows the ordinary current-owner passkey error without leaking another owner state', async ({ page }) => {
    const fixture = await installSettingsFixture(page, { deferredAOutcome: 'error' })
    const passkeyResponse = page.waitForResponse((response) => response.url().includes('/api/auth/passkey/list-user-passkeys') && response.status() === 500)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => fixture.passkeyOwners).toContain('a')
    fixture.releaseDeferredA()
    await (await passkeyResponse).finished()
    await expect(page.getByText('Could not load passkeys.', { exact: true })).toBeVisible()
    await expect.poll(() => passkeyBodyReads(page)).toContain('a')
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('completes synthetic two-factor setup with QR/manual URI and backup codes', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    fixture.releaseDeferredA()
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Current password for two-factor setup').fill('synthetic-password')
    await page.getByRole('button', { name: 'Set up authenticator' }).click()
    await expect(fixture.waitForTwoFactorAStarted).resolves.toBeUndefined()
    fixture.releaseDeferredTwoFactorA()
    await expect(page.getByText('otpauth://totp/Latexy:a@example.invalid', { exact: false })).toBeVisible()
    await expect(page.getByText('a-backup-code-1', { exact: true })).toBeVisible()
    await expect(page.getByRole('img', { name: 'Authenticator setup QR code' })).toBeVisible()
    await expect.poll(() => securityBodyReads(page)).toContain('two-factor:a')
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('clears private two-factor drafts when a deferred A action is followed by B', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    fixture.releaseDeferredA()
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Current password for two-factor setup').fill('a-only-password')
    await page.getByLabel('Passkey name').fill('A-only passkey draft')
    await page.getByRole('button', { name: 'Set up authenticator' }).click()
    await expect(fixture.waitForTwoFactorAStarted).resolves.toBeUndefined()

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.sessionOwners).toContain('b')
    await expect.poll(() => fixture.githubBSeen()).toBe(true)

    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    const actionResponse = page.waitForResponse((response) => response.url().includes('/api/auth/two-factor/enable') && response.status() === 200)
    fixture.releaseDeferredTwoFactorA()
    await (await actionResponse).finished()
    await expect.poll(() => securityBodyReads(page)).toContain('two-factor:a')
    await settle(page)
    const staleUriCount = await page.getByText('otpauth://totp/Latexy:a@example.invalid', { exact: false }).count()
    const staleBackupCodeCount = await page.getByText('a-backup-code-1', { exact: true }).count()
    console.log(`[diagnostic-stale-mfa-uri-count] ${staleUriCount}`)
    console.log(`[diagnostic-stale-mfa-backup-count] ${staleBackupCodeCount}`)
    expect(staleBackupCodeCount).toBe(0)
    expect(staleUriCount).toBe(0)
    await expect(page.getByLabel('Current password for two-factor setup')).toHaveValue('')
    await expect(page.getByLabel('Passkey name')).toHaveValue('')
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('rejects deferred owner-A passkey rows after retained A→B session switch', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => fixture.passkeyOwners).toContain('a')

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.sessionOwners).toContain('b')
    expect(fixture.sessionOwners[fixture.sessionOwners.length - 1]).toBe('b')
    await expect.poll(() => fixture.githubBSeen()).toBe(true)
    await expect(page.getByText('BobGitHub', { exact: true })).toBeVisible()

    const passkeyResponse = page.waitForResponse((response) => response.url().includes('/api/auth/passkey/list-user-passkeys') && response.status() === 200)
    fixture.releaseDeferredA()
    await (await passkeyResponse).finished()
    await expect.poll(() => passkeyBodyReads(page)).toContain('a')
    await settle(page)

    await expect.poll(() => fixture.pageErrors).toEqual([])
    // Once B is applied, B's list must replace the deferred A list.
    await expect(page.getByRole('button', { name: 'Remove Owner B passkey' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove Owner A passkey' })).toHaveCount(0)
  })

  test('rejects the first A response after an A→B→A owner cycle', async ({ page }) => {
    const fixture = await installSettingsFixture(page, { distinguishAbaResponses: true })
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => fixture.passkeyOwners.filter((owner) => owner === 'a')).toHaveLength(1)

    fixture.owner.current = 'b'
    await refreshSession(page)
    await expect.poll(() => fixture.passkeyOwners).toContain('b')
    fixture.owner.current = 'a'
    await refreshSession(page)
    await expect.poll(() => fixture.passkeyOwners.filter((owner) => owner === 'a')).toHaveLength(2)
    await expect(page.getByRole('button', { name: 'Remove Owner A current passkey' })).toBeVisible()

    const staleResponse = page.waitForResponse((response) => response.url().includes('/api/auth/passkey/list-user-passkeys') && response.status() === 200)
    fixture.releaseDeferredA()
    await (await staleResponse).finished()
    await expect.poll(() => passkeyBodyReads(page).then((owners) => owners.filter((owner) => owner === 'a').length)).toBeGreaterThanOrEqual(2)
    await settle(page)
    await expect(page.getByRole('button', { name: 'Remove Owner A current passkey' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove Owner A stale passkey' })).toHaveCount(0)
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })

  test('does not surface a deferred response after the security form unmounts', async ({ page }) => {
    const fixture = await installSettingsFixture(page)
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect.poll(() => fixture.passkeyOwners).toContain('a')
    const staleResponse = page.waitForResponse((response) => response.url().includes('/api/auth/passkey/list-user-passkeys') && response.status() === 200)
    const dashboardNavigation = page.waitForURL('**/dashboard')
    await page.locator('a[href="/dashboard"]').first().click()
    await dashboardNavigation
    fixture.releaseDeferredA()
    await (await staleResponse).finished()
    await expect.poll(() => fixture.pageErrors).toEqual([])
  })
})
