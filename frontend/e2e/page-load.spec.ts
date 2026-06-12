import { test, expect } from '@playwright/test'

const PAGES = [
  ['/', 'landing'],
  ['/login', 'login'],
  ['/signup', 'signup'],
  ['/try', 'try-studio'],
  ['/workspace/new', 'new-resume'],
  ['/billing', 'billing'],
]

for (const [path, name] of PAGES) {
  test(`${name} page loads without JS errors`, async ({ page }) => {
    const jsErrors: string[] = []
    page.on('pageerror', e => jsErrors.push(e.message))
    const resp = await page.goto(path, { waitUntil: 'domcontentloaded' })
    expect(resp?.status()).toBeLessThan(500)
    const critical = jsErrors.filter(e => !e.includes('webpack') && !e.includes('hydrat') && !e.includes('ResizeObserver'))
    expect(critical).toHaveLength(0)
  })
}
