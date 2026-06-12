import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Fixtures                                                           //
// ------------------------------------------------------------------ //

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
const TARGET_SELECTION_TEXT = 'Responsible for building payment integration'

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
  await page.addInitScript(() => {
    window.localStorage.setItem('latexy_onboarding_completed', 'true')
  })

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
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText(/\d+ chars/).first()).toBeVisible({ timeout: 15_000 })
  await waitForMonacoEditor(page)
  await page.waitForTimeout(800)
}

async function waitForMonacoEditor(page: import('@playwright/test').Page) {
  await page.waitForFunction(
    () => {
      const editor = (window as Window & {
        __latexyMonacoEditor?: { getModel?: () => unknown }
      }).__latexyMonacoEditor
      return typeof editor?.getModel === 'function' && !!editor.getModel()
    },
    null,
    { timeout: 15_000 }
  )
}

async function selectWritingSample(page: import('@playwright/test').Page) {
  await page.waitForFunction(
    (targetText) => {
      const editor = (window as Window & {
        __latexyMonacoEditor?: {
          getModel: () => { getValue: () => string } | null
        }
      }).__latexyMonacoEditor
      const model = editor?.getModel()
      return !!model && model.getValue().includes(targetText)
    },
    TARGET_SELECTION_TEXT,
    { timeout: 10_000 }
  )

  const selection = await page.evaluate((targetText) => {
    const editor = (window as Window & {
      __latexyMonacoEditor?: {
        focus: () => void
        getModel: () => {
          getValue: () => string
          getLineCount: () => number
          getLineContent: (line: number) => string
        } | null
        revealLineInCenter: (line: number) => void
        setSelection: (selection: {
          startLineNumber: number
          startColumn: number
          endLineNumber: number
          endColumn: number
        }) => void
      }
    }).__latexyMonacoEditor

    const model = editor?.getModel()
    if (!editor || !model) return null

    for (let lineNumber = 1; lineNumber <= model.getLineCount(); lineNumber += 1) {
      const line = model.getLineContent(lineNumber)
      const startIndex = line.indexOf(targetText)
      if (startIndex === -1) continue

      const startColumn = startIndex + 1
      const endColumn = startColumn + targetText.length
      editor.focus()
      editor.revealLineInCenter(lineNumber)
      editor.setSelection({
        startLineNumber: lineNumber,
        startColumn,
        endLineNumber: lineNumber,
        endColumn,
      })
      return { lineNumber, startColumn, endColumn }
    }

    return null
  }, TARGET_SELECTION_TEXT)

  expect(selection).not.toBeNull()

  await page.waitForFunction(
    () => {
      const editor = (window as Window & {
        __latexyMonacoEditor?: {
          getAction?: (id: string) => { isSupported?: () => boolean } | null
          getSelection?: () => {
            startLineNumber: number
            startColumn: number
            endLineNumber: number
            endColumn: number
          } | null
        }
      }).__latexyMonacoEditor

      const selection = editor?.getSelection?.()
      const action = editor?.getAction?.('latexy.writingAssistant')
      const hasSelection = !!selection && (
        selection.startLineNumber !== selection.endLineNumber ||
        selection.startColumn !== selection.endColumn
      )
      const isSupported = typeof action?.isSupported === 'function' ? action.isSupported() : !!action
      return hasSelection && isSupported
    },
    null,
    { timeout: 5_000 }
  )
}

async function openWritingAssistantMenu(page: import('@playwright/test').Page) {
  await selectWritingSample(page)
  await page.evaluate(() => {
    const editor = (window as Window & {
      __latexyMonacoEditor?: { focus: () => void; trigger: (source: string, handlerId: string, payload: unknown) => void }
    }).__latexyMonacoEditor

    editor?.focus()
    editor?.trigger('playwright', 'editor.action.showContextMenu', null)
  })
  await expect(page.locator('.context-view.monaco-component')).toBeVisible({ timeout: 5_000 })
}

async function triggerWritingAssistant(page: import('@playwright/test').Page) {
  await selectWritingSample(page)

  const triggered = await page.evaluate(async () => {
    const editor = (window as Window & {
      __latexyMonacoEditor?: {
        focus: () => void
        getAction?: (id: string) => { isSupported?: () => boolean; run: () => Promise<void> } | null
      }
    }).__latexyMonacoEditor

    const action = editor?.getAction?.('latexy.writingAssistant')
    const isSupported = typeof action?.isSupported === 'function' ? action.isSupported() : !!action
    if (!editor || !action || !isSupported) return false

    editor.focus()
    await action.run()
    return true
  })

  expect(triggered).toBe(true)
  await expect(page.getByText('AI Writing Assistant').last()).toBeVisible({ timeout: 5_000 })
}

function getWritingAssistantPanel(page: import('@playwright/test').Page) {
  return page
    .locator('div.z-50')
    .filter({ has: page.getByRole('button', { name: 'Close writing assistant' }) })
    .first()
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

  // ── 2. Context menu entry ───────────────────────────────────────── //

  test('AI Writing Assistant appears in Monaco context menu when text is selected', async ({ page }) => {
    await gotoEditPage(page)
    await openWritingAssistantMenu(page)

    const menuItem = page.locator('.context-view.monaco-component').getByText('AI Writing Assistant')
    await expect(menuItem).toBeVisible({ timeout: 5_000 })
  })

  // ── 3. Widget opens with action picker ──────────────────────────── //

  test('widget opens with all action buttons when the editor action is triggered', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    await expect(page.getByRole('button', { name: /Improve/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Shorten/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Quantify/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Power Verbs/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Expand/i })).toBeVisible()
  })

  // ── 4. Selected text preview ───────────────────────────────────── //

  test('widget shows selected text in preview', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const panel = getWritingAssistantPanel(page)
    await expect(page.getByText('Selected text')).toBeVisible({ timeout: 5_000 })
    await expect(panel.getByText(TARGET_SELECTION_TEXT, { exact: true })).toBeVisible()
  })

  // ── 5. API call made with correct fields ───────────────────────── //

  test('clicking an action sends correct request to /ai/rewrite', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ai/rewrite', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await responsePromise

    expect(capturedBody).not.toBeNull()
    expect(typeof capturedBody!.selected_text).toBe('string')
    expect((capturedBody!.selected_text as string).length).toBeGreaterThan(0)
    expect(capturedBody!.selected_text).toBe(TARGET_SELECTION_TEXT)
    expect(capturedBody!.action).toBe('improve')
  })

  // ── 6. Loading state ───────────────────────────────────────────── //

  test('loading spinner shows while API call is in progress', async ({ page }) => {
    await page.route((url) => url.pathname === '/ai/rewrite', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_500))
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    await page.getByRole('button', { name: /Improve/i }).click()

    await expect(page.getByText('Rewriting')).toBeVisible({ timeout: 3_000 })
    await expect(page.locator('.animate-spin').first()).toBeVisible({ timeout: 3_000 })
  })

  // ── 7. Result state — diff view ────────────────────────────────── //

  test('result state shows original and rewritten text in diff view', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await page.getByRole('button', { name: /Improve/i }).click()
    await responsePromise

    await expect(page.getByText('Original')).toBeVisible({ timeout: 5_000 })
    await expect(page.getByText('Rewritten')).toBeVisible()
    await expect(page.getByText('Spearheaded payment integration')).toBeVisible()
    await expect(page.getByRole('button', { name: /Accept/i })).toBeVisible()
  })

  // ── 8. Accept replaces editor content ──────────────────────────── //

  test('Accept button applies rewrite and closes the widget', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await responsePromise

    const acceptBtn = page.getByRole('button', { name: /Accept/i })
    await expect(acceptBtn).toBeVisible({ timeout: 5_000 })
    await acceptBtn.click()

    await expect(page.locator('[aria-label="Close writing assistant"]')).not.toBeVisible({ timeout: 5_000 })
  })

  // ── 9. Close button closes widget ──────────────────────────────── //

  test('X button closes the widget without making changes', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const closeBtn = page.getByRole('button', { name: 'Close writing assistant' })
    await expect(closeBtn).toBeVisible({ timeout: 5_000 })
    await closeBtn.click()

    await expect(closeBtn).not.toBeVisible({ timeout: 5_000 })
  })

  // ── 10. Escape key closes widget ───────────────────────────────── //

  test('Escape key closes the widget', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const closeBtn = page.getByRole('button', { name: 'Close writing assistant' })
    await expect(closeBtn).toBeVisible({ timeout: 5_000 })

    await page.getByText('Selected text').click()
    await page.keyboard.press('Escape')
    await expect(closeBtn).not.toBeVisible({ timeout: 5_000 })
  })

  // ── 11. API error is handled gracefully ────────────────────────── //

  test('API error shows error message and returns to picker', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route((url) => url.pathname === '/ai/rewrite', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"server error"}' })
    )

    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await page.getByRole('button', { name: /Improve/i }).click()
    await responsePromise
    await page.waitForTimeout(500)

    expect(errors.filter((e) => !e.includes('Warning:'))).toEqual([])
    await expect(page.locator('.z-50')).toBeVisible({ timeout: 3_000 })
  })

  // ── 12. Regenerate calls API again ─────────────────────────────── //

  test('Regenerate button triggers a second API call', async ({ page }) => {
    let callCount = 0
    await page.route((url) => url.pathname === '/ai/rewrite', (route) => {
      callCount++
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const firstResponse = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await firstResponse
    expect(callCount).toBe(1)

    const regenerateBtn = page.getByRole('button', { name: 'Try again' })
    await expect(regenerateBtn).toBeVisible({ timeout: 3_000 })
    const secondResponse = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await regenerateBtn.click()
    await secondResponse
    expect(callCount).toBe(2)
  })

  // ── 13. "Try a different action" resets to picker ─────────────── //

  test('"Try a different action" link returns to action picker', async ({ page }) => {
    await mockRewriteEndpoint(page)
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await responsePromise

    const backLink = page.getByText('Try a different action')
    await expect(backLink).toBeVisible({ timeout: 5_000 })
    await backLink.click()

    await expect(page.getByRole('button', { name: /Improve/i })).toBeVisible({ timeout: 3_000 })
    await expect(page.getByRole('button', { name: /Shorten/i })).toBeVisible()
  })

  // ── 14. Request body includes context ──────────────────────────── //

  test('API request body contains context field', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/ai/rewrite', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_REWRITE_RESPONSE) })
    })

    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const improveBtn = page.getByRole('button', { name: /Improve/i })
    await expect(improveBtn).toBeVisible({ timeout: 5_000 })
    const responsePromise = page.waitForResponse((r) => r.url().includes('/ai/rewrite'), { timeout: 10_000 })
    await improveBtn.click()
    await responsePromise

    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.action).toBe('improve')
    expect(capturedBody!.selected_text).toBe(TARGET_SELECTION_TEXT)
    expect(typeof capturedBody!.context).toBe('string')
    expect((capturedBody!.context as string).length).toBeGreaterThan(0)
  })
})
