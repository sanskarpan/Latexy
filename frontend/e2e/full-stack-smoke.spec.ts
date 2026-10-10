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

  const frontendOrigin = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5180'}`
  const preflight = await request.fetch(`${apiBase}/config/entitlements`, {
    method: 'OPTIONS',
    headers: { Origin: frontendOrigin, 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'authorization' },
  })
  expect(preflight.ok(), 'Local browser API CORS preflight must succeed before checking UI').toBeTruthy()
  expect(preflight.headers()['access-control-allow-origin']).toBe(frontendOrigin)
  expect(preflight.headers()['access-control-allow-credentials']).toBe('true')

  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('link', { name: 'Start compiling →' })).toBeVisible()

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
  await page.waitForSelector('.monaco-editor', { timeout: 20_000 })
  await expect(page.getByRole('button', { name: /recompile/i })).toBeVisible()
})
