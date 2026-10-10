import { expect, test } from '@playwright/test'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Full-stack smoke requires an explicitly started backend')
test.setTimeout(60_000)

test('backend health and core frontend routes load end to end', async ({ page, request }) => {
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

  const health = await request.get(`${apiBase}/health`)
  expect(health.ok()).toBeTruthy()
  const healthPayload = await health.json()
  expect(String(healthPayload.status)).toMatch(/healthy|degraded/)

  const flags = await request.get(`${apiBase}/config/feature-flags`)
  expect(flags.ok()).toBeTruthy()

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  const studioLink = page.getByRole('link', { name: 'Build my résumé', exact: true }).first()
  await expect(studioLink).toBeVisible()
  await expect(studioLink).toHaveAttribute('href', '/try?mode=visual')

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await page.goto('/try', { waitUntil: 'domcontentloaded' })
      break
    } catch (error) {
      if (attempt === 3) {
        throw error
      }
      await page.waitForTimeout(1_000)
    }
  }

  await page.waitForURL('**/try', { timeout: 20_000 })
  await expect(page.locator('[data-editor-mode="visual"]')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Update PDF preview', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('button', { name: 'Update PDF preview', exact: true })).toBeVisible()
})
