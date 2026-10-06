import { expect, test } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174031'
const TARGET = 'Built reliable APIs for customers.'
const REPLACEMENT = 'Designed and delivered reliable APIs for enterprise customers.'
const LATEX = [
  '\\documentclass{article}',
  '\\begin{document}',
  '\\section{Experience}',
  TARGET,
  'Collaborated with product and design teams to ship customer-facing improvements.',
  '\\section{Education}',
  'B.S. Computer Science',
  '\\end{document}',
].join('\n')

test('document assistant proposes a reviewable edit and applies it only after approval', async ({ page }) => {
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'assistant-token' },
      user: { id: 'assistant-user', email: 'assistant@example.com', name: 'Assistant User' },
    }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: 'assistant-user',
      title: 'Assistant Resume',
      latex_content: LATEX,
      document_type: 'resume',
      metadata: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route((url) => url.pathname.includes('/checkpoints'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '[]',
  }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ score: 70, grade: 'C', sections_found: ['experience', 'education'], missing_sections: [] }),
  }))
  await page.route('**/ws/**', route => route.abort())

  let requestBody: Record<string, unknown> | null = null
  await page.route((url) => url.pathname === '/ai/document-assistant', route => {
    requestBody = route.request().postDataJSON()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        message: 'I proposed a more specific, evidence-preserving opening bullet.',
        proposed_edit: { target_text: TARGET, replacement_text: REPLACEMENT },
      }),
    })
  })

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: 'Ask AI' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Ask AI' }).click()
  await expect(page.getByRole('complementary', { name: 'Document assistant' })).toBeVisible()

  await page.getByLabel('Message the document assistant').fill('Make the opening bullet more specific without inventing facts.')
  await page.getByRole('button', { name: 'Send message' }).click()
  await expect(page.getByText(/evidence-preserving opening bullet/i)).toBeVisible()
  await expect(page.getByRole('region', { name: 'Proposed edit' })).toContainText(REPLACEMENT)

  expect(requestBody).toMatchObject({
    resume_id: RESUME_ID,
    latex_content: LATEX,
    message: 'Make the opening bullet more specific without inventing facts.',
  })
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue())).toContain(TARGET)

  await page.getByRole('button', { name: 'Apply edit' }).click()
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue())).toContain(REPLACEMENT)
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }
  ).__latexyMonacoEditor?.getValue())).not.toContain(TARGET)
})
