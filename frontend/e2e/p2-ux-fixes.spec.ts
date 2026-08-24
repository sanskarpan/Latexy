import { test, expect, type Page } from '@playwright/test'

// ------------------------------------------------------------------ //
//  P2 (Low) UX-audit fixes — the reliably browser-testable ones:     //
//  flash-free ModeToggle (both icons in the DOM, CSS-switched), and   //
//  the editor still mounting with the new ConfirmDialog + clickable   //
//  Recent Activity wiring in place.                                   //
// ------------------------------------------------------------------ //

test.describe('ModeToggle — flash-free icons', () => {
  test('renders a theme toggle with both icons present (CSS-switched)', async ({ page }) => {
    await page.goto('/faq', { waitUntil: 'domcontentloaded' })
    const toggle = page.getByRole('button', { name: /toggle.*mode/i }).first()
    await expect(toggle).toBeVisible()
    // Both glyphs are always in the DOM; CSS shows the right one per data-mode,
    // so there is no post-hydration element swap / flash.
    await expect(toggle.locator('.mode-icon-light')).toHaveCount(1)
    await expect(toggle.locator('.mode-icon-dark')).toHaveCount(1)
    // Exactly one is visible for the current theme.
    const lightVisible = await toggle.locator('.mode-icon-light').isVisible()
    const darkVisible = await toggle.locator('.mode-icon-dark').isVisible()
    expect(lightVisible).not.toEqual(darkVisible)
  })
})

// --- Editor still mounts (ConfirmDialog import + Recent-Activity wiring) ---

const RESUME_ID = 'resume-p2-1'
const LATEX = '\\documentclass{article}\\begin{document}\nJane Doe — a resume with more than two hundred characters of content so the workspace editor mounts and renders its full header, toolbar, and status bar without any runtime errors on load.\n\\end{document}'
const SESSION = { session: { token: 't' }, user: { id: 'u1', email: 'a@b.com', name: 'A' } }

async function mockEdit(page: Page) {
  await page.route('**/api/auth/get-session', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SESSION) }))
  await page.route((u) => u.pathname === `/resumes/${RESUME_ID}`, (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, user_id: 'u1', title: 'R', latex_content: LATEX, created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }) }))
  await page.route((u) => u.pathname.includes('/checkpoints'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((u) => u.pathname.endsWith('/academic-cv-report'), (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0, reasons: [] }) }))
  await page.route((u) => u.pathname.startsWith('/analytics') || u.pathname.startsWith('/format') || u.pathname.startsWith('/ats') || u.pathname === '/me', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (r) => r.abort())
}

test.describe('Editor mounts cleanly with P2 wiring', () => {
  test('edit page loads without runtime errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))
    await mockEdit(page)
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(/\d+ chars/).first()).toBeVisible({ timeout: 15_000 })
    expect(errors).toEqual([])
  })
})
