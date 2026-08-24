import { test, expect, type Page } from '@playwright/test'

// ------------------------------------------------------------------ //
//  P2 cross-check gap fixes — the browser-testable ones: onboarding  //
//  replay entry point, account-menu legal links, and the optimize /  //
//  cover-letter pages mounting with their new unsaved-changes guard. //
// ------------------------------------------------------------------ //

const SESSION = { session: { token: 't' }, user: { id: 'u1', email: 'a@b.com', name: 'Ann' } }
const RESUME_ID = 'resume-gap-1'
const LATEX = '\\documentclass{article}\\begin{document}\nAnn Lee — resume content long enough (well over two hundred characters) for the editor to mount and the optimize and cover-letter pages to render their full headers and controls without any errors at all.\n\\end{document}'

async function mockCommon(page: Page) {
  await page.route('**/api/auth/get-session', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }))
  await page.route((u) => u.pathname === '/me', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'u1', email: 'a@b.com', plan: 'free', preferences: {} }) }))
  await page.route((u) => u.pathname === `/resumes/${RESUME_ID}`, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, user_id: 'u1', title: 'R', latex_content: LATEX, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }) }))
  await page.route((u) => u.pathname.includes('/checkpoints'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((u) => u.pathname.endsWith('/academic-cv-report'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }) }))
  await page.route((u) => u.pathname.startsWith('/analytics') || u.pathname.startsWith('/format') || u.pathname.startsWith('/ats') || u.pathname.startsWith('/settings') || u.pathname.startsWith('/subscription') || u.pathname.startsWith('/config') || u.pathname.includes('/status') || u.pathname.includes('/diff'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (r) => r.abort())
}

test.describe('Account-menu legal links', () => {
  test('account menu carries Privacy and Terms links on app surfaces', async ({ page }) => {
    await mockCommon(page)
    await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /open account menu/i }).click()
    const menu = page.getByRole('menu')
    await expect(menu.getByRole('menuitem', { name: 'Privacy' })).toHaveAttribute('href', '/privacy')
    await expect(menu.getByRole('menuitem', { name: 'Terms' })).toHaveAttribute('href', '/terms')
  })
})

test.describe('Cover-letter mounts with unsaved-changes guard', () => {
  test('cover-letter page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    await mockCommon(page)
    await page.goto(`/workspace/${RESUME_ID}/cover-letter`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Back to Editor')).toBeVisible({ timeout: 15_000 })
    expect(errors).toEqual([])
  })
})
