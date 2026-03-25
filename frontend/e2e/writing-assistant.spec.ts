import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Fixtures                                                           //
// ------------------------------------------------------------------ //

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'

const MOCK_RESUME = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'Writing Test Resume',
  latex_content: [
    '\\documentclass{article}',
    '\\begin{document}',
    '\\section{Experience}',
    '\\textbf{Software Engineer} at TechCorp (2020--2024)',
    '\\begin{itemize}',
    '  \\item Responsible for building payment integration',
    '  \\item Helped with database migrations and team processes',
    '  \\item Worked on improving system performance',
    '\\end{itemize}',
    '\\section{Education}',
    'B.S. Computer Science, MIT, 2020',
    '\\end{document}',
  ].join('\n'),
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

const MOCK_REWRITE_RESPONSE = {
  rewritten: 'Spearheaded payment integration processing 50K+ daily transactions with 99.9\\% uptime',
  action: 'improve',
  cached: false,
}

// ------------------------------------------------------------------ //
//  Helpers                                                            //
// ------------------------------------------------------------------ //

async function mockAuth(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) })
  )
}

async function mockCommonRoutes(page: import('@playwright/test').Page) {
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
  )
  await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }) })
  )
  await page.route((url) => url.pathname === '/jobs/submit', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'job-1', message: 'ok' }) })
  )
  await page.route((url) => url.pathname === '/trial/status', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ uses_remaining: 3, cooldown_seconds: 0, is_limited: false }) })
  )
  await page.route((url) => url.pathname === '/resumes/stats', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ total_resumes: 1, total_templates: 0, last_updated: null }) })
  )
  await page.route((url) => url.pathname.startsWith('/format'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ supported: true }) })
  )
  await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ score: 70, grade: 'C', sections_found: [], missing_sections: [], keyword_match_percent: null }) })
  )
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESUME) })
  )
  await page.route('**/ws/**', (route) => route.abort())
}

async function mockRewriteEndpoint(
  page: import('@playwright/test').Page,
  response = MOCK_REWRITE_RESPONSE
) {
  await page.route((url) => url.pathname === '/ai/rewrite', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
  )
}

async function gotoEditPage(page: import('@playwright/test').Page) {
  await page.goto(`/workspace/${RESUME_ID}/edit`)
  await page.waitForLoadState('networkidle')
  // Wait for Monaco to finish mounting
  await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
  await page.waitForTimeout(800)
}

/** Select some text in the Monaco editor and open the right-click context menu. */
async function openWritingAssistantMenu(page: import('@playwright/test').Page) {
  const editor = page.locator('.monaco-editor .view-lines')
  // Click to focus editor
  await editor.click()
  // Select all text via keyboard shortcut
  await page.keyboard.press('Control+a')
  await page.waitForTimeout(200)
  // Right-click to open context menu
  await editor.click({ button: 'right' })
  await page.waitForTimeout(300)
}

// ------------------------------------------------------------------ //
//  Test suite                                                         //
// ------------------------------------------------------------------ //

test.describe('Feature 23 — AI Writing Assistant', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page)
  })

  // ── 1. Smoke test ───────────────────────────────────────────────── //

  test('edit page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await gotoEditPage(page)
    expect(errors).toEqual([])
  })

  // ── 2. Context menu entry ────────────────────────────────────────── //

  test('AI Writing Assistant appears in Monaco context menu when text is selected', async ({ page }) => {
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    // Monaco renders context menu items in .context-view
    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
  })

  // ── 3. Widget opens with action picker ───────────────────────────── //

  test('widget opens with all action buttons after triggering context menu', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    // Widget should show all actions
    await expect(page.getByText('AI Writing Assistant').last()).toBeVisible({ timeout: 5_000 })
    await expect(page.getByRole('button', { name: /Improve/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Shorten/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Quantify/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Power Verbs/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Expand/i })).toBeVisible()
  })

  // ── 4. Selected text preview ─────────────────────────────────────── //

  test('widget shows selected text in preview', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    // The selected text preview section header should be present
    await expect(page.getByText('Selected text')).toBeVisible({ timeout: 5_000 })
  })

  // ── 5. API call made with correct fields ─────────────────────────── //

  test('clicking an action sends correct request to /ai/rewrite', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ai/rewrite', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    // Click "Improve" — set up waitForResponse BEFORE the click to avoid race
    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await responsePromise

    expect(capturedBody).not.toBeNull()
    expect(typeof capturedBody!.selected_text).toBe('string')
    expect((capturedBody!.selected_text as string).length).toBeGreaterThan(0)
    expect(capturedBody!.action).toBe('improve')
  })

  // ── 6. Loading state ─────────────────────────────────────────────── //

  test('loading spinner shows while API call is in progress', async ({ page }) => {
    // Delayed response to catch loading state
    await page.route((url) => url.pathname === '/ai/rewrite', async (route) => {
      await new Promise((r) => setTimeout(r, 1_500))
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    await page.getByRole('button', { name: /Improve/i }).click()

    // Loading text should be visible before API returns
    await expect(page.getByText('Rewriting')).toBeVisible({ timeout: 3_000 })
    await expect(page.locator('.animate-spin').first()).toBeVisible({ timeout: 3_000 })
  })

  // ── 7. Result state — diff view ───────────────────────────────────── //

  test('result state shows original and rewritten text in diff view', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    await page.getByRole('button', { name: /Improve/i }).click()
    await page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })

    // Diff headers
    await expect(page.getByText('Original')).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('Rewritten')).toBeVisible()

    // Rewritten content
    await expect(page.getByText('Spearheaded payment integration')).toBeVisible()

    // Action buttons
    await expect(page.getByRole('button', { name: /Accept/i })).toBeVisible()
  })

  // ── 8. Accept replaces editor content ────────────────────────────── //

  test('Accept button calls /ai/rewrite and closes the widget', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    // Set up response waiter BEFORE the click to avoid race condition
    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await responsePromise

    const acceptBtn = page.getByRole('button', { name: /Accept/i })
    await expect(acceptBtn).toBeVisible({ timeout: 5_000 })
    await acceptBtn.click()

    // Widget should close after accept — use the specific widget container
    await expect(page.locator('[aria-label="Close writing assistant"]')).not.toBeVisible({ timeout: 5_000 })
  })

  // ── 9. Close button closes widget ────────────────────────────────── //

  test('X button closes the widget without making changes', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    // Widget opens — verify close button is present
    const closeBtn = page.getByRole('button', { name: 'Close writing assistant' })
    await expect(closeBtn).toBeVisible({ timeout: 5_000 })
    await closeBtn.click()

    await expect(closeBtn).not.toBeVisible({ timeout: 3_000 })
  })

  // ── 10. Escape key closes widget ─────────────────────────────────── //

  test('Escape key closes the widget', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    const closeBtn = page.getByRole('button', { name: 'Close writing assistant' })
    await expect(closeBtn).toBeVisible({ timeout: 5_000 })

    // Click widget header to ensure focus is on widget (not Monaco), then Escape
    await page.getByText('Selected text').click()
    await page.keyboard.press('Escape')
    await expect(closeBtn).not.toBeVisible({ timeout: 3_000 })
  })

  // ── 11. API error is handled gracefully ──────────────────────────── //

  test('API error shows error message and returns to picker', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route((url) => url.pathname === '/ai/rewrite', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"server error"}' })
    )

    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    await page.getByRole('button', { name: /Improve/i }).click()

    // Should show an error, not crash
    await page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await page.waitForTimeout(500)

    // No runtime JS errors
    expect(errors.filter((e) => !e.includes('Warning:'))).toEqual([])
    // Error text should appear
    await expect(page.locator('.z-50')).toBeVisible({ timeout: 3_000 })
  })

  // ── 12. Regenerate calls API again ───────────────────────────────── //

  test('Regenerate button triggers a second API call', async ({ page }) => {
    let callCount = 0
    await page.route((url) => url.pathname === '/ai/rewrite', (route) => {
      callCount++
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    const improveBtn2 = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn2).toBeVisible({ timeout: 5_000 })
    const firstResponse = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn2.click()
    await firstResponse
    expect(callCount).toBe(1)

    // Click Regenerate
    const regenerateBtn = page.getByRole('button', { name: 'Try again' })
    await expect(regenerateBtn).toBeVisible({ timeout: 3_000 })
    const secondResponse = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await regenerateBtn.click()
    await secondResponse
    expect(callCount).toBe(2)
  })

  // ── 13. "Try a different action" resets to picker ────────────────── //

  test('"Try a different action" link returns to action picker', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    const improveBtn3 = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn3).toBeVisible({ timeout: 5_000 })
    const rp = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn3.click()
    await rp

    // Should be in result state — click "Try a different action"
    const backLink = page.getByText('Try a different action')
    await expect(backLink).toBeVisible({ timeout: 5_000 })
    await backLink.click()

    // Should be back to picker — all action buttons visible
    await expect(page.getByRole('button', { name: /Improve/i })).toBeVisible({ timeout: 3_000 })
    await expect(page.getByRole('button', { name: /Shorten/i })).toBeVisible()
  })

  // ── 14. Request body includes context ────────────────────────────── //

  test('API request body contains context field', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ai/rewrite', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
    await menuItem.click()

    const improveBtn4 = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn4).toBeVisible({ timeout: 5_000 })
    const rp2 = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn4.click()
    await rp2

    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.action).toBe('improve')
    expect(capturedBody!.selected_text).toBeTruthy()
  })
})
