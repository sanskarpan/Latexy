import { test, expect, type Page } from '@playwright/test'

// ------------------------------------------------------------------ //
//  UX-audit backlog fixes — the reliably browser-testable ones:      //
//  legal pages + footer links (#footer-legal), changelog data source //
//  (#changelog), and the theme toggle on the fullscreen editor.      //
// ------------------------------------------------------------------ //

test.describe('Legal pages + footer', () => {
  test('/privacy renders the Privacy Policy content', async ({ page }) => {
    await page.goto('/privacy', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /Privacy Policy/i }).first()).toBeVisible()
    await expect(page.getByText(/Information We Collect/i).first()).toBeVisible()
  })

  test('/terms renders the Terms of Service content', async ({ page }) => {
    await page.goto('/terms', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: /Terms of Service/i }).first()).toBeVisible()
    await expect(page.getByText(/Acceptance of Terms/i).first()).toBeVisible()
  })

  test('marketing footer exposes Privacy, Terms, and Contact links', async ({ page }) => {
    await page.goto('/faq', { waitUntil: 'domcontentloaded' })
    const footer = page.locator('footer')
    await expect(footer.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy')
    await expect(footer.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms')
    await expect(footer.getByRole('link', { name: 'Contact' })).toHaveAttribute('href', /^mailto:/)
  })
})

test.describe('Changelog', () => {
  test('/updates renders the data-sourced changelog with the latest entry', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    await page.goto('/updates', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('ATS Score Card & Trust Commitments')).toBeVisible()
    await expect(page.getByText('Onboarding & Workspace Redesign')).toBeVisible()
    expect(errors).toEqual([])
  })
})

// --- Theme toggle on the fullscreen editor (reuses a mocked edit page) ---

const RESUME_ID = 'resume-theme-1'
const LATEX = '\\documentclass{article}\\begin{document}\nJane Doe, resume content that is comfortably over two hundred characters so the editor mounts and the workspace shell renders its full header with all of its controls visible.\n\\end{document}'
const SESSION = { session: { token: 't' }, user: { id: 'u1', email: 'a@b.com', name: 'A' } }

async function mockEdit(page: Page) {
  await page.route('**/api/auth/get-session', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }))
  await page.route((u) => u.pathname === `/resumes/${RESUME_ID}`, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, user_id: 'u1', title: 'R', latex_content: LATEX, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }) }))
  await page.route((u) => u.pathname.includes('/checkpoints'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((u) => u.pathname.endsWith('/academic-cv-report'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }) }))
  await page.route((u) => u.pathname.startsWith('/analytics') || u.pathname.startsWith('/format') || u.pathname.startsWith('/ats'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (r) => r.abort())
}

test.describe('Theme toggle on fullscreen editor', () => {
  test('the editor header renders a theme toggle', async ({ page }) => {
    await mockEdit(page)
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(/\d+ chars/).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: /theme|dark|light|mode/i }).first()).toBeVisible()
  })
})
