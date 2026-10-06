import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Smoke tests — backend health + frontend load                       //
// ------------------------------------------------------------------ //

test('backend health endpoint is reachable', async ({ request }) => {
  test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Backend health requires an explicitly started backend')
  const res = await request.get('http://localhost:8030/health')
  expect(res.status()).toBe(200)
  const body = await res.json()
  expect(body).toHaveProperty('status')
})

test('frontend loads without JS errors', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (err) => errors.push(err.message))
  await page.goto('/')
  expect(errors.filter(e => !e.includes('webpack'))).toHaveLength(0)
})

test('frontend responses carry the security baseline', async ({ request }) => {
  const res = await request.get('/')

  expect(res.headers()['x-content-type-options']).toBe('nosniff')
  expect(res.headers()['x-frame-options']).toBe('DENY')
  expect(res.headers()['referrer-policy']).toBe('strict-origin-when-cross-origin')
  expect(res.headers()['permissions-policy']).toContain('camera=()')
  expect(res.headers()['content-security-policy']).toContain("frame-ancestors 'none'")
  expect(res.headers()['x-powered-by']).toBeUndefined()
})
