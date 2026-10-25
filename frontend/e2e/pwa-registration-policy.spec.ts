import { expect, test } from '@playwright/test'

type PolicyObservation = { calls: number; policy: 'undefined' | 'reject' }

for (const [policy, title] of [
  ['undefined', 'public UI survives a blocked service worker without a registration'],
  ['reject', 'public UI survives a service-worker registration denied by browser policy'],
] as const) {
  test(title, async ({ page, context }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await context.addInitScript((policy) => {
      const observation: PolicyObservation = { calls: 0, policy }
      ;(window as Window & { __pwaPolicy?: PolicyObservation }).__pwaPolicy = observation
      const original = navigator.serviceWorker.register.bind(navigator.serviceWorker)
      Object.defineProperty(navigator.serviceWorker, 'register', {
        configurable: true,
        value: (...args: Parameters<ServiceWorkerContainer['register']>) => {
          observation.calls += 1
          // The first path executes Playwright's actual blocked implementation,
          // which resolves undefined. The second models a legitimate denial.
          return policy === 'reject'
            ? Promise.reject(new DOMException('Synthetic policy denies service workers', 'SecurityError'))
            : original(...args)
        },
      })
    }, policy)
    await context.route('**/*', route => {
      const request = route.request()
      const url = new URL(request.url())
      if (!['localhost', '127.0.0.1'].includes(url.hostname) ||
          !['GET', 'HEAD'].includes(request.method()) ||
          url.pathname.startsWith('/api/') || ['xhr', 'fetch'].includes(request.resourceType())) {
        return route.abort('blockedbyclient')
      }
      return route.continue()
    })
    await context.routeWebSocket('**/*', route => route.close())
    await page.goto('/updates', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.locator('header a[href="/pricing"]')).toBeVisible()
    await expect(page).toHaveTitle('Product Updates and Release Notes | Latexy')
    await expect.poll(() => page.evaluate(() =>
      (window as Window & { __pwaPolicy?: PolicyObservation }).__pwaPolicy?.calls,
    )).toBe(1)
    // Allow registration's promise and the browser's rejection event to finish
    // before checking page errors; a synchronous empty snapshot is insufficient.
    await page.evaluate(() => new Promise<void>(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    ))
    const observation = await page.evaluate(() => ({
      policy: (window as Window & { __pwaPolicy?: PolicyObservation }).__pwaPolicy,
      workboxCreated: typeof (window as Window & { workbox?: { register?: unknown } }).workbox?.register === 'function',
    }))
    expect(observation.workboxCreated).toBe(true)
    await testInfo.attach('optional-registration-policy.json', {
      body: JSON.stringify({ observation, errors }), contentType: 'application/json',
    })
    expect(errors, 'Optional worker failure must not become an unhandled page error').toEqual([])
  })
}
