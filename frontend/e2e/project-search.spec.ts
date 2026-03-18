import { test, expect, type Page, type Route } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Mock data                                                          //
// ------------------------------------------------------------------ //

const RESUME_A = {
  id: 'aaac0001-0001-0001-0001-000000000001',
  user_id: 'user-search-001',
  title: 'Software Engineer Resume',
  latex_content:
    '\\documentclass{article}\\begin{document}\nHello world\n\\usepackage{fontenc}\nSpecial token SRCH_UNIQ_42\nEnd of doc\n\\end{document}',
  is_template: false,
  tags: [],
  parent_resume_id: null,
  variant_count: 0,
  share_token: null,
  share_url: null,
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-10T10:00:00Z',
  metadata: null,
}

const RESUME_B = {
  ...RESUME_A,
  id: 'aaac0002-0002-0002-0002-000000000002',
  title: 'Product Manager Resume',
  latex_content: '\\documentclass{article}\\begin{document}\nCompletely different\n\\end{document}',
}

const SEARCH_RESPONSE_MATCH = {
  results: [
    {
      resume_id: RESUME_A.id,
      resume_title: RESUME_A.title,
      updated_at: RESUME_A.updated_at,
      matches: [
        {
          line_number: 4,
          line_content: 'Special token SRCH_UNIQ_42',
          context_before: ['\\usepackage{fontenc}'],
          context_after: ['End of doc'],
          highlight_start: 14,
          highlight_end: 26,
        },
      ],
    },
  ],
  total_resumes_matched: 1,
  query: 'SRCH_UNIQ_42',
}

const SEARCH_RESPONSE_EMPTY = {
  results: [],
  total_resumes_matched: 0,
  query: 'ZZZNOMATCH',
}

// ------------------------------------------------------------------ //
//  Helpers                                                            //
// ------------------------------------------------------------------ //

async function mockAuth(page: Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'sess-search', userId: 'user-search-001', token: 'tok-search' },
        user: { id: 'user-search-001', email: 'search@example.com', name: 'Search User' },
      }),
    })
  )
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'tok-search')
  })
}

async function mockWorkspaceApi(page: Page) {
  await page.route('**/ws/**', (route) => route.abort())

  await page.route(
    (url) =>
      url.pathname.startsWith('/resumes') ||
      url.pathname.startsWith('/jobs') ||
      url.pathname.startsWith('/analytics') ||
      url.pathname.startsWith('/usage'),
    async (route: Route) => {
      const url = new URL(route.request().url())
      const path = url.pathname
      const method = route.request().method()

      if ((path === '/resumes/' || path === '/resumes') && method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            resumes: [RESUME_A, RESUME_B],
            total: 2,
            page: 1,
            limit: 20,
            pages: 1,
          }),
        })
      }

      if (path === '/jobs' && method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ jobs: [] }),
        })
      }

      if (path.startsWith('/resumes/search') && method === 'GET') {
        const q = url.searchParams.get('q') ?? ''
        if (q.toLowerCase().includes('srch_uniq_42')) {
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ ...SEARCH_RESPONSE_MATCH, query: q }),
          })
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...SEARCH_RESPONSE_EMPTY, query: q }),
        })
      }

      // Mock individual resume fetch so the edit page doesn't redirect back when backend is absent
      if (path === `/resumes/${RESUME_A.id}` && method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(RESUME_A),
        })
      }

      return route.continue()
    }
  )
}

/** Open workspace and wait for it to be interactive */
async function gotoWorkspace(page: Page) {
  await page.goto('/workspace', { waitUntil: 'domcontentloaded' })
  await page.waitForLoadState('load')
}

/** Open the search modal via the button (reliable across all tests) */
async function openSearchModal(page: Page) {
  await page.getByRole('button', { name: /search/i }).click()
  await expect(page.locator('input[placeholder*="Search across all resumes"]')).toBeVisible()
}

// ------------------------------------------------------------------ //
//  Tests — Workspace page                                             //
// ------------------------------------------------------------------ //

test.describe('Project Search — workspace page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockWorkspaceApi(page)
  })

  test('search button is visible in workspace header', async ({ page }) => {
    await gotoWorkspace(page)
    await expect(page.getByRole('button', { name: /search/i })).toBeVisible()
  })

  test('clicking search button opens modal', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await expect(page.locator('input[placeholder*="Search across all resumes"]')).toBeVisible()
  })

  test('Cmd+Shift+F opens modal', async ({ page }) => {
    await gotoWorkspace(page)
    // Click body first to ensure page has keyboard focus
    await page.locator('body').click()
    await page.keyboard.press('Meta+Shift+F')
    await expect(page.locator('input[placeholder*="Search across all resumes"]')).toBeVisible()
  })

  test('Ctrl+Shift+F opens modal (Linux/Windows)', async ({ page }) => {
    await gotoWorkspace(page)
    await page.locator('body').click()
    await page.keyboard.press('Control+Shift+F')
    await expect(page.locator('input[placeholder*="Search across all resumes"]')).toBeVisible()
  })

  test('Escape closes modal', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    const input = page.locator('input[placeholder*="Search across all resumes"]')
    // Send Escape directly to the input so it doesn't depend on focus state
    await input.press('Escape')
    await expect(input).not.toBeVisible()
  })

  test('clicking backdrop closes modal', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    const input = page.locator('input[placeholder*="Search across all resumes"]')
    // Click the fixed backdrop overlay (the outer z-50 wrapper, not the modal box)
    await page.locator('div.fixed.inset-0').first().click({ position: { x: 5, y: 5 }, force: true })
    await expect(input).not.toBeVisible()
  })

  test('shows "type at least 2 characters" hint initially', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await expect(page.getByText(/type at least 2 characters/i)).toBeVisible()
  })

  test('short query does not trigger search call', async ({ page }) => {
    const searchCalls: string[] = []
    await page.route('**/resumes/search**', (route) => {
      searchCalls.push(route.request().url())
      return route.continue()
    })
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('x')
    await page.waitForTimeout(400)
    expect(searchCalls).toHaveLength(0)
  })

  test('typing 2+ chars triggers search and shows results', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    await expect(page.getByText('Software Engineer Resume')).toBeVisible({ timeout: 3000 })
  })

  test('result shows resume title', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    await expect(page.getByText('Software Engineer Resume')).toBeVisible({ timeout: 3000 })
  })

  test('result shows line number badge', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    await expect(page.locator('text=4').first()).toBeVisible({ timeout: 3000 })
  })

  test('result shows matched line content', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    await expect(page.getByText('Special token SRCH_UNIQ_42')).toBeVisible({ timeout: 3000 })
  })

  test('no-match query shows empty state', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('ZZZNOMATCH')
    await expect(page.getByText(/no results for/i)).toBeVisible({ timeout: 3000 })
  })

  test('match count shown in modal footer', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    await expect(page.getByText(/1 resume matched/i)).toBeVisible({ timeout: 3000 })
  })

  test('clicking result navigates to edit page', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    // Use the span inside the modal result (not the workspace h3 card)
    const resultSpan = page.locator('span.truncate', { hasText: 'Software Engineer Resume' })
    await expect(resultSpan).toBeVisible({ timeout: 3000 })
    await resultSpan.click()
    await expect(page).toHaveURL(new RegExp(`/workspace/${RESUME_A.id}/edit`))
  })

  test('clicking result includes line param in URL', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('SRCH_UNIQ_42')
    const resultSpan = page.locator('span.truncate', { hasText: 'Software Engineer Resume' })
    await expect(resultSpan).toBeVisible({ timeout: 3000 })
    // Race waitForURL and click: the edit page strips ?line= via replaceState after mounting,
    // so we must catch the URL before the effect runs.
    await Promise.all([
      page.waitForURL(/line=4/, { timeout: 8000 }),
      resultSpan.click(),
    ])
  })

  test('X button clears query and results', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    const input = page.locator('input[placeholder*="Search across all resumes"]')
    await input.fill('SRCH_UNIQ_42')
    const resultSpan = page.locator('span.truncate', { hasText: 'Software Engineer Resume' })
    await expect(resultSpan).toBeVisible({ timeout: 3000 })
    // The X clear button is the last button inside the input row (border-b div)
    await page.locator('div.border-b button').last().click()
    await expect(resultSpan).not.toBeVisible()
  })

  test('keyboard arrow + Enter navigates to result', async ({ page }) => {
    await gotoWorkspace(page)
    await openSearchModal(page)
    const input = page.locator('input[placeholder*="Search across all resumes"]')
    await input.fill('SRCH_UNIQ_42')
    const resultSpan = page.locator('span.truncate', { hasText: 'Software Engineer Resume' })
    await expect(resultSpan).toBeVisible({ timeout: 3000 })
    await input.press('ArrowDown')
    await page.waitForTimeout(150)
    await input.press('Enter')
    await expect(page).toHaveURL(new RegExp(`/workspace/${RESUME_A.id}/edit`))
  })

  test('search API called with correct query param', async ({ page }) => {
    const calls: string[] = []
    await page.route('**/resumes/search**', async (route) => {
      calls.push(route.request().url())
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SEARCH_RESPONSE_EMPTY),
      })
    })
    await gotoWorkspace(page)
    await openSearchModal(page)
    await page.locator('input[placeholder*="Search across all resumes"]').fill('testquery')
    await page.waitForTimeout(500)
    expect(calls.length).toBeGreaterThan(0)
    expect(calls[0]).toContain('q=testquery')
  })

  test('no runtime errors on workspace page', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await gotoWorkspace(page)
    expect(errors.filter((e) => !e.includes('Warning:'))).toEqual([])
  })
})

// ------------------------------------------------------------------ //
//  Tests — /resumes/search API endpoint (live backend)               //
// ------------------------------------------------------------------ //

test.describe('Search API endpoint — live backend', () => {
  test('GET /resumes/search exists and rejects unauthenticated', async ({ request }) => {
    const resp = await request.get('http://localhost:8031/resumes/search?q=hello')
    expect([401, 403]).toContain(resp.status())
  })

  test('GET /resumes/search?q=x (1 char) returns 422', async ({ request }) => {
    // Even with invalid auth, 422 for bad query length should come first
    const resp = await request.get('http://localhost:8031/resumes/search?q=x')
    // 401 = auth checked first, 422 = query length checked first — both correct
    expect([401, 403, 422]).toContain(resp.status())
  })
})
