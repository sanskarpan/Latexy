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

const MOCK_VARIANT_SET = {
  id: 'bullet-variant-set-1',
  resume_id: RESUME_ID,
  source_text: TARGET_SELECTION_TEXT,
  target_label: 'Acme — Staff Engineer',
  options: [
    'Directed a payment integration from design through launch',
    'Orchestrated delivery of a production payment integration',
    'Led end-to-end implementation of a payment integration',
  ],
  created_at: '2026-09-08T00:00:00Z',
  updated_at: '2026-09-08T00:00:00Z',
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
    // Monaco is a large dynamic chunk; a cold dev server can take longer than
    // 15 seconds to compile and mount it when the suite runs in parallel.
    { timeout: 30_000 }
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

async function openLatexGenerator(page: import('@playwright/test').Page) {
  await gotoEditPage(page)
  await page.getByRole('button', { name: /^More$/i }).click()
  await page.getByRole('menuitem', { name: 'Generate LaTeX', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Generate LaTeX' })).toBeVisible()
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
    await expect(page.getByRole('button', { name: /Paraphrase/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Concise/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Scientific/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Split sentences/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Join sentences/i })).toBeVisible()
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

  test('named rewrite modes send their distinct operation', async ({ page }) => {
    const capturedActions: string[] = []
    await page.route((url) => url.pathname === '/ai/rewrite', async route => {
      capturedActions.push(route.request().postDataJSON().action)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_REWRITE_RESPONSE),
      })
    })
    await gotoEditPage(page)
    await triggerWritingAssistant(page)

    const modes = [
      ['Paraphrase', 'paraphrase'],
      ['Concise', 'concise'],
      ['Scientific', 'scientific'],
      ['Split sentences', 'split'],
      ['Join sentences', 'join'],
    ] as const
    for (const [label, action] of modes) {
      const response = page.waitForResponse(result => new URL(result.url()).pathname === '/ai/rewrite')
      await page.getByRole('button', { name: new RegExp(`^${label}`) }).click()
      await response
      expect(capturedActions[capturedActions.length - 1]).toBe(action)
      await page.getByRole('button', { name: 'Try a different action' }).click()
    }
  })

  test('synonym suggestions are contextual and replace only after selection', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    const replacement = 'Accountable for constructing payment integration'
    await page.route((url) => url.pathname === '/ai/synonyms', async route => {
      capturedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          synonyms: [replacement, 'Led payment integration development'],
          cached: false,
        }),
      })
    })
    await gotoEditPage(page)
    await triggerWritingAssistant(page)
    await page.getByRole('button', { name: /^Synonyms/ }).click()

    await expect(page.getByText('Choose one replacement')).toBeVisible()
    expect(capturedBody).toMatchObject({ text: TARGET_SELECTION_TEXT, count: 5 })
    expect(typeof capturedBody!.context).toBe('string')
    await page.getByRole('button', { name: new RegExp(`^${replacement}`) }).click()

    await expect(page.getByRole('button', { name: 'Close writing assistant' })).not.toBeVisible()
    await expect.poll(() => page.evaluate(() => {
      const editor = (window as Window & {
        __latexyMonacoEditor?: { getModel: () => { getValue: () => string } | null }
      }).__latexyMonacoEditor
      return editor?.getModel()?.getValue() ?? ''
    })).toContain(replacement)
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
    await expect(page.getByText('Choose an action')).toBeVisible({ timeout: 3_000 })
    await expect(page.getByRole('button', { name: /Improve/i })).toBeVisible()
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

  test('generates three persisted variants, shows their diffs, and applies one', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.pathname === '/ai/bullet-variants', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_VARIANT_SET),
      })
    })

    await gotoEditPage(page)
    await triggerWritingAssistant(page)
    await page.getByRole('button', { name: /Generate 3 variants/i }).click()
    await expect(page.getByText('Three reviewable variants')).toBeVisible()
    await page.getByPlaceholder('e.g. Acme — Staff Engineer').fill('Acme — Staff Engineer')

    const responsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/ai/bullet-variants'
    )
    await page.getByRole('button', { name: /Generate and save 3 variants/i }).click()
    await responsePromise

    expect(capturedBody).toMatchObject({
      resume_id: RESUME_ID,
      source_text: TARGET_SELECTION_TEXT,
      target_label: 'Acme — Staff Engineer',
    })
    await expect(page.getByText(MOCK_VARIANT_SET.options[0], { exact: true })).toBeVisible()
    await expect(page.getByText(MOCK_VARIANT_SET.options[1], { exact: true })).toBeVisible()
    await expect(page.getByText(MOCK_VARIANT_SET.options[2], { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Apply this variant' }).first().click()
    await expect(page.getByRole('button', { name: 'Close writing assistant' })).not.toBeVisible()
    await expect.poll(() => page.evaluate(() => {
      const editor = (window as Window & {
        __latexyMonacoEditor?: { getModel: () => { getValue: () => string } | null }
      }).__latexyMonacoEditor
      return editor?.getModel()?.getValue() ?? ''
    })).toContain(MOCK_VARIANT_SET.options[0])
  })

  test('loads saved bullet variants for the current resume', async ({ page }) => {
    await page.route((url) => url.pathname === '/ai/bullet-variants', (route) => {
      const url = new URL(route.request().url())
      expect(url.searchParams.get('resume_id')).toBe(RESUME_ID)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_VARIANT_SET]),
      })
    })

    await gotoEditPage(page)
    await triggerWritingAssistant(page)
    await page.getByRole('button', { name: 'Saved bullet library' }).click()

    await expect(page.getByText('Acme — Staff Engineer')).toBeVisible()
    await expect(page.getByText(MOCK_VARIANT_SET.options[0], { exact: false })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Apply to selection' }).first()).toBeVisible()
  })
})

test.describe('B18.1 — Natural language to LaTeX', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page)
  })

  test('previews a generated fragment and inserts it only after explicit approval', async ({ page }) => {
    const fragment = '\\section{Projects}\n\\begin{itemize}\n\\item Built a compiler\n\\end{itemize}'
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.pathname === '/ai/generate-latex', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ latex: fragment, cached: false }),
      })
    })

    await openLatexGenerator(page)
    const intent = page.getByRole('textbox', { name: 'What should be created?' })
    await intent.fill('Create a Projects section with one concise item')
    const response = page.waitForResponse((candidate) =>
      new URL(candidate.url()).pathname === '/ai/generate-latex'
    )
    await page.getByRole('button', { name: 'Generate fragment' }).click()
    await response

    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.intent).toBe('Create a Projects section with one concise item')
    expect(capturedBody!.document_context).toContain('Responsible for building payment integration')
    await expect(page.getByText(fragment, { exact: true })).toBeVisible()

    const beforeInsert = await page.evaluate(() => (
      window as Window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue() ?? '')
    expect(beforeInsert).not.toContain('\\section{Projects}')

    await page.evaluate(() => {
      const editor = (
        window as Window & {
          __latexyMonacoEditor?: { setPosition(position: { lineNumber: number; column: number }): void }
        }
      ).__latexyMonacoEditor
      editor?.setPosition({ lineNumber: 1, column: 1 })
    })
    await page.getByRole('button', { name: 'Insert at cursor' }).click()

    await expect.poll(() => page.evaluate(() => (
      window as Window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue() ?? '')).toMatch(/^\\section\{Projects\}/)
    await expect(page.getByRole('button', { name: 'Inserted at cursor' })).toBeDisabled()
  })

  test('keeps the document unchanged when generation fails', async ({ page }) => {
    await page.route((url) => url.pathname === '/ai/generate-latex', (route) =>
      route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'AI provider returned unsafe or malformed LaTeX' }),
      })
    )

    await openLatexGenerator(page)
    const original = await page.evaluate(() => (
      window as Window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue() ?? '')
    await page.getByRole('textbox', { name: 'What should be created?' }).fill('Create a Projects section')
    await page.getByRole('button', { name: 'Generate fragment' }).click()

    const generator = page.getByRole('region', { name: 'Generate LaTeX' })
    await expect(generator.getByRole('alert')).toContainText('unsafe or malformed LaTeX')
    await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
    const after = await page.evaluate(() => (
      window as Window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue() ?? '')
    expect(after).toBe(original)
  })
})

test.describe('B18.2 — Text or image to LaTeX table', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page)
  })

  test('converts pasted CSV to a reviewable table and inserts it at the cursor', async ({ page }) => {
    const table = [
      '\\begin{table}[htbp]',
      '\\centering',
      '\\begin{tabular}{lr}',
      '\\hline',
      '\\textbf{Name} & \\textbf{Score} \\\\',
      '\\hline',
      'Ada & 99 \\\\',
      '\\hline',
      '\\end{tabular}',
      '\\end{table}',
    ].join('\n')
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.pathname === '/ai/generate-table', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ latex: table, rows: 2, columns: 2, source: 'text' }),
      })
    })

    await openLatexGenerator(page)
    await page.getByRole('tab', { name: 'Table' }).click()
    await page.getByRole('textbox', { name: 'Paste CSV or TSV' }).fill('Name,Score\nAda,99')
    const response = page.waitForResponse((candidate) =>
      new URL(candidate.url()).pathname === '/ai/generate-table'
    )
    await page.getByRole('button', { name: 'Generate table' }).click()
    await response

    expect(capturedBody).toEqual({ table_text: 'Name,Score\nAda,99', first_row_header: true })
    await expect(page.getByText('2 rows × 2 columns')).toBeVisible()
    await expect(page.getByText(table, { exact: true })).toBeVisible()

    await page.evaluate(() => {
      const editor = (
        window as Window & {
          __latexyMonacoEditor?: { setPosition(position: { lineNumber: number; column: number }): void }
        }
      ).__latexyMonacoEditor
      editor?.setPosition({ lineNumber: 1, column: 1 })
    })
    await page.getByRole('button', { name: 'Insert at cursor' }).click()
    await expect.poll(() => page.evaluate(() => (
      window as Window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue() ?? '')).toMatch(/^\\begin\{table\}/)
  })

  test('uploads a table image as multipart and previews the recognized shape', async ({ page }) => {
    const table = [
      '\\begin{table}[htbp]',
      '\\centering',
      '\\begin{tabular}{ll}',
      '\\hline',
      'A & B \\\\',
      '\\hline',
      '\\end{tabular}',
      '\\end{table}',
    ].join('\n')
    let contentType = ''
    let postData = ''
    await page.route((url) => url.pathname === '/ai/generate-table-image', async (route) => {
      contentType = route.request().headers()['content-type'] ?? ''
      postData = route.request().postData() ?? ''
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ latex: table, rows: 1, columns: 2, source: 'image' }),
      })
    })

    await openLatexGenerator(page)
    await page.getByRole('tab', { name: 'Table' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'scores.png',
      mimeType: 'image/png',
      buffer: Buffer.from('89504e470d0a1a0a', 'hex'),
    })
    await expect(page.getByText('scores.png')).toBeVisible()
    const response = page.waitForResponse((candidate) =>
      new URL(candidate.url()).pathname === '/ai/generate-table-image'
    )
    await page.getByRole('button', { name: 'Generate table' }).click()
    await response

    expect(contentType).toContain('multipart/form-data; boundary=')
    expect(postData).toContain('name="first_row_header"')
    expect(postData).toContain('true')
    expect(postData).toContain('filename="scores.png"')
    await expect(page.getByText('1 rows × 2 columns')).toBeVisible()
  })
})

test.describe('B18.3 — Text or image to LaTeX math', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockCommonRoutes(page)
  })

  test('converts a math description, applies the requested wrapper, and inserts it', async ({ page }) => {
    const latex = '\\begin{equation}\nE = mc^2\n\\end{equation}'
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.pathname === '/ai/generate-math', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ latex, display_mode: 'equation', source: 'text', cached: false }),
      })
    })

    await openLatexGenerator(page)
    await page.getByRole('tab', { name: 'Math' }).click()
    await page.getByRole('textbox', { name: 'Describe or paste math' }).fill('energy equals mass times speed of light squared')
    await page.getByRole('radio', { name: 'equation' }).click()
    const response = page.waitForResponse((candidate) =>
      new URL(candidate.url()).pathname === '/ai/generate-math'
    )
    await page.getByRole('button', { name: 'Generate math' }).click()
    await response

    expect(capturedBody).toEqual({
      math_text: 'energy equals mass times speed of light squared',
      display_mode: 'equation',
    })
    await expect(page.getByText(latex, { exact: true })).toBeVisible()

    await page.evaluate(() => {
      const editor = (
        window as Window & {
          __latexyMonacoEditor?: { setPosition(position: { lineNumber: number; column: number }): void }
        }
      ).__latexyMonacoEditor
      editor?.setPosition({ lineNumber: 1, column: 1 })
    })
    await page.getByRole('button', { name: 'Insert at cursor' }).click()
    await expect.poll(() => page.evaluate(() => (
      window as Window & { __latexyMonacoEditor?: { getValue(): string } }
    ).__latexyMonacoEditor?.getValue() ?? '')).toMatch(/^\\begin\{equation\}/)
  })

  test('uploads a math image with its selected display mode', async ({ page }) => {
    let contentType = ''
    let postData = ''
    await page.route((url) => url.pathname === '/ai/generate-math-image', async (route) => {
      contentType = route.request().headers()['content-type'] ?? ''
      postData = route.request().postData() ?? ''
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          latex: '$x^2$',
          display_mode: 'inline',
          source: 'image',
          cached: false,
        }),
      })
    })

    await openLatexGenerator(page)
    await page.getByRole('tab', { name: 'Math' }).click()
    await page.locator('input[type="file"]').setInputFiles({
      name: 'formula.webp',
      mimeType: 'image/webp',
      buffer: Buffer.from('52494646', 'hex'),
    })
    await page.getByRole('radio', { name: 'inline' }).click()
    const response = page.waitForResponse((candidate) =>
      new URL(candidate.url()).pathname === '/ai/generate-math-image'
    )
    await page.getByRole('button', { name: 'Generate math' }).click()
    await response

    expect(contentType).toContain('multipart/form-data; boundary=')
    expect(postData).toContain('filename="formula.webp"')
    expect(postData).toContain('name="display_mode"')
    expect(postData).toContain('inline')
    await expect(page.getByText('$x^2$', { exact: true })).toBeVisible()
  })
})
