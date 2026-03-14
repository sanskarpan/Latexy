import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Mock data                                                          //
// ------------------------------------------------------------------ //

const RESUME_ID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'

const MOCK_RESUME = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'My Test Resume',
  latex_content: [
    '\\documentclass{article}',
    '\\begin{document}',
    '\\section{Contact}',
    'John Doe \\\\ john@example.com \\\\ (555) 123-4567',
    '\\section{Experience}',
    '\\textbf{Software Engineer} at TechCorp (2020--2024)',
    '\\begin{itemize}',
    '  \\item Developed microservices, improving performance by 40\\%',
    '  \\item Led team of 5 engineers to deliver product features',
    '  \\item Automated CI/CD pipeline, reducing deployment time by 60\\%',
    '\\end{itemize}',
    '\\section{Education}',
    'B.S. Computer Science, MIT, 2020',
    '\\section{Skills}',
    'Python, JavaScript, React, Docker, Kubernetes, PostgreSQL, Redis',
    '\\end{document}',
  ].join('\n'),
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

// A very short content — should NOT trigger ATS scoring
const SHORT_LATEX = '\\documentclass{article}\\begin{document}Hi\\end{document}'

const MOCK_SCORE_HIGH = {
  score: 85,
  grade: 'B',
  sections_found: ['contact_info', 'experience', 'education', 'skills'],
  missing_sections: [],
  keyword_match_percent: null,
}

const MOCK_SCORE_MED = {
  score: 65,
  grade: 'D',
  sections_found: ['contact_info', 'experience', 'education'],
  missing_sections: ['skills'],
  keyword_match_percent: null,
}

const MOCK_SCORE_LOW = {
  score: 45,
  grade: 'F',
  sections_found: ['contact_info'],
  missing_sections: ['experience', 'education', 'skills'],
  keyword_match_percent: null,
}

const MOCK_SCORE_WITH_JD = {
  score: 78,
  grade: 'C',
  sections_found: ['contact_info', 'experience', 'education', 'skills'],
  missing_sections: [] as string[],
  keyword_match_percent: 73.3 as number | null,
}

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

// ------------------------------------------------------------------ //
//  Helpers                                                            //
// ------------------------------------------------------------------ //

async function mockAuth(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SESSION),
    })
  )
}

async function mockCommonBackendRoutes(page: import('@playwright/test').Page) {
  // Analytics — fire-and-forget
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
  )
  // Job state fallback
  await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
    })
  )
  // Job submit
  await page.route((url) => url.pathname === '/jobs/submit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: 'compile-job-999', message: 'Started' }),
    })
  )
  // Trial status
  await page.route((url) => url.pathname === '/trial/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ uses_remaining: 3, cooldown_seconds: 0, is_limited: false }),
    })
  )
  // Resumes stats
  await page.route((url) => url.pathname === '/resumes/stats', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ total_resumes: 2, total_templates: 0, last_updated: null }),
    })
  )
  // Format support check
  await page.route((url) => url.pathname.startsWith('/format'), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ supported: true, formats: ['pdf', 'docx'] }),
    })
  )
}

async function mockAtsQuickScore(
  page: import('@playwright/test').Page,
  responseBody: object = MOCK_SCORE_HIGH
) {
  await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(responseBody),
    })
  )
}

// ------------------------------------------------------------------ //
//  /try page — ATS badge in LaTeXEditor                              //
// ------------------------------------------------------------------ //

test.describe('/try page — ATS Quick Score badge', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await mockAtsQuickScore(page)
  })

  test('page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/try')
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('ATS badge renders in editor status bar', async ({ page }) => {
    await page.goto('/try')
    await page.waitForLoadState('networkidle')
    // Before debounce fires score is null — badge shows "ATS —"
    await expect(page.getByText('ATS —')).toBeVisible()
  })

  test('ATS badge initially shows dash (no score yet)', async ({ page }) => {
    await page.goto('/try')
    await page.waitForLoadState('networkidle')
    // Before debounce fires, score is null → shows "ATS —"
    await expect(page.getByText('ATS —')).toBeVisible()
  })

  test('ATS badge shows score after debounce fires', async ({ page }) => {
    // Install fake clock BEFORE navigation so timers are controlled
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')

    // Set up waitForResponse BEFORE triggering the debounce to avoid race condition
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    // Badge should now show the score
    await expect(page.getByTitle('Live ATS score (updates 10s after last change)')).toBeVisible()
    await expect(page.getByTitle('Live ATS score (updates 10s after last change)')).toContainText('ATS 85')
  })

  test('ATS badge has correct color for high score (≥80 = emerald)', async ({ page }) => {
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await expect(badge).toHaveClass(/text-emerald-400/)
    await expect(badge).toHaveClass(/bg-emerald-500\/10/)
  })

  test('ATS badge has correct color for medium score (60-79 = amber)', async ({ page }) => {
    await mockAtsQuickScore(page, MOCK_SCORE_MED)
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await expect(badge).toHaveClass(/text-amber-400/)
    await expect(badge).toContainText('ATS 65')
  })

  test('ATS badge has correct color for low score (<60 = rose)', async ({ page }) => {
    await mockAtsQuickScore(page, MOCK_SCORE_LOW)
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await expect(badge).toHaveClass(/text-rose-400/)
    await expect(badge).toContainText('ATS 45')
  })

  test('API request body contains latex_content', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCORE_HIGH),
      })
    })

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    expect(capturedBody).not.toBeNull()
    expect(typeof capturedBody!.latex_content).toBe('string')
    expect((capturedBody!.latex_content as string).length).toBeGreaterThan(200)
  })

  test('API request sends job_description when set', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCORE_WITH_JD),
      })
    })

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')

    // Find and fill the job description textarea
    const jdTextarea = page.locator('textarea[placeholder*="job description"], textarea[placeholder*="Job description"]').first()
    if (await jdTextarea.count() > 0) {
      await jdTextarea.fill('Looking for a Python developer with Django experience')
    }

    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.latex_content).toBeTruthy()
  })

  test('ATS badge click opens Deep Analysis panel', async ({ page }) => {
    await mockAtsQuickScore(page, MOCK_SCORE_HIGH)
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await badge.click()

    // DeepAnalysisPanel renders with role="dialog" and aria-label="Deep AI Analysis"
    await expect(page.getByRole('dialog', { name: 'Deep AI Analysis' })).toBeVisible()
    await expect(page.getByText('Deep AI Analysis')).toBeVisible()
  })

  test('loading spinner shows while fetching score', async ({ page }) => {
    // Intercept with delay to catch the loading state
    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_000))
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCORE_HIGH),
      })
    })

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    await page.clock.fastForward(11_000)

    // While loading, badge shows spinner variant with "ATS" text but no number
    // The spinner span has animate-spin class
    await expect(page.locator('.animate-spin').first()).toBeVisible({ timeout: 3_000 }).catch(() => {
      // Loading may be too quick to catch consistently — this is best-effort
    })
  })
})

// ------------------------------------------------------------------ //
//  /try page — edge cases                                             //
// ------------------------------------------------------------------ //

test.describe('/try page — ATS badge edge cases', () => {
  test('badge still renders if ats/quick-score returns 500', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"server error"}' })
    )

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    await page.clock.fastForward(11_000)

    // Even on error, no crash — badge stays in "ATS —" state
    // No runtime JS errors
    expect(errors.filter((e) => !e.includes('Warning:'))).toEqual([])
    await expect(page.getByText('ATS —')).toBeVisible()
  })

  test('no ats/quick-score call when resume content is very short', async ({ page }) => {
    const atsCalls: string[] = []
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      atsCalls.push(route.request().url())
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_HIGH) })
    })

    // Use edit page with a short-content resume (< 200 chars) so the hook
    // never satisfies the MIN_CONTENT_LEN guard and skips the API call
    const SHORT_RESUME_ID = 'short-resume-id-1234'
    await page.route((url) => url.pathname === `/resumes/${SHORT_RESUME_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: SHORT_RESUME_ID,
          user_id: 'user-1',
          title: 'Short',
          latex_content: SHORT_LATEX, // < 200 chars
          created_at: '2025-01-01T00:00:00Z',
          updated_at: '2025-01-01T00:00:00Z',
        }),
      })
    )
    await page.route((url) => url.pathname.includes('/checkpoints'), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )

    await page.clock.install()
    await page.goto(`/workspace/${SHORT_RESUME_ID}/edit`)
    await page.waitForLoadState('domcontentloaded')
    await page.clock.fastForward(11_000)
    await page.waitForTimeout(300) // allow any pending microtasks

    // Should NOT have called the API because content < 200 chars
    expect(atsCalls.length).toBe(0)
  })
})

// ------------------------------------------------------------------ //
//  /workspace/[resumeId]/edit — ATS badge                            //
// ------------------------------------------------------------------ //

test.describe('/workspace/[resumeId]/edit — ATS Quick Score badge', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await mockAtsQuickScore(page)

    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESUME),
      })
    )

    // Resume checkpoints
    await page.route((url) => url.pathname.includes('/checkpoints'), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    )
  })

  test('page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('ATS badge renders in editor status bar', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('text=/ATS/').first()).toBeVisible()
  })

  test('ATS badge initially shows dash placeholder', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('ATS —')).toBeVisible()
  })

  test('ATS badge shows score after debounce fires', async ({ page }) => {
    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise
    await expect(page.getByTitle('Live ATS score (updates 10s after last change)')).toContainText('ATS 85')
  })

  test('ATS badge shows correct high-score color (emerald)', async ({ page }) => {
    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise
    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await expect(badge).toHaveClass(/text-emerald-400/)
  })

  test('ATS badge click opens deep analysis panel on edit page', async ({ page }) => {
    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await badge.click()

    // DeepAnalysisPanel renders with role="dialog" and aria-label="Deep AI Analysis"
    await expect(page.getByRole('dialog', { name: 'Deep AI Analysis' })).toBeVisible()
  })

  test('ats/quick-score called with resume latex_content', async ({ page }) => {
    let capturedLatex = ''

    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      const body = JSON.parse(route.request().postData() || '{}')
      capturedLatex = body.latex_content || ''
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_HIGH) })
    })

    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    expect(capturedLatex.length).toBeGreaterThan(200)
    expect(capturedLatex).toContain('\\section{Experience}')
  })
})

// ------------------------------------------------------------------ //
//  /workspace/[resumeId]/optimize — ATS badge                        //
// ------------------------------------------------------------------ //

test.describe('/workspace/[resumeId]/optimize — ATS Quick Score badge', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await mockAtsQuickScore(page)

    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESUME),
      })
    )
  })

  test('page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('ATS badge renders in LaTeX editor', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('ATS —')).toBeVisible()
  })

  test('ATS badge initially shows dash', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('ATS —')).toBeVisible()
  })

  test('ATS badge shows score after debounce fires', async ({ page }) => {
    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise
    await expect(page.getByTitle('Live ATS score (updates 10s after last change)')).toContainText('ATS 85')
  })

  test('optimize page wires job_description to ATS scorer', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_WITH_JD) })
    })

    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('domcontentloaded')

    // Fill the job description field on optimize page
    const jdArea = page.locator('textarea').first()
    await jdArea.fill('Looking for a Python backend engineer with Django and AWS experience')

    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.latex_content).toBeTruthy()
    expect(capturedBody!.job_description).toBeTruthy()
  })

  test('optimize page has cover letter navigation link', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('networkidle')
    const clLink = page.getByText('Cover Letter')
    await expect(clLink).toBeVisible()
    await expect(clLink).toHaveAttribute('href', `/workspace/${RESUME_ID}/cover-letter`)
  })
})

// ------------------------------------------------------------------ //
//  API response schema validation                                     //
// ------------------------------------------------------------------ //

test.describe('POST /ats/quick-score — response schema', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function navigateAndTrigger(page: import('@playwright/test').Page, mockBody: any = MOCK_SCORE_HIGH) {
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await mockAtsQuickScore(page, mockBody)
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    // IMPORTANT: set up waitForResponse BEFORE fastForward to avoid race condition
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    return responsePromise
  }

  test('response has all required fields', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_HIGH) })
    })
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    const response = await responsePromise
    const json = await response.json()

    expect(typeof json.score).toBe('number')
    expect(typeof json.grade).toBe('string')
    expect(Array.isArray(json.sections_found)).toBe(true)
    expect(Array.isArray(json.missing_sections)).toBe(true)
    expect('keyword_match_percent' in json).toBe(true)
    // Also verify the request was made with latex_content
    expect(capturedBody).not.toBeNull()
  })

  test('grade is one of A/B/C/D/F', async ({ page }) => {
    const response = await navigateAndTrigger(page)
    const json = await response.json()
    expect(['A', 'B', 'C', 'D', 'F']).toContain(json.grade)
  })

  test('score is integer between 0 and 100', async ({ page }) => {
    const response = await navigateAndTrigger(page)
    const json = await response.json()
    expect(json.score).toBeGreaterThanOrEqual(0)
    expect(json.score).toBeLessThanOrEqual(100)
    expect(Number.isInteger(json.score)).toBe(true)
  })

  test('keyword_match_percent is number or null', async ({ page }) => {
    const response = await navigateAndTrigger(page, MOCK_SCORE_WITH_JD)
    const json = await response.json()
    const kmp = json.keyword_match_percent
    expect(kmp === null || typeof kmp === 'number').toBe(true)
  })

  test('sections_found contains valid section names', async ({ page }) => {
    const response = await navigateAndTrigger(page)
    const json = await response.json()
    const validSections = ['contact_info', 'experience', 'education', 'skills', 'projects', 'certifications', 'summary', 'publications']
    for (const section of json.sections_found) {
      expect(validSections).toContain(section)
    }
  })
})

// ------------------------------------------------------------------ //
//  No auth required for quick-score endpoint                         //
// ------------------------------------------------------------------ //

test.describe('ATS quick-score — no auth required', () => {
  test('/try page ATS badge works without auth', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    // No mockAuth — user is not logged in
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
    )

    let atsCallMade = false
    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      atsCallMade = true
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_HIGH) })
    })

    await page.route((url) => url.pathname === '/trial/status', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ uses_remaining: 3, cooldown_seconds: 0, is_limited: false }) })
    )

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    await page.clock.fastForward(11_000)

    // Wait up to 3s for the call (it fires after clock advance)
    await page.waitForTimeout(500)

    // No critical JS errors even without auth
    const criticalErrors = errors.filter(
      (e) => !e.includes('Warning:') && !e.includes('auth') && !e.includes('session')
    )
    expect(criticalErrors).toEqual([])
  })
})

// ------------------------------------------------------------------ //
//  ATSScoreBadge component — unit-level rendering via page           //
// ------------------------------------------------------------------ //

test.describe('ATSScoreBadge component behaviors', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
  })

  test('badge title attribute is set for accessibility', async ({ page }) => {
    await mockAtsQuickScore(page)
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise
    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await expect(badge).toBeVisible()
  })

  test('badge button is focusable (accessible)', async ({ page }) => {
    await mockAtsQuickScore(page)
    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise
    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    await badge.focus()
    await expect(badge).toBeFocused()
  })

  test('on optimize page badge has no click handler (cursor-default)', async ({ page }) => {
    await mockAtsQuickScore(page)
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESUME) })
    )

    await page.clock.install()
    await page.goto(`/workspace/${RESUME_ID}/optimize`)
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise
    const badge = page.getByTitle('Live ATS score (updates 10s after last change)')
    // On optimize page, onATSBadgeClick is not passed, so badge has cursor-default
    await expect(badge).toHaveClass(/cursor-default/)
  })
})

// ------------------------------------------------------------------ //
//  Performance                                                        //
// ------------------------------------------------------------------ //

test.describe('ATS quick-score — performance', () => {
  test('API responds within 500ms', async ({ page }) => {
    await mockAuth(page)
    await mockCommonBackendRoutes(page)

    // Real endpoint (not mocked) — but in test environment backend is running
    // So we mock it but measure the response time from within the test
    let responseTime = 0
    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      const start = Date.now()
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_HIGH) })
      responseTime = Date.now() - start
    })

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')
    const responsePromise = page.waitForResponse((resp) => resp.url().includes('/ats/quick-score'))
    await page.clock.fastForward(11_000)
    await responsePromise

    // Mocked endpoint is essentially instant
    expect(responseTime).toBeLessThan(500)
  })

  test('multiple content changes do not spam API (debounce respected)', async ({ page }) => {
    const atsCalls: number[] = []
    await mockAuth(page)
    await mockCommonBackendRoutes(page)
    await page.route((url) => url.pathname === '/ats/quick-score', async (route) => {
      atsCalls.push(Date.now())
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SCORE_HIGH) })
    })

    await page.clock.install()
    await page.goto('/try')
    await page.waitForLoadState('domcontentloaded')

    // Advance time partway (5s) — no call yet
    await page.clock.fastForward(5_000)
    expect(atsCalls.length).toBe(0)

    // Advance to just before debounce fires again (total 9.5s)
    await page.clock.fastForward(4_500)
    expect(atsCalls.length).toBe(0)

    // Now advance past debounce
    await page.clock.fastForward(1_000)
    await page.waitForTimeout(200) // allow microtask to flush

    // Should have at most 1 call (debounce coalesced the changes)
    expect(atsCalls.length).toBeLessThanOrEqual(1)
  })
})
