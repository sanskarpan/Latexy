import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeef'

const session = (owner: 'a' | 'b') => ({
  session: { token: `parent-diff-token-${owner}` },
  user: { id: `parent-diff-owner-${owner}`, email: `parent-diff-${owner}@example.com`, name: `Parent Diff ${owner}` },
})

const resume = (owner: 'a' | 'b') => ({
  id: RESUME_ID,
  user_id: `parent-diff-owner-${owner}`,
  title: `Variant ${owner}`,
  latex_content: '\\documentclass{article}\\begin{document}Diff fixture.\\end{document}',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  document_type: 'resume',
  content_source: 'builder_variant',
  parent_resume_id: owner === 'a' ? 'parent-a' : 'parent-b',
  metadata: {},
})

const diff = (owner: 'a' | 'b') => ({
  parent_latex: `\\documentclass{article}\\begin{document}Parent ${owner}.\\end{document}`,
  parent_title: `Parent ${owner.toUpperCase()}`,
  variant_latex: `\\documentclass{article}\\begin{document}Variant ${owner}.\\end{document}`,
  variant_title: `Variant ${owner.toUpperCase()}`,
})

async function mockEditor(page: Page, ownerRef: { current: 'a' | 'b' }, sessionCalls: { value: number }) {
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls.value += 1
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session(ownerRef.current)) })
  })
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(resume(ownerRef.current)) }))
  await page.route((url) => url.pathname === '/resumes/parent-a', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title: 'Parent A' }) }))
  await page.route((url) => url.pathname === '/resumes/parent-b', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ title: 'Parent B' }) }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 }) }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname === '/me' || url.pathname.includes('/checkpoints'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/dropbox/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"connected":false}' }))
  await page.route('**/github/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"private_sync":false}' }))
  await page.route('**/ws/**', (route) => route.abort())
}

async function switchOwner(page: Page, ownerRef: { current: 'a' | 'b' }, sessionCalls: { value: number }) {
  const before = sessionCalls.value
  ownerRef.current = 'b'
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(() => sessionCalls.value).toBeGreaterThan(before)
  await expect(page.getByText('Parent B', { exact: true })).toBeVisible({ timeout: 15_000 })
}

async function settle(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 80))))
  )
}

test.describe('editor parent-diff ownership diagnostics', () => {
  test('does not open a deferred old-owner parent diff after account switch', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'parent-diff ownership proof runs against the production editor bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const sessionCalls = { value: 0 }
    await mockEditor(page, ownerRef, sessionCalls)
    let releaseOldDiff!: () => void
    let diffStarted!: () => void
    const diffGate = new Promise<void>((resolve) => { releaseOldDiff = resolve })
    const diffRequest = new Promise<void>((resolve) => { diffStarted = resolve })
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/diff-with-parent`, async (route) => {
      diffStarted()
      await diffGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(diff('a')) })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Parent A', { exact: true })).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: 'Compare with Parent', exact: true }).click()
    await diffRequest

    await switchOwner(page, ownerRef, sessionCalls)
    const oldResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/${RESUME_ID}/diff-with-parent`) && response.status() === 200)
    releaseOldDiff()
    const response = await oldResponse
    await response.finished()
    await settle(page)
    await expect(page.getByRole('heading', { name: 'Compare Versions' })).toHaveCount(0)
    await expect(page.getByText('Parent A', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Parent B', { exact: true })).toBeVisible()
  })

  test('same-owner parent diff still opens successfully', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'parent-diff ownership proof runs against the production editor bundle')
    const ownerRef: { current: 'a' | 'b' } = { current: 'a' }
    const sessionCalls = { value: 0 }
    await mockEditor(page, ownerRef, sessionCalls)
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/diff-with-parent`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(diff('a')) }))

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('button', { name: 'Compare with Parent', exact: true })).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: 'Compare with Parent', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Compare Versions' })).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('div.fixed.inset-0').getByText('Parent A', { exact: true })).toBeVisible()
  })
})
