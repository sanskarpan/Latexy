import { expect, test, type Page } from '@playwright/test'

const OWNER_A = 'workspace-owner-a'
const OWNER_B = 'workspace-owner-b'
const RESUME_A = 'aaaa0001-0001-0001-0001-000000000001'
const VARIANT_A = 'variant-from-owner-a'

function resume(ownerId: string, title: string, id = RESUME_A) {
  return {
    id,
    user_id: ownerId,
    title,
    latex_content: `\\documentclass{article}\\begin{document}${title}\\end{document}`,
    is_template: false,
    tags: [],
    parent_resume_id: null,
    variant_count: 0,
    share_token: null,
    share_url: null,
    created_at: '2026-10-04T00:00:00Z',
    updated_at: '2026-10-04T00:00:00Z',
    metadata: null,
    days_since_updated: 0,
  }
}

async function mockSession(page: Page, ownerRef: { current: string }) {
  let sessionCalls = 0
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  await page.route('**/api/auth/get-session', route => {
    sessionCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { token: `token-${ownerRef.current}` },
        user: { id: ownerRef.current, email: `${ownerRef.current}@example.invalid`, name: ownerRef.current },
      }),
    })
  })
  return { getSessionCalls: () => sessionCalls }
}

async function switchOwner(page: Page, ownerRef: { current: string }, getSessionCalls: () => number, ownerId: string) {
  ownerRef.current = ownerId
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(getSessionCalls).toBeGreaterThan(1)
}

async function mockCommonWorkspaceEndpoints(page: Page) {
  await page.route('**/ws/**', route => route.abort())
  await page.route(url => url.pathname === '/jobs/' || url.pathname === '/jobs', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ jobs: [] }),
  }))
  await page.route(url => url.pathname === '/me' || url.pathname === '/trial/status' || url.pathname === '/config/feature-flags' || url.pathname.startsWith('/analytics'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }))
}

test('workspace does not let deferred owner A list/stats overwrite owner B', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')
  const ownerRef = { current: OWNER_A }
  const { getSessionCalls } = await mockSession(page, ownerRef)
  await mockCommonWorkspaceEndpoints(page)
  let releaseAList!: () => void
  let releaseAStats!: () => void
  const aListGate = new Promise<void>(resolve => { releaseAList = resolve })
  const aStatsGate = new Promise<void>(resolve => { releaseAStats = resolve })
  let aListSeen = false
  let aStatsSeen = false
  let listRequestCount = 0
  let statsRequestCount = 0

  await page.route(url => url.pathname === '/resumes/' && url.searchParams.get('page') === '1', async route => {
    listRequestCount += 1
    if (listRequestCount === 1) {
      aListSeen = true
      await aListGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [resume(OWNER_A, 'Owner A resume')], total: 1, pages: 1 }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [resume(OWNER_B, 'Owner B resume')], total: 1, pages: 1 }) })
  })
  await page.route(url => url.pathname === '/resumes/stats', async route => {
    statsRequestCount += 1
    if (statsRequestCount === 1) {
      aStatsSeen = true
      await aStatsGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 1, avg_ats_score: 11, best_ats_score: 22, total_resumes: 1, total_templates: 0, last_updated: null }) })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 2, avg_ats_score: 88, best_ats_score: 99, total_resumes: 1, total_templates: 0, last_updated: null }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  await expect.poll(() => aListSeen, { timeout: 10_000 }).toBe(true)
  await expect.poll(() => aStatsSeen, { timeout: 10_000 }).toBe(true)
  await switchOwner(page, ownerRef, getSessionCalls, OWNER_B)
  await expect.poll(() => listRequestCount, { timeout: 10_000 }).toBeGreaterThan(1)
  await expect.poll(() => statsRequestCount, { timeout: 10_000 }).toBeGreaterThan(1)
  await expect(page.getByText('Owner B resume', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('88', { exact: true })).toBeVisible({ timeout: 10_000 })

  const aListResponse = page.waitForResponse(response => response.url().includes('/resumes/?page=1') && response.request().headers()['authorization'] === `Bearer token-${OWNER_A}`)
  const aStatsResponse = page.waitForResponse(response => response.url().endsWith('/resumes/stats') && response.request().headers()['authorization'] === `Bearer token-${OWNER_A}`)
  releaseAList()
  releaseAStats()
  await (await aListResponse).finished()
  await (await aStatsResponse).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))) )

  // Intended invariant; current workspace fetchData has no owner/generation guard.
  await expect(page.getByText('Owner B resume', { exact: true })).toBeVisible()
  await expect(page.getByText('88', { exact: true })).toBeVisible()
  await expect(page.getByText('Owner A resume', { exact: true })).toHaveCount(0)
})

test('workspace does not navigate to a stale owner A translation result', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')
  const ownerRef = { current: OWNER_A }
  const { getSessionCalls } = await mockSession(page, ownerRef)
  await mockCommonWorkspaceEndpoints(page)
  await page.route(url => url.pathname === '/resumes/' && url.searchParams.get('page') === '1', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [resume(ownerRef.current, ownerRef.current === OWNER_A ? 'Owner A resume' : 'Owner B resume')], total: 1, pages: 1 }),
  }))
  await page.route(url => url.pathname === '/resumes/stats', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 0, avg_ats_score: null, best_ats_score: null, total_resumes: 1, total_templates: 0, last_updated: null }),
  }))
  let releaseTranslation!: () => void
  const translationGate = new Promise<void>(resolve => { releaseTranslation = resolve })
  let translationStarted!: () => void
  const translationStartedPromise = new Promise<void>(resolve => { translationStarted = resolve })
  await page.route(url => url.pathname === '/ai/translate', async route => {
    translationStarted()
    await translationGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, variant_resume_id: VARIANT_A, message: 'Created' }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Owner A resume', { exact: true })).toBeVisible({ timeout: 10_000 })
  const card = page.locator('article').filter({ hasText: 'Owner A resume' })
  await card.getByRole('button', { name: 'More actions' }).click()
  await card.getByRole('button', { name: 'Translate', exact: true }).click()
  await page.getByRole('button', { name: 'Translate', exact: true }).last().click()
  await translationStartedPromise

  await switchOwner(page, ownerRef, getSessionCalls, OWNER_B)
  const response = page.waitForResponse(response => response.url().endsWith('/ai/translate') && response.status() === 200)
  releaseTranslation()
  await (await response).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))) )

  // Intended invariant; current handleTranslate navigates unconditionally after await.
  expect(page.url()).toMatch(/\/workspace(?:\/?(?:\?.*)?)?$/)
  await expect(page.getByText('Owner B resume', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page).not.toHaveURL(new RegExp(`/workspace/${VARIANT_A}/edit`))
})

test('workspace preserves successful same-owner translation navigation', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'translation success proof runs against the production workspace bundle')
  const ownerRef = { current: OWNER_A }
  await mockSession(page, ownerRef)
  await mockCommonWorkspaceEndpoints(page)
  await page.route(url => url.pathname === '/resumes/' && url.searchParams.get('page') === '1', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [resume(OWNER_A, 'Owner A resume')], total: 1, pages: 1 }),
  }))
  await page.route(url => url.pathname === '/resumes/stats', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 1, avg_ats_score: 77, best_ats_score: 91, total_resumes: 1, total_templates: 0, last_updated: null }),
  }))
  await page.route(url => url.pathname === '/ai/translate', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, variant_resume_id: 'same-owner-translation', message: 'Created' }),
  }))

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Owner A resume', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('77', { exact: true })).toBeVisible({ timeout: 10_000 })
  const card = page.locator('article').filter({ hasText: 'Owner A resume' })
  await card.getByRole('button', { name: 'More actions' }).click()
  await card.getByRole('button', { name: 'Translate', exact: true }).click()
  await page.getByRole('button', { name: 'Translate', exact: true }).last().click()
  await expect(page).toHaveURL(/\/workspace\/same-owner-translation\/edit/, { timeout: 10_000 })
})

test('same-owner close and reopen keeps a newer translation modal after the old result', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'translation ownership proof runs against the production workspace bundle')
  const ownerRef = { current: OWNER_A }
  await mockSession(page, ownerRef)
  await mockCommonWorkspaceEndpoints(page)
  await page.route(url => url.pathname === '/resumes/' && url.searchParams.get('page') === '1', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [resume(OWNER_A, 'Owner A resume')], total: 1, pages: 1 }),
  }))
  await page.route(url => url.pathname === '/resumes/stats', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 0, avg_ats_score: null, best_ats_score: null, total_resumes: 1, total_templates: 0, last_updated: null }),
  }))
  let releaseTranslation!: () => void
  const translationGate = new Promise<void>(resolve => { releaseTranslation = resolve })
  let translationStarted!: () => void
  const translationStartedPromise = new Promise<void>(resolve => { translationStarted = resolve })
  await page.route(url => url.pathname === '/ai/translate', async route => {
    translationStarted()
    await translationGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, variant_resume_id: 'stale-translation-result', message: 'Created' }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const card = page.locator('article').filter({ hasText: 'Owner A resume' })
  await expect(card).toBeVisible({ timeout: 10_000 })
  await card.getByRole('button', { name: 'More actions' }).click()
  await card.getByRole('button', { name: 'Translate', exact: true }).click()
  await page.getByRole('button', { name: 'Translate', exact: true }).last().click()
  await translationStartedPromise

  await page.locator('div.fixed.inset-0').last().click({ position: { x: 5, y: 5 }, force: true })
  await expect(page.getByText('Translate Resume', { exact: true })).toHaveCount(0)
  await card.getByRole('button', { name: 'More actions' }).click()
  await card.getByRole('button', { name: 'Translate', exact: true }).click()
  await expect(page.getByText('Translate Resume', { exact: true })).toBeVisible()

  const response = page.waitForResponse(response => response.url().endsWith('/ai/translate') && response.status() === 200)
  releaseTranslation()
  await (await response).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))) )
  expect(page.url()).toMatch(/\/workspace\/?$/)
  await expect(page.getByText('Translate Resume', { exact: true })).toBeVisible()
})

test('same-owner stale translation failure cannot toast or mutate a reopened modal', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'translation ownership proof runs against the production workspace bundle')
  const ownerRef = { current: OWNER_A }
  await mockSession(page, ownerRef)
  await mockCommonWorkspaceEndpoints(page)
  await page.route(url => url.pathname === '/resumes/' && url.searchParams.get('page') === '1', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [resume(OWNER_A, 'Owner A resume')], total: 1, pages: 1 }),
  }))
  await page.route(url => url.pathname === '/resumes/stats', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 0, avg_ats_score: null, best_ats_score: null, total_resumes: 1, total_templates: 0, last_updated: null }),
  }))
  let releaseTranslation!: () => void
  const translationGate = new Promise<void>(resolve => { releaseTranslation = resolve })
  let translationStarted!: () => void
  const translationStartedPromise = new Promise<void>(resolve => { translationStarted = resolve })
  await page.route(url => url.pathname === '/ai/translate', async route => {
    translationStarted()
    await translationGate
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'stale-translation-error-token' }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const card = page.locator('article').filter({ hasText: 'Owner A resume' })
  await expect(card).toBeVisible({ timeout: 10_000 })
  await card.getByRole('button', { name: 'More actions' }).click()
  await card.getByRole('button', { name: 'Translate', exact: true }).click()
  await page.getByRole('button', { name: 'Translate', exact: true }).last().click()
  await translationStartedPromise

  await page.locator('div.fixed.inset-0').last().click({ position: { x: 5, y: 5 }, force: true })
  await card.getByRole('button', { name: 'More actions' }).click()
  await card.getByRole('button', { name: 'Translate', exact: true }).click()
  await expect(page.getByText('Translate Resume', { exact: true })).toBeVisible()

  const response = page.waitForResponse(response => response.url().endsWith('/ai/translate') && response.status() === 503)
  releaseTranslation()
  await (await response).finished()
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))) )
  expect(page.url()).toMatch(/\/workspace\/?$/)
  await expect(page.getByText('Translate Resume', { exact: true })).toBeVisible()
  await expect(page.locator('[data-sonner-toast]')).toHaveCount(0)
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'stale-translation-error-token' })).toHaveCount(0)
})
