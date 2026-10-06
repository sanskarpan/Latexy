import { expect, test, type Page } from '@playwright/test'

const SESSION = {
  session: { id: 'session-drive', userId: 'user-drive', token: 'session-token' },
  user: { id: 'user-drive', email: 'drive@example.com', name: 'Drive User' },
}

async function mockSettings(page: Page, drive: { connected: boolean; scope: 'drive.file' | null }) {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(SESSION),
  }))

  await page.route((url) => url.pathname === '/settings/notifications', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false, tracker_updates: true, comment_mentions: true }),
  }))
  await page.route((url) => url.pathname === '/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ preferences: { spell_dictionary: [] } }),
  }))
  for (const path of ['/github/status', '/zotero/status', '/mendeley/status', '/dropbox/status']) {
    await page.route((url) => url.pathname === path, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false }),
    }))
  }
  await page.route((url) => url.pathname === '/google-drive/status', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(drive),
  }))
}

test.describe('Google Drive export integration', () => {
  test('completes OAuth once, cleans the ticket, and never renders credentials', async ({ page }) => {
    await mockSettings(page, { connected: false, scope: null })
    let completionCalls = 0
    let statusCalls = 0
    await page.route((url) => url.pathname === '/google-drive/status', async (route) => {
      statusCalls += 1
      await new Promise((resolve) => setTimeout(resolve, 250))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ connected: true, scope: 'drive.file' }),
      })
    })
    await page.route((url) => url.pathname === '/google-drive/complete', (route) => {
      completionCalls += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'connected' }),
      })
    })
    await page.goto('/settings?google_drive=complete&ticket=one-time-secret-ticket', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Google Drive connected successfully!')).toBeVisible()
    await expect.poll(() => completionCalls).toBe(1)
    // The delayed status response is the only status read: the normal mount
    // request is deferred while the completion ticket is being exchanged.
    await expect.poll(() => statusCalls).toBe(1)
    await expect.poll(() => new URL(page.url()).search).toBe('')
    await expect(page.locator('body')).not.toContainText('one-time-secret-ticket')
    await expect(page.locator('body')).not.toContainText('access_token')
  })

  test('shows a persistent OAuth error and cleans the error query', async ({ page }) => {
    await mockSettings(page, { connected: false, scope: null })
    await page.goto('/settings?google_drive=error&reason=access_denied', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Google Drive authorization was cancelled.')).toBeVisible()
    await expect.poll(() => new URL(page.url()).search).toBe('')
  })

  test('rejects a same-host URL with an unexpected OAuth path', async ({ page }) => {
    await mockSettings(page, { connected: false, scope: null })
    await page.route((url) => url.pathname === '/google-drive/connect', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ authorization_url: 'https://accounts.google.com/not-oauth' }),
    }))
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Connect Google Drive' }).click()
    await expect(page.getByText('Google Drive returned an invalid authorization URL. Please retry.')).toBeVisible()
    expect(new URL(page.url()).pathname).toBe('/settings')
  })

  test('disconnects without exposing account credentials', async ({ page }) => {
    await mockSettings(page, { connected: true, scope: 'drive.file' })
    let disconnectCalls = 0
    await page.route((url) => url.pathname === '/google-drive/disconnect', (route) => {
      disconnectCalls += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'disconnected' }),
      })
    })
    page.on('dialog', (dialog) => void dialog.accept())
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('Google Drive connected', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Disconnect Google Drive' }).click()
    await expect.poll(() => disconnectCalls).toBe(1)
    await expect(page.getByRole('button', { name: 'Connect Google Drive' })).toBeVisible()
    await expect(page.locator('body')).not.toContainText('refresh_token')
  })
})
