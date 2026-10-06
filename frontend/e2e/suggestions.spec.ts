import { expect, test } from '@playwright/test'

const RESUME_ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
const SOURCE = 'Alpha target phrase omega'

test('suggestion mode keeps source unchanged until an owner accepts', async ({ page }) => {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session: {}, user: { id: 'owner-1', email: 'owner@example.com', name: 'Owner' } }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: RESUME_ID, user_id: 'owner-1', title: 'Suggestion Resume', latex_content: SOURCE, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', document_type: 'resume', metadata: {} }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/suggestion-decisions`, async (route) => {
    expect(route.request().method()).toBe('POST')
    const body = route.request().postDataJSON() as { expected_content: string; original_text: string; replacement_text: string }
    expect(body.expected_content).toBe(SOURCE)
    expect(body.original_text).toBe('target phrase')
    expect(body.replacement_text).toBe('improved phrase')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        suggestion_id: 'suggestion-owner-1',
        status: 'accepted',
        decided_by_role: 'owner',
        decided_at: '2026-01-01T00:00:00Z',
        latex_content: 'Alpha improved phrase omega',
        replayed: false,
      }),
    })
  })
  await page.route('**/ws/**', (route) => route.abort())
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })

  await page.getByRole('button', { name: 'More' }).click()
  await page.getByRole('menuitem', { name: 'Suggestions' }).click()
  await page.getByRole('button', { name: 'Turn on', exact: true }).click()
  await page.getByLabel('Existing text').fill('target phrase')
  await page.getByLabel('Suggested replacement').fill('improved phrase')
  await page.getByRole('button', { name: 'Create suggestion' }).click()
  await expect(page.getByText('+ improved phrase', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue: () => string } }).__latexyMonacoEditor?.getValue())).toBe(SOURCE)

  await page.getByRole('button', { name: 'Accept' }).click()
  await expect(page.getByText('No pending suggestions')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue: () => string } }).__latexyMonacoEditor?.getValue())).toContain('improved phrase')
})
