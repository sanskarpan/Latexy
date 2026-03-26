import { test, expect, type Page, type Route } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Mock data                                                          //
// ------------------------------------------------------------------ //

const RESUME_ID = 'aaaa1111-1111-1111-1111-111111111111'
const FORK_ID = 'bbbb2222-2222-2222-2222-222222222222'
const JOB_ID = 'job-tailor-001'

const MOCK_RESUME = {
  id: RESUME_ID,
  user_id: 'user-test-001',
  title: 'Full Stack Developer Resume',
  latex_content: '\\documentclass{article}\\begin{document}Hello\\end{document}',
  is_template: false,
  tags: [],
  parent_resume_id: null,
  variant_count: 0,
  share_token: null,
  share_url: null,
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-10T10:00:00Z',
}

const MOCK_FORK = {
  ...MOCK_RESUME,
  id: FORK_ID,
  title: 'Full Stack Developer Resume — Senior SWE',
  parent_resume_id: RESUME_ID,
  variant_count: 0,
}

const QUICK_TAILOR_RESPONSE = {
  fork_id: FORK_ID,
  job_id: JOB_ID,
}

const MOCK_JD =
  'We are looking for a Senior Software Engineer with 5+ years of experience in Python and FastAPI to build scalable microservices.'

// ------------------------------------------------------------------ //
//  Setup helpers                                                      //
// ------------------------------------------------------------------ //

async function mockAuthAndApi(page: Page) {
  await page.route('**/ws/**', (route) => route.abort())

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'test-session', userId: 'user-test-001', token: 'test-token' },
        user: { id: 'user-test-001', email: 'test@example.com', name: 'Test User' },
      }),
    })
  )

  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-token-mock')
  })

  await page.route(
    (url) => url.pathname.startsWith('/resumes') || url.pathname.startsWith('/jobs'),
    async (route: Route) => {
      const url = new URL(route.request().url())
      const path = url.pathname
      const method = route.request().method()

      // GET /resumes/ — list resumes
      if ((path === '/resumes/' || path === '/resumes') && method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            resumes: [MOCK_RESUME],
            total: 1,
            page: 1,
            limit: 20,
            pages: 1,
          }),
        })
      }

      // GET /resumes/:id — get resume
      if (path.match(/^\/resumes\/[0-9a-f-]{36}$/) && method === 'GET') {
        const id = path.split('/')[2]
        const resume = id === FORK_ID ? MOCK_FORK : MOCK_RESUME
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(resume),
        })
      }

      // POST /resumes/:id/quick-tailor
      if (path.match(/^\/resumes\/[0-9a-f-]{36}\/quick-tailor$/) && method === 'POST') {
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(QUICK_TAILOR_RESPONSE),
        })
      }

      // PUT /resumes/:id — update (for saving optimized content)
      if (path.match(/^\/resumes\/[0-9a-f-]{36}$/) && method === 'PUT') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...MOCK_FORK, updated_at: new Date().toISOString() }),
        })
      }

      // GET /jobs — list jobs
      if ((path === '/jobs' || path === '/jobs/') && method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ jobs: [] }),
        })
      }

      return route.continue()
    }
  )
}

async function openQuickTailorModal(page: Page) {
  await page.goto('/workspace')
  await page.waitForLoadState('networkidle')
  await page.getByRole('button', { name: /tailor/i }).first().click()
  await expect(page.getByRole('heading', { name: /quick tailor/i })).toBeVisible()
}

// ------------------------------------------------------------------ //
//  Tests                                                              //
// ------------------------------------------------------------------ //

test.describe('Quick Tailor — workspace integration', () => {
  test('Quick Tailor button is visible on resume card', async ({ page }) => {
    await mockAuthAndApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')

    const tailorBtn = page.getByRole('button', { name: /tailor/i }).first()
    await expect(tailorBtn).toBeVisible()
  })

  test('clicking Quick Tailor opens the modal', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    // Modal header and description
    await expect(page.getByText(/quick tailor/i).first()).toBeVisible()
    await expect(page.getByPlaceholder(/paste the full job description/i)).toBeVisible()
  })

  test('modal shows optional company and role inputs', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    await expect(page.getByPlaceholder(/e\.g\. google/i)).toBeVisible()
    await expect(page.getByPlaceholder(/e\.g\. senior swe/i)).toBeVisible()
  })

  test('"Start Tailoring" is disabled when job description is too short', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    const btn = page.getByRole('button', { name: /start tailoring/i })
    await expect(btn).toBeDisabled()

    // Type less than 10 characters
    await page.getByPlaceholder(/paste the full job description/i).fill('short')
    await expect(btn).toBeDisabled()
  })

  test('"Start Tailoring" is enabled when job description is long enough', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    await page.getByPlaceholder(/paste the full job description/i).fill(MOCK_JD)
    const btn = page.getByRole('button', { name: /start tailoring/i })
    await expect(btn).toBeEnabled()
  })

  test('submitting form transitions to progress step', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    await page.getByPlaceholder(/paste the full job description/i).fill(MOCK_JD)
    await page.getByRole('button', { name: /start tailoring/i }).click()

    // Progress step should appear (progress bar or stage text)
    await expect(page.locator('.h-1\\.5').first()).toBeVisible()
  })

  test('modal captures company and role inputs and sends them', async ({ page }) => {
    await mockAuthAndApi(page)

    let capturedBody: Record<string, unknown> | null = null
    await page.route('**/resumes/**/quick-tailor', async (route) => {
      const body = route.request().postData()
      if (body) capturedBody = JSON.parse(body) as Record<string, unknown>
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(QUICK_TAILOR_RESPONSE),
      })
    })

    await openQuickTailorModal(page)

    await page.getByPlaceholder(/e\.g\. google/i).fill('Google')
    await page.getByPlaceholder(/e\.g\. senior swe/i).fill('Senior SWE')
    await page.getByPlaceholder(/paste the full job description/i).fill(MOCK_JD)
    await page.getByRole('button', { name: /start tailoring/i }).click()

    await expect(async () => {
      expect(capturedBody).not.toBeNull()
      expect(capturedBody!.company_name).toBe('Google')
      expect(capturedBody!.role_title).toBe('Senior SWE')
      expect(capturedBody!.job_description).toBe(MOCK_JD)
    }).toPass()
  })

  test('modal can be closed with Cancel button', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    await page.getByRole('button', { name: /^cancel$/i }).click()
    await expect(page.getByRole('heading', { name: /quick tailor/i })).not.toBeVisible()
  })

  test('modal can be closed by clicking the X button', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    // X button is the only button in the header area without text
    await page.locator('button[class*="rounded-md"][class*="p-1.5"]').click()
    await expect(page.getByRole('heading', { name: /quick tailor/i })).not.toBeVisible()
  })

  test('modal closes on Escape key', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    await page.keyboard.press('Escape')
    await expect(page.getByRole('heading', { name: /quick tailor/i })).not.toBeVisible()
  })

  test('modal shows the resume title in the description', async ({ page }) => {
    await mockAuthAndApi(page)
    await openQuickTailorModal(page)

    await expect(page.getByText(/Full Stack Developer Resume/).first()).toBeVisible()
  })
})

test.describe('Quick Tailor — error state', () => {
  test('shows error state when API call fails', async ({ page }) => {
    await mockAuthAndApi(page)

    // Override quick-tailor to fail
    await page.route('**/resumes/**/quick-tailor', (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      })
    )

    await openQuickTailorModal(page)
    await page.getByPlaceholder(/paste the full job description/i).fill(MOCK_JD)
    await page.getByRole('button', { name: /start tailoring/i }).click()

    await expect(page.getByText(/tailoring failed/i)).toBeVisible()
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible()
  })

  test('"Try Again" button resets to form step', async ({ page }) => {
    await mockAuthAndApi(page)

    await page.route('**/resumes/**/quick-tailor', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"error"}' })
    )

    await openQuickTailorModal(page)
    await page.getByPlaceholder(/paste the full job description/i).fill(MOCK_JD)
    await page.getByRole('button', { name: /start tailoring/i }).click()
    await expect(page.getByRole('button', { name: /try again/i })).toBeVisible()

    await page.getByRole('button', { name: /try again/i }).click()
    await expect(page.getByPlaceholder(/paste the full job description/i)).toBeVisible()
  })
})

test.describe('Quick Tailor — list view', () => {
  test('Quick Tailor (Tailor) button is visible in list view', async ({ page }) => {
    await mockAuthAndApi(page)
    await page.goto('/workspace')
    await page.waitForLoadState('networkidle')

    // Switch to list view
    await page.getByRole('button', { name: /list/i }).click()
    await expect(page.getByRole('button', { name: /tailor/i }).first()).toBeVisible()
  })
})
