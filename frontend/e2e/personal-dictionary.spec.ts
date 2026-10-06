import { expect, test, type Page, type Route } from '@playwright/test'

const SESSION = {
  session: { id: 'session-1', userId: 'user-1', token: 'dictionary-session' },
  user: { id: 'user-1', email: 'writer@example.com', name: 'Dictionary User' },
}

async function mockSettings(page: Page) {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(SESSION),
  }))
  await page.route('**/settings/notifications', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false }),
  }))
  const disconnected = (route: Route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ connected: false }),
  })
  for (const provider of ['github', 'zotero', 'mendeley', 'dropbox']) {
    await page.route(`**/${provider}/status`, disconnected)
  }
}

test('personal dictionary merges devices and supports account-synced add/remove', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('latexy_spell_dictionary', JSON.stringify(['LocalTerm']))
  })
  await mockSettings(page)

  let preferences = { has_onboarded: true, spell_dictionary: ['OpenAI'] }
  const patches: Array<Record<string, unknown>> = []
  await page.route((url) => url.pathname === '/me' || url.pathname === '/me/preferences', async (route) => {
    expect(await route.request().headerValue('authorization')).toBe('Bearer dictionary-session')
    if (route.request().method() === 'PATCH') {
      const patch = route.request().postDataJSON() as Record<string, unknown>
      patches.push(patch)
      preferences = { ...preferences, ...patch } as typeof preferences
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'user-1', email: 'writer@example.com', plan: 'free', role: 'user', preferences }),
    })
  })

  await page.goto('/settings', { waitUntil: 'domcontentloaded' })
  const dictionary = page.getByRole('list', { name: 'Personal dictionary words' })
  await expect(dictionary.getByText('openai', { exact: true })).toBeVisible()
  await expect(dictionary.getByText('localterm', { exact: true })).toBeVisible()
  await expect.poll(() => patches.length).toBe(1)
  expect(patches[0]).toEqual({ spell_dictionary: ['openai', 'localterm'] })

  await page.getByRole('button', { name: 'Remove openai from personal dictionary' }).click()
  await expect(dictionary.getByText('openai', { exact: true })).toHaveCount(0)
  await expect.poll(() => patches.length).toBe(2)
  expect(patches[1]).toEqual({ spell_dictionary: ['localterm'] })

  await page.getByLabel('Word to add').fill(' Node.js ')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(dictionary.getByText('node.js', { exact: true })).toBeVisible()
  await expect.poll(() => patches.length).toBe(3)
  expect(patches[2]).toEqual({ spell_dictionary: ['localterm', 'node.js'] })
  await expect(page.getByText('2/500 words')).toBeVisible()
})
