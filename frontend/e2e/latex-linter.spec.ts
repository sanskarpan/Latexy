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
  '\\input{glyphtounicode}',
  '\\pdfgentounicode=1',
  '\\usepackage{geometry}',
  '\\usepackage{hyperref}',
  '\\begin{document}',
  '\\section{Introduction}',
  '\\label{sec:intro}',
  'Some \\textbf{bold} and \\textit{italic} text.',
  '\\end{document}',
].join('\n')

/** Resume with one duplicate label and references that should not be flagged. */
const DUPLICATE_LABEL_LATEX = [
  '\\documentclass[11pt]{article}',
  '\\input{glyphtounicode}',
  '\\pdfgentounicode=1',
  '\\begin{document}',
  '\\section{Introduction}',
  '\\label{sec:intro}',
  '\\ref{sec:intro}',
  '\\label { sec:intro }',
  '\\begin{verbatim}',
  '\\label{sec:intro}',
  '\\end{verbatim}',
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
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/interview-prep`, (route) =>
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
  await Promise.all([
    page.waitForResponse((response) => {
      if (response.request().method() !== 'GET' || response.status() !== 200) {
        return false
      }

      const url = new URL(response.url())
      return url.pathname === `/resumes/${RESUME_ID}`
    }),
    page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' }),
  ])
  // The editor includes Monaco plus optional Vim/Emacs/KaTeX chunks. A cold
  // Turbopack browser compilation can outlive the server-side route warmup,
  // especially when two workers arrive together, so readiness must cover that
  // one-time client bundle without treating the loading shell as a failure.
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/\d+ chars/).first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: /^More$/i })).toBeVisible({ timeout: 30_000 })
  // The surrounding editor chrome renders before Monaco's async chunk has
  // mounted. Waiting for the real editor instance prevents later interactions
  // from racing that final hydration step on a cold/two-worker dev server.
  await page.waitForFunction(
    () => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor),
    undefined,
    { timeout: 30_000 }
  )
}

/** Click the Linter tab in the right sidebar. */
async function openLinterTab(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: /^More$/i }).click()
  await page.getByRole('menuitem', { name: /^Linter/i }).click()
  // The panel is open once the issue/ATS sub-tabs and linting switch are rendered.
  await expect(page.getByRole('button', { name: /^Issues/i })).toBeVisible({ timeout: 5_000 })
  await expect(page.getByRole('button', { name: /^ATS Text/i })).toBeVisible({ timeout: 5_000 })
  await expect(page.getByRole('switch')).toBeVisible({ timeout: 5_000 })
}

/** Wait for the linter debounce (3 s) to fire and issues to appear in the panel. */
async function waitForLintIssues(page: import('@playwright/test').Page) {
  // Issues section appears once debounce fires — use a generous timeout
  await expect(
    page.getByText(/Warnings|deprecated-bf|wrong-quotes/i).first()
  ).toBeVisible({ timeout: 10_000 })
}

function getIssueMeta(page: import('@playwright/test').Page, ruleId: string) {
  return page.getByText(ruleId).locator('xpath=..')
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
    await page.getByRole('button', { name: /^More$/i }).click()
    await expect(page.getByRole('menuitem', { name: /^Linter/i })).toBeVisible()
  })

  // ── 3. Panel opens ───────────────────────────────────────────────── //

  test('clicking Linter tab opens the linter panel', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    // Toggle switch should be present
    await expect(page.getByRole('switch')).toBeVisible()
  })

  test('ATS Text shows the compiled PDF extraction through the REST fallback', async ({ page }) => {
    const extractedText = [
      'Jordan Lee',
      'jordan@example.com',
      'EXPERIENCE',
      'Senior Engineer at Acme',
      'EDUCATION',
      'BSc Computer Science',
      'SKILLS',
      'TypeScript Python PostgreSQL',
    ].join('\n')

    // The suite deliberately aborts WebSockets. A completed state therefore
    // exercises the production REST reconciliation path rather than a mocked
    // job.pdf_extracted frame.
    await page.route((url) => url.pathname === '/jobs/job-1/state', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000 }),
      })
    )
    await page.route((url) => url.pathname === '/jobs/job-1/result', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'job-1',
          result: {
            success: true,
            job_id: 'job-1',
            pdf_job_id: 'job-1',
            page_count: 2,
            extracted_text: extractedText,
          },
        }),
      })
    )

    await gotoEditPage(page)
    await openLinterTab(page)
    await page.getByRole('button', { name: /^ATS Text/i }).click()

    await expect(page.getByText('Plain text recovered by Latexy from your compiled PDF. Employer parsers may differ.')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Senior Engineer at Acme')).toBeVisible()
    await expect(page.getByText('2 pages.', { exact: true })).toBeVisible()
    await expect(page.getByText('18 rendered words', { exact: true })).toBeVisible()
  })

  test('Interview Prep explains asynchronous AI screening scope and privacy', async ({ page }) => {
    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: /^Interview Prep$/i }).click()

    await expect(page.getByText('AI Screening Prep')).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText(/spoken audio\/video-style practice/i)).toBeVisible()
    await expect(page.getByText(/does not capture audio or video/i)).toBeVisible()
    await expect(page.getByText(/does not.*simulate a specific employer/i)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Generate Screening Practice' })).toBeVisible()
    await expect(page.getByRole('link', { name: /how LinkedIn describes its AI interviews/i })).toHaveAttribute(
      'href',
      'https://www.linkedin.com/help/linkedin/answer/a10376002',
    )
  })

  test('Interview Prep renders grounded answer guidance and spoken timing', async ({ page }) => {
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/interview-prep`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{
          id: '11111111-1111-1111-1111-111111111111',
          user_id: 'user-1',
          resume_id: RESUME_ID,
          job_description: 'Lead reliable platform delivery.',
          company_name: 'Acme',
          role_title: 'Senior Engineer',
          questions: [{
            category: 'behavioral',
            question: 'Tell me about a time you improved service reliability.',
            what_interviewer_assesses: 'Evidence, ownership, and a measurable outcome.',
            star_hint: 'Situation: set context | Task: define ownership | Action: explain steps | Result: quantify impact',
            ideal_response_outline: [
              'Choose a reliability example supported by the resume.',
              'Explain the action and quantify the observed result.',
            ],
            spoken_answer_tip: 'Lead with the result, then explain the evidence.',
            recommended_seconds: 90,
          }],
          generation_job_id: 'job-old',
          created_at: '2026-09-08T00:00:00Z',
          updated_at: '2026-09-08T00:00:00Z',
        }]),
      })
    )

    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: /^Interview Prep$/i }).click()

    await expect(page.getByText('Tell me about a time you improved service reliability.')).toBeVisible()
    await expect(page.getByText('Aim for 90s')).toBeVisible()
    await expect(page.getByText('Strong-answer outline')).toBeVisible()
    await expect(page.getByText('Explain the action and quantify the observed result.')).toBeVisible()
    await expect(page.getByText(/does not record, transcribe, or rate your audio\/video/i)).toBeVisible()
  })

  test('Interview Coach mode gives feedback after each text answer', async ({ page }) => {
    const questions = [{
      category: 'behavioral',
      question: 'Tell me about a time you improved reliability.',
      what_interviewer_assesses: 'Evidence and ownership',
      ideal_response_outline: ['Context', 'Action', 'Result'],
      recommended_seconds: 90,
    }]
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/interview-prep`, route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{
          id: '22222222-2222-2222-2222-222222222222',
          resume_id: RESUME_ID,
          user_id: 'user-1',
          questions,
          created_at: '2026-09-08T00:00:00Z',
          updated_at: '2026-09-08T00:00:00Z',
        }]),
      }),
    )
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.pathname.endsWith('/simulate'), async route => {
      capturedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          mode: 'coach',
          feedback: [{
            question_index: 0,
            score: 84,
            strengths: ['Uses a concrete example'],
            improvements: ['Quantify the result'],
            suggested_outline: ['Context', 'Action', 'Measured result'],
          }],
          average_score: 84,
          overall_feedback: 'Grounded answer with room for specificity.',
        }),
      })
    })

    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: /^Interview Prep$/i }).click()
    await expect(page.getByText('Text interview simulation')).toBeVisible()
    await expect(page.getByText(/not saved; no microphone, camera, or hiring prediction/i)).toBeVisible()
    await page.getByRole('button', { name: /Start Coach session/ }).click()
    await page.getByRole('textbox', { name: 'Answer to question 1' }).fill(
      'I led a retry redesign that reduced failed jobs by thirty percent.',
    )
    await page.getByRole('button', { name: 'Finish session' }).click()

    await expect(page.getByText('Answer feedback')).toBeVisible()
    await expect(page.getByText('84/100')).toBeVisible()
    expect(capturedBody).toMatchObject({ mode: 'coach' })
    await page.getByRole('button', { name: 'View session summary' }).click()
    await expect(page.getByText('Practice score 84/100')).toBeVisible()
  })

  test('Interview Mock mode withholds feedback until the full text session ends', async ({ page }) => {
    const questions = [
      { category: 'behavioral', question: 'Describe a reliability improvement.', what_interviewer_assesses: 'Impact' },
      { category: 'technical', question: 'Design a resilient job queue.', what_interviewer_assesses: 'Tradeoffs' },
    ]
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/interview-prep`, route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{
          id: '33333333-3333-3333-3333-333333333333',
          resume_id: RESUME_ID,
          user_id: 'user-1',
          questions,
          created_at: '2026-09-08T00:00:00Z',
          updated_at: '2026-09-08T00:00:00Z',
        }]),
      }),
    )
    let requestCount = 0
    let submittedAnswers: unknown[] = []
    await page.route((url) => url.pathname.endsWith('/simulate'), async route => {
      requestCount += 1
      submittedAnswers = route.request().postDataJSON().answers
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          mode: 'mock',
          feedback: [0, 1].map(question_index => ({
            question_index,
            score: question_index ? 90 : 80,
            strengths: ['Clear structure'],
            improvements: ['Add one metric'],
            suggested_outline: ['Context', 'Action', 'Result'],
          })),
          average_score: 85,
          overall_feedback: 'Clear session; add more measurable evidence.',
        }),
      })
    })

    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: /^Interview Prep$/i }).click()
    await page.getByRole('button', { name: /Mock mode/ }).click()
    await page.getByRole('button', { name: /Start Mock session/ }).click()
    await page.getByRole('textbox', { name: 'Answer to question 1' }).fill('A sufficiently detailed first practice answer.')
    await page.getByRole('button', { name: 'Submit answer' }).click()
    expect(requestCount).toBe(0)
    await expect(page.getByText('Question 2 of 2')).toBeVisible()
    await page.getByRole('textbox', { name: 'Answer to question 2' }).fill('A sufficiently detailed second practice answer.')
    await page.getByRole('button', { name: 'Finish session' }).click()

    await expect(page.getByText('Practice score 85/100')).toBeVisible()
    expect(requestCount).toBe(1)
    expect(submittedAnswers).toHaveLength(2)
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

  test('persists duplicate-label diagnostic with precise line and Monaco marker', async ({ page }) => {
    await mockCommonRoutes(page, DUPLICATE_LABEL_LATEX)
    await gotoEditPage(page)
    await openLinterTab(page)

    const issue = page.getByText('duplicate-label')
    await expect(issue).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Duplicate \\label{sec:intro} definition')).toBeVisible()
    await expect(issue.locator('xpath=..').getByRole('button', { name: 'line 8' })).toBeVisible()

    await page.waitForFunction(() => {
      const testWindow = window as typeof window & {
        __latexyMonaco?: { editor?: { getModelMarkers?: (options: { owner: string }) => Array<{ message: string }> } }
      }
      const markers = testWindow.__latexyMonaco?.editor?.getModelMarkers?.({ owner: 'latex-lint' }) ?? []
      return markers.some((marker) => marker.message.includes('Duplicate \\label{sec:intro} definition'))
    })
  })

  // ── 5. Issue count badge on tab ──────────────────────────────────── //

  test('Linter tab shows issue count badge when issues exist', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    // The count badge is a small element next to the Linter tab label
    // It contains a number > 0
    await page.getByRole('button', { name: /^More$/i }).click()
    const linterItem = page.getByRole('menuitem', { name: /^Linter/i })
    await expect(linterItem).toBeVisible({ timeout: 5_000 })
    const text = await linterItem.textContent()
    expect(Number(text?.match(/\d+/)?.[0])).toBeGreaterThan(0)
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
    await page.getByRole('button', { name: /^More$/i }).click()
    await expect(page.getByRole('menuitem', { name: /^Linter\s*$/i })).toBeVisible({ timeout: 3_000 })
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

    // deprecated-bf is fixable, so its issue row should expose a Fix button.
    const fixBtn = getIssueMeta(page, 'deprecated-bf').getByRole('button', { name: 'Fix' })
    await expect(fixBtn).toBeVisible({ timeout: 3_000 })
  })

  // ── 11. Single Fix updates editor content ────────────────────────── //

  test('clicking Fix on deprecated-bf removes \\bf from editor', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    const fixBtn = getIssueMeta(page, 'deprecated-bf').getByRole('button', { name: 'Fix' })
    await expect(fixBtn).toBeVisible()
    await fixBtn.click()

    // A single-rule fix should remove the targeted lint issue without clearing the others.
    await page.waitForTimeout(3_500)
    await expect(page.getByText('deprecated-bf')).not.toBeVisible()
    await expect(page.getByText('wrong-quotes')).toBeVisible()
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

    // Auto-Fix All should clear all fixable issues from the linter output.
    await page.waitForTimeout(3_500)
    await expect(page.getByText('deprecated-bf')).not.toBeVisible()
    await expect(page.getByText('wrong-quotes')).not.toBeVisible()
  })

  // ── 13. Monaco markers registered ────────────────────────────────── //

  test('Auto-Fix All re-runs linting and leaves only non-fixable issues', async ({ page }) => {
    await gotoEditPage(page)
    await openLinterTab(page)
    await waitForLintIssues(page)

    await page.getByRole('button', { name: /Auto-Fix All/i }).click()
    await page.waitForTimeout(3_500)

    await expect(page.getByText('deprecated-bf')).not.toBeVisible()
    await expect(page.getByText('wrong-quotes')).not.toBeVisible()
    await expect(page.getByText('hyperref-order')).toBeVisible()
    await expect(page.getByText('missing-label')).toBeVisible()
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
    await expect(page.locator('p').filter({ hasText: /\d+ issue/i })).toBeVisible({ timeout: 3_000 })
  })
})

test.describe('Feature 1.11 — Symbol Palette', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
  })

  async function openSymbolPalette(page: import('@playwright/test').Page) {
    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: 'Symbols', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Search LaTeX symbols' })).toBeVisible()
  }

  test('search and category controls expose insertable commands and package metadata', async ({ page }) => {
    await openSymbolPalette(page)

    await page.getByRole('textbox', { name: 'Search LaTeX symbols' }).fill('real numbers')
    const realNumbers = page.getByRole('button', { name: /real numbers: \\mathbb\{R\}/ })
    await expect(realNumbers).toBeVisible()
    await expect(realNumbers).toHaveAttribute('title', /amssymb/)
    await expect(page.getByText('1 symbol', { exact: false })).toBeVisible()

    await page.getByRole('textbox', { name: 'Search LaTeX symbols' }).fill('')
    await page.getByRole('button', { name: 'Greek', exact: true }).click()
    await expect(page.getByRole('button', { name: /alpha: \\alpha/ })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Greek', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  test('clicking a symbol inserts its command at the Monaco cursor', async ({ page }) => {
    await openSymbolPalette(page)
    await page.waitForFunction(() => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor))
    await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { setPosition(position: { lineNumber: number; column: number }): void }
      }).__latexyMonacoEditor
      editor?.setPosition({ lineNumber: 1, column: 1 })
    })

    await page.getByRole('button', { name: /alpha: \\alpha/ }).click()

    const value = await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { getValue(): string }
      }).__latexyMonacoEditor
      return editor?.getValue() ?? ''
    })
    expect(value.startsWith('\\alpha\\documentclass')).toBe(true)
  })
})

test.describe('Feature 42 — Read-only reference library', () => {
  test('Monaco completes commands, document labels, and saved BibTeX citations', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...makeMockResume(CLEAN_LATEX),
          metadata: {
            bibtex: [
              '@article{doe2024, title={First}}',
              '@article{smith2025, title={Second}}',
            ].join('\n'),
          },
        }),
      }),
    )
    await gotoEditPage(page)
    await page.waitForFunction(() => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor))

    const suggest = async (value: string, expected: string) => {
      await page.evaluate((nextValue) => {
        const testWindow = window as typeof window & {
          __latexyMonacoEditor?: {
            focus(): void
            getModel(): {
              getLineCount(): number
              getLineMaxColumn(lineNumber: number): number
            } | null
            setPosition(position: { lineNumber: number; column: number }): void
            setValue(value: string): void
            trigger(source: string, handlerId: string, payload: unknown): void
          }
        }
        const editor = testWindow.__latexyMonacoEditor
        const model = editor?.getModel()
        if (!editor || !model) throw new Error('Monaco test hook is unavailable')
        editor.setValue(nextValue)
        const lineNumber = model.getLineCount()
        editor.setPosition({ lineNumber, column: model.getLineMaxColumn(lineNumber) })
        editor.focus()
        editor.trigger('e2e', 'editor.action.triggerSuggest', {})
      }, value)
      const widget = page.locator('.suggest-widget')
      await expect(widget).toBeVisible()
      await expect(widget).toContainText(expected)
      await page.keyboard.press('Escape')
    }

    await suggest('\\textb', '\\textbf')
    await suggest('\\label{sec:intro}\nSee \\autoref{sec:', 'sec:intro')
    await suggest('Prior \\cite{doe2024, sm', 'smith2025')

    // Monaco providers are global. They must survive this component unmount/remount.
    await page.evaluate(({ cleanLatex, resumeId }) => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { setValue(value: string): void }
      }).__latexyMonacoEditor
      editor?.setValue(cleanLatex)
      localStorage.setItem(`latexy_wysiwyg_warned_${resumeId}`, 'true')
    }, { cleanLatex: CLEAN_LATEX, resumeId: RESUME_ID })
    await page.getByRole('button', { name: 'Visual', exact: true }).click()
    await page.waitForFunction(
      () => !(window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor,
      undefined,
      { timeout: 5_000 },
    )
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await page.waitForFunction(() => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor))
    await suggest('\\textb', '\\textbf')
  })

  test('saved Zotero snapshot is refreshable and inserts only cite commands', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
    await page.route('**/zotero/status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ connected: true, username: 'researcher', user_id: '42' }),
      }),
    )
    await page.route('**/mendeley/status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ connected: false, name: null }),
      }),
    )
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...makeMockResume(CLEAN_LATEX),
          metadata: {
            bibtex: '@article{smith2020, title={Example}}',
            bibtex_source: {
              provider: 'zotero',
              scope: 'library',
              scope_id: null,
              filename: 'references.bib',
              read_only: true,
              synced_at: '2026-09-08T00:00:00Z',
            },
          },
        }),
      }),
    )

    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: 'References', exact: true }).click()

    await expect(page.getByText('Read-only references.bib (1)')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Download references.bib' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Insert All/ })).toHaveCount(0)

    await page.getByRole('button', { name: /Zotero/ }).click()
    await expect(page.getByText(/One-way, read-only snapshot/)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Refresh references.bib' })).toBeVisible()

    await page.waitForFunction(() => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor))
    await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { setPosition(position: { lineNumber: number; column: number }): void }
      }).__latexyMonacoEditor
      editor?.setPosition({ lineNumber: 1, column: 1 })
    })
    await page.getByRole('button', { name: '\\cite', exact: true }).click()
    const value = await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { getValue(): string }
      }).__latexyMonacoEditor
      return editor?.getValue() ?? ''
    })
    expect(value.startsWith('\\cite{smith2020}\\documentclass')).toBe(true)
  })

  test('citation checker audits saved BibTeX and explains metadata mismatches', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
    await page.route('**/zotero/status', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false, username: null, user_id: null }),
    }))
    await page.route('**/mendeley/status', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false, name: null }),
    }))
    const savedBibtex = '@article{smith2020, title={Wrong title}, doi={10.1000/example}}'
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...makeMockResume(CLEAN_LATEX),
        metadata: { bibtex: savedBibtex },
      }),
    }))
    await page.route((url) => url.pathname === '/references/verify', async route => {
      expect(route.request().postDataJSON()).toEqual({ bibtex: savedBibtex })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          results: [{
            cite_key: 'smith2020',
            status: 'mismatch',
            source: 'crossref',
            identifier: '10.1000/example',
            matched_title: 'Canonical title',
            matched_authors: 'Smith, Ada',
            matched_year: 2020,
            title_similarity: 0.2,
            issues: ['Title does not closely match the scholarly record'],
          }],
          total: 1,
          verified: 0,
          mismatched: 1,
          processing_time: 0.01,
        }),
      })
    })

    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: 'References', exact: true }).click()
    await page.getByRole('button', { name: 'Check BibTeX citations' }).click()
    await expect(page.getByText(/Cross-check up to 20 works/)).toBeVisible()
    await page.getByRole('button', { name: 'Use saved references.bib' }).click()
    await expect(page.getByRole('textbox', { name: 'BibTeX citations to check' })).toHaveValue(savedBibtex)
    await page.getByRole('button', { name: 'Check scholarly records' }).click()

    await expect(page.getByLabel('Citation check results')).toContainText('smith2020')
    await expect(page.getByLabel('Citation check results')).toContainText('Canonical title')
    await expect(page.getByLabel('Citation check results')).toContainText('Title does not closely match')
  })
})

test.describe('B19.2 — continuous background compile', () => {
  test('the persisted toggle compiles a short non-empty document after the debounce', async ({ page }) => {
    await mockAuth(page)
    const initialShortDocument = '\\documentclass{article}\n\\begin{document}\nOne\n\\end{document}'
    await mockCommonRoutes(page, initialShortDocument)
    const submittedLatex: string[] = []
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      const body = route.request().postDataJSON() as { latex_content?: string }
      submittedLatex.push(body.latex_content ?? '')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: `job-${submittedLatex.length}`, message: 'ok' }),
      })
    })
    await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'completed', stage: 'done', percent: 100, last_updated: Date.now() / 1000 }),
      }),
    )

    await gotoEditPage(page)
    expect(submittedLatex).toHaveLength(0)
    const toggle = page.getByRole('button', { name: 'Auto-compile on change' })
    await expect(toggle).toHaveAttribute('aria-pressed', 'false')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-pressed', 'true')

    const shortDocument = '\\documentclass{article}\n\\begin{document}\nTwo\n\\end{document}'
    await page.evaluate((value) => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { setValue(value: string): void }
      }).__latexyMonacoEditor
      if (!editor) throw new Error('Monaco test hook is unavailable')
      editor.setValue(value)
    }, shortDocument)

    await expect.poll(() => submittedLatex.length, { timeout: 6_000 }).toBe(1)
    expect(submittedLatex[submittedLatex.length - 1]).toBe(shortDocument)
  })
})

test.describe('B19.3 — document outline', () => {
  test('shows the parsed hierarchy, jumps to source, and remains available on mobile', async ({ page }) => {
    await mockAuth(page)
    const outlinedLatex = [
      '\\documentclass{article}',
      '\\begin{document}',
      '% \\section{Hidden}',
      '\\section[Short]{Introduction}',
      'Text',
      '\\subsection{Details}',
      '\\end{document}',
    ].join('\n')
    await mockCommonRoutes(page, outlinedLatex)
    await gotoEditPage(page)

    const toggle = page.getByRole('button', { name: 'Show document outline' })
    await expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await toggle.click()
    await expect(page.getByRole('navigation', { name: 'Document outline' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Introduction, line 4' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Details, line 6' })).toBeVisible()
    await expect(page.getByText('Hidden', { exact: true })).toHaveCount(0)

    await page.getByRole('button', { name: 'Details, line 6' }).click()
    await expect.poll(() => page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { getPosition(): { lineNumber: number } | null }
      }).__latexyMonacoEditor
      return editor?.getPosition()?.lineNumber ?? 0
    })).toBe(6)

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.getByRole('navigation', { name: 'Document outline' })).toBeVisible()
    await page.getByRole('button', { name: 'Hide document outline' }).click()
    await expect(page.getByRole('button', { name: 'Show document outline' })).toBeVisible()
  })
})

test.describe('B19.4 — LaTeX code folding', () => {
  test('Monaco exposes enabled fold/unfold actions for structured LaTeX', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, [
      '\\documentclass{article}',
      '\\begin{document}',
      '\\section{Fold me}',
      'First line',
      'Second line',
      '\\end{document}',
    ].join('\n'))
    await gotoEditPage(page)

    const result = await page.evaluate(async () => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: {
          getAction(id: string): { run(): Promise<void> } | null
          getRawOptions(): { folding?: boolean; foldingHighlight?: boolean; showFoldingControls?: string }
          setPosition(position: { lineNumber: number; column: number }): void
        }
      }).__latexyMonacoEditor
      if (!editor) throw new Error('Monaco test hook is unavailable')
      const fold = editor.getAction('editor.fold')
      const unfold = editor.getAction('editor.unfold')
      editor.setPosition({ lineNumber: 3, column: 1 })
      await fold?.run()
      await unfold?.run()
      return {
        options: editor.getRawOptions(),
        hasFoldAction: Boolean(fold),
        hasUnfoldAction: Boolean(unfold),
      }
    })

    expect(result).toMatchObject({
      options: { folding: true, foldingHighlight: true, showFoldingControls: 'mouseover' },
      hasFoldAction: true,
      hasUnfoldAction: true,
    })
  })
})

test.describe('B19.9 — multi-cursor editing', () => {
  test('keeps native add-cursor controls and selects the next matching token', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, [
      '\\documentclass{article}',
      '\\begin{document}',
      'repeat repeat',
      '\\end{document}',
    ].join('\n'))
    await gotoEditPage(page)

    const result = await page.evaluate(async () => {
      const testWindow = window as typeof window & {
        __latexyMonacoEditor?: {
          getAction(id: string): { run(): Promise<void> } | null
          getRawOptions(): { multiCursorModifier?: string; multiCursorPaste?: string }
          getSelections(): unknown[] | null
          setSelection(selection: unknown): void
        }
        __latexyMonaco?: { Selection: new (...values: number[]) => unknown }
      }
      const editor = testWindow.__latexyMonacoEditor
      const monaco = testWindow.__latexyMonaco
      if (!editor || !monaco) throw new Error('Monaco test hook is unavailable')
      editor.setSelection(new monaco.Selection(3, 1, 3, 7))
      const addNext = editor.getAction('editor.action.addSelectionToNextFindMatch')
      await addNext?.run()
      return {
        options: editor.getRawOptions(),
        hasAddNextAction: Boolean(addNext),
        selectionCount: editor.getSelections()?.length ?? 0,
      }
    })

    expect(result).toMatchObject({
      options: { multiCursorModifier: 'alt', multiCursorPaste: 'spread' },
      hasAddNextAction: true,
      selectionCount: 2,
    })
  })
})

test.describe('B19.10 — modal editor keybindings', () => {
  test('activates, persists, and cleanly switches Vim and Emacs adapters', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, [
      '\\documentclass{article}',
      '\\begin{document}',
      'repeat repeat',
      '\\end{document}',
    ].join('\n'))
    await gotoEditPage(page)

    const keybindings = page.getByRole('combobox', { name: 'Editor keybindings' })
    await expect(keybindings).toHaveValue('standard')
    await keybindings.selectOption('vim')
    await expect.poll(() => page.evaluate(() => (
      window as typeof window & { __latexyKeybindingMode?: string }
    ).__latexyKeybindingMode)).toBe('vim')
    await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_editor_keybindings'))).toBe('vim')

    await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: {
          focus(): void
          setPosition(position: { lineNumber: number; column: number }): void
        }
      }).__latexyMonacoEditor
      if (!editor) throw new Error('Monaco test hook is unavailable')
      editor.setPosition({ lineNumber: 3, column: 1 })
      editor.focus()
    })
    await page.keyboard.press('i')
    await page.keyboard.type('X')
    await page.keyboard.press('Escape')
    await expect.poll(() => page.evaluate(() => (
      window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue().split('\n')[2])).toBe('Xrepeat repeat')

    await keybindings.selectOption('emacs')
    await expect.poll(() => page.evaluate(() => (
      window as typeof window & { __latexyKeybindingMode?: string }
    ).__latexyKeybindingMode)).toBe('emacs')
    await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: {
          focus(): void
          setPosition(position: { lineNumber: number; column: number }): void
        }
      }).__latexyMonacoEditor
      if (!editor) throw new Error('Monaco test hook is unavailable')
      editor.setPosition({ lineNumber: 3, column: 5 })
      editor.focus()
    })
    await page.keyboard.press('Control+a')
    await page.keyboard.type('Y')
    await expect.poll(() => page.evaluate(() => (
      window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue().split('\n')[2])).toBe('YXrepeat repeat')

    await keybindings.selectOption('standard')
    await expect.poll(() => page.evaluate(() => (
      window as typeof window & { __latexyKeybindingMode?: string }
    ).__latexyKeybindingMode)).toBe('standard')
  })
})

test.describe('B19.11 — rich LaTeX hover previews', () => {
  test('renders math and exposes graphic and saved-citation context', async ({ page }) => {
    await mockAuth(page)
    const hoverLatex = [
      '\\documentclass{article}',
      '\\begin{document}',
      'Math $E=mc^2$.',
      '\\includegraphics[width=.5\\linewidth]{diagram.png}',
      'Research \\cite{smith2024}.',
      '\\end{document}',
    ].join('\n')
    await mockCommonRoutes(page, hoverLatex)
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...makeMockResume(hoverLatex),
        metadata: { bibtex: '@article{smith2024,title={Reliable Systems},author={Ada Smith},year={2024}}' },
      }),
    }))
    await gotoEditPage(page)

    const pointAt = async (lineNumber: number, column: number) => {
      const point = await page.evaluate(({ lineNumber, column }) => {
        const editor = (window as typeof window & {
          __latexyMonacoEditor?: {
            getDomNode(): HTMLElement | null
            getScrolledVisiblePosition(position: { lineNumber: number; column: number }): { left: number; top: number; height: number } | null
          }
        }).__latexyMonacoEditor
        if (!editor) throw new Error('Monaco test hook is unavailable')
        const node = editor.getDomNode()
        const visible = editor.getScrolledVisiblePosition({ lineNumber, column })
        if (!node || !visible) throw new Error('Hovered source position is not visible')
        const bounds = node.getBoundingClientRect()
        return { x: bounds.left + visible.left + 2, y: bounds.top + visible.top + visible.height / 2 }
      }, { lineNumber, column })
      await page.mouse.move(point.x, point.y)
    }

    const hoverAtAndExpect = async (lineNumber: number, column: number, label: string) => {
      const richHover = page.getByTestId('latex-rich-hover')
      await expect(async () => {
        // Auto-compile can resize the neighboring preview just after Monaco
        // mounts. Re-resolve the source coordinate for each attempt so this
        // still exercises Monaco's real mouse event rather than a test hook.
        await page.mouse.move(900, 40)
        await pointAt(lineNumber, column)
        await expect(richHover.getByText(label, { exact: true })).toBeVisible({ timeout: 1_500 })
      }).toPass({ timeout: 12_000 })
      return richHover
    }

    const showKeyboardHover = async (lineNumber: number, column: number) => page.evaluate(async ({ lineNumber, column }) => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: {
          focus(): void
          setPosition(position: { lineNumber: number; column: number }): void
          getAction(id: string): { run(): Promise<void> } | null
        }
      }).__latexyMonacoEditor
      if (!editor) throw new Error('Monaco test hook is unavailable')
      editor.setPosition({ lineNumber, column })
      editor.focus()
      await editor.getAction('editor.action.showHover')?.run()
    }, { lineNumber, column })

    let richHover = await hoverAtAndExpect(3, 8, 'Rendered math')
    await expect(richHover.locator('.katex')).toBeVisible()
    await page.mouse.move(900, 40)
    await expect(richHover).toBeHidden()

    richHover = await hoverAtAndExpect(4, 20, 'Graphic include')
    await expect(richHover.getByText('diagram.png', { exact: true })).toBeVisible()
    await page.mouse.move(900, 40)

    richHover = await hoverAtAndExpect(5, 18, 'Citation preview')
    await expect(richHover.getByText('Reliable Systems', { exact: true })).toBeVisible()
    await expect(richHover.getByText(/Ada Smith.*2024/)).toBeVisible()

    await showKeyboardHover(5, 18)
    await expect(page.locator('.monaco-hover').getByText('Citation preview', { exact: true })).toBeVisible()
  })
})

test.describe('B19.13 — presentation preview', () => {
  test('uses slide-aware preview controls and keyboard navigation for presentation documents', async ({ page }) => {
    await mockAuth(page)
    const presentationLatex = [
      '\\documentclass{beamer}',
      '\\begin{document}',
      '\\begin{frame}{One}First slide content with enough text to trigger the initial compile.\\end{frame}',
      '\\begin{frame}{Two}Second slide.\\end{frame}',
      '\\begin{frame}{Three}Third slide.\\end{frame}',
      '\\end{document}',
    ].join('\n')
    await mockCommonRoutes(page, presentationLatex)
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...makeMockResume(presentationLatex), document_type: 'presentation' }),
    }))
    await page.route((url) => url.pathname === '/jobs/job-1/state', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'completed', stage: 'done', percent: 100, last_updated: Date.now() / 1000 }),
    }))
    await page.route((url) => url.pathname === '/jobs/job-1/result', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: 'job-1', result: { success: true, pdf_job_id: 'job-1', page_count: 3 } }),
    }))
    await page.route((url) => url.pathname === '/download/job-1', (route) => route.fulfill({
      status: 200,
      contentType: 'application/pdf',
      body: '%PDF-1.4 mocked presentation',
    }))

    await gotoEditPage(page)
    const preview = page.getByRole('region', { name: 'Presentation preview' })
    await expect(preview).toBeVisible({ timeout: 10_000 })
    await expect(preview).toContainText('1/3slides')
    await page.getByRole('button', { name: 'Next slide' }).click()
    await expect(preview).toContainText('2/3slides')
    await preview.focus()
    await page.keyboard.press('End')
    await expect(preview).toContainText('3/3slides')
    await page.keyboard.press('Home')
    await expect(preview).toContainText('1/3slides')
    await expect(page.getByRole('button', { name: 'Previous slide' })).toBeDisabled()
  })
})

test.describe('B19.14 — regex-aware find and replace', () => {
  test('opens a structural regex preset and replaces every captured section title', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, [
      '\\documentclass{article}',
      '\\begin{document}',
      '\\section{First}',
      'Text',
      '\\section{Second}',
      '\\end{document}',
    ].join('\n'))
    await gotoEditPage(page)

    const presetToggle = page.getByRole('button', { name: 'LaTeX search presets' })
    await expect(presetToggle).toHaveAttribute('aria-expanded', 'false')
    await presetToggle.click()
    await page.getByRole('button', { name: /All section headers/ }).click()

    await expect.poll(() => page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { getContribution(id: string): any }
      }).__latexyMonacoEditor
      const state = editor?.getContribution('editor.contrib.findController')?.getState()
      return state ? { searchString: state.searchString, isRegex: state.isRegex, matchesCount: state.matchesCount } : null
    })).toEqual({ searchString: '\\\\section\\{([^}]+)\\}', isRegex: true, matchesCount: 2 })

    const replaced = await page.evaluate(() => {
      const editor = (window as typeof window & {
        __latexyMonacoEditor?: { getContribution(id: string): any; getValue(): string }
      }).__latexyMonacoEditor
      if (!editor) throw new Error('Monaco test hook is unavailable')
      const controller = editor.getContribution('editor.contrib.findController')
      controller.getState().change({ replaceString: '\\\\subsection{$1}' }, false)
      controller.replaceAll()
      return editor.getValue()
    })
    expect(replaced).toContain('\\subsection{First}')
    expect(replaced).toContain('\\subsection{Second}')
    expect(replaced).not.toContain('\\section{')
  })
})

test.describe('B19.15 — package documentation', () => {
  test('searches package docs and exposes usage and examples beside installation', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
    await gotoEditPage(page)

    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: 'Packages', exact: true }).click()
    await page.getByRole('textbox', { name: 'Search LaTeX packages' }).fill('geometry')
    await expect(page.getByText('Flexible page margin and layout control')).toBeVisible()
    await page.getByRole('button', { name: 'Expand geometry details' }).click()
    await expect(page.getByText('\\usepackage[margin=1in]{geometry}', { exact: true })).toBeVisible()
    await expect(page.getByText('\\geometry{left=1in, right=1in, top=1in, bottom=1in}', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove geometry from preamble' }).first()).toBeVisible()
  })
})

test.describe('B19.6/B19.7 — compile flow controls', () => {
  test('persists stop-on-error and image-draft choices as per-resume booleans', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
    const savedSettings: Array<Record<string, unknown>> = []
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/settings`, async (route) => {
      const settings = route.request().postDataJSON() as Record<string, unknown>
      savedSettings.push(settings)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...makeMockResume(CLEAN_LATEX), metadata: settings }),
      })
    })
    await gotoEditPage(page)

    await page.getByRole('button', { name: 'Compile settings' }).click()
    const dialog = page.getByRole('dialog', { name: 'Compile Settings' })
    const stopOnError = dialog.getByRole('checkbox', { name: /Stop on first error/ })
    const draftMode = dialog.getByRole('checkbox', { name: /Draft mode/ })
    await expect(stopOnError).toBeChecked()
    await expect(draftMode).not.toBeChecked()
    await stopOnError.uncheck()
    await draftMode.check()
    await dialog.getByRole('button', { name: 'Save Settings' }).click()

    await expect(dialog).toBeHidden()
    expect(savedSettings).toHaveLength(1)
    expect(savedSettings[0]).toMatchObject({ halt_on_error: false, draft_mode: true })
    expect((savedSettings[0].latexmk_flags as string[]) ?? []).not.toContain('--halt-on-error')
  })
})

test.describe('B51a — resume comment mentions', () => {
  test('renders resolved mentions and keeps picker failures visible', async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page, CLEAN_LATEX)
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/comments`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{
        id: 'comment-1', resume_id: RESUME_ID, author_id: 'user-1', author_name: 'Test User',
        content: 'Please review this with @Ada Lovelace', resolved: false,
        created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z',
        mentions: [{ user_id: 'user-2', display_name: 'Ada Lovelace', email: 'ada@example.com' }],
      }]) }),
    )
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/comments/participants`, (route) =>
      route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'unavailable' }) }),
    )
    await gotoEditPage(page)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: 'Comments', exact: true }).click()
    await expect(page.getByText('@Ada Lovelace', { exact: true })).toBeVisible()
    await expect(page.getByText('Mention picker unavailable.', { exact: false })).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Comment' })).toBeVisible()
  })
})
