import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174032'
const OWNER_A_SOURCE = '\\documentclass{article}\\begin{document}Owner A source.\\end{document}'
const OWNER_B_SOURCE = '\\documentclass{article}\\begin{document}Owner B source.\\end{document}'
const STALE_PULL_SOURCE = '\\documentclass{article}\\begin{document}Stale owner A GitHub pull.\\end{document}'

async function mockEditor(page: Page, ownerRef: { current: string }, sync: 'github' | 'dropbox' = 'github'): Promise<void> {
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: ownerRef.current,
      title: 'Ownership mutation fixture',
      latex_content: ownerRef.current === 'owner-a' ? OWNER_A_SOURCE : OWNER_B_SOURCE,
      document_type: 'resume',
      github_sync_enabled: sync === 'github',
      dropbox_sync_enabled: sync === 'dropbox',
      metadata: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route('**/github/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ connected: true, username: 'octocat', public_import: true, private_sync: sync === 'github' }),
  }))
  await page.route('**/dropbox/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connected: sync === 'dropbox' }) }))
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '{"is_academic_cv":false,"detected_sections":[],"estimated_pages":1,"confidence":0}',
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}' }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())
}

test('does not apply a deferred GitHub pull after an account switch', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'mutation ownership proof runs against the production editor bundle')

  const ownerRef = { current: 'owner-a' }
  let sessionCalls = 0
  let pullStarted = false
  let releasePull!: () => void
  const pullGate = new Promise<void>((resolve) => { releasePull = resolve })

  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { token: `token-${ownerRef.current}` },
        user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current },
      }),
    })
  })
  await mockEditor(page, ownerRef)
  await page.route((url) => url.pathname.endsWith(`/github/resumes/${RESUME_ID}/pull`), async (route) => {
    pullStarted = true
    await pullGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, latex_content: STALE_PULL_SOURCE }) })
  })

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: 'Pull', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor))).toBe(true)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A source')

  await page.getByRole('button', { name: 'Pull', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Replace', exact: true }).click()
  await expect.poll(() => pullStarted).toBe(true)
  const sameDocumentUrl = page.url()
  await page.evaluate(() => {
    ;(window as Window & { __mutationOwnershipMarker?: number }).__mutationOwnershipMarker = 1
  })

  ownerRef.current = 'owner-b'
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(() => sessionCalls).toBeGreaterThan(1)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner B source')

  const pullResponse = page.waitForResponse((response) => response.url().endsWith(`/github/resumes/${RESUME_ID}/pull`) && response.status() === 200)
  releasePull()
  const response = await pullResponse
  await response.finished()
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  }))

  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).not.toContain('Stale owner A GitHub pull')
  expect(page.url()).toBe(sameDocumentUrl)
  expect(await page.evaluate(() => (window as Window & { __mutationOwnershipMarker?: number }).__mutationOwnershipMarker)).toBe(1)
})

test('does not apply a deferred Dropbox pull after an account switch', async ({ page }) => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'mutation ownership proof runs against the production editor bundle')

  const ownerRef = { current: 'owner-a' }
  let sessionCalls = 0
  let pullStarted = false
  let releasePull!: () => void
  const pullGate = new Promise<void>((resolve) => { releasePull = resolve })

  await page.route('**/api/auth/get-session', (route) => {
    sessionCalls += 1
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { token: `token-${ownerRef.current}` },
        user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current },
      }),
    })
  })
  await mockEditor(page, ownerRef, 'dropbox')
  await page.route((url) => url.pathname.endsWith(`/dropbox/resumes/${RESUME_ID}/pull`), async (route) => {
    pullStarted = true
    await pullGate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, latex_content: STALE_PULL_SOURCE }) })
  })

  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByTitle('Pull from Dropbox')).toBeVisible({ timeout: 30_000 })
  await expect.poll(() => page.evaluate(() => Boolean((window as typeof window & { __latexyMonacoEditor?: unknown }).__latexyMonacoEditor))).toBe(true)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A source')

  await page.getByTitle('Pull from Dropbox').click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Replace', exact: true }).click()
  await expect.poll(() => pullStarted).toBe(true)

  ownerRef.current = 'owner-b'
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(() => sessionCalls).toBeGreaterThan(1)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner B source')

  const pullResponse = page.waitForResponse((response) => response.url().endsWith(`/dropbox/resumes/${RESUME_ID}/pull`) && response.status() === 200)
  releasePull()
  const response = await pullResponse
  await response.finished()
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))
  }))

  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).not.toContain('Stale owner A GitHub pull')
})
