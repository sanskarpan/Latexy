import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Fixtures                                                           //
// ------------------------------------------------------------------ //

const RESUME_ID = 'ffffffff-ffff-ffff-ffff-ffffffffffff'

/** Resume with several intentional lint violations:
 *  - {\bf ...}           → deprecated-bf
 *  - "quoted text"       → wrong-quotes
 *  - \usepackage{hyperref} before geometry → hyperref-order
 *  - \section{...} with no \label         → missing-label
 */
const DIRTY_LATEX = [
  '\\documentclass[11pt]{article}',
  '\\usepackage{hyperref}',
  '\\usepackage{geometry}',
  '\\begin{document}',
  '\\section{Introduction}',
  'Some text with {\\bf bold} style.',
  'He said "hello world".',
  '\\end{document}',
].join('\n')

/** Resume with clean LaTeX — no violations. */
const CLEAN_LATEX = [
  '\\documentclass[11pt]{article}',
  '\\usepackage{geometry}',
  '\\usepackage{hyperref}',
  '\\begin{document}',
  '\\section{Introduction}',
  '\\label{sec:intro}',
  'Some \\textbf{bold} and \\textit{italic} text.',
  '\\end{document}',
].join('\n')

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

function makeMockResume(latexContent: string) {
  return {
    id: RESUME_ID,
    user_id: 'user-1',
    title: 'Linter Test Resume',
    latex_content: latexContent,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-01T00:00:00Z',
  }
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

async function mockCommonRoutes(
  page: import('@playwright/test').Page,
  latexContent = DIRTY_LATEX
) {
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
  )
  await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
    })
  )
  await page.route((url) => url.pathname === '/jobs/submit', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: 'job-1', message: 'ok' }),
    })
  )
  await page.route((url) => url.pathname === '/trial/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ uses_remaining: 3, cooldown_seconds: 0, is_limited: false }),
    })
  )
  await page.route((url) => url.pathname === '/resumes/stats', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ total_resumes: 1, total_templates: 0, last_updated: null }),
    })
  )
  await page.route((url) => url.pathname.startsWith('/format'), (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ supported: true }),
    })
  )
  await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ score: 70, grade: 'C', sections_found: [], missing_sections: [], keyword_match_percent: null }),
    })
  )
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(makeMockResume(latexContent)),
    })
  )
  await page.route('**/ws/**', (route) => route.abort())
}

async function gotoEditPage(page: import('@playwright/test').Page) {
  await page.goto(`/workspace/${RESUME_ID}/edit`)
  await page.waitForLoadState('networkidle')
  await page.waitForSelector('.monaco-editor', { timeout: 15_000 })
  await page.waitForTimeout(800)
}

/** Click the Linter tab in the right sidebar. */
async function openLinterTab(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /Linter/i }).click()
  // Panel header should appear
  await expect(page.getByText('Real-time linting')).toBeVisible({ timeout: 5_000 })
}

/** Wait for the linter debounce (3 s) to fire and issues to appear in the panel. */
async function waitForLintIssues(page: import('@playwright/test').Page) {
  // Issues section appears once debounce fires — use a generous timeout
  await expect(
    page.getByText(/Warnings|deprecated-bf|wrong-quotes/i).first()
  ).toBeVisible({ timeout: 10_000 })
}

// ------------------------------------------------------------------ //
//  Test suite                                                         //
// ------------------------------------------------------------------ //

test.describe('Feature 29 — LaTeX Linter', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page)
  })

  // ── 1. Smoke ─────────────────────────────────────────────────────── //

  test('edit page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await gotoEditPage(page)
    expect(errors).toEqual([])
  })

  // ── 2. Tab visible ───────────────────────────────────────────────── //

  test('Linter tab appears in the right sidebar', async ({ page }) => {
    await gotoEditPage(page)
    await expect(page.getByRole('button', { name: /Linter/i })).toBeVisible()
  })

  // ── 3. Panel opens ───────────────────────────────────────────────── //

  test('clicking Linter tab opens the linter panel', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    // Toggle switch should be present
    await expect(page.getByRole('switch')).toBeVisible()
  })

  // ── 4. Issues detected ───────────────────────────────────────────── //

  test('detects deprecated \\bf and wrong-quotes in dirty LaTeX after debounce', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // deprecated-bf rule badge should be visible
    await expect(page.locator('text=deprecated-bf')).toBeVisible()
    // wrong-quotes rule badge should be visible
    await expect(page.locator('text=wrong-quotes')).toBeVisible()
  })

  // ── 5. Issue count badge on tab ──────────────────────────────────── //

  test('Linter tab shows issue count badge when issues exist', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // The count badge is a small element next to the Linter tab label
    // It contains a number > 0
    const badge = page.locator('button:has-text("Linter") span').filter({ hasText: /^\d+$/ })
    await expect(badge).toBeVisible({ timeout: 5_000 })
    const text = await badge.textContent()
    expect(Number(text)).toBeGreaterThan(0)
  })

  // ── 6. Clean LaTeX → no issues ──────────────────────────────────── //

  test('shows "No issues found" for clean LaTeX', async ({ page }) => {
    await mockCommonRoutes(page, CLEAN_LATEX)
    await gotoEditPage(page)
    await openLinterTab(page)

    // Wait for debounce to fire (no issues expected)
    await page.waitForTimeout(4_000)
    await expect(page.getByText('No issues found')).toBeVisible({ timeout: 3_000 })
  })

  // ── 7. Toggle disables linting ───────────────────────────────────── //

  test('toggling linting off clears issues and shows disabled state', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // Disable the toggle
    await page.getByRole('switch').click()

    // Panel should now show disabled state
    await expect(page.getByText('Linting is disabled')).toBeVisible({ timeout: 3_000 })
    // Count badge on tab should disappear (no issues when disabled)
    await expect(
      page.locator('button:has-text("Linter") span').filter({ hasText: /^\d+$/ })
    ).not.toBeVisible({ timeout: 3_000 })
  })

  // ── 8. Toggle re-enables linting ────────────────────────────────── //

  test('toggling off then on re-runs the linter', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // Disable
    await page.getByRole('switch').click()
    await expect(page.getByText('Linting is disabled')).toBeVisible({ timeout: 3_000 })

    // Re-enable
    await page.getByRole('switch').click()

    // Issues should come back after debounce
    await waitForLintIssues(page)
    await expect(page.locator('text=deprecated-bf')).toBeVisible()
  })

  // ── 9. Line number link in issue ─────────────────────────────────── //

  test('line number link is clickable and present for each issue', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // At least one "line N" link should be present
    const lineLink = page.getByText(/^line \d+$/).first()
    await expect(lineLink).toBeVisible({ timeout: 3_000 })
    // Click should not throw / crash (just navigates editor)
    await lineLink.click()
    // No page error
  })

  // ── 10. Fix button present for fixable issues ─────────────────────── //

  test('Fix button is visible for fixable issues', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // deprecated-bf is fixable, so "Fix" button should appear
    const fixBtn = page.getByRole('button', { name: 'Fix' }).first()
    await expect(fixBtn).toBeVisible({ timeout: 3_000 })
  })

  // ── 11. Single Fix updates editor content ────────────────────────── //

  test('clicking Fix on deprecated-bf removes \\bf from editor', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // There should be a Fix button for deprecated-bf
    const fixBtn = page.getByRole('button', { name: 'Fix' }).first()
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()

    // After fix the editor should no longer contain {\\bf bold}
    // Wait a moment for setValue to propagate
    await page.waitForTimeout(500)
    const editorContent = await page.evaluate(() => {
      const model = (window as any).monaco?.editor?.getModels?.()[0]
      return model?.getValue() ?? ''
    })
    // The raw \bf pattern should no longer be in the content
    expect(editorContent).not.toContain('{\\bf ')
  })

  // ── 12. Auto-Fix All applies all fixable rules ────────────────────── //

  test('Auto-Fix All button removes all fixable violations', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // Auto-Fix All button should be visible since there are fixable issues
    const autoFixBtn = page.getByRole('button', { name: /Auto-Fix All/i })
    await expect(autoFixBtn).toBeVisible({ timeout: 3_000 })
    await autoFixBtn.click()

    // After Auto-Fix All the editor should not contain straight double quotes or \bf
    await page.waitForTimeout(500)
    const editorContent = await page.evaluate(() => {
      const model = (window as any).monaco?.editor?.getModels?.()[0]
      return model?.getValue() ?? ''
    })
    expect(editorContent).not.toContain('"hello world"')
    expect(editorContent).not.toContain('{\\bf ')
  })

  // ── 13. Monaco markers registered ────────────────────────────────── //

  test('Monaco markers are registered with latex-lint owner after debounce', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // Give markers a moment to register
    await page.waitForTimeout(500)

    const markerCount = await page.evaluate(() => {
      const monaco = (window as any).monaco
      if (!monaco) return -1
      const models = monaco.editor.getModels()
      if (!models.length) return -1
      const markers = monaco.editor.getModelMarkers({ owner: 'latex-lint', resource: models[0].uri })
      return markers.length
    })

    expect(markerCount).toBeGreaterThan(0)
  })

  // ── 14. Warnings group heading ────────────────────────────────────── //

  test('issues are grouped under Warnings heading', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // The dirty LaTeX has deprecated-bf which is severity:warning
    await expect(page.getByText(/Warnings \(\d+\)/i)).toBeVisible({ timeout: 3_000 })
  })

  // ── 15. Footer count ─────────────────────────────────────────────── //

  test('footer shows total issue count', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // Footer text like "4 issues · 2 warnings · 2 info"
    await expect(page.getByText(/\d+ issue/i)).toBeVisible({ timeout: 3_000 })
  })
})
