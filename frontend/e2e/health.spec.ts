import { test, expect } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Smoke tests — backend health + frontend load                       //
// ------------------------------------------------------------------ //

test('backend health endpoint is reachable', async ({ request }) => {
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
