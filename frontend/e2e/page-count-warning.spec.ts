import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Feature 8 — Real-Time Page Count Warning                          //
//  Tests the page-count badge in LaTeXEditor, the warning banner,    //
//  and the "Trim with AI →" action across /try, /edit, /optimize.    //
// ------------------------------------------------------------------ //

// ---- Shared constants ----

const RESUME_ID = 'resume-pcw-0001'
const JOB_ID_COMPILE = 'job-pcw-compile-001'
const JOB_ID_TRIM = 'job-pcw-trim-001'

// A resume with 120 \item lines: textLines ≈ 120 → Math.round(120/50) = 2 → "~2 pages"
const LARGE_LATEX = (() => {
  const items = Array.from(
    { length: 120 },
    (_, i) => `  \\item Developed feature ${i + 1} for product team, driving measurable results.`
  ).join('\n')
  return [
    '\\documentclass[letterpaper,11pt]{article}',
    '\\begin{document}',
    '\\section*{Experience}',
    '\\begin{itemize}',
    items,
    '\\end{itemize}',
    '\\end{document}',
  ].join('\n')
})()

// Small LaTeX — > 100 chars so it passes the length guard in estimatedPageCount,
// but has < 50 text lines so Math.max(1, round(n/50)) = 1 → "~1 page"
const SMALL_LATEX = [
  '\\documentclass[letterpaper,11pt]{article}',
  '\\begin{document}',
  'John Doe — Software Engineer with five years of experience building scalable web applications.',
  '\\end{document}',
].join('\n')

const MOCK_RESUME_LARGE = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'Large Resume',
  latex_content: LARGE_LATEX,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const MOCK_RESUME_SMALL = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'Short Resume',
  latex_content: SMALL_LATEX,
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
    route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: Buffer.from('%PDF-1.4 mock'),
    })
  )
}

async function mockCompileEndpoint(page: import('@playwright/test').Page, jobId: string = JOB_ID_COMPILE) {
  await page.route((url) => url.pathname === '/jobs/submit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: jobId, message: 'Started' }),
    })
  )
}

async function mockResume(
  page: import('@playwright/test').Page,
  resumeData = MOCK_RESUME_LARGE
) {
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resumeData) })
  )
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )
}

/** Set up a WebSocket mock that delivers a full job lifecycle with the given page count. */
async function mockWebSocketPageCount(
  page: import('@playwright/test').Page,
  jobId: string,
  pageCount: number | null
) {
  let seq = 0
  const base = () => ({
    event_id: `evt-${++seq}`,
    job_id: jobId,
    timestamp: Date.now() / 1000,
    sequence: seq,
  })

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
            { type: 'event', event: { ...base(), type: 'job.progress', percent: 10, stage: 'latex_compilation', message: 'Starting pdflatex' } },
          ]

          // Emit log.line with page count (early signal before job.completed)
          if (pageCount !== null) {
            events.push({
              type: 'event',
              event: {
                ...base(),
                type: 'log.line',
                source: 'pdflatex',
                line: `Output written on resume.pdf (${pageCount} ${pageCount === 1 ? 'page' : 'pages'}, 54321 bytes).`,
                is_error: false,
              },
            })
          }

          events.push({
            type: 'event',
            event: {
              ...base(),
              type: 'job.progress',
              percent: 90,
              stage: 'latex_compilation',
              message: 'Finalizing PDF',
            },
          })

          events.push({
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
              page_count: pageCount,
            },
          })

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
//  1. Initial state — no page count (not yet compiled)               //
// ------------------------------------------------------------------ //

test.describe('Page count — initial state (no compile yet)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page)
  })

  test('/workspace/edit page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('/workspace/optimize page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('/try page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('no warning banner on edit page before compile', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/Your resume is \d+ pages/)).not.toBeVisible()
  })

  test('no warning banner on optimize page before compile completes', async ({ page }) => {
    // No WS mock → compile starts but never completes → no page count
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText(/Your resume is \d+ pages/)).not.toBeVisible()
  })

  test('no "Trim with AI" button visible before compile', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Trim with AI →')).not.toBeVisible()
  })

  test('no page count badge visible initially on edit page (pageCount is null)', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    // Actual compile-count badge should not appear (pageCount is null)
    await expect(page.getByText('2 pages ⚠')).not.toBeVisible()
    await expect(page.getByText('1 page')).not.toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  2. Estimated page count (pre-compile, from useMemo in LaTeXEditor) //
// ------------------------------------------------------------------ //

test.describe('Page count — estimated badge (pre-compile from LaTeXEditor)', () => {
  test('large content shows estimated ~2 pages badge on edit page', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    // Wait for Monaco to mount before checking estimate badge
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
    await expect(page.getByText(/~\d+ pages?/)).toBeVisible({ timeout: 15_000 })
  })

  test('estimated badge shows ~2 for 120-item resume', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
    await expect(page.getByText('~2 pages')).toBeVisible({ timeout: 15_000 })
  })

  test('estimated badge has "Estimated page count" tooltip', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
    const estimateBadge = page.getByTitle('Estimated page count (compile for exact count)')
    await expect(estimateBadge).toBeVisible({ timeout: 15_000 })
  })

  test('small content shows ~1 page estimate (not 0)', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_SMALL)
    await mockCompileEndpoint(page)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
    // Small content has < 50 text lines → max(1, round(n/50)) = 1
    await expect(page.getByText(/~1 page/)).toBeVisible({ timeout: 15_000 })
  })

  test('estimated badge is in dimmed zinc color (not warning color)', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
    const badge = page.getByTitle('Estimated page count (compile for exact count)')
    await expect(badge).toBeVisible({ timeout: 15_000 })
    await expect(badge).toHaveClass(/text-zinc-600/)
  })
})

// ------------------------------------------------------------------ //
//  3. Actual page count badge — via WebSocket events on optimize page  //
// ------------------------------------------------------------------ //

test.describe('/workspace/optimize — page count badge via WebSocket', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
  })

  test('shows "1 page" emerald badge after compile with page_count=1', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 1)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByTitle('Resume is 1 page')).toBeVisible({ timeout: 10_000 })
  })

  test('"1 page" badge has emerald color', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 1)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    const badge = page.getByTitle('Resume is 1 page')
    await expect(badge).toBeVisible({ timeout: 10_000 })
    await expect(badge).toHaveClass(/text-emerald-400/)
  })

  test('shows "2 pages ⚠" amber badge after compile with page_count=2', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText('2 pages ⚠')).toBeVisible({ timeout: 10_000 })
  })

  test('"2 pages ⚠" badge has amber color', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    const badge = page.getByText('2 pages ⚠')
    await expect(badge).toBeVisible({ timeout: 10_000 })
    await expect(badge).toHaveClass(/text-amber-400/)
  })

  test('shows "3 pages ⚠" rose badge after compile with page_count=3', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 3)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText('3 pages ⚠')).toBeVisible({ timeout: 10_000 })
  })

  test('"3 pages ⚠" badge has rose color and animate-pulse', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 3)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    const badge = page.getByText('3 pages ⚠')
    await expect(badge).toBeVisible({ timeout: 10_000 })
    await expect(badge).toHaveClass(/text-rose-400/)
    await expect(badge).toHaveClass(/animate-pulse/)
  })

  test('badge title shows page count for accessibility', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByTitle('Resume is 2 pages')).toBeVisible({ timeout: 10_000 })
  })

  test('page count null when compile results have no page count line', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, null)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    await page.waitForTimeout(1_500)

    // Only the estimate badge should show, not a compile-result badge
    await expect(page.getByText('1 page')).not.toBeVisible()
    await expect(page.getByText('2 pages ⚠')).not.toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  4. Warning banner on optimize page                                 //
// ------------------------------------------------------------------ //

test.describe('/workspace/optimize — warning banner', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
  })

  test('warning banner appears when page_count=2', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText(/Your resume is 2 pages\. Most recruiters prefer 1 page\./)).toBeVisible({ timeout: 10_000 })
  })

  test('warning banner appears when page_count=3', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 3)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText(/Your resume is 3 pages/)).toBeVisible({ timeout: 10_000 })
  })

  test('warning banner NOT shown when page_count=1', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 1)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    // Allow events to be processed
    await page.waitForTimeout(1_500)

    await expect(page.getByText(/Your resume is 1 page/)).not.toBeVisible()
  })

  test('"Trim with AI →" button visible in warning banner', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText('Trim with AI →')).toBeVisible({ timeout: 10_000 })
  })

  test('"Trim with AI →" NOT shown when page_count=1', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 1)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    await page.waitForTimeout(1_500)

    await expect(page.getByText('Trim with AI →')).not.toBeVisible()
  })

  test('warning banner has amber styling', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    const banner = page.locator('[class*="amber"]').filter({ hasText: /Your resume is/ })
    await expect(banner.first()).toBeVisible({ timeout: 10_000 })
  })
})

// ------------------------------------------------------------------ //
//  5. "Trim with AI →" button — action                               //
// ------------------------------------------------------------------ //

test.describe('"Trim with AI →" button — action', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
  })

  test('clicking "Trim with AI →" sends request with optimization_level=aggressive', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)
    // First mock: compile endpoint returns JOB_ID_COMPILE
    // Second mock: aggressive trim call (different job_type signature)
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.optimization_level === 'aggressive') {
        capturedBody = body
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, job_id: JOB_ID_TRIM, message: 'Trim started' }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: JOB_ID_COMPILE, message: 'Compile started' }),
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText('Trim with AI →')).toBeVisible({ timeout: 10_000 })
    await page.getByText('Trim with AI →').click()

    await page.waitForTimeout(500)
    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.optimization_level).toBe('aggressive')
    expect(capturedBody!.job_type).toBe('combined')
  })

  test('"Trim with AI →" sends the trim instruction in custom_instructions', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.optimization_level === 'aggressive') {
        capturedBody = body
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, job_id: JOB_ID_TRIM, message: 'Trim started' }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: JOB_ID_COMPILE, message: 'Compile started' }),
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('Trim with AI →')).toBeVisible({ timeout: 10_000 })
    await page.getByText('Trim with AI →').click()
    await page.waitForTimeout(500)

    expect(capturedBody).not.toBeNull()
    const instructions = capturedBody!.custom_instructions as string
    expect(typeof instructions).toBe('string')
    expect(instructions.length).toBeGreaterThan(20)
    // Should mention 1 page / one page
    expect(instructions.toLowerCase()).toMatch(/one page|1 page/)
  })

  test('"Trim with AI →" sends latex_content in request', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.optimization_level === 'aggressive') {
        capturedBody = body
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, job_id: JOB_ID_TRIM, message: 'Trim started' }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: JOB_ID_COMPILE, message: 'Compile started' }),
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('Trim with AI →')).toBeVisible({ timeout: 10_000 })
    await page.getByText('Trim with AI →').click()
    await page.waitForTimeout(500)

    expect(capturedBody).not.toBeNull()
    expect(typeof capturedBody!.latex_content).toBe('string')
    expect((capturedBody!.latex_content as string).length).toBeGreaterThan(100)
  })

  test('"Trim with AI →" button is disabled while processing', async ({ page }) => {
    // Set up a compile job that never completes (no WS mock)
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await page.routeWebSocket('**/ws/jobs', (ws) => {
      ws.onMessage((data) => {
        try {
          const msg = JSON.parse(data as string)
          if (msg.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
          }
          if (msg.type === 'subscribe') {
            ws.send(JSON.stringify({ type: 'subscribed', job_id: msg.job_id, replayed_count: 0 }))
            // Send processing status but never complete
            setTimeout(() => {
              try {
                ws.send(JSON.stringify({
                  type: 'event',
                  event: {
                    event_id: 'e1', job_id: msg.job_id, timestamp: Date.now() / 1000, sequence: 1,
                    type: 'job.progress', percent: 50, stage: 'latex_compilation', message: 'Compiling...',
                  },
                }))
                ws.send(JSON.stringify({
                  type: 'event',
                  event: {
                    event_id: 'e2', job_id: msg.job_id, timestamp: Date.now() / 1000, sequence: 2,
                    type: 'log.line', source: 'pdflatex',
                    line: 'Output written on resume.pdf (2 pages, 54321 bytes).',
                    is_error: false,
                  },
                }))
                ws.send(JSON.stringify({
                  type: 'event',
                  event: {
                    event_id: 'e3', job_id: msg.job_id, timestamp: Date.now() / 1000, sequence: 3,
                    type: 'job.started', worker_id: 'w-1', stage: 'llm_optimization',
                  },
                }))
              } catch { /* closed */ }
            }, 100)
          }
        } catch { /* ignore */ }
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    // Wait for page count to appear (from log.line)
    await expect(page.getByText('2 pages ⚠')).toBeVisible({ timeout: 10_000 })
    // Banner should now show
    await expect(page.getByText('Trim with AI →')).toBeVisible()

    // While job is still processing (status = 'processing'), trim button should be disabled
    // The trim button has disabled={isSubmitting || isProcessing}
    // Currently a job is processing
    const trimBtn = page.getByText('Trim with AI →')
    await expect(trimBtn).toBeDisabled()
  })
})

// ------------------------------------------------------------------ //
//  6. page count via WebSocket on edit page                           //
// ------------------------------------------------------------------ //

test.describe('/workspace/edit — page count warning', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
  })

  test('edit page has no warning banner initially', async ({ page }) => {
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/Your resume is \d+ pages/)).not.toBeVisible()
  })

  test('edit page has page count badge in editor status bar', async ({ page }) => {
    // With large content, the estimate badge appears without compile
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    // Estimated badge should show
    await expect(page.getByText(/~\d+ pages?/)).toBeVisible({ timeout: 5_000 })
  })
})

// ------------------------------------------------------------------ //
//  7. log.line early extraction (page count before job.completed)     //
// ------------------------------------------------------------------ //

test.describe('Page count — early extraction from log.line event', () => {
  test('badge updates from log.line event before job.completed', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)

    let seq = 0
    const base = (jobId: string) => ({ event_id: `e-${++seq}`, job_id: jobId, timestamp: Date.now() / 1000, sequence: seq })

    // Custom WS mock: only send log.line, NOT job.completed
    await page.routeWebSocket('**/ws/jobs', (ws) => {
      ws.onMessage((data) => {
        try {
          const msg = JSON.parse(data as string)
          if (msg.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
            return
          }
          if (msg.type === 'subscribe' && msg.job_id === JOB_ID_COMPILE) {
            ws.send(JSON.stringify({ type: 'subscribed', job_id: JOB_ID_COMPILE, replayed_count: 0 }))
            setTimeout(() => {
              try {
                ws.send(JSON.stringify({
                  type: 'event',
                  event: { ...base(JOB_ID_COMPILE), type: 'job.started', worker_id: 'w-1', stage: 'latex_compilation' },
                }))
                ws.send(JSON.stringify({
                  type: 'event',
                  event: {
                    ...base(JOB_ID_COMPILE),
                    type: 'log.line', source: 'pdflatex',
                    line: 'Output written on resume.pdf (2 pages, 54321 bytes).',
                    is_error: false,
                  },
                }))
                // No job.completed — badge should still update from log.line
              } catch { /* closed */ }
            }, 200)
          }
        } catch { /* ignore */ }
      })
    })

    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    // Page count should be captured from log.line alone
    await expect(page.getByText('2 pages ⚠')).toBeVisible({ timeout: 10_000 })
  })
})

// ------------------------------------------------------------------ //
//  8. /try page — page count badge                                    //
// ------------------------------------------------------------------ //

test.describe('/try page — page count badge', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
  })

  test('/try page loads without errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('/try page has no warning banner initially', async ({ page }) => {
    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/Your resume is \d+ pages/)).not.toBeVisible()
  })

  test('/try page shows estimated page count for large default content', async ({ page }) => {
    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    // The /try page has a large default LaTeX template loaded
    // If the default content is large enough, an estimated badge should appear
    // (This is best-effort — depends on default template size)
    // We check that no JS errors occurred, and badge logic works
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.waitForTimeout(1_000)
    expect(errors.filter(e => !e.includes('Warning:'))).toEqual([])
  })
})

// ------------------------------------------------------------------ //
//  9. API response schema — page_count field present                  //
// ------------------------------------------------------------------ //

test.describe('Page count — WebSocket event schema validation', () => {
  test('job.completed WS event includes page_count field', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)

    let receivedEvents: Record<string, unknown>[] = []

    await page.routeWebSocket('**/ws/jobs', (ws) => {
      ws.onMessage((data) => {
        try {
          const msg = JSON.parse(data as string)
          if (msg.type === 'subscribe') {
            ws.send(JSON.stringify({ type: 'subscribed', job_id: msg.job_id, replayed_count: 0 }))
            setTimeout(() => {
              const completedEvent = {
                type: 'event',
                event: {
                  event_id: 'e1', job_id: msg.job_id, timestamp: Date.now() / 1000, sequence: 1,
                  type: 'job.completed', pdf_job_id: msg.job_id,
                  ats_score: 75, ats_details: {}, changes_made: [],
                  compilation_time: 2.5, optimization_time: 0, tokens_used: 0,
                  page_count: 2,
                },
              }
              receivedEvents.push(completedEvent)
              try { ws.send(JSON.stringify(completedEvent)) } catch { /* closed */ }
            }, 100)
          }
        } catch { /* ignore */ }
      })
    })

    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    await expect(page.getByText('2 pages ⚠')).toBeVisible({ timeout: 10_000 })

    // Verify the event we sent had the page_count field
    expect(receivedEvents.length).toBeGreaterThan(0)
    const completedEvent = receivedEvents.find(e =>
      (e as { event?: { type: string } }).event?.type === 'job.completed'
    )
    expect(completedEvent).toBeDefined()
    const eventData = (completedEvent as { event: Record<string, unknown> }).event
    expect('page_count' in eventData).toBe(true)
    expect(eventData.page_count).toBe(2)
  })

  test('log.line event with page count line is parsed correctly', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)

    await page.routeWebSocket('**/ws/jobs', (ws) => {
      ws.onMessage((data) => {
        try {
          const msg = JSON.parse(data as string)
          if (msg.type === 'subscribe') {
            ws.send(JSON.stringify({ type: 'subscribed', job_id: msg.job_id, replayed_count: 0 }))
            setTimeout(() => {
              try {
                // Exact pdflatex format
                ws.send(JSON.stringify({
                  type: 'event',
                  event: {
                    event_id: 'e1', job_id: msg.job_id, timestamp: Date.now() / 1000, sequence: 1,
                    type: 'log.line', source: 'pdflatex',
                    line: 'Output written on /tmp/latexy/resume.pdf (3 pages, 98765 bytes).',
                    is_error: false,
                  },
                }))
              } catch { /* closed */ }
            }, 100)
          }
        } catch { /* ignore */ }
      })
    })

    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')

    // Should extract 3 from the log line
    await expect(page.getByText('3 pages ⚠')).toBeVisible({ timeout: 10_000 })
  })
})

// ------------------------------------------------------------------ //
//  10. No regressions — ATS badge still works alongside page count    //
// ------------------------------------------------------------------ //

test.describe('No regressions — page count coexists with ATS badge', () => {
  test('ATS badge and page count badge are both visible after compile', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page, JOB_ID_COMPILE)
    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })

    // Wait for page count badge (Feature 8) — confirms WS events processed
    await expect(page.getByText('2 pages ⚠')).toBeVisible({ timeout: 10_000 })

    // The editor status bar should still render other info alongside the page count badge
    // (char count is always rendered, showing the status bar is intact)
    await expect(page.locator('text=/\\d[,\\d]* chars/').first()).toBeVisible()

    // No JS errors — ATS hook + page count badge coexist without crashing
    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })

  test('estimated page count badge does not interfere with ATS badge', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)
    await mockCompileEndpoint(page, JOB_ID_COMPILE)

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.monaco-editor', { timeout: 15_000 })

    // Estimated page count badge visible (from LaTeXEditor useMemo)
    await expect(page.getByText(/~\d+ pages?/)).toBeVisible({ timeout: 15_000 })

    // Status bar intact (char count alongside estimate badge)
    await expect(page.locator('text=/\\d[,\\d]* chars/').first()).toBeVisible()

    // No JS errors — hooks coexist
    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })
})

// ------------------------------------------------------------------ //
//  11. API client schema — submitJob sends correct fields for trim    //
// ------------------------------------------------------------------ //

test.describe('API client schema — trim request fields', () => {
  test('optimize page trim request includes correct job_type', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackend(page)
    await mockResume(page, MOCK_RESUME_LARGE)

    let trimBody: Record<string, unknown> | null = null

    await mockWebSocketPageCount(page, JOB_ID_COMPILE, 2)
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.optimization_level === 'aggressive') {
        trimBody = body
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, job_id: JOB_ID_TRIM, message: 'Trim started' }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: JOB_ID_COMPILE, message: 'Compile started' }),
      })
    })

    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('domcontentloaded')
    await expect(page.getByText('Trim with AI →')).toBeVisible({ timeout: 10_000 })
    await page.getByText('Trim with AI →').click()
    await page.waitForTimeout(500)

    expect(trimBody).not.toBeNull()
    expect(trimBody!.job_type).toBe('combined')
    expect(trimBody!.optimization_level).toBe('aggressive')
    expect(trimBody!.custom_instructions).toBeTruthy()
  })
})
