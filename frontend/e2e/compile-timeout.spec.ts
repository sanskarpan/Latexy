import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Feature 11 — Compile Timeout per Plan                             //
//  Tests the timeout upgrade banner on /try and /workspace/edit.     //
//  Covers: free / basic / pro plans, success (no banner), and        //
//  non-timeout errors (no banner).                                    //
// ------------------------------------------------------------------ //

// ---- Shared constants ----

const RESUME_ID = 'resume-cto-0001'
const JOB_ID_COMPILE = 'job-cto-compile-001'
const JOB_ID_AI = 'job-cto-ai-001'

const MOCK_RESUME = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'Timeout Test Resume',
  latex_content: [
    '\\documentclass[letterpaper,11pt]{article}',
    '\\begin{document}',
    'John Doe — Software Engineer, 5 years experience.',
    '\\end{document}',
  ].join('\n'),
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

// ---- Helpers ----

async function mockAuth(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) })
  )
}

async function mockCommonBackend(page: import('@playwright/test').Page) {
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
  )
  await page.route((url) => url.pathname === '/trial/status' || url.pathname.startsWith('/public/trial'), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ uses_remaining: 3, cooldown_seconds: 0, is_limited: false }),
    })
  )
  await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ score: 75, grade: 'C', sections_found: ['experience'], missing_sections: [], keyword_match_percent: null }),
    })
  )
  await page.route((url) => url.pathname.startsWith('/format'), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ supported: true, formats: ['pdf', 'docx'] }),
    })
  )
  await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
    })
  )
  await page.route((url) => !!url.pathname.match(/\/download\/.+/), (route) =>
    route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.4 mock') })
  )
}

async function mockResume(page: import('@playwright/test').Page) {
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESUME) })
  )
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )
}

async function mockSubmitJob(
  page: import('@playwright/test').Page,
  jobId: string = JOB_ID_COMPILE
) {
  await page.route((url) => url.pathname === '/jobs/submit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: jobId, message: 'Started' }),
    })
  )
}

/**
 * Set up a WebSocket mock that delivers a job.failed event with
 * error_code='compile_timeout' for the given jobId.
 */
async function mockWebSocketTimeout(
  page: import('@playwright/test').Page,
  jobId: string,
  userPlan: string = 'free',
  upgradeMessage: string = 'Upgrade to Pro for a 4-minute compile timeout'
) {
  let seq = 0
  const base = () => ({ event_id: `evt-${++seq}`, job_id: jobId, timestamp: Date.now() / 1000, sequence: seq })

  await page.routeWebSocket('**/ws/jobs', (ws) => {
    ws.onMessage((data) => {
      try {
        const msg = JSON.parse(data as string)

        if (msg.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
          return
        }

        if (msg.type === 'subscribe' && msg.job_id === jobId) {
          ws.send(JSON.stringify({ type: 'subscribed', job_id: jobId, replayed_count: 0 }))

          const events: object[] = [
            { type: 'event', event: { ...base(), type: 'job.queued', job_type: 'compile', user_id: null, estimated_seconds: 30 } },
            { type: 'event', event: { ...base(), type: 'job.started', worker_id: 'w-1', stage: 'latex_compilation' } },
            {
              type: 'event',
              event: {
                ...base(),
                type: 'job.failed',
                stage: 'latex_compilation',
                error_code: 'compile_timeout',
                error_message: `Compilation timed out after ${userPlan === 'free' ? 30 : userPlan === 'basic' ? 120 : 240}s (${userPlan} plan limit)`,
                retryable: false,
                upgrade_message: upgradeMessage,
                user_plan: userPlan,
              },
            },
          ]

          let delay = 80
          for (const event of events) {
            const captured = event
            setTimeout(() => {
              try { ws.send(JSON.stringify(captured)) } catch { /* closed */ }
            }, delay)
            delay += 120
          }
        }
      } catch { /* ignore */ }
    })
  })
}

/**
 * Set up a WebSocket mock for a successful compilation.
 */
async function mockWebSocketSuccess(
  page: import('@playwright/test').Page,
  jobId: string
) {
  let seq = 0
  const base = () => ({ event_id: `evt-${++seq}`, job_id: jobId, timestamp: Date.now() / 1000, sequence: seq })

  await page.routeWebSocket('**/ws/jobs', (ws) => {
    ws.onMessage((data) => {
      try {
        const msg = JSON.parse(data as string)
        if (msg.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
          return
        }
        if (msg.type === 'subscribe' && msg.job_id === jobId) {
          ws.send(JSON.stringify({ type: 'subscribed', job_id: jobId, replayed_count: 0 }))

          const events: object[] = [
            { type: 'event', event: { ...base(), type: 'job.queued', job_type: 'compile', user_id: null, estimated_seconds: 5 } },
            { type: 'event', event: { ...base(), type: 'job.started', worker_id: 'w-1', stage: 'latex_compilation' } },
            {
              type: 'event',
              event: {
                ...base(),
                type: 'job.completed',
                pdf_job_id: jobId,
                ats_score: 75,
                ats_details: { category_scores: {}, recommendations: [], strengths: [], warnings: [] },
                changes_made: [],
                compilation_time: 2.5,
                optimization_time: 0,
                tokens_used: 0,
                page_count: 1,
              },
            },
          ]

          let delay = 80
          for (const event of events) {
            const captured = event
            setTimeout(() => {
              try { ws.send(JSON.stringify(captured)) } catch { /* closed */ }
            }, delay)
            delay += 120
          }
        }
      } catch { /* ignore */ }
    })
  })
}

/**
 * Set up a WebSocket mock for a non-timeout failure.
 */
async function mockWebSocketLatexError(
  page: import('@playwright/test').Page,
  jobId: string
) {
  let seq = 0
  const base = () => ({ event_id: `evt-${++seq}`, job_id: jobId, timestamp: Date.now() / 1000, sequence: seq })

  await page.routeWebSocket('**/ws/jobs', (ws) => {
    ws.onMessage((data) => {
      try {
        const msg = JSON.parse(data as string)
        if (msg.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
          return
        }
        if (msg.type === 'subscribe' && msg.job_id === jobId) {
          ws.send(JSON.stringify({ type: 'subscribed', job_id: jobId, replayed_count: 0 }))

          const events: object[] = [
            { type: 'event', event: { ...base(), type: 'job.queued', job_type: 'compile', user_id: null, estimated_seconds: 5 } },
            { type: 'event', event: { ...base(), type: 'job.started', worker_id: 'w-1', stage: 'latex_compilation' } },
            {
              type: 'event',
              event: {
                ...base(),
                type: 'job.failed',
                stage: 'latex_compilation',
                error_code: 'latex_error',
                error_message: 'Undefined control sequence \\foo',
                retryable: true,
              },
            },
          ]

          let delay = 80
          for (const event of events) {
            const captured = event
            setTimeout(() => {
              try { ws.send(JSON.stringify(captured)) } catch { /* closed */ }
            }, delay)
            delay += 120
          }
        }
      } catch { /* ignore */ }
    })
  })
}

// ------------------------------------------------------------------ //
//  1. /try page — compile timeout banner                             //
// ------------------------------------------------------------------ //

test.describe('/try page — compile timeout banner', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
  })

  test('shows timeout banner after compile_timeout event (free plan)', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/free plan limit/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('30s')).toBeVisible({ timeout: 5_000 })
  })

  test('shows correct timeout duration for basic plan (120s)', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'basic')

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/basic plan limit/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('120s')).toBeVisible({ timeout: 5_000 })
  })

  test('shows correct timeout duration for pro plan (240s)', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'pro')

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/pro plan limit/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('240s')).toBeVisible({ timeout: 5_000 })
  })

  test('upgrade link points to /billing', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    const upgradeLink = page.getByRole('link', { name: /Upgrade for longer timeouts/i })
    await expect(upgradeLink).toBeVisible({ timeout: 5_000 })
    await expect(upgradeLink).toHaveAttribute('href', '/billing')
  })

  test('NO timeout banner when compile succeeds', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketSuccess(page, JOB_ID_COMPILE)

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    // Wait for job to complete (success banner or status change)
    await page.waitForTimeout(2_000)
    await expect(page.getByText(/Compile timed out/)).not.toBeVisible()
    await expect(page.getByText(/Upgrade for longer timeouts/i)).not.toBeVisible()
  })

  test('NO timeout banner for non-timeout LaTeX errors', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketLatexError(page, JOB_ID_COMPILE)

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    await page.waitForTimeout(2_000)
    await expect(page.getByText(/Compile timed out/)).not.toBeVisible()
    await expect(page.getByText(/Upgrade for longer timeouts/i)).not.toBeVisible()
  })

  test('banner is orange-themed', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Compile/i }).first().click()

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    const banner = page.locator('[class*="orange"]').filter({ hasText: /Compile timed out/ })
    await expect(banner.first()).toBeVisible({ timeout: 5_000 })
  })

  test('/try page loads without JS errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })
})

// ------------------------------------------------------------------ //
//  2. /workspace/edit — compile stream timeout banner                //
// ------------------------------------------------------------------ //

test.describe('/workspace/edit — compile stream timeout banner', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page)
  })

  test('shows compile timeout banner after auto-compile times out (free plan)', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await page.waitForSelector('.monaco-editor', { timeout: 20_000 })

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/free plan limit/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('30s')).toBeVisible({ timeout: 5_000 })
  })

  test('compile stream timeout banner shows correct pro plan duration (240s)', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'pro')

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await page.waitForSelector('.monaco-editor', { timeout: 20_000 })

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/pro plan limit/)).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('240s')).toBeVisible({ timeout: 5_000 })
  })

  test('compile timeout banner has "Upgrade for longer timeouts →" link to /billing', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })
    const upgradeLink = page.getByRole('link', { name: /Upgrade for longer timeouts/i })
    await expect(upgradeLink).toBeVisible({ timeout: 5_000 })
    await expect(upgradeLink).toHaveAttribute('href', '/billing')
  })

  test('NO compile timeout banner when compile succeeds', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketSuccess(page, JOB_ID_COMPILE)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })

    // Wait for job.completed to arrive
    await page.waitForTimeout(2_000)
    await expect(page.getByText(/Compile timed out/)).not.toBeVisible()
    await expect(page.getByText(/Upgrade for longer timeouts/i)).not.toBeVisible()
  })

  test('NO compile timeout banner for non-timeout LaTeX errors', async ({ page }) => {
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketLatexError(page, JOB_ID_COMPILE)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })

    await page.waitForTimeout(2_000)
    await expect(page.getByText(/Compile timed out/)).not.toBeVisible()
    await expect(page.getByText(/Upgrade for longer timeouts/i)).not.toBeVisible()
  })

  test('edit page loads without JS errors when timeout occurs', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })

    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })
})

// ------------------------------------------------------------------ //
//  3. /workspace/edit — AI stream timeout banner                     //
// ------------------------------------------------------------------ //

test.describe('/workspace/edit — AI stream (optimize+compile) timeout banner', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page)
  })

  /**
   * Mock WebSocket for TWO separate job subscriptions:
   * - JOB_ID_COMPILE: succeeds (auto-compile on load)
   * - JOB_ID_AI: fails with compile_timeout
   */
  async function mockWebSocketAITimeout(
    page: import('@playwright/test').Page,
    userPlan: string = 'free'
  ) {
    let seq = 0
    const base = (jid: string) => ({ event_id: `evt-${++seq}`, job_id: jid, timestamp: Date.now() / 1000, sequence: seq })

    await page.routeWebSocket('**/ws/jobs', (ws) => {
      ws.onMessage((data) => {
        try {
          const msg = JSON.parse(data as string)
          if (msg.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
            return
          }
          if (msg.type === 'subscribe') {
            const jid: string = msg.job_id
            ws.send(JSON.stringify({ type: 'subscribed', job_id: jid, replayed_count: 0 }))

            if (jid === JOB_ID_COMPILE) {
              // auto-compile succeeds
              setTimeout(() => {
                try {
                  ws.send(JSON.stringify({ type: 'event', event: { ...base(jid), type: 'job.queued', job_type: 'compile', user_id: null, estimated_seconds: 5 } }))
                  ws.send(JSON.stringify({
                    type: 'event',
                    event: {
                      ...base(jid), type: 'job.completed', pdf_job_id: jid,
                      ats_score: 75, ats_details: {}, changes_made: [],
                      compilation_time: 2.5, optimization_time: 0, tokens_used: 0, page_count: 1,
                    },
                  }))
                } catch { /* closed */ }
              }, 100)
            } else if (jid === JOB_ID_AI) {
              // AI job times out
              setTimeout(() => {
                try {
                  ws.send(JSON.stringify({ type: 'event', event: { ...base(jid), type: 'job.queued', job_type: 'combined', user_id: null, estimated_seconds: 60 } }))
                  ws.send(JSON.stringify({ type: 'event', event: { ...base(jid), type: 'job.started', worker_id: 'w-1', stage: 'llm_optimization' } }))
                  ws.send(JSON.stringify({ type: 'event', event: { ...base(jid), type: 'job.started', worker_id: 'w-1', stage: 'latex_compilation' } }))
                  ws.send(JSON.stringify({
                    type: 'event',
                    event: {
                      ...base(jid),
                      type: 'job.failed',
                      stage: 'latex_compilation',
                      error_code: 'compile_timeout',
                      error_message: `Compilation timed out after ${userPlan === 'free' ? 30 : 240}s (${userPlan} plan limit)`,
                      retryable: false,
                      upgrade_message: 'Upgrade to Pro for a 4-minute compile timeout',
                      user_plan: userPlan,
                    },
                  }))
                } catch { /* closed */ }
              }, 200)
            }
          }
        } catch { /* ignore */ }
      })
    })
  }

  test('AI stream timeout shows plan limit reached banner (free plan)', async ({ page }) => {
    // First job is compile (auto-compile on load), second is AI
    let submitCount = 0
    await page.route((url) => url.pathname === '/jobs/submit', (route) => {
      submitCount++
      const jobId = submitCount === 1 ? JOB_ID_COMPILE : JOB_ID_AI
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: jobId, message: 'Started' }),
      })
    })
    await mockWebSocketAITimeout(page, 'free')

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })

    // Wait for auto-compile to settle (WS mock sends success events for JOB_ID_COMPILE)
    await page.waitForTimeout(1_500)

    // Step 1: Click "AI Optimize" header button to open the AI panel
    await page.getByRole('button', { name: 'AI Optimize' }).click()

    // Step 2: Wait for AI panel's "Optimize Resume" button, then click it
    await page.waitForSelector('button:has-text("Optimize Resume")', { timeout: 8_000 })
    await page.getByRole('button', { name: /Optimize Resume/i }).click()

    // The AI timeout banner in the AI panel shows "plan limit reached"
    await expect(page.getByText(/plan limit reached/i)).toBeVisible({ timeout: 15_000 })
    const upgradeLink = page.getByRole('link', { name: /Upgrade →/i })
    await expect(upgradeLink).toBeVisible({ timeout: 5_000 })
    await expect(upgradeLink).toHaveAttribute('href', '/billing')
  })
})

// ------------------------------------------------------------------ //
//  4. WebSocket event schema — compile_timeout fields present        //
// ------------------------------------------------------------------ //

test.describe('WebSocket event schema — compile_timeout fields', () => {
  test('job.failed event contains upgrade_message and user_plan when error_code=compile_timeout', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)

    const receivedEvents: Record<string, unknown>[] = []

    await page.routeWebSocket('**/ws/jobs', (ws) => {
      ws.onMessage((data) => {
        try {
          const msg = JSON.parse(data as string)
          if (msg.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
            return
          }
          if (msg.type === 'subscribe') {
            ws.send(JSON.stringify({ type: 'subscribed', job_id: msg.job_id, replayed_count: 0 }))
            setTimeout(() => {
              const failedEvent = {
                type: 'event',
                event: {
                  event_id: 'e1', job_id: msg.job_id, timestamp: Date.now() / 1000, sequence: 1,
                  type: 'job.failed',
                  stage: 'latex_compilation',
                  error_code: 'compile_timeout',
                  error_message: 'Compilation timed out after 30s (free plan limit)',
                  retryable: false,
                  upgrade_message: 'Upgrade to Pro for a 4-minute compile timeout',
                  user_plan: 'free',
                },
              }
              receivedEvents.push(failedEvent)
              try { ws.send(JSON.stringify(failedEvent)) } catch { /* closed */ }
            }, 100)
          }
        } catch { /* ignore */ }
      })
    })

    await page.route((url) => url.pathname === '/jobs/submit', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: JOB_ID_COMPILE, message: 'Started' }),
      })
    )

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: /Compile/i }).first().click()

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })

    // Verify the event schema
    expect(receivedEvents.length).toBeGreaterThan(0)
    const failedEvent = receivedEvents.find((e) =>
      (e as { event?: { type: string } }).event?.type === 'job.failed'
    )
    expect(failedEvent).toBeDefined()
    const eventData = (failedEvent as { event: Record<string, unknown> }).event
    expect(eventData.error_code).toBe('compile_timeout')
    expect(eventData.upgrade_message).toBeTruthy()
    expect(eventData.user_plan).toBe('free')
  })
})

// ------------------------------------------------------------------ //
//  5. No regressions — timeout banner coexists with page count badge //
// ------------------------------------------------------------------ //

test.describe('No regressions — timeout and page count coexist', () => {
  test('timeout does not show page count badge (pageCount remains null on failure)', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page)
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'free')

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })

    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })

    // No page count badge from compile — no "1 page" / "2 pages ⚠" from this job
    // (The estimate badge ~N pages is fine — it's from useMemo, not the stream)
    await expect(page.getByTitle(/Resume is \d+ page/)).not.toBeVisible()
  })

  test('/try page has no JS errors when timeout banner appears', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockAuth(page)
    await mockCommonBackend(page)
    await mockSubmitJob(page, JOB_ID_COMPILE)
    await mockWebSocketTimeout(page, JOB_ID_COMPILE, 'pro')

    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: /Compile/i }).first().click()
    await expect(page.getByText(/Compile timed out/)).toBeVisible({ timeout: 15_000 })

    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })
})
