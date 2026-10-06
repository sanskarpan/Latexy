import { expect, test, type Page } from '@playwright/test'

const SESSION_A = {
  session: { token: 'tracker-owner-a-token' },
  user: { id: 'tracker-owner-a', email: 'a@example.com', name: 'Owner A' },
}
const SESSION_B = {
  session: { token: 'tracker-owner-b-token' },
  user: { id: 'tracker-owner-b', email: 'b@example.com', name: 'Owner B' },
}

const application = (id: string, ownerId: string, company: string, status = 'applied') => ({
  id,
  user_id: ownerId,
  company_name: company,
  role_title: 'Engineer',
  status,
  resume_id: null,
  ats_score_at_submission: null,
  job_description_text: null,
  job_url: null,
  company_logo_url: null,
  notes: null,
  applied_at: '2026-10-03T00:00:00Z',
  updated_at: '2026-10-03T00:00:00Z',
  created_at: '2026-10-03T00:00:00Z',
})

const board = (item: ReturnType<typeof application>) => ({
  applied: item.status === 'applied' ? [item] : [],
  phone_screen: item.status === 'phone_screen' ? [item] : [],
  technical: [],
  onsite: [],
  offer: [],
  rejected: [],
  withdrawn: [],
})

const staleApplication = (item: ReturnType<typeof application>, days_since_update: number) => ({
  ...item,
  days_since_update,
})

async function emitOwnerRefresh(page: Page) {
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
}

async function settleRenderedState(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  }))
}

test.describe('tracker board ownership diagnostics', () => {
  test('a deferred old-owner board response cannot overwrite the new-owner board', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')

    let owner: 'a' | 'b' = 'a'
    let sessionCalls = 0
    let releaseOldBoard!: () => void
    let oldBoardStarted!: () => void
    const oldBoard = new Promise<void>((resolve) => { releaseOldBoard = resolve })
    const oldStarted = new Promise<void>((resolve) => { oldBoardStarted = resolve })

    const appA = application('tracker-app-a', 'tracker-owner-a', 'Owner A Company')
    const appB = application('tracker-app-b', 'tracker-owner-b', 'Owner B Company')

    await page.route('**/api/auth/get-session', (route) => {
      sessionCalls += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(owner === 'a' ? SESSION_A : SESSION_B),
      })
    })
    await page.route((url) => url.pathname === '/tracker/applications', async (route) => {
      if (owner === 'a') {
        oldBoardStarted()
        await oldBoard
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: board(appA) }) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: board(appB) }) })
    })
    await page.route((url) => url.pathname === '/tracker/stale-applications', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await oldStarted

    owner = 'b'
    await emitOwnerRefresh(page)
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect(page.getByText('Owner B Company', { exact: true })).toBeVisible({ timeout: 15_000 })

    const oldResponse = page.waitForResponse((response) =>
      response.url().includes('/tracker/applications') && response.status() === 200)
    let released = false
    try {
      releaseOldBoard()
      released = true
      const response = await oldResponse
      await response.finished()
      await settleRenderedState(page)
      await expect(page.getByText('Owner B Company', { exact: true })).toBeVisible()
      await expect(page.getByText('Owner A Company', { exact: true })).toHaveCount(0)
    } finally {
      if (!released) releaseOldBoard()
    }
  })

  test('a failed old-owner response cannot clear the new-owner loading state', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')

    let owner: 'a' | 'b' = 'a'
    let sessionCalls = 0
    let releaseOldBoard!: () => void
    let releaseNewBoard!: () => void
    let oldBoardStarted!: () => void
    let newBoardStarted!: () => void
    const oldBoard = new Promise<void>((resolve) => { releaseOldBoard = resolve })
    const newBoard = new Promise<void>((resolve) => { releaseNewBoard = resolve })
    const oldStarted = new Promise<void>((resolve) => { oldBoardStarted = resolve })
    const newStarted = new Promise<void>((resolve) => { newBoardStarted = resolve })
    const appA = application('tracker-app-a', 'tracker-owner-a', 'Owner A Company')
    const appB = application('tracker-app-b', 'tracker-owner-b', 'Owner B Company')

    await page.route('**/api/auth/get-session', (route) => {
      sessionCalls += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(owner === 'a' ? SESSION_A : SESSION_B),
      })
    })
    await page.route((url) => url.pathname === '/tracker/applications', async (route) => {
      if (owner === 'a') {
        oldBoardStarted()
        await oldBoard
        return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic old-owner failure' }) })
      }
      newBoardStarted()
      await newBoard
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: board(appB) }) })
    })
    await page.route((url) => url.pathname === '/tracker/stale-applications', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await oldStarted
    owner = 'b'
    await emitOwnerRefresh(page)
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await newStarted

    const oldResponse = page.waitForResponse((response) =>
      response.url().includes('/tracker/applications') && response.status() === 503)
    let oldReleased = false
    let newReleased = false
    try {
      releaseOldBoard()
      oldReleased = true
      const response = await oldResponse
      await response.finished()
      await settleRenderedState(page)
      await expect(page.getByRole('status', { name: 'Loading' })).toBeVisible()
      await expect(page.getByText('Owner B Company', { exact: true })).toHaveCount(0)

      const newResponse = page.waitForResponse((candidate) =>
        candidate.url().includes('/tracker/applications') && candidate.status() === 200)
      releaseNewBoard()
      newReleased = true
      const responseB = await newResponse
      await responseB.finished()
      await settleRenderedState(page)
      await expect(page.getByText('Owner B Company', { exact: true })).toBeVisible()
      await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0)
    } finally {
      if (!oldReleased) releaseOldBoard()
      if (!newReleased) releaseNewBoard()
    }
  })

  test('same-owner board refresh still applies its successful response', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')

    let releaseBoard!: () => void
    let boardStarted!: () => void
    const boardResponse = new Promise<void>((resolve) => { releaseBoard = resolve })
    const started = new Promise<void>((resolve) => { boardStarted = resolve })
    const appA = application('tracker-app-a', 'tracker-owner-a', 'Owner A Company')

    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION_A) }))
    await page.route((url) => url.pathname === '/tracker/applications', async (route) => {
      boardStarted()
      await boardResponse
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: board(appA) }) })
    })
    await page.route((url) => url.pathname === '/tracker/stale-applications', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))

    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await started
    const responsePromise = page.waitForResponse((response) =>
      response.url().includes('/tracker/applications') && response.status() === 200)
    let released = false
    try {
      releaseBoard()
      released = true
      const response = await responsePromise
      await response.finished()
      await settleRenderedState(page)
      await expect(page.getByText('Owner A Company', { exact: true })).toBeVisible()
    } finally {
      if (!released) releaseBoard()
    }
  })

  test('a deferred old-owner stale-applications response cannot replace the new-owner follow-up list', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership diagnostic runs against the production bundle')

    let owner: 'a' | 'b' = 'a'
    let oldStaleCalls = 0
    let releaseOldStale!: () => void
    let releaseNewStale!: () => void
    let oldStaleStarted!: () => void
    let newStaleStarted!: () => void
    const oldStale = new Promise<void>((resolve) => { releaseOldStale = resolve })
    const newStale = new Promise<void>((resolve) => { releaseNewStale = resolve })
    const staleStarted = new Promise<void>((resolve) => { oldStaleStarted = resolve })
    const newStarted = new Promise<void>((resolve) => { newStaleStarted = resolve })
    const appA = application('tracker-app-a', 'tracker-owner-a', 'Owner A Company')
    const appB = application('tracker-app-b', 'tracker-owner-b', 'Owner B Company')

    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(owner === 'a' ? SESSION_A : SESSION_B),
      }))
    await page.route((url) => url.pathname === '/tracker/applications', (route) => {
      const current = owner === 'a' ? appA : appB
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ by_status: board(current) }) })
    })
    await page.route((url) => url.pathname === '/tracker/stale-applications', async (route) => {
      if (oldStaleCalls++ === 0) {
        oldStaleStarted()
        await oldStale
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([staleApplication(appA, 21)]) })
      }
      newStaleStarted()
      await newStale
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([staleApplication(appB, 18)]) })
    })

    await page.goto('/tracker', { waitUntil: 'domcontentloaded' })
    await oldStaleStarted
    const oldResponse = page.waitForResponse((response) =>
      response.url().includes('/tracker/stale-applications') && response.status() === 200)

    owner = 'b'
    await emitOwnerRefresh(page)
    await expect(page.getByRole('button', { name: /OB Owner B Company Engineer/ })).toBeVisible({ timeout: 15_000 })
    await newStarted

    let released = false
    let newReleased = false
    try {
      releaseOldStale()
      released = true
      const response = await oldResponse
      await response.finished()
      await settleRenderedState(page)
      await expect(page.getByText('21d since your last update · Add reminder', { exact: true })).toHaveCount(0)

      const newResponse = page.waitForResponse((candidate) =>
        candidate.url().includes('/tracker/stale-applications') && candidate.status() === 200)
      releaseNewStale()
      newReleased = true
      const responseB = await newResponse
      await responseB.finished()
      await settleRenderedState(page)
      await expect(page.getByText('18d since your last update · Add reminder', { exact: true })).toBeVisible()
      await expect(page.getByText('21d since your last update · Add reminder', { exact: true })).toHaveCount(0)
    } finally {
      if (!released) releaseOldStale()
      if (!newReleased) releaseNewStale()
    }
  })

})
