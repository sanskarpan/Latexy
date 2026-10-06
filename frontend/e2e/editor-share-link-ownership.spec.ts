import { expect, test } from '@playwright/test'

const RESUME_ID = 'b9234567-e89b-42d3-a456-426614174032'

for (const outcome of ['old-owner success', 'old-owner failure', 'same-owner success'] as const) {
test(`deferred share-link ownership: ${outcome}`, async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires a production editor ownership boundary')
  let owner = 'share-owner-a'
  let sessionCalls = 0
  let shareStarted = false
  let releaseShare!: () => void
  const shareGate = new Promise<void>((resolve) => { releaseShare = resolve })
  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      session: { token: `token-${owner}` }, user: { id: owner, email: `${owner}@example.com`, name: owner },
    }) })
  })
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      id: RESUME_ID, user_id: owner, title: `Share link ${owner}`,
      latex_content: `\\documentclass{article}\\begin{document}${owner} source.\\end{document}`,
      document_type: 'resume', metadata: {}, share_token: null, share_url: null,
      created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"is_academic_cv":false,"detected_sections":[]}' }))
  await page.route('**/github/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"private_sync":false}' }))
  await page.route('**/dropbox/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"connected":false}' }))
  await page.route((url) => url.pathname.startsWith('/analytics') || ['/trial/status', '/resumes/stats', '/me'].includes(url.pathname), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}' }))
  await page.route('**/ws/**', (route) => route.abort())
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/share`, async (route) => {
    shareStarted = true
    await shareGate
    if (outcome === 'old-owner failure') {
      await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"Old account share failure"}' })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      share_token: 'old-owner-a-token', share_url: 'https://latexy.xyz/r/old-owner-a-token',
      anonymous: false, review_comments: false, created_at: '2026-01-01T00:00:00Z',
    }) })
  })

  try {
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Share resume', exact: true })).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'Share resume', exact: true }).click()
    await page.getByRole('button', { name: 'Generate shareable link', exact: true }).click()
    await expect.poll(() => shareStarted).toBe(true)
    if (outcome !== 'same-owner success') {
    owner = 'share-owner-b'
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => sessionCalls).toBeGreaterThan(1)
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('share-owner-b source')
    }
    const response = page.waitForResponse((res) => res.url().endsWith(`/resumes/${RESUME_ID}/share`) && res.status() === (outcome === 'old-owner failure' ? 500 : 200))
    releaseShare()
    await (await response).finished()
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))
    if (outcome === 'same-owner success') {
      await expect(page.getByText('https://latexy.xyz/r/old-owner-a-token', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Manage share link', exact: true })).toBeVisible()
      await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Share link created' })).toHaveCount(1)
      return
    }
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Old account share failure' })).toHaveCount(0)
    await expect(page.getByText('https://latexy.xyz/r/old-owner-a-token', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Manage share link', exact: true })).toHaveCount(0)
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Share link created' })).toHaveCount(0)
  } finally {
    releaseShare()
  }
})
}
