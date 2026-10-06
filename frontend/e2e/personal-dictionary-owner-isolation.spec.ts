import { expect, test, type Page } from '@playwright/test'

type Owner = 'A' | 'B'
const ownerId = (owner: Owner) => `dictionary-owner-${owner.toLowerCase()}`
const token = (owner: Owner) => `dictionary-token-${owner.toLowerCase()}`
const word = (owner: Owner) => `private-term-${owner.toLowerCase()}`

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

async function fixture(page: Page, options: { holdFirstAReads?: boolean; failAReads?: boolean } = {}) {
  const owner = { current: 'A' as Owner }
  const preferences: Record<Owner, { has_onboarded: boolean; spell_dictionary: string[] }> = {
    A: { has_onboarded: true, spell_dictionary: [word('A')] },
    B: { has_onboarded: true, spell_dictionary: [word('B')] },
  }
  const patches: Array<{ owner: Owner; body: Record<string, unknown> }> = []
  const reads: Owner[] = []
  const heldAReads: Array<() => void> = []
  let holdA = options.holdFirstAReads ?? false
  const pageErrors: string[] = []
  await page.addInitScript(() => {
    const state = window as Window & { __dictionaryHeldBodyReads?: string[] }
    state.__dictionaryHeldBodyReads = []
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init)
      const request = input instanceof Request ? input : new Request(input, init)
      if (request.method !== 'GET' || new URL(request.url).pathname !== '/me') return response
      const heldMarker = response.headers.get('x-dictionary-held')
      if (!heldMarker) return response
      const json = response.json.bind(response)
      const text = response.text.bind(response)
      let counted = false
      const mark = () => {
        if (counted) return
        counted = true
        state.__dictionaryHeldBodyReads?.push(heldMarker)
      }
      response.json = async () => { const body = await json(); mark(); return body }
      response.text = async () => { const body = await text(); mark(); return body }
      return response
    }
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  // New empty browser contexts; no real backend or auth request is permitted.
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'GET' && url.origin === new URL(test.info().project.use.baseURL!).origin && !url.pathname.startsWith('/api/')) {
      return route.continue()
    }
    return route.abort()
  })
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      session: { id: ownerId(owner.current), userId: ownerId(owner.current), token: token(owner.current), expiresAt: '2099-01-01T00:00:00Z' },
      user: { id: ownerId(owner.current), email: `${ownerId(owner.current)}@example.invalid`, name: ownerId(owner.current) },
    }),
  }))
  await page.route((url) => url.pathname === '/me' || url.pathname === '/me/preferences', async route => {
    const requestOwner: Owner = route.request().headers().authorization === `Bearer ${token('B')}` ? 'B' : 'A'
    expect(route.request().headers().authorization).toBe(`Bearer ${token(requestOwner)}`)
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      patches.push({ owner: requestOwner, body })
      preferences[requestOwner] = { ...preferences[requestOwner], ...body } as typeof preferences.A
    } else reads.push(requestOwner)
    if (route.request().method() === 'GET' && requestOwner === 'A' && options.failAReads) {
      return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Synthetic preference read unavailable"}' })
    }
    const responsePreferences = { ...preferences[requestOwner], spell_dictionary: [...preferences[requestOwner].spell_dictionary] }
    let heldMarker: string | null = null
    if (route.request().method() === 'GET' && requestOwner === 'A' && holdA) {
      heldMarker = `held-${heldAReads.length + 1}`
      responsePreferences.spell_dictionary = ['stale-first-a-term']
      await new Promise<void>(resolve => heldAReads.push(resolve))
    }
    await route.fulfill({ status: 200, contentType: 'application/json', headers: heldMarker ? {
      'x-dictionary-held': heldMarker, 'access-control-expose-headers': 'x-dictionary-held',
    } : {}, body: JSON.stringify({
      id: ownerId(requestOwner), role: 'user', plan: 'free', preferences: responsePreferences,
    }) })
  })
  await page.route((url) => url.pathname === '/settings/notifications', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false }),
  }))
  await page.route((url) => /^\/(github|zotero|mendeley|dropbox|google-drive)\/status$/.test(url.pathname), route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ connected: false }),
  }))
  await page.route('**/api/auth/passkey/list-user-passkeys', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/config/feature-flags', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/config/entitlements', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"features":{}}' }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))
  await page.route('**/api/referral', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
    available: false, scope: 'test', message: 'Unavailable in fixture', share_code: null, your_attribution: null,
    referral_summary: { total: 0, captured: 0, qualified: 0, reversed: 0 },
    reward_summary: { issued: 0, pending: 0, reversed: 0, issued_extension_days: 0 }, policy_configured: false,
  }) }))
  return {
    owner, preferences, patches, reads, pageErrors,
    heldCount: () => heldAReads.length,
    allowFreshAReads: () => { holdA = false },
    releaseHeldA: async () => {
      const count = heldAReads.length
      heldAReads.forEach(release => release())
      await expect.poll(() => page.evaluate(() =>
        (window as Window & { __dictionaryHeldBodyReads?: string[] }).__dictionaryHeldBodyReads ?? []))
        .toEqual(expect.arrayContaining(Array.from({ length: count }, (_, index) => `held-${index + 1}`)))
      await settle(page)
    },
  }
}

async function switchOwner(page: Page, state: Awaited<ReturnType<typeof fixture>>, next: Owner) {
  state.owner.current = next
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'dictionary-owner-test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  // Session identity visibly applied, not merely returned by the mock route.
  await expect(page.getByRole('button', { name: 'Open account menu', exact: true })).toContainText(ownerId(next))
}

test('a second account never sees or syncs the first account dictionary on the same device', async ({ page }) => {
  const state = await fixture(page)
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  const dictionary = page.getByRole('list', { name: 'Personal dictionary words' })
  await expect(dictionary.getByText(word('A'), { exact: true })).toBeVisible()
  state.owner.current = 'B'
  await page.reload({ waitUntil: 'domcontentloaded' })
  // B's own visible word is a positive response/application barrier, not a
  // timing-only absence assertion. Inspect both rendered words and PATCH bodies.
  await expect(dictionary.getByText(word('B'), { exact: true })).toBeVisible()
  expect(state.reads).toContain('B')
  const leakedPatches = state.patches.filter(patch => patch.owner === 'B' &&
    Array.isArray(patch.body.spell_dictionary) && patch.body.spell_dictionary.includes(word('A')))
  console.log('DICTIONARY_OWNER_EVIDENCE', JSON.stringify({
    accountBRead: state.reads.includes('B'), accountBLeakedPatchCount: leakedPatches.length,
    accountBDictionary: await dictionary.innerText(), pageErrors: state.pageErrors,
  }))
  await expect(dictionary.getByText(word('A'), { exact: true })).toHaveCount(0)
  expect(leakedPatches).toEqual([])
  expect(state.pageErrors).toEqual([])
})

test('ownerless legacy words are not assigned or uploaded to a signed-in account', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('latexy_spell_dictionary', JSON.stringify(['ownerless-private-term'])))
  const state = await fixture(page)
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  const dictionary = page.getByRole('list', { name: 'Personal dictionary words' })
  await expect(dictionary.getByText(word('A'), { exact: true })).toBeVisible()
  await settle(page)
  await expect(dictionary.getByText('ownerless-private-term', { exact: true })).toHaveCount(0)
  expect(state.patches.some(patch => Array.isArray(patch.body.spell_dictionary) &&
    patch.body.spell_dictionary.includes('ownerless-private-term'))).toBe(false)
  // Retain legacy data for anonymous use; do not delete potentially user-owned words.
  expect(await page.evaluate(() => localStorage.getItem('latexy_spell_dictionary'))).toBe(JSON.stringify(['ownerless-private-term']))
  expect(state.pageErrors).toEqual([])
})

test('retained account switch resets private entry and restores only each owner dictionary', async ({ page }) => {
  const state = await fixture(page)
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  const dictionary = page.getByRole('list', { name: 'Personal dictionary words' })
  await expect(dictionary.getByText(word('A'), { exact: true })).toBeVisible()
  await page.getByLabel('Word to add').fill('unsaved-a-entry')
  await switchOwner(page, state, 'B')
  await expect(page.getByLabel('Word to add')).toHaveValue('')
  await expect(dictionary.getByText(word('B'), { exact: true })).toBeVisible()
  await settle(page)
  await expect(dictionary.getByText(word('A'), { exact: true })).toHaveCount(0)
  await switchOwner(page, state, 'A')
  await expect(dictionary.getByText(word('A'), { exact: true })).toBeVisible()
  await expect(dictionary.getByText(word('B'), { exact: true })).toHaveCount(0)
  expect(state.patches.some(patch => patch.owner === 'B' && Array.isArray(patch.body.spell_dictionary) &&
    patch.body.spell_dictionary.includes(word('A')))).toBe(false)
  expect(state.pageErrors).toEqual([])
})

test('fully consumed first-A responses cannot enter a fresh A dictionary after A→B→A', async ({ page }) => {
  const state = await fixture(page, { holdFirstAReads: true })
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  await expect.poll(state.heldCount).toBeGreaterThanOrEqual(3)
  const dictionary = page.getByRole('list', { name: 'Personal dictionary words' })
  await switchOwner(page, state, 'B')
  await expect(dictionary.getByText(word('B'), { exact: true })).toBeVisible()
  state.allowFreshAReads()
  await switchOwner(page, state, 'A')
  await expect(dictionary.getByText(word('A'), { exact: true })).toBeVisible()
  await state.releaseHeldA()
  await expect(dictionary.getByText('stale-first-a-term', { exact: true })).toHaveCount(0)
  await expect(dictionary.getByText(word('B'), { exact: true })).toHaveCount(0)
  expect(state.patches.some(patch => Array.isArray(patch.body.spell_dictionary) &&
    patch.body.spell_dictionary.includes('stale-first-a-term'))).toBe(false)
  expect(state.pageErrors).toEqual([])
})

test('ordinary account dictionary load and add/remove remain functional', async ({ page }) => {
  const state = await fixture(page)
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  const dictionary = page.getByRole('list', { name: 'Personal dictionary words' })
  await expect(dictionary.getByText(word('A'), { exact: true })).toBeVisible()
  await page.getByLabel('Word to add').fill('ordinary-term')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect.poll(() => state.patches.some(patch => patch.owner === 'A' &&
    Array.isArray(patch.body.spell_dictionary) && patch.body.spell_dictionary.includes('ordinary-term'))).toBe(true)
  await expect(dictionary.getByText('ordinary-term', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Remove ordinary-term from personal dictionary' }).click()
  await expect(dictionary.getByText('ordinary-term', { exact: true })).toHaveCount(0)
  await expect.poll(() => state.patches.some(patch => patch.owner === 'A' &&
    JSON.stringify(patch.body.spell_dictionary) === JSON.stringify([word('A')]))).toBe(true)
  expect(state.pageErrors).toEqual([])
})

test('a failed account sync keeps only its offline words and reports unsynchronized changes', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('latexy_spell_dictionary:account:dictionary-owner-a', JSON.stringify(['offline-private-term'])))
  const state = await fixture(page, { failAReads: true })
  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('list', { name: 'Personal dictionary words' }).getByText('offline-private-term', { exact: true })).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'Your saved dictionary could not be synchronized. Local changes remain on this device.' })).toBeVisible()
  expect(state.patches).toEqual([])
  expect(state.pageErrors).toEqual([])
})
