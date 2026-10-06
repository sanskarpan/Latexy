import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = 'macro-browser-resume'
const RECORDED_ID = '11111111-1111-4111-8111-111111111111'
const SCRIPT_ID = '22222222-2222-4222-8222-222222222222'
const LATEX = 'old'

async function mockEditor(page: Page) {
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session: { token: 'macro-token' }, user: { id: 'macro-user', email: 'macro@example.com', name: 'Macro User' } }),
  }))
  await page.route(url => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: RESUME_ID, user_id: 'macro-user', title: 'Macro browser', latex_content: LATEX, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }),
  }))
  await page.route(url => url.pathname.includes('/checkpoints'), route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route(url => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }) }))
  await page.route(url => url.pathname.startsWith('/analytics') || url.pathname.startsWith('/format') || url.pathname.startsWith('/ats') || url.pathname === '/me', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', route => route.abort())
}

test('macro shortcuts replay recorded and script macros against the live Monaco editor', async ({ page }) => {
  await mockEditor(page)
  await page.route(url => url.pathname === '/macros' && url.search === '', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([
      { id: RECORDED_ID, name: 'Recorded prefix', description: null, shortcut: 'ctrl+shift+1', actions: [{ type: 'insert', text: 'RECORDED ' }], script: null, script_version: 1, script_hash: null, created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z' },
      { id: SCRIPT_ID, name: 'Script replacement', description: null, shortcut: 'ctrl+shift+2', actions: [], script: 'replace "old" with "new"', script_version: 4, script_hash: 'a'.repeat(64), created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' },
    ]),
  }))
  await page.route(url => url.pathname === `/macros/${SCRIPT_ID}/execute`, async route => {
    const payload = await route.request().postDataJSON() as { document: string; expected_script_version: number }
    expect(payload.expected_script_version).toBe(4)
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ document: payload.document.split('old').join('new'), script_version: 4, script_hash: 'a'.repeat(64), operation_count: 1 }),
    })
  })

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor ready')).toBeVisible({ timeout: 30_000 })
  // The job-status label is not Monaco's mount signal. Wait for the actual
  // editor and loaded document before sending shortcuts (also after reload).
  await expect.poll(() => page.evaluate(() =>
    (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } })
      .__latexyMonacoEditor?.getValue(),
  ), { timeout: 30_000 }).toBe(LATEX)
  await page.getByRole('button', { name: /^More$/i }).click()
  await page.getByRole('menuitem', { name: 'Macros' }).click()
  await expect(page.getByText('Keyboard Macros')).toBeVisible()

  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: '@', code: 'Digit2', ctrlKey: true, shiftKey: true, bubbles: true })))
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toBe('new')

  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor ready')).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => page.evaluate(() =>
    (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } })
      .__latexyMonacoEditor?.getValue(),
  ), { timeout: 30_000 }).toBe(LATEX)
  await page.getByRole('button', { name: /^More$/i }).click()
  await page.getByRole('menuitem', { name: 'Macros' }).click()
  await expect(page.getByText('Keyboard Macros')).toBeVisible()
  await page.evaluate(() => {
    const editor = (window as typeof window & {
      __latexyMonacoEditor?: {
        focus(): void
        setPosition(position: { lineNumber: number; column: number }): void
      }
    }).__latexyMonacoEditor
    if (!editor) throw new Error('Monaco test editor is unavailable')
    editor.setPosition({ lineNumber: 1, column: 1 })
    editor.focus()
  })
  await page.evaluate(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: '!', code: 'Digit1', ctrlKey: true, shiftKey: true, bubbles: true })))
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toBe('RECORDED old')
})
