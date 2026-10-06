import { expect, test } from '@playwright/test'

test.describe('production service worker', () => {
  test.skip(process.env.PWA_PRODUCTION !== '1', 'requires a production build and server')

  test('installs a lean worker, excludes private caches, and serves the offline fallback', async ({ page, context }) => {
    await page.goto('/', { waitUntil: 'networkidle' })
    await page.evaluate(() => navigator.serviceWorker.ready)
    await page.reload({ waitUntil: 'networkidle' })
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))

    const cacheAudit = await page.evaluate(async () => {
      const names = await caches.keys()
      const urls = (await Promise.all(names.map(async (name) => {
        const cache = await caches.open(name)
        return (await cache.keys()).map(request => request.url)
      }))).flat()
      return { names, urls }
    })
    expect(cacheAudit.names).not.toContain('latexy-pdf-cache')
    expect(cacheAudit.names).not.toContain('latexy-api-resumes')
    expect(cacheAudit.urls.some(url => url.includes('/monaco/'))).toBe(false)

    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.goto(`/definitely-not-cached-pwa-route?nonce=${crypto.randomUUID()}`)
    await expect(offlinePage.getByRole('heading', { name: "You're offline" })).toBeVisible()
    await context.setOffline(false)
  })
})
