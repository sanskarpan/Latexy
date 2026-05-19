import { expect, test } from '@playwright/test'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Full-stack smoke requires an explicitly started backend')

test('backend health and core frontend routes load end to end', async ({ page, request }) => {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

  const health = await request.get(`${apiBase}/health`)
  expect(health.ok()).toBeTruthy()
  const healthPayload = await health.json()
  expect(String(healthPayload.status)).toMatch(/healthy|degraded/)

  const flags = await request.get(`${apiBase}/config/feature-flags`)
  expect(flags.ok()).toBeTruthy()

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('link', { name: 'Start Building' })).toBeVisible()

  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.monaco-editor', { timeout: 20_000 })
  await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeVisible()
})
