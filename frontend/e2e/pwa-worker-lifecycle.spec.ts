import { expect, test } from '@playwright/test'

test('activates a real generated worker update while retaining the offline fallback', async ({ page, context }, testInfo) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  await page.evaluate(() => navigator.serviceWorker.ready)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
  const before = await page.request.get('/__pwa_acceptance__/worker-version').then(response => response.json())
  expect(before.workerIdentity.originalSha256).toMatch(/^[a-f0-9]{64}$/)
  expect(before.workerIdentity.derivedSha256).toBe(before.workerIdentity.originalSha256)
  await page.request.post('/__pwa_acceptance__/worker-version')
  const updated = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    const previous = registration.active
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Worker did not activate its update')), 30_000)
      const check = () => {
        if (registration.active && registration.active !== previous && registration.active.state === 'activated') {
          clearTimeout(timeout)
          resolve()
        }
      }
      registration.addEventListener('updatefound', () => {
        registration.installing?.addEventListener('statechange', check)
      })
      navigator.serviceWorker.addEventListener('controllerchange', check)
      registration.update().catch(reject)
    })
    return { previousState: previous?.state, activeState: registration.active?.state,
      controlled: navigator.serviceWorker.controller === registration.active }
  })
  expect(updated).toEqual({ previousState: 'redundant', activeState: 'activated', controlled: true })
  const after = await page.request.get('/__pwa_acceptance__/worker-version').then(response => response.json())
  expect(after.workerIdentity.originalSha256).toBe(before.workerIdentity.originalSha256)
  expect(after.workerIdentity.derivedSha256).not.toBe(before.workerIdentity.derivedSha256)
  await testInfo.attach('actual-worker-update.json', { body: JSON.stringify({ before, after, updated }), contentType: 'application/json' })
  await context.setOffline(true)
  const offlinePage = await context.newPage()
  await offlinePage.goto(`/pwa-update-offline-${crypto.randomUUID()}`)
  await expect(offlinePage.getByRole('heading', { name: "You're offline" })).toBeVisible()
  await context.setOffline(false)
})

test('never persists synthetic owner API or PDF responses in the active worker cache', async ({ page, context }, testInfo) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  await page.evaluate(() => navigator.serviceWorker.ready)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
  const observed = await page.evaluate(async () => {
    const results = []
    for (const owner of ['alpha', 'beta']) {
      for (const path of ['/api/pwa-acceptance/private', '/api/pwa-acceptance/private.pdf']) {
        const response = await fetch(path, { headers: { 'X-Test-Owner': owner } })
        results.push({ owner, path, status: response.status, body: await response.text() })
      }
    }
    const urls = (await Promise.all((await caches.keys()).map(async name =>
      (await (await caches.open(name)).keys()).map(request => request.url)))).flat()
    const unsigned = await fetch('/api/pwa-acceptance/private')
    return { results, urls, unsignedStatus: unsigned.status }
  })
  expect(observed.results).toHaveLength(4)
  for (const result of observed.results) {
    expect(result.status).toBe(200)
    expect(result.body).toContain(result.owner)
  }
  expect(observed.urls.filter(url => new URL(url).pathname.startsWith('/api/'))).toEqual([])
  expect(observed.unsignedStatus).toBe(401)
  await context.setOffline(true)
  const replay = await page.evaluate(async () => {
    try {
      const response = await fetch('/api/pwa-acceptance/private', { headers: { 'X-Test-Owner': 'beta' } })
      return { replayed: response.ok, body: await response.text() }
    } catch { return { replayed: false, body: '' } }
  })
  expect(replay.replayed).toBe(false)
  expect(replay.body).not.toContain('Synthetic private')
  await context.setOffline(false)
  await testInfo.attach('synthetic-private-cache.json', { body: JSON.stringify({ cachedApiUrls: [], requestCount: observed.results.length + 1, unsignedStatus: observed.unsignedStatus, offlineReplay: replay.replayed }), contentType: 'application/json' })
})
