import { expect, test, type Page } from '@playwright/test'

test.setTimeout(60_000)

const PROJECT = {
  source: 'github',
  title: 'original-project',
  description: 'Original imported description',
  tech: ['TypeScript', 'Redis'],
  metrics: { stars: 12, forks: 2 },
  dates: { last_active: '2026-08-01T00:00:00Z' },
  url: 'https://github.com/example/original-project',
  suggested_bullets: ['Original imported bullet'],
  raw_excerpt: '',
}

async function openAuthenticatedImport(page: Page) {
  await page.routeWebSocket('**/ws/jobs**', (ws) => {
    ws.onMessage((data) => {
      try {
        const message = JSON.parse(data as string)
        if (message.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
        }
      } catch {
        // The idle test transport ignores malformed frames.
      }
    })
  })
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'session-1', userId: 'user-1', token: 'test-token' },
        user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
      }),
    })
  )
  await page.route('**/config/feature-flags', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  )
  await page.route('**/public/trial-status?*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ usageCount: 0, trialLimit: 3, blocked: false }),
    })
  )
  await page.route('**/github/status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: true }),
    })
  )

  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('button', { name: /recompile/i })).toBeVisible()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_try_latex'))).not.toBeNull()
  await page.locator('nav button[title="Import"]').click()
  await page.getByRole('button', { name: /^Import projects/i }).click()
}

test('GitHub import retries in place and inserts edited evidence', async ({ page }) => {
  let importAttempts = 0
  await page.route('**/github/import-projects', async (route) => {
    if (route.request().method() === 'POST') {
      importAttempts += 1
      if (importAttempts === 1) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Temporary GitHub failure' }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'github-job-1' }),
      })
    }

    return route.continue()
  })
  await page.route('**/github/import-projects/github-job-1', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'completed', projects: [PROJECT], error: null }),
    })
  )

  await openAuthenticatedImport(page)

  await expect(page.getByText('Temporary GitHub failure')).toBeVisible()
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByLabel('Project title 1')).toHaveValue('original-project')
  expect(importAttempts).toBe(2)

  await page.getByLabel('Project title 1').fill('edited_project')
  await page.getByLabel('Project description 1').fill('Edited description for R&D')
  await page.getByLabel('Project bullet 1.1', { exact: true }).fill('Reduced latency by 45%')
  await expect(page.getByLabel('Project description 1')).toHaveValue('Edited description for R&D')
  await page.getByRole('button', { name: 'Insert into resume' }).click()

  await expect.poll(() => page.evaluate(() => localStorage.getItem('latexy_try_latex'))).toContain('edited\\_project')
  const saved = await page.evaluate(() => localStorage.getItem('latexy_try_latex'))
  expect(saved).toContain('Reduced latency by 45\\%')
  expect(saved).not.toContain('Original imported bullet')
  expect(saved?.split('edited\\_project')).toHaveLength(2)
})
