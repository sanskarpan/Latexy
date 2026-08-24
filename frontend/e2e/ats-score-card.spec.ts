import { test, expect, type Page } from '@playwright/test'

// ------------------------------------------------------------------ //
//  #1367 — Multi-dimensional ATS score card with deep links          //
//  The ATS badge opens DeepAnalysisPanel, which now shows a          //
//  5-category breakdown (Content / Format / Optimization /           //
//  Best Practices / Application Ready) fed by the quick score +      //
//  Textkernel simulator, each finding deep-linking to its line.      //
// ------------------------------------------------------------------ //

const RESUME_ID = 'resume-scorecard-1'

// >200 chars (so useQuickATSScore runs) with a \section on line 5.
const LATEX = [
  '\\documentclass[11pt]{article}',                 // 1
  '\\begin{document}',                              // 2
  '\\begin{center}Jane Doe\\end{center}',           // 3
  '',                                               // 4
  '\\section*{Experience}',                         // 5
  'Senior Software Engineer at Acme Corporation, building resilient distributed backend systems.', // 6
  '\\section*{Education}',                          // 7
  'B.Sc. Computer Science, State University, 2015', // 8
  '\\end{document}',                                // 9
].join('\n')

const MOCK_RESUME = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'Score Card Resume',
  latex_content: LATEX,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

async function mockBackend(page: Page) {
  await page.route('**/api/auth/get-session', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) }))
  await page.route((u) => u.pathname === `/resumes/${RESUME_ID}`, (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESUME) }))
  await page.route((u) => u.pathname.includes('/checkpoints'), (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((u) => u.pathname.endsWith('/academic-cv-report'), (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }) }))
  await page.route((u) => u.pathname.startsWith('/analytics'), (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' }))
  await page.route((u) => u.pathname.startsWith('/format'), (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ supported: true, formats: ['pdf'] }) }))

  // The two signals that drive the card.
  await page.route((u) => u.pathname === '/ats/quick-score', (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ score: 62, grade: 'C', sections_found: ['experience', 'education'], missing_sections: ['skills'], keyword_match_percent: 20 }),
    }))
  await page.route((u) => u.pathname === '/ats/simulate', (r) =>
    r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ats_label: 'Taleo (Oracle)',
        plain_text_view: 'Jane Doe\nExperience',
        issues: [
          { type: 'multi_column', severity: 'high', description: 'Multi-column layout detected', line_range: 'line 5' },
          { type: 'contact_not_at_top', severity: 'medium', description: 'Contact details are not near the top', line_range: '' },
        ],
        score: 45, recommendations: [], cached: false,
      }),
    }))

  // No backend WS in the harness.
  await page.route('**/ws/**', (r) => r.abort())
}

async function openScorePanel(page: Page) {
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText(/\d+ chars/).first()).toBeVisible({ timeout: 15_000 })
  // The live ATS badge appears after the quick-score debounce (~10s), then opens the panel.
  const badge = page.getByRole('button', { name: /ATS 62/ })
  await expect(badge).toBeVisible({ timeout: 20_000 })
  await badge.click()
  await expect(page.getByText('Score breakdown')).toBeVisible({ timeout: 10_000 })
}

test.describe('ATS multi-dimensional score card (#1367)', () => {
  test.beforeEach(async ({ page }) => {
    await mockBackend(page)
  })

  test('opening the ATS badge shows the five named categories', async ({ page }) => {
    await openScorePanel(page)
    for (const label of ['Content', 'Format', 'Optimization', 'Best Practices', 'Application Ready']) {
      await expect(page.getByText(label, { exact: true })).toBeVisible()
    }
  })

  test('findings are mapped into the right categories from both signals', async ({ page }) => {
    await openScorePanel(page)
    // Content: the missing-section quick-score finding.
    await expect(page.getByText('Missing Skills section').first()).toBeVisible()
    // Format: the simulator structural issue, with a line to jump to.
    await expect(page.getByText('Multi-column layout detected')).toBeVisible()
    // Optimization: low keyword match.
    await expect(page.getByText(/Low keyword match/)).toBeVisible()
    // Best Practices: the Textkernel contact check.
    await expect(page.getByText('Contact details are not near the top')).toBeVisible()
  })

  test('clicking a line-anchored finding deep-links and closes the panel', async ({ page }) => {
    await openScorePanel(page)
    const finding = page.getByRole('button', { name: /Multi-column layout detected/ })
    await expect(finding).toBeVisible()
    await expect(finding).toContainText('Line 5')
    await finding.click()
    // The panel steps out of the way so the highlighted line is visible.
    await expect(page.getByText('Score breakdown')).not.toBeVisible()
  })
})
