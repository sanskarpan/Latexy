import { expect, test } from './quality-test'

async function assertStaticWrappers(page: import('@playwright/test').Page) {
  await expect.poll(() => page.locator('[data-marketing-motion]').evaluateAll(nodes =>
    nodes.length > 1 && nodes.every(node => {
      const style = getComputedStyle(node)
      return style.opacity === '1' && style.transform === 'none'
    }),
  )).toBe(true)
}

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false })
  for (const reducedMotion of ['reduce', 'no-preference'] as const) {
    test(`updates remain readable (${reducedMotion})`, async ({ page }, testInfo) => {
      await page.emulateMedia({ reducedMotion })
      await page.goto('/updates')
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await assertStaticWrappers(page)
      const path = testInfo.outputPath(`updates-${reducedMotion}-no-js.png`)
      await page.screenshot({ path, fullPage: true })
      await testInfo.attach(`updates-${reducedMotion}-no-js`, { path, contentType: 'image/png' })
    })
  }
})

test('reduced-motion updates stay static across scrolling and preference changes', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/updates')
  await assertStaticWrappers(page)
  await page.getByRole('heading', { level: 2 }).last().scrollIntoViewIfNeeded()
  await assertStaticWrappers(page)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await assertStaticWrappers(page)
  await expect(page.getByText(/no-training data commitment/i)).toHaveCount(0)
  const path = testInfo.outputPath('updates-reduced-hydrated.png')
  await page.screenshot({ path, fullPage: true })
  await testInfo.attach('updates-reduced-hydrated', { path, contentType: 'image/png' })
})
