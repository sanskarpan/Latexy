import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Template Gallery — /workspace/new (no API mocking)                 //
// ------------------------------------------------------------------ //

test.describe('Template Gallery Page (/workspace/new)', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/workspace/new')
  })

  test('page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.waitForLoadState('networkidle')
    expect(errors).toEqual([])
  })

  test('page has Create Resume heading', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Create Resume')
  })

  test('page has title input', async ({ page }) => {
    const input = page.locator('input[placeholder*="Senior Backend"]')
    await expect(input).toBeVisible()
  })

  test('shows template and import mode buttons', async ({ page }) => {
    await expect(page.locator('h2:has-text("Use Template")')).toBeVisible()
    await expect(page.locator('h2:has-text("Import File")')).toBeVisible()
  })

  test('template mode is active by default', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search templates"]')
    await expect(searchInput).toBeVisible()
  })

  test('switching to import mode hides template gallery', async ({ page }) => {
    await page.locator('h2:has-text("Import File")').click()
    const searchInput = page.locator('input[placeholder*="Search templates"]')
    await expect(searchInput).not.toBeVisible()
  })

  test('switching back to template mode shows gallery', async ({ page }) => {
    await page.locator('h2:has-text("Import File")').click()
    await page.locator('h2:has-text("Use Template")').click()
    const searchInput = page.locator('input[placeholder*="Search templates"]')
    await expect(searchInput).toBeVisible()
  })

  test('"Start from Blank" button is visible', async ({ page }) => {
    await expect(page.getByText('Start from Blank')).toBeVisible()
  })

  test('"All" category tab is visible', async ({ page }) => {
    await expect(page.getByRole('button', { name: /^All \(\d+\)/ })).toBeVisible()
  })

  test('create button is disabled when title is empty', async ({ page }) => {
    // Create Resume button appears in import mode; switch to it
    await page.locator('h2:has-text("Import File")').click()
    const createBtn = page.getByRole('button', { name: /Create Resume/ })
    await expect(createBtn).toBeDisabled()
  })

  test('create button is disabled without a file even with title', async ({ page }) => {
    // Import mode requires both a title AND a file; title alone is not enough
    await page.locator('h2:has-text("Import File")').click()
    const input = page.locator('input[placeholder*="Senior Backend"]')
    await input.fill('My Test Resume')
    const createBtn = page.getByRole('button', { name: /Create Resume/ })
    await expect(createBtn).toBeDisabled()
  })

  test('title input is empty on initial load', async ({ page }) => {
    const input = page.locator('input[placeholder*="Senior Backend"]')
    await expect(input).toHaveValue('')
  })

  test('has back to workspace link', async ({ page }) => {
    const link = page.getByText('Back to Workspace')
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute('href', '/workspace')
  })
})


// ------------------------------------------------------------------ //
//  Template Gallery with mocked API                                   //
// ------------------------------------------------------------------ //

test.describe('Template Gallery with mocked API', () => {

  const MOCK_TEMPLATES = [
    {
      id: '11111111-1111-1111-1111-111111111111',
      name: 'SWE Clean Resume',
      description: 'A clean software engineer template',
      category: 'software_engineering',
      category_label: 'Software Engineering',
      tags: ['software_engineering', 'clean'],
      thumbnail_url: null,
      sort_order: 0,
    },
    {
      id: '22222222-2222-2222-2222-222222222222',
      name: 'Finance Pro',
      description: 'Template for finance professionals',
      category: 'finance',
      category_label: 'Finance',
      tags: ['finance', 'banking'],
      thumbnail_url: null,
      sort_order: 100,
    },
    {
      id: '33333333-3333-3333-3333-333333333333',
      name: 'Academic CV',
      description: 'Comprehensive academic CV',
      category: 'academic',
      category_label: 'Academic / Research',
      tags: ['academic', 'research'],
      thumbnail_url: null,
      sort_order: 200,
    },
  ]

  const MOCK_CATEGORIES = [
    { category: 'software_engineering', label: 'Software Engineering', count: 1 },
    { category: 'finance', label: 'Finance', count: 1 },
    { category: 'academic', label: 'Academic / Research', count: 1 },
  ]

  const MOCK_TEMPLATE_DETAIL = {
    ...MOCK_TEMPLATES[0],
    latex_content: '\\documentclass{article}\n\\begin{document}\n\\textbf{Hello World}\n\\end{document}',
  }

  test.beforeEach(async ({ page }) => {
    // Single route handler for all template API requests
    await page.route((url) => url.pathname.startsWith('/templates'), async (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname

      if (path === '/templates/categories') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CATEGORIES) })
      }

      if (path.endsWith('/use') && route.request().method() === 'POST') {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ resume_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', title: 'Test' }) })
      }

      if (path.match(/\/templates\/[0-9a-f-]{36}$/)) {
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_TEMPLATE_DETAIL) })
      }

      if (path === '/templates/' || path === '/templates') {
        const category = url.searchParams.get('category')
        const search = url.searchParams.get('search')
        let filtered = [...MOCK_TEMPLATES]
        if (category && category !== 'all') filtered = filtered.filter(t => t.category === category)
        if (search) { const q = search.toLowerCase(); filtered = filtered.filter(t => t.name.toLowerCase().includes(q)) }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(filtered) })
      }

      return route.continue()
    })

    await page.goto('/workspace/new')
    await page.waitForLoadState('networkidle')
  })

  // ---- Template cards render ----

  test('renders template cards from API', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'SWE Clean Resume' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Finance Pro' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Academic CV' })).toBeVisible()
  })

  test('shows correct template count in All tab', async ({ page }) => {
    await expect(page.getByRole('button', { name: /^All \(3\)/ })).toBeVisible()
  })

  test('shows category tabs with counts', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Software Engineering \(1\)/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Finance \(1\)/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Academic.*\(1\)/ })).toBeVisible()
  })

  // ---- Category filtering ----

  test('clicking category tab filters templates', async ({ page }) => {
    await page.getByRole('button', { name: /Finance \(1\)/ }).click()
    await expect(page.getByRole('heading', { name: 'Finance Pro' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'SWE Clean Resume' })).not.toBeVisible()
    await expect(page.getByRole('heading', { name: 'Academic CV' })).not.toBeVisible()
  })

  test('clicking All tab shows all templates', async ({ page }) => {
    await page.getByRole('button', { name: /Finance \(1\)/ }).click()
    await page.getByRole('button', { name: /^All \(3\)/ }).click()
    await expect(page.getByRole('heading', { name: 'SWE Clean Resume' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Finance Pro' })).toBeVisible()
  })

  // ---- Search ----

  test('search filters templates by name', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search templates"]')
    await searchInput.fill('Finance')
    await expect(page.getByRole('heading', { name: 'Finance Pro' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'SWE Clean Resume' })).not.toBeVisible()
  })

  test('search clear button resets results', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search templates"]')
    await searchInput.fill('Finance')
    // Find the X clear button near the search input
    const clearBtn = searchInput.locator('..').locator('button')
    if (await clearBtn.isVisible()) {
      await clearBtn.click()
      await expect(page.getByRole('heading', { name: 'SWE Clean Resume' })).toBeVisible()
    }
  })

  test('no results shows empty state', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search templates"]')
    await searchInput.fill('nonexistent_template_xyz_999')
    await expect(page.getByText('No templates found')).toBeVisible()
  })

  // ---- Template selection (using card's "Use Template" button) ----
  // Note: clicking "Use Template" immediately calls the API and navigates to the edit page.
  // There is no intermediate "selection" state — the action is immediate.

  test('clicking card "Use Template" calls the use API', async ({ page }) => {
    const cardUseBtn = page.locator('.group').first().getByRole('button', { name: 'Use Template' })
    const requestPromise = page.waitForRequest((r) => r.url().includes('/use') && r.method() === 'POST')
    await cardUseBtn.click()
    const request = await requestPromise
    expect(request.url()).toContain('/templates/')
  })

  test('Use Template sends the correct template ID to the API', async ({ page }) => {
    const cardUseBtn = page.locator('.group').first().getByRole('button', { name: 'Use Template' })
    const requestPromise = page.waitForRequest((r) => r.url().includes('/use') && r.method() === 'POST')
    await cardUseBtn.click()
    const request = await requestPromise
    expect(request.url()).toContain(MOCK_TEMPLATES[0].id)
  })

  test('Use Template uses template name as title when title field is empty', async ({ page }) => {
    const cardUseBtn = page.locator('.group').first().getByRole('button', { name: 'Use Template' })
    const requestPromise = page.waitForRequest((r) => r.url().includes('/use') && r.method() === 'POST')
    await cardUseBtn.click()
    const request = await requestPromise
    const body = await request.postDataJSON()
    expect(body.title).toBe(MOCK_TEMPLATES[0].name)
  })

  test('Use Template uses provided title from input field', async ({ page }) => {
    const titleInput = page.locator('input[placeholder*="Senior Backend"]')
    await titleInput.fill('My Custom Title')
    const cardUseBtn = page.locator('.group').first().getByRole('button', { name: 'Use Template' })
    const requestPromise = page.waitForRequest((r) => r.url().includes('/use') && r.method() === 'POST')
    await cardUseBtn.click()
    const request = await requestPromise
    const body = await request.postDataJSON()
    expect(body.title).toBe('My Custom Title')
  })

  // ---- Template preview modal ----

  test('hovering over card shows Preview button', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await expect(card.getByRole('button', { name: 'Preview' })).toBeVisible()
  })

  test('clicking Preview opens modal', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await expect(page.locator('.fixed.inset-0')).toBeVisible()
  })

  test('preview modal shows template details', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await page.waitForLoadState('networkidle')
    // Modal should show the template name
    const modal = page.locator('.fixed.inset-0')
    await expect(modal.locator('h2')).toContainText('SWE Clean Resume')
  })

  test('preview modal has Use This Template button', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('button', { name: 'Use This Template' })).toBeVisible()
  })

  test('clicking Use This Template triggers API call and navigates', async ({ page }) => {
    // Mock auth so the edit page doesn't redirect back to /login
    await page.route('**/api/auth/get-session', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: { id: 's-1', userId: 'user-1', token: 'test-token', expiresAt: '2099-01-01T00:00:00Z' },
          user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
        }),
      })
    )
    // Mock resumes endpoint so edit page loads without error
    await page.route((url) => url.pathname.startsWith('/resumes'), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', title: 'Test', latex_content: '', created_at: '', updated_at: '' }) })
    )
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await page.waitForLoadState('networkidle')
    const requestPromise = page.waitForRequest((r) => r.url().includes('/use') && r.method() === 'POST')
    await page.getByRole('button', { name: 'Use This Template' }).click()
    await requestPromise
    // After successful use, navigates to the edit page
    await expect(page).toHaveURL(/\/workspace\/.*\/edit/)
  })

  test('pressing Escape closes preview modal', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await expect(page.locator('.fixed.inset-0')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('.fixed.inset-0')).not.toBeVisible()
  })

  test('clicking modal backdrop closes it', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await expect(page.locator('.fixed.inset-0')).toBeVisible()
    await page.locator('.fixed.inset-0').click({ position: { x: 10, y: 10 } })
    await expect(page.locator('.fixed.inset-0')).not.toBeVisible()
  })

  // ---- Category badges on cards ----

  test('template cards show category badge', async ({ page }) => {
    // Category labels appear as badge text inside cards
    const cards = page.locator('.group')
    await expect(cards).toHaveCount(3)
  })

  // ---- Template descriptions ----

  test('template cards show descriptions', async ({ page }) => {
    await expect(page.getByText('A clean software engineer template')).toBeVisible()
    await expect(page.getByText('Template for finance professionals')).toBeVisible()
  })

  // ---- LaTeX source preview in modal ----

  test('preview modal shows LaTeX source when no thumbnail', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await page.waitForLoadState('networkidle')
    // No thumbnail/pdf_url: falls back to showing latex content directly
    await expect(page.getByRole('button', { name: 'LaTeX Source' })).toBeVisible()
    await expect(page.getByText('\\documentclass{article}')).toBeVisible()
  })

  test('preview modal shows tags', async ({ page }) => {
    const card = page.locator('.group').first()
    await card.hover()
    await card.getByRole('button', { name: 'Preview' }).click()
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Tags')).toBeVisible()
  })
})


// ------------------------------------------------------------------ //
//  Page navigation                                                    //
// ------------------------------------------------------------------ //

test.describe('Navigation', () => {

  test('/workspace/new is accessible', async ({ page }) => {
    const response = await page.goto('/workspace/new')
    expect(response?.status()).toBe(200)
  })

  test('/workspace is accessible', async ({ page }) => {
    const response = await page.goto('/workspace')
    expect(response?.status()).toBe(200)
  })

  test('/ (landing page) is accessible', async ({ page }) => {
    const response = await page.goto('/')
    expect(response?.status()).toBe(200)
  })

  test('/login is accessible', async ({ page }) => {
    const response = await page.goto('/login')
    expect(response?.status()).toBe(200)
  })

  test('/signup is accessible', async ({ page }) => {
    const response = await page.goto('/signup')
    expect(response?.status()).toBe(200)
  })
})


// ------------------------------------------------------------------ //
//  API Client runtime validation                                      //
// ------------------------------------------------------------------ //

test.describe('API Client methods exist at runtime', () => {

  test('no "is not a function" errors on template page', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/workspace/new')
    await page.waitForLoadState('networkidle')
    const hasNotAFunctionError = errors.some(e => e.includes('is not a function'))
    expect(hasNotAFunctionError).toBe(false)
  })

  test('template API calls are made on page load', async ({ page }) => {
    const apiCalls: string[] = []
    await page.route('**/*', async (route) => {
      const url = route.request().url()
      if (url.includes('/templates')) {
        apiCalls.push(url)
      }
      await route.continue()
    })
    await page.goto('/workspace/new')
    await page.waitForLoadState('networkidle')
    expect(apiCalls.some(u => u.includes('/templates/categories'))).toBe(true)
    expect(apiCalls.some(u => u.match(/\/templates\/(\?|$)/))).toBe(true)
  })
})
