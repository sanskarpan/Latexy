import { expect, test, type Page } from '@playwright/test'

const OWNER_A = 'workspace-job-owner-a'
const OWNER_B = 'workspace-job-owner-b'
const JOB_A = 'workspace-job-a'
const JOB_B = 'workspace-job-b'
const JOB_X = 'workspace-job-x'
const JOB_Y = 'workspace-job-y'
const JOB_ABA = 'workspace-job-aba'
const JOB_ERROR = 'workspace-job-error'

const session = (owner: string) => ({
  session: { token: `token-${owner}` },
  user: { id: owner, email: `${owner}@example.invalid`, name: owner },
})

const job = (jobId: string, stage: string) => ({
  job_id: jobId,
  job_type: 'compile',
  status: 'completed',
  stage,
  last_updated: 1_791_000_000,
  error: null,
})

async function mockWorkspace(page: Page, ownerRef: { current: string }, jobs: () => object[]) {
  let sessionCalls = 0
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session(ownerRef.current)) })
  })
  await page.route((url) => url.pathname === '/jobs/' || url.pathname === '/jobs', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ jobs: jobs() }) }))
  await page.route((url) => url.pathname === '/resumes/' && url.searchParams.get('page') === '1', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resumes: [], total: 0, pages: 0 }) }))
  await page.route((url) => url.pathname === '/resumes/stats', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ optimized_count: 0, avg_ats_score: null, best_ats_score: null, total_resumes: 0, total_templates: 0, last_updated: null }) }))
  await page.route((url) => url.pathname === '/me' || url.pathname === '/trial/status' || url.pathname === '/config/feature-flags' || url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())
  return {
    getSessionCalls: () => sessionCalls,
    switchOwner: async (nextOwner: string) => {
      ownerRef.current = nextOwner
      await page.evaluate(() => {
        const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
        localStorage.setItem('better-auth.message', message)
        window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
      })
      await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    },
  }
}

async function settleRenderedState(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  }))
}

function activitySection(page: Page) {
  return page.locator('section').filter({ hasText: 'Recent Activity' }).first()
}

test('old-owner job-result finally cannot clear a newer owner result loading state', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')

  const ownerRef = { current: OWNER_A }
  const workspace = await mockWorkspace(page, ownerRef, () => ownerRef.current === OWNER_A ? [job(JOB_A, 'Owner A run')] : [job(JOB_B, 'Owner B run')])
  let releaseA!: () => void
  let releaseB!: () => void
  let resultAStarted!: () => void
  let resultBStarted!: () => void
  const gateA = new Promise<void>((resolve) => { releaseA = resolve })
  const gateB = new Promise<void>((resolve) => { releaseB = resolve })
  const startedA = new Promise<void>((resolve) => { resultAStarted = resolve })
  const startedB = new Promise<void>((resolve) => { resultBStarted = resolve })

  await page.route((url) => url.pathname === `/jobs/${JOB_A}/result`, async (route) => {
    resultAStarted()
    await gateA
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_A, result: { success: true, ats_score: 11 } }) })
  })
  await page.route((url) => url.pathname === `/jobs/${JOB_B}/result`, async (route) => {
    resultBStarted()
    await gateB
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_B, result: { success: true, ats_score: 88 } }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const activity = activitySection(page)
  await expect(activity.getByText('Owner A run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').first().click()
  await resultAStarted

  await workspace.switchOwner(OWNER_B)
  await expect(activity.getByText('Owner B run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').first().click()
  await resultBStarted

  const responseA = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_A}/result`) && response.status() === 200)
  let releasedA = false
  let releasedB = false
  try {
    releaseA()
    releasedA = true
    const completedA = await responseA
    await completedA.finished()
    await settleRenderedState(page)
    await expect(activity.getByText('Loading result…', { exact: true })).toBeVisible()
    await expect(activity.getByText('No detailed result is available for this run.', { exact: true })).toHaveCount(0)

    const responseB = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_B}/result`) && response.status() === 200)
    releaseB()
    releasedB = true
    const completedB = await responseB
    await completedB.finished()
    await settleRenderedState(page)
    await expect(activity.getByText('ATS score:', { exact: false })).toBeVisible()
    await expect(activity.getByText('88', { exact: true })).toBeVisible()
  } finally {
    if (!releasedA) releaseA()
    if (!releasedB) releaseB()
  }
})

test('same-owner deferred job result remains loading until its response completes', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')

  const ownerRef = { current: OWNER_A }
  await mockWorkspace(page, ownerRef, () => [job(JOB_A, 'Owner A run')])
  let release!: () => void
  let resultStarted!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  const started = new Promise<void>((resolve) => { resultStarted = resolve })
  await page.route((url) => url.pathname === `/jobs/${JOB_A}/result`, async (route) => {
    resultStarted()
    await gate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_A, result: { success: true, ats_score: 91 } }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const activity = activitySection(page)
  await expect(activity.getByText('Owner A run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').first().click()
  await started
  await expect(activity.getByText('Loading result…', { exact: true })).toBeVisible()

  const response = page.waitForResponse((candidate) => candidate.url().endsWith(`/jobs/${JOB_A}/result`) && candidate.status() === 200)
  release()
  const completed = await response
  await completed.finished()
  await settleRenderedState(page)
  await expect(activity.getByText('91', { exact: true })).toBeVisible()
})

test('an old A result cannot win after switching B and returning to A', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')

  const ownerRef = { current: OWNER_A }
  const workspace = await mockWorkspace(page, ownerRef, () => ownerRef.current === OWNER_A
    ? [job(JOB_ABA, 'Owner A run')]
    : [job(JOB_B, 'Owner B run')])
  let releaseFirst!: () => void
  let releaseSecond!: () => void
  let resultFirstStarted!: () => void
  let resultSecondStarted!: () => void
  let requestCount = 0
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve })
  const secondGate = new Promise<void>((resolve) => { releaseSecond = resolve })
  const firstStarted = new Promise<void>((resolve) => { resultFirstStarted = resolve })
  const secondStarted = new Promise<void>((resolve) => { resultSecondStarted = resolve })
  await page.route((url) => url.pathname === `/jobs/${JOB_ABA}/result`, async (route) => {
    requestCount += 1
    if (requestCount === 1) {
      resultFirstStarted()
      await firstGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_ABA, result: { success: true, ats_score: 13 } }) })
    } else {
      resultSecondStarted()
      await secondGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_ABA, result: { success: true, ats_score: 97 } }) })
    }
  })
  await page.route((url) => url.pathname === `/jobs/${JOB_B}/result`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_B, result: { success: true, ats_score: 88 } }) }))

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const activity = activitySection(page)
  await expect(activity.getByText('Owner A run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').first().click()
  await firstStarted

  await workspace.switchOwner(OWNER_B)
  await expect(activity.getByText('Owner B run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await workspace.switchOwner(OWNER_A)
  await expect(activity.getByText('Owner A run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').first().click()
  await secondStarted

  const firstResponse = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_ABA}/result`) && response.status() === 200)
  const secondResponse = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_ABA}/result`) && response.status() === 200)
  let releasedFirst = false
  let releasedSecond = false
  try {
    releaseFirst()
    releasedFirst = true
    const completedFirst = await firstResponse
    await completedFirst.finished()
    await settleRenderedState(page)
    await expect(activity.getByText('13', { exact: true })).toHaveCount(0)
    await expect(activity.getByText('Loading result…', { exact: true })).toBeVisible()

    releaseSecond()
    releasedSecond = true
    const completedSecond = await secondResponse
    await completedSecond.finished()
    await settleRenderedState(page)
    await expect(activity.getByText('97', { exact: true })).toBeVisible()
  } finally {
    if (!releasedFirst) releaseFirst()
    if (!releasedSecond) releaseSecond()
  }
})

test('an old owner result error cannot surface after switching accounts', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')

  const ownerRef = { current: OWNER_A }
  const workspace = await mockWorkspace(page, ownerRef, () => ownerRef.current === OWNER_A
    ? [job(JOB_ERROR, 'Owner A run')]
    : [job(JOB_B, 'Owner B run')])
  let releaseA!: () => void
  let resultAStarted!: () => void
  const gateA = new Promise<void>((resolve) => { releaseA = resolve })
  const startedA = new Promise<void>((resolve) => { resultAStarted = resolve })
  await page.route((url) => url.pathname === `/jobs/${JOB_ERROR}/result`, async (route) => {
    resultAStarted()
    await gateA
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'temporary failure' }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const activity = activitySection(page)
  await expect(activity.getByText('Owner A run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').first().click()
  await resultAStarted

  await workspace.switchOwner(OWNER_B)
  await expect(activity.getByText('Owner B run', { exact: true })).toBeVisible({ timeout: 15_000 })
  const responseA = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_ERROR}/result`) && response.status() === 503)
  releaseA()
  const completedA = await responseA
  await completedA.finished()
  await settleRenderedState(page)
  await expect(activity.getByText('Run details could not be loaded', { exact: true })).toHaveCount(0)
})

test('same-owner overlapping result requests do not clear the newer job loading state', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'ownership proof runs against the production workspace bundle')

  const ownerRef = { current: OWNER_A }
  await mockWorkspace(page, ownerRef, () => [job(JOB_X, 'Owner X run'), job(JOB_Y, 'Owner Y run')])
  let releaseX!: () => void
  let releaseY!: () => void
  let startedX!: () => void
  let startedY!: () => void
  const gateX = new Promise<void>((resolve) => { releaseX = resolve })
  const gateY = new Promise<void>((resolve) => { releaseY = resolve })
  const seenX = new Promise<void>((resolve) => { startedX = resolve })
  const seenY = new Promise<void>((resolve) => { startedY = resolve })
  await page.route((url) => url.pathname === `/jobs/${JOB_X}/result`, async (route) => {
    startedX()
    await gateX
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_X, result: { success: true, ats_score: 21 } }) })
  })
  await page.route((url) => url.pathname === `/jobs/${JOB_Y}/result`, async (route) => {
    startedY()
    await gateY
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: JOB_Y, result: { success: true, ats_score: 79 } }) })
  })

  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  const activity = activitySection(page)
  await expect(activity.getByText('Owner X run', { exact: true })).toBeVisible({ timeout: 15_000 })
  await activity.getByRole('button').nth(0).click()
  await seenX
  await activity.getByRole('button').nth(1).click()
  await seenY

  const responseX = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_X}/result`) && response.status() === 200)
  const responseY = page.waitForResponse((response) => response.url().endsWith(`/jobs/${JOB_Y}/result`) && response.status() === 200)
  releaseX()
  const completedX = await responseX
  await completedX.finished()
  await settleRenderedState(page)
  await expect(activity.getByText('Loading result…', { exact: true })).toBeVisible()

  releaseY()
  const completedY = await responseY
  await completedY.finished()
  await settleRenderedState(page)
  await expect(activity.getByText('79', { exact: true })).toBeVisible()
})
