import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Mock data                                                          //
// ------------------------------------------------------------------ //

const MOCK_RESUME = {
  id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  user_id: 'user-1',
  title: 'Test Resume',
  latex_content: '\\documentclass{article}\\begin{document}Hello\\end{document}',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const MOCK_COVER_LETTERS = [
  {
    id: 'cl-111111-1111-1111-1111-111111111111',
    user_id: 'user-1',
    resume_id: MOCK_RESUME.id,
    job_description: 'Python developer needed',
    company_name: 'Acme Corp',
    role_title: 'Senior Engineer',
    tone: 'formal',
    length_preference: '3_paragraphs',
    latex_content: '\\documentclass{article}\\begin{document}Dear Hiring Manager\\end{document}',
    pdf_path: null,
    generation_job_id: 'job-1',
    created_at: '2025-06-15T10:00:00Z',
    updated_at: '2025-06-15T10:00:00Z',
    resume_title: 'Test Resume',
  },
  {
    id: 'cl-222222-2222-2222-2222-222222222222',
    user_id: 'user-1',
    resume_id: MOCK_RESUME.id,
    job_description: 'Frontend role at startup',
    company_name: 'StartupCo',
    role_title: 'Frontend Developer',
    tone: 'conversational',
    length_preference: '4_paragraphs',
    latex_content: '\\documentclass{article}\\begin{document}Hi there\\end{document}',
    pdf_path: null,
    generation_job_id: 'job-2',
    created_at: '2025-06-14T09:00:00Z',
    updated_at: '2025-06-14T09:00:00Z',
    resume_title: 'Test Resume',
  },
  {
    id: 'cl-333333-3333-3333-3333-333333333333',
    user_id: 'user-1',
    resume_id: MOCK_RESUME.id,
    job_description: 'Data science role',
    company_name: 'DataInc',
    role_title: 'Data Scientist',
    tone: 'enthusiastic',
    length_preference: 'detailed',
    latex_content: null,
    pdf_path: null,
    generation_job_id: 'job-3',
    created_at: '2025-06-13T08:00:00Z',
    updated_at: '2025-06-13T08:00:00Z',
    resume_title: 'Test Resume',
  },
]

const MOCK_PAGINATED_RESPONSE = {
  cover_letters: MOCK_COVER_LETTERS,
  total: 3,
  page: 1,
  limit: 20,
  pages: 1,
}

const MOCK_STATS = { total: 3 }

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

// Helper: mock the auth session API so pages think the user is logged in
async function mockAuth(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SESSION),
    })
  )
}

// ------------------------------------------------------------------ //
//  Cover Letters listing page — /workspace/cover-letters              //
// ------------------------------------------------------------------ //

test.describe('Cover Letters Listing Page (/workspace/cover-letters)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Mock cover-letters API
    await page.route((url) => {
      const path = url.pathname
      return path.startsWith('/cover-letters')
    }, async (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname

      if (path === '/cover-letters/stats') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_STATS),
        })
      }

      if ((path === '/cover-letters/' || path === '/cover-letters') && route.request().method() === 'GET') {
        const search = url.searchParams.get('search') || ''
        let filtered = [...MOCK_COVER_LETTERS]
        if (search) {
          const q = search.toLowerCase()
          filtered = filtered.filter(
            (cl) =>
              (cl.company_name || '').toLowerCase().includes(q) ||
              (cl.role_title || '').toLowerCase().includes(q)
          )
        }
        const page_ = parseInt(url.searchParams.get('page') || '1')
        const limit = parseInt(url.searchParams.get('limit') || '20')
        const total = filtered.length
        const pages = Math.max(1, Math.ceil(total / limit))
        const start = (page_ - 1) * limit
        const sliced = filtered.slice(start, start + limit)
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            cover_letters: sliced,
            total,
            page: page_,
            limit,
            pages,
          }),
        })
      }

      if (route.request().method() === 'DELETE') {
        return route.fulfill({ status: 204 })
      }

      return route.continue()
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
  })

  // ---- Basic rendering ----

  test('page loads with heading', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Cover Letter Library')
  })

  test('shows total count', async ({ page }) => {
    await expect(page.getByText('3 total')).toBeVisible()
  })

  test('renders cover letter cards in grid view', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Acme Corp' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'StartupCo' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'DataInc' })).toBeVisible()
  })

  test('cards show role title', async ({ page }) => {
    await expect(page.getByText('Senior Engineer')).toBeVisible()
    await expect(page.getByText('Frontend Developer')).toBeVisible()
  })

  test('cards show resume link', async ({ page }) => {
    const resumeLinks = page.locator(`a[href="/workspace/${MOCK_RESUME.id}/edit"]`)
    await expect(resumeLinks.first()).toBeVisible()
  })

  test('cards show tone badge', async ({ page }) => {
    await expect(page.getByText('formal').first()).toBeVisible()
    await expect(page.getByText('conversational')).toBeVisible()
    await expect(page.getByText('enthusiastic')).toBeVisible()
  })

  test('cards show date', async ({ page }) => {
    // At least one date should be rendered
    await expect(page.locator('article').first().getByText(/\d{1,2}\/\d{1,2}\/\d{4}/)).toBeVisible()
  })

  test('cards have View and Delete buttons', async ({ page }) => {
    const firstCard = page.locator('article').first()
    await expect(firstCard.getByText('View')).toBeVisible()
    await expect(firstCard.getByText('Delete')).toBeVisible()
  })

  test('View links to resume cover letter page', async ({ page }) => {
    const viewLink = page.locator('article').first().getByText('View')
    await expect(viewLink).toHaveAttribute(
      'href',
      `/workspace/${MOCK_RESUME.id}/cover-letter`
    )
  })

  // ---- Search ----

  test('search filters by company name', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search by company"]')
    await searchInput.fill('Acme')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'Acme Corp' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'StartupCo' })).not.toBeVisible()
  })

  test('search filters by role title', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search by company"]')
    await searchInput.fill('Frontend')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'StartupCo' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Acme Corp' })).not.toBeVisible()
  })

  test('search with no results shows empty state', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search by company"]')
    await searchInput.fill('nonexistent_xyz')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('No cover letters yet')).toBeVisible()
  })

  // ---- View mode toggle ----

  test('grid mode is active by default', async ({ page }) => {
    // Grid layout has article cards
    await expect(page.locator('article').first()).toBeVisible()
  })

  test('switching to list mode shows table', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    await expect(page.locator('table')).toBeVisible()
    await expect(page.locator('th', { hasText: 'Company / Role' })).toBeVisible()
    await expect(page.locator('th', { hasText: 'Resume' })).toBeVisible()
    await expect(page.locator('th', { hasText: 'Tone' })).toBeVisible()
  })

  test('list view shows all cover letters', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    await expect(page.locator('tbody tr')).toHaveCount(3)
  })

  test('list view has View and Delete actions', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    const firstRow = page.locator('tbody tr').first()
    await expect(firstRow.getByText('View')).toBeVisible()
    await expect(firstRow.getByText('Delete')).toBeVisible()
  })

  test('switching back to grid from list', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    await expect(page.locator('table')).toBeVisible()
    await page.getByRole('button', { name: 'Grid' }).click()
    await expect(page.locator('article').first()).toBeVisible()
  })

  // ---- Delete ----

  test('delete removes card from grid', async ({ page }) => {
    await expect(page.locator('article')).toHaveCount(3)
    const firstCard = page.locator('article').first()
    await firstCard.getByText('Delete').click()
    await expect(page.locator('article')).toHaveCount(2)
  })

  // ---- Navigation ----

  test('has Workspace link', async ({ page }) => {
    const link = page.getByRole('navigation').getByRole('link', { name: 'Workspace' })
    await expect(link).toHaveAttribute('href', '/workspace')
  })
})

// ------------------------------------------------------------------ //
//  Empty state                                                        //
// ------------------------------------------------------------------ //

test.describe('Cover Letters Listing — empty state', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    await page.route((url) => url.pathname.startsWith('/cover-letters'), async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === '/cover-letters/stats') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ total: 0 }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cover_letters: [],
          total: 0,
          page: 1,
          limit: 20,
          pages: 1,
        }),
      })
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
  })

  test('shows empty state message', async ({ page }) => {
    await expect(page.getByText('No cover letters yet')).toBeVisible()
  })

  test('shows CTA to workspace', async ({ page }) => {
    await expect(page.getByText('Go to Workspace')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Pagination                                                         //
// ------------------------------------------------------------------ //

test.describe('Cover Letters Listing — pagination', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Generate 5 mock CLs, serve with limit=2 to force multiple pages
    const allCLs = Array.from({ length: 5 }, (_, i) => ({
      id: `cl-page-${i}`,
      user_id: 'user-1',
      resume_id: MOCK_RESUME.id,
      job_description: `JD ${i}`,
      company_name: `Company ${i}`,
      role_title: `Role ${i}`,
      tone: 'formal',
      length_preference: '3_paragraphs',
      latex_content: null,
      pdf_path: null,
      generation_job_id: null,
      created_at: new Date(2025, 5, 15 - i).toISOString(),
      updated_at: new Date(2025, 5, 15 - i).toISOString(),
      resume_title: 'Test Resume',
    }))

    await page.route((url) => url.pathname.startsWith('/cover-letters'), async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === '/cover-letters/stats') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ total: 5 }),
        })
      }
      // The page always requests with limit=20, but we override to simulate pagination
      // by returning subsets
      const pg = parseInt(url.searchParams.get('page') || '1')
      const lim = 2 // Force small page size for testing
      const start = (pg - 1) * lim
      const sliced = allCLs.slice(start, start + lim)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cover_letters: sliced,
          total: 5,
          page: pg,
          limit: lim,
          pages: 3,
        }),
      })
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
  })

  test('shows pagination controls', async ({ page }) => {
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Previous' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Next' })).toBeVisible()
  })

  test('Previous is disabled on first page', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  test('clicking Next navigates to page 2', async ({ page }) => {
    await page.getByRole('button', { name: 'Next' }).click()
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  GlobalHeader — Cover Letters NOT in main nav (accessible via       //
//  workspace cards instead)                                           //
// ------------------------------------------------------------------ //

test.describe('GlobalHeader — Cover Letters not in nav', () => {
  test('Cover Letters link not in main nav for authenticated users', async ({ page }) => {
    await mockAuth(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    const navLink = page.locator('nav a', { hasText: 'Cover Letters' })
    await expect(navLink).not.toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Dashboard — cover letter KPI card                                  //
// ------------------------------------------------------------------ //

test.describe('Dashboard — Cover Letter stat', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Mock all dashboard APIs
    await page.route((url) => url.pathname.startsWith('/analytics'), (route) => {
      const url = new URL(route.request().url())
      if (url.pathname.includes('/timeseries')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            user_id: 'user-1',
            period_days: 30,
            activity_series: [],
            compilation_series: [],
            optimization_series: [],
            feature_series: [],
            status_distribution: {},
          }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: 'user-1',
          period_days: 30,
          total_compilations: 10,
          successful_compilations: 8,
          success_rate: 80,
          total_optimizations: 5,
          avg_compilation_time: 2.5,
          feature_usage: {},
          daily_activity: { '2025-01-01': 5 },
          most_active_day: '2025-01-01',
        }),
      })
    })

    await page.route((url) => url.pathname === '/resumes/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_resumes: 3,
          total_templates: 1,
          last_updated: '2025-01-01T00:00:00Z',
        }),
      })
    )

    await page.route((url) => url.pathname === '/cover-letters/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 7 }),
      })
    )

    await page.route((url) => url.pathname === '/jobs' || url.pathname === '/jobs/', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [] }),
      })
    )

    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
  })

  test('shows Cover Letters KPI card', async ({ page }) => {
    await expect(page.getByText('Cover Letters', { exact: true })).toBeVisible()
  })

  test('shows correct cover letter count', async ({ page }) => {
    // The KPI value "7" should appear on the page
    const kpiSection = page.locator('article', { hasText: 'Cover Letters' })
    await expect(kpiSection.locator('text=7')).toBeVisible()
  })

  test('shows cover letter description', async ({ page }) => {
    await expect(page.getByText('Generated cover letters')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Cover Letter Generation Page — /workspace/[resumeId]/cover-letter  //
// ------------------------------------------------------------------ //

test.describe('Cover Letter Generation Page', () => {
  const resumeId = MOCK_RESUME.id

  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Mock resume fetch
    await page.route((url) => url.pathname === `/resumes/${resumeId}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESUME),
      })
    )

    // Mock existing cover letters for this resume
    await page.route(
      (url) => url.pathname === `/cover-letters/resume/${resumeId}`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_COVER_LETTERS.slice(0, 2)),
        })
    )

    // Mock compile endpoint
    await page.route((url) => url.pathname === '/jobs/submit', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'compile-job-1',
          message: 'Compilation started',
        }),
      })
    )

    // Mock job state (for WebSocket fallback)
    await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'queued',
          stage: '',
          percent: 0,
          last_updated: Date.now() / 1000,
        }),
      })
    )

    // Mock analytics (fire-and-forget)
    await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
    )
  })

  // Note: this page has fullscreenPatterns match so GlobalHeader is hidden.
  // The page is an editor-style fullscreen layout.

  test('page loads without errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('shows page heading', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('h1')).toContainText('AI Cover Letter Generator')
  })

  test('shows resume title in description', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(MOCK_RESUME.title)).toBeVisible()
  })

  test('shows job description textarea', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const textarea = page.locator('textarea[placeholder*="Paste the job description"]')
    await expect(textarea).toBeVisible()
  })

  test('shows company name and role title inputs', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('input[placeholder="Company name"]')).toBeVisible()
    await expect(page.locator('input[placeholder="Role title"]')).toBeVisible()
  })

  test('shows tone selection buttons', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('button', { name: 'Formal' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Conversational' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Enthusiastic' })).toBeVisible()
  })

  test('shows length selection buttons', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('button', { name: '3 Paragraphs' })).toBeVisible()
    await expect(page.getByRole('button', { name: '4 Paragraphs' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Detailed' })).toBeVisible()
  })

  test('generate button disabled when no job description', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const btn = page.getByRole('button', { name: /Generate Cover Letter/ })
    await expect(btn).toBeDisabled()
  })

  test('generate button enabled when job description entered', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const textarea = page.locator('textarea[placeholder*="Paste the job description"]')
    await textarea.fill('We are looking for a Python developer with 5 years of experience.')
    const btn = page.getByRole('button', { name: /Generate Cover Letter/ })
    await expect(btn).toBeEnabled()
  })

  test('shows existing cover letters in sidebar', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Previous Cover Letters (2)')).toBeVisible()
    await expect(page.getByText('Acme Corp').first()).toBeVisible()
    await expect(page.getByText('StartupCo')).toBeVisible()
  })

  test('loads most recent cover letter into editor on page load', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    // The first CL (Acme Corp) should be highlighted as active in the sidebar
    // Active card uniquely has bg-violet-500/10 (tone/length buttons use bg-violet-500/20)
    const activeCard = page.locator('.border-violet-400\\/40.bg-violet-500\\/10')
    await expect(activeCard).toBeVisible()
  })

  test('has Back to Editor link', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const link = page.getByText('Back to Editor')
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute('href', `/workspace/${resumeId}/edit`)
  })

  test('has Compile PDF button', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Compile PDF')).toBeVisible()
  })

  test('has auto-compile toggle', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Auto')).toBeVisible()
  })

  test('shows Live Logs section', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Live Logs')).toBeVisible()
  })

  test('shows Output Preview section', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Output Preview')).toBeVisible()
  })

  test('tone selection changes active state', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const conversational = page.getByRole('button', { name: 'Conversational' })
    await conversational.click()
    await expect(conversational).toHaveClass(/bg-violet-500/)
  })

  test('length selection changes active state', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const detailed = page.getByRole('button', { name: 'Detailed' })
    await detailed.click()
    await expect(detailed).toHaveClass(/bg-violet-500/)
  })

  test('generation request sends correct data', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/cover-letters/generate', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'gen-job-1',
          cover_letter_id: 'new-cl-1',
          message: 'Started',
        }),
      })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')

    // Fill form
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('Need a developer')
    await page.locator('input[placeholder="Company name"]').fill('TestCo')
    await page.locator('input[placeholder="Role title"]').fill('SWE')
    await page.getByRole('button', { name: 'Conversational' }).click()
    await page.getByRole('button', { name: '4 Paragraphs' }).click()

    // Submit
    await page.getByRole('button', { name: /Generate Cover Letter/ }).click()

    // Verify captured request
    await page.waitForTimeout(500)
    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.resume_id).toBe(resumeId)
    expect(capturedBody!.job_description).toBe('Need a developer')
    expect(capturedBody!.company_name).toBe('TestCo')
    expect(capturedBody!.role_title).toBe('SWE')
    expect(capturedBody!.tone).toBe('conversational')
    expect(capturedBody!.length_preference).toBe('4_paragraphs')
  })

  test('generation adds new entry to sidebar', async ({ page }) => {
    await page.route((url) => url.pathname === '/cover-letters/generate', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'gen-job-2',
          cover_letter_id: 'new-cl-2',
          message: 'Started',
        }),
      })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')

    // Initially 2 existing CLs
    await expect(page.getByText('Previous Cover Letters (2)')).toBeVisible()

    // Fill JD and submit
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('Need a dev')
    await page.locator('input[placeholder="Company name"]').fill('NewCo')
    await page.getByRole('button', { name: /Generate Cover Letter/ }).click()

    // Should now show 3
    await expect(page.getByText('Previous Cover Letters (3)')).toBeVisible()
    await expect(page.getByText('NewCo')).toBeVisible()
  })

  test('delete cover letter from sidebar', async ({ page }) => {
    await page.route((url) => {
      return !!url.pathname.match(/\/cover-letters\/cl-/) && !url.pathname.includes('/resume/')
    }, async (route) => {
      if (route.request().method() === 'DELETE') {
        return route.fulfill({ status: 204 })
      }
      return route.continue()
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Previous Cover Letters (2)')).toBeVisible()

    // Click delete on first CL
    const deleteButtons = page.locator('button', { hasText: 'Delete' })
    // There might be multiple Delete buttons (sidebar items)
    const sidebarDeletes = page.locator('.max-h-48 button:has-text("Delete")')
    await sidebarDeletes.first().click()

    await expect(page.getByText('Previous Cover Letters (1)')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Page accessibility / navigation                                    //
// ------------------------------------------------------------------ //

test.describe('Page navigation — cover letters', () => {
  test('/workspace/cover-letters is accessible', async ({ page }) => {
    const response = await page.goto('/workspace/cover-letters')
    expect(response?.status()).toBe(200)
  })

  test('no runtime errors on cover letters page', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/workspace/cover-letters', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors.filter((e) => !e.includes('Warning:'))).toEqual([])
  })
})

// ------------------------------------------------------------------ //
//  API Client runtime validation                                      //
// ------------------------------------------------------------------ //

test.describe('API Client — cover letter methods exist', () => {
  test('no "is not a function" errors on cover letters page', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockAuth(page)
    await page.route((url) => url.pathname.startsWith('/cover-letters'), (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cover_letters: [],
          total: 0,
          page: 1,
          limit: 20,
          pages: 1,
        }),
      })
    )

    await page.goto('/workspace/cover-letters', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    const hasNotAFunctionError = errors.some((e) => e.includes('is not a function'))
    expect(hasNotAFunctionError).toBe(false)
  })

  test('cover-letters API calls made on listing page load', async ({ page }) => {
    const apiCalls: string[] = []
    await mockAuth(page)
    await page.route('**/*', async (route) => {
      const url = route.request().url()
      if (url.includes('/cover-letters')) {
        apiCalls.push(url)
      }
      if (url.includes('/cover-letters/stats')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ total: 0 }),
        })
      }
      if (url.match(/\/cover-letters\/(\?|$)/)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            cover_letters: [],
            total: 0,
            page: 1,
            limit: 20,
            pages: 1,
          }),
        })
      }
      await route.continue()
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
    expect(apiCalls.some((u) => u.includes('/cover-letters/'))).toBe(true)
  })
})
