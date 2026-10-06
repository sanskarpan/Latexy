import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174032'
const OWNER_A_SOURCE = '\\documentclass{article}\\begin{document}Owner A saved source.\\end{document}'
const OWNER_B_SOURCE = '\\documentclass{article}\\begin{document}Owner B saved source.\\end{document}'

async function mockSaveEditor(page: Page, ownerRef: { current: string }, onSave: (route: import('@playwright/test').Route) => Promise<void>, onSession?: () => void): Promise<void> {
  await page.route('**/api/auth/get-session', (route) => {
    // Keep the session response dynamic so an in-document auth refresh loads
    // the next owner's document without replacing the page.
    onSession?.()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { token: `token-${ownerRef.current}` },
        user: { id: ownerRef.current, email: `${ownerRef.current}@example.com`, name: ownerRef.current },
      }),
    })
  })
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, async (route) => {
    if (route.request().method() === 'PUT') {
      await onSave(route)
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: RESUME_ID,
        user_id: ownerRef.current,
        title: ownerRef.current === 'owner-a' ? 'Owner A title' : 'Owner B title',
        latex_content: ownerRef.current === 'owner-a' ? OWNER_A_SOURCE : OWNER_B_SOURCE,
        document_type: 'resume',
        metadata: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      }),
    })
  })
  await page.route('**/github/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"private_sync":false}' }))
  await page.route('**/dropbox/status', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"connected":false}' }))
  await page.route((url) => url.pathname.includes('/checkpoints'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"is_academic_cv":false,"detected_sections":[],"estimated_pages":1,"confidence":0}' }))
  await page.route((url) => url.pathname === '/ats/quick-score', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}' }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname === '/me', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())
}

async function switchSaveOwner(page: Page, ownerRef: { current: string }, sessionCalls: () => number): Promise<void> {
  ownerRef.current = 'owner-b'
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'test' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
  await expect.poll(sessionCalls).toBeGreaterThan(1)
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner B saved source')
}

test.describe('editor save ownership', () => {
  test('does not apply a deferred explicit save after an account switch', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'save ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let sessionCalls = 0
    let saveStarted = false
    let releaseSave!: () => void
    const saveGate = new Promise<void>((resolve) => { releaseSave = resolve })

    await mockSaveEditor(page, ownerRef, async (route) => {
      saveStarted = true
      await saveGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, success: true }) })
    }, () => { sessionCalls += 1 })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A saved source')
    const sameDocumentUrl = page.url()
    await page.evaluate(() => { (window as Window & { __saveOwnershipMarker?: number }).__saveOwnershipMarker = 1 })
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => saveStarted).toBe(true)

    await switchSaveOwner(page, ownerRef, () => sessionCalls)
    const saveResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/${RESUME_ID}`) && response.request().method() === 'PUT' && response.status() === 200)
    releaseSave()
    const response = await saveResponse
    await response.finished()
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))

    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).not.toContain('Owner A saved source')
    expect(page.url()).toBe(sameDocumentUrl)
    expect(await page.evaluate(() => (window as Window & { __saveOwnershipMarker?: number }).__saveOwnershipMarker)).toBe(1)
  })

  test('does not apply a deferred autosave after an account switch', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'save ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let sessionCalls = 0
    let saveStarted = false
    let releaseSave!: () => void
    const saveGate = new Promise<void>((resolve) => { releaseSave = resolve })

    await mockSaveEditor(page, ownerRef, async (route) => {
      saveStarted = true
      await saveGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, success: true }) })
    }, () => { sessionCalls += 1 })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A saved source')
    await page.getByPlaceholder('Untitled').fill('Owner A edited title')
    await expect.poll(() => saveStarted, { timeout: 7_000 }).toBe(true)

    await switchSaveOwner(page, ownerRef, () => sessionCalls)
    const saveResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/${RESUME_ID}`) && response.request().method() === 'PUT' && response.status() === 200)
    releaseSave()
    const response = await saveResponse
    await response.finished()
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 50)))))

    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).not.toContain('Owner A saved source')
    await expect(page.getByPlaceholder('Untitled')).toHaveValue('Owner B title')
  })

  test('applies a deferred explicit save for the same owner', async ({ page }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'save ownership proof runs against the production editor bundle')
    const ownerRef = { current: 'owner-a' }
    let saveStarted = false
    let releaseSave!: () => void
    const saveGate = new Promise<void>((resolve) => { releaseSave = resolve })

    await mockSaveEditor(page, ownerRef, async (route) => {
      saveStarted = true
      await saveGate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: RESUME_ID, success: true }) })
    })

    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toContain('Owner A saved source')
    await page.getByPlaceholder('Untitled').fill('Owner A saved title')
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => saveStarted).toBe(true)
    const saveResponse = page.waitForResponse((response) => response.url().endsWith(`/resumes/${RESUME_ID}`) && response.request().method() === 'PUT' && response.status() === 200)
    releaseSave()
    const response = await saveResponse
    await response.finished()
    await expect(page.getByRole('status')).toHaveText('Saved')
  })
})
