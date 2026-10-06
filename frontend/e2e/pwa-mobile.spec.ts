import { expect, test, type Page } from '@playwright/test'

const RESUME_ID = '123e4567-e89b-42d3-a456-426614174099'

async function mockMobileEditor(page: Page) {
  await page.route('**/api/auth/get-session', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { token: 'mobile-token' },
      user: { id: 'mobile-user', email: 'mobile@example.com', name: 'Mobile User' },
    }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: RESUME_ID,
      user_id: 'mobile-user',
      title: 'Mobile Resume',
      latex_content: '\\documentclass{article}\n\\begin{document}\nMobile source\n\\end{document}',
      document_type: 'resume',
      metadata: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
    }),
  }))
  await page.route('**/github/status', route => route.fulfill({ status: 200, body: '{"connected":false}' }))
  await page.route('**/dropbox/status', route => route.fulfill({ status: 200, body: '{"connected":false}' }))
  await page.route((url) => url.pathname.includes('/checkpoints'), route => route.fulfill({ status: 200, body: '[]' }))
  await page.route((url) => url.pathname.endsWith('/academic-cv-report'), route => route.fulfill({
    status: 200,
    body: '{"is_academic_cv":false,"detected_sections":[],"estimated_pages":1,"confidence":0}',
  }))
  await page.route((url) => url.pathname === '/ats/quick-score', route => route.fulfill({
    status: 200,
    body: '{"score":70,"grade":"C","sections_found":[],"missing_sections":[]}',
  }))
  await page.route((url) => url.pathname === '/jobs/submit', route => route.fulfill({
    status: 200,
    body: '{"success":false,"message":"preview skipped"}',
  }))
  await page.route((url) => url.pathname.startsWith('/analytics'), route => route.fulfill({ status: 200, body: '{}' }))
  await page.route('**/ws/**', route => route.abort())
}

test.describe('mobile PWA', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test('offers installation inside the mobile menu and consumes the prompt once', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    const anyInstallControl = page.locator('header button').filter({ hasText: /Install/ })
    await expect.poll(async () => {
      await page.evaluate(() => {
        const event = new Event('beforeinstallprompt') as Event & {
          prompt: () => Promise<void>
          userChoice: Promise<{ outcome: 'accepted' }>
        }
        event.prompt = async () => {
          ;(window as typeof window & { __installPrompted?: boolean }).__installPrompted = true
        }
        event.userChoice = Promise.resolve({ outcome: 'accepted' })
        window.dispatchEvent(event)
      })
      return anyInstallControl.count()
    }).toBe(1)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    await expect(page.getByRole('button', { name: 'Close navigation menu' })).toBeVisible()
    const install = page.getByRole('button', { name: 'Install Latexy' })
    await expect(install).toBeVisible()
    await install.click()
    await expect.poll(() => page.evaluate(() => (
      window as typeof window & { __installPrompted?: boolean }
    ).__installPrompted)).toBe(true)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    await expect(page.getByRole('button', { name: 'Install Latexy' })).toHaveCount(0)
  })

  test('uses the touch-sized mobile editor with save and compile controls', async ({ page }) => {
    await mockMobileEditor(page)
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })

    await expect(page.getByTitle('Bold')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('button[title="Save"]')).toBeVisible()
    await expect(page.locator('button[title="Compile"]')).toBeVisible()
    await expect(page.locator('.cm-editor')).toContainText('Mobile source')
    await expect(page.getByRole('button', { name: 'Ask AI' })).toBeVisible()
  })
})
