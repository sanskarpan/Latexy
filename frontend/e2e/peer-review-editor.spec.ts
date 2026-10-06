import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeef'
const SOURCE = `\\documentclass{article}\\begin{document}
Reviewable editor fixture with enough content to mount the authenticated Latexy editor and its review tab safely.
\\end{document}`

const COMMENT = {
  id: 'review-comment-1',
  reviewer_label: 'Reviewer ABC123',
  content: 'Please quantify this outcome.',
  line_number: null,
  section_tag: null,
  page_number: 1,
  x: 0.25,
  y: 0.3,
  resolved: false,
  created_at: '2026-09-14T00:00:00Z',
  updated_at: '2026-09-14T00:00:00Z',
}

async function mockEditor(page: Page, accessRole: 'owner' | 'viewer') {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session: { token: 'editor-review-token' }, user: { id: accessRole === 'owner' ? 'owner-1' : 'viewer-1', email: 'review@example.com', name: 'Review User' } }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: 'owner-1',
      access_role: accessRole,
      title: 'Review editor fixture',
      latex_content: SOURCE,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      document_type: 'resume',
      metadata: {},
    }),
  }))
  await page.route((url) => url.pathname.startsWith(`/resumes/${RESUME_ID}/review-comments`), async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (route.request().method() === 'GET' && pathname === `/resumes/${RESUME_ID}/review-comments`) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([COMMENT]) })
    }
    const body = route.request().postDataJSON() as { resolved: boolean }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...COMMENT, resolved: body.resolved }) })
  })
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname.startsWith('/format') || url.pathname.startsWith('/ats') || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname.includes('/academic-cv-report'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }) }))
  await page.route('**/ws/**', (route) => route.abort())
}

test.describe('authenticated peer review editor integration', () => {
  test('owner can open Review beside existing panels and resolve a comment', async ({ page }) => {
    await mockEditor(page, 'owner')
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })

    await page.getByRole('button', { name: 'More' }).click()
    await page.getByRole('menuitem', { name: 'Review', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Review comments' })).toBeVisible()
    await expect(page.getByTestId('review-comment').getByText(COMMENT.content, { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Mark resolved' })).toBeVisible()
    await page.getByRole('button', { name: 'Mark resolved' }).click()
    await expect(page.getByRole('button', { name: 'Mark unresolved' })).toBeVisible()
  })

  test('viewer can read review comments but cannot resolve them', async ({ page }) => {
    await mockEditor(page, 'viewer')
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'More' }).click()
    await page.getByRole('menuitem', { name: 'Review', exact: true }).click()
    await expect(page.getByTestId('review-comment').getByText(COMMENT.content, { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Mark resolved' })).not.toBeVisible()
  })
})
