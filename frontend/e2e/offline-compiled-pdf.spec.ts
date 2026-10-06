import { expect, test } from '@playwright/test'

const RESUME_ID = 'ffffffff-ffff-ffff-ffff-ffffffffffff'

async function seedOfflinePdf(page: import('@playwright/test').Page, ownerId: string, resumeId: string): Promise<void> {
  await page.evaluate(async ({ ownerId, resumeId }) => {
    const request = indexedDB.open('latexy-offline', 3)
    await new Promise<void>((resolve, reject) => {
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains('drafts')) {
          const drafts = db.createObjectStore('drafts', { keyPath: 'key' })
          drafts.createIndex('by-status', 'syncStatus')
          drafts.createIndex('by-owner', 'ownerId')
        }
        if (!db.objectStoreNames.contains('compiled-pdfs')) {
          const pdfs = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
          pdfs.createIndex('by-owner', 'ownerId')
          pdfs.createIndex('by-accessed', 'lastAccessedAt')
        }
      }
      request.onsuccess = () => {
        const db = request.result
        const tx = db.transaction('compiled-pdfs', 'readwrite')
        tx.objectStore('compiled-pdfs').put({
          key: JSON.stringify([ownerId, resumeId]),
          ownerId,
          resumeId,
          title: 'Offline Resume',
          pdf: new Blob(['%PDF-1.4 offline fixture'], { type: 'application/pdf' }),
          byteSize: 24,
          savedAt: Date.now(),
          lastAccessedAt: Date.now(),
        })
        tx.oncomplete = () => resolve()
        tx.onerror = () => reject(tx.error)
      }
      request.onerror = () => reject(request.error)
    })
  }, { ownerId, resumeId })
  await page.evaluate((ownerId) => localStorage.setItem('latexy:last-authenticated-owner', ownerId), ownerId)
}

async function prepareControlledEditor(page: import('@playwright/test').Page, ownerId: string): Promise<void> {
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session: { token: `offline-token-${ownerId}` }, user: { id: ownerId, email: `${ownerId}@example.com`, name: ownerId } }),
  }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ id: RESUME_ID, user_id: ownerId, title: 'Offline Resume', latex_content: 'offline source', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', document_type: 'resume', metadata: {} }),
  }))
  await page.route((url) => url.pathname.startsWith('/analytics') || url.pathname === '/trial/status' || url.pathname === '/resumes/stats' || url.pathname.includes('/checkpoints') || url.pathname.includes('/interview-prep'), (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/ws/**', (route) => route.abort())
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
  await page.evaluate(async () => navigator.serviceWorker.ready)
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
  await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
}

test.describe('offline compiled PDF reader', () => {
  test('restores the owner-scoped latest PDF after a cold offline reload and uses download fallback', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    // Establish the authenticated editor online so the production service
    // worker is installed before the offline navigation. Only the owner marker
    // and the explicit IndexedDB PDF are reused; the document/API/PDF itself is
    // never put in a service-worker cache.
    await prepareControlledEditor(page, 'offline-owner')
    await seedOfflinePdf(page, 'offline-owner', RESUME_ID)

    // This is the real cold navigation: keep the installed worker registered,
    // make the network unavailable, and let its NetworkOnly document route
    // serve public/offline.html. No private HTML/API/PDF response is replayed.
    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByText('Offline saved PDF', { exact: true })).toBeVisible({ timeout: 30_000 })
    const downloadButton = offlinePage.getByRole('link', { name: 'Download PDF', exact: true })
    await expect(downloadButton).toBeVisible()

    const download = offlinePage.waitForEvent('download')
    await downloadButton.click()
    expect((await download).suggestedFilename()).toBe('Offline_Resume.pdf')
    await context.setOffline(false)
  })

  test('hides a stale PDF when the remembered owner changes during cold fallback loading', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    await prepareControlledEditor(page, 'offline-owner-a')
    await seedOfflinePdf(page, 'offline-owner-a', RESUME_ID)
    await context.setOffline(true)

    const offlinePage = await context.newPage()
    // Hold the exact-IDB read long enough for the other page to switch the
    // remembered owner. This exercises the fallback's generation/owner guard,
    // not a document replacement or a test-only private HTML replay.
    await offlinePage.addInitScript(() => {
      const get = IDBObjectStore.prototype.get
      const descriptor = Object.getOwnPropertyDescriptor(IDBRequest.prototype, 'onsuccess')
      if (!descriptor?.set) return
      IDBObjectStore.prototype.get = function (key: IDBValidKey | IDBKeyRange) {
        const request = get.call(this, key)
        let handler: ((event: Event) => void) | null = null
        Object.defineProperty(request, 'onsuccess', {
          configurable: true,
          get: () => handler,
          set: (next: ((event: Event) => void) | null) => {
            handler = next
            descriptor.set?.call(request, next ? (event: Event) => setTimeout(() => next.call(request, event), 750) : null)
          },
        })
        return request
      }
    })
    await offlinePage.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => localStorage.setItem('latexy:last-authenticated-owner', 'offline-owner-b'))
    await expect(offlinePage.getByText('Latexy could not find a saved PDF for this resume on this device.', { exact: true })).toBeVisible({ timeout: 5_000 })
    await expect(offlinePage.getByRole('link', { name: 'Download PDF', exact: true })).toHaveCount(0)
    await context.setOffline(false)
  })

  test('hides the reader when storage is cleared after it has shown a PDF', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    await prepareControlledEditor(page, 'offline-owner')
    await seedOfflinePdf(page, 'offline-owner', RESUME_ID)
    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByText('Offline saved PDF', { exact: true })).toBeVisible({ timeout: 30_000 })
    await page.evaluate(() => localStorage.clear())
    await expect(offlinePage.getByText('Latexy could not find a saved PDF for this resume on this device.', { exact: true })).toBeVisible({ timeout: 5_000 })
    await expect(offlinePage.getByRole('link', { name: 'Download PDF', exact: true })).toHaveCount(0)
    await context.setOffline(false)
  })

  test('rejects malformed and oversized cached PDFs without exposing them', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    await prepareControlledEditor(page, 'offline-owner')
    await seedOfflinePdf(page, 'offline-owner', RESUME_ID)
    await page.evaluate(async ({ resumeId }) => {
      const request = indexedDB.open('latexy-offline')
      await new Promise<void>((resolve, reject) => {
        request.onsuccess = () => {
          const tx = request.result.transaction('compiled-pdfs', 'readwrite')
          tx.objectStore('compiled-pdfs').put({ key: JSON.stringify(['offline-owner', resumeId]), ownerId: 'offline-owner', resumeId, title: 'Malformed', pdf: new Blob(['not-a-pdf']), byteSize: 9, savedAt: Date.now(), lastAccessedAt: Date.now() })
          tx.oncomplete = () => resolve()
          tx.onerror = () => reject(tx.error)
        }
        request.onerror = () => reject(request.error)
      })
    }, { resumeId: RESUME_ID })
    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByText('Latexy could not find a saved PDF for this resume on this device.', { exact: true })).toBeVisible({ timeout: 30_000 })

    await page.evaluate(async ({ resumeId }) => {
      const request = indexedDB.open('latexy-offline')
      await new Promise<void>((resolve, reject) => {
        request.onsuccess = () => {
          const tx = request.result.transaction('compiled-pdfs', 'readwrite')
          const bytes = new Uint8Array(5 * 1024 * 1024 + 1)
          bytes.set([37, 80, 68, 70, 45])
          tx.objectStore('compiled-pdfs').put({ key: JSON.stringify(['offline-owner', resumeId]), ownerId: 'offline-owner', resumeId, title: 'Oversized', pdf: new Blob([bytes], { type: 'application/pdf' }), byteSize: bytes.byteLength, savedAt: Date.now(), lastAccessedAt: Date.now() })
          tx.oncomplete = () => resolve()
          tx.onerror = () => reject(tx.error)
        }
        request.onerror = () => reject(request.error)
      })
    }, { resumeId: RESUME_ID })
    await offlinePage.reload({ waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByText('Latexy could not find a saved PDF for this resume on this device.', { exact: true })).toBeVisible({ timeout: 30_000 })
    await context.setOffline(false)
  })

  test('does not execute HTML from a PDF-header cached Blob', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    await prepareControlledEditor(page, 'offline-owner')
    await page.evaluate(async ({ resumeId }) => {
      const request = indexedDB.open('latexy-offline')
      await new Promise<void>((resolve, reject) => {
        request.onsuccess = () => {
          const tx = request.result.transaction('compiled-pdfs', 'readwrite')
          const payload = '%PDF-1.7\n<script>parent.postMessage("latexy-pdf-script", "*")</script>'
          tx.objectStore('compiled-pdfs').put({
            key: JSON.stringify(['offline-owner', resumeId]),
            ownerId: 'offline-owner',
            resumeId,
            title: 'Untrusted MIME',
            pdf: new Blob([payload], { type: 'text/html' }),
            byteSize: new Blob([payload]).size,
            savedAt: Date.now(),
            lastAccessedAt: Date.now(),
          })
          tx.oncomplete = () => resolve()
          tx.onerror = () => reject(tx.error)
        }
        request.onerror = () => reject(request.error)
      })
      localStorage.setItem('latexy:last-authenticated-owner', 'offline-owner')
    }, { resumeId: RESUME_ID })
    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.addInitScript(() => {
      ;(window as Window & { __latexyPdfScriptExecuted?: boolean }).__latexyPdfScriptExecuted = false
      window.addEventListener('message', (event) => {
        if (event.data === 'latexy-pdf-script') {
          ;(window as Window & { __latexyPdfScriptExecuted?: boolean }).__latexyPdfScriptExecuted = true
        }
      })
    })
    await offlinePage.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByText('Offline saved PDF', { exact: true })).toBeVisible({ timeout: 30_000 })
    await offlinePage.waitForTimeout(500)
    expect(await offlinePage.evaluate(() => Boolean((window as Window & { __latexyPdfScriptExecuted?: boolean }).__latexyPdfScriptExecuted))).toBe(false)
    await context.setOffline(false)
  })

  test('does not create a partial v3 database when no offline store exists', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    await page.goto('/', { waitUntil: 'networkidle' })
    await page.evaluate(async () => {
      localStorage.setItem('latexy:last-authenticated-owner', 'offline-owner')
      await new Promise<void>((resolve, reject) => {
        const request = indexedDB.deleteDatabase('latexy-offline')
        request.onsuccess = () => resolve()
        request.onerror = () => reject(request.error)
        request.onblocked = () => reject(new Error('offline database deletion was blocked'))
      })
    })
    await page.evaluate(async () => navigator.serviceWorker.ready)
    await page.reload({ waitUntil: 'networkidle' })
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByRole('heading', { name: "You're offline" })).toBeVisible({ timeout: 30_000 })
    const databaseNames = await page.evaluate(async () => (await indexedDB.databases()).filter((database) => database.name === 'latexy-offline'))
    expect(databaseNames).toEqual([])
    await context.setOffline(false)
  })

  test('handles malformed workspace route encoding without crashing the fallback', async ({ page, context }) => {
    test.skip(process.env.PWA_PRODUCTION !== '1', 'cold app-shell reload requires the production service worker')
    await page.goto('/', { waitUntil: 'networkidle' })
    await page.evaluate(async () => navigator.serviceWorker.ready)
    await page.reload({ waitUntil: 'networkidle' })
    await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller))
    await context.setOffline(true)
    const offlinePage = await context.newPage()
    await offlinePage.goto('/workspace/%E0%A4%A/edit', { waitUntil: 'domcontentloaded' })
    await expect(offlinePage.getByRole('heading', { name: "You're offline" })).toBeVisible({ timeout: 30_000 })
    await context.setOffline(false)
  })

  test('logout clears the owner marker and cached PDFs', async ({ page }) => {
    await page.route('**/api/auth/get-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session: { token: 'offline-token' }, user: { id: 'offline-owner', email: 'offline@example.com', name: 'Offline User' } }),
    }))
    await page.route('**/api/auth/sign-out**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await page.evaluate(() => {
      localStorage.setItem('latexy:last-authenticated-owner', 'offline-owner')
      const request = indexedDB.open('latexy-offline', 3)
      request.onupgradeneeded = () => {
        const db = request.result
        if (!db.objectStoreNames.contains('drafts')) {
          const drafts = db.createObjectStore('drafts', { keyPath: 'key' })
          drafts.createIndex('by-status', 'syncStatus')
          drafts.createIndex('by-owner', 'ownerId')
        }
        if (!db.objectStoreNames.contains('compiled-pdfs')) {
          const pdfs = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
          pdfs.createIndex('by-owner', 'ownerId')
          pdfs.createIndex('by-accessed', 'lastAccessedAt')
        }
      }
      request.onsuccess = () => {
        const db = request.result
        const tx = db.transaction('compiled-pdfs', 'readwrite')
        tx.objectStore('compiled-pdfs').put({ key: JSON.stringify(['offline-owner', 'r1']), ownerId: 'offline-owner', resumeId: 'r1', title: 'R', pdf: new Blob(['%PDF-1.4 x']), byteSize: 10, savedAt: Date.now(), lastAccessedAt: Date.now() })
      }
    })
    await page.getByRole('button', { name: 'Open account menu' }).click()
    await page.getByRole('menuitem', { name: 'Sign Out' }).click()
    await expect(page).toHaveURL(/\/$/, { timeout: 10_000 })
    await expect.poll(() => page.evaluate(async () => {
      const owner = localStorage.getItem('latexy:last-authenticated-owner')
      const request = indexedDB.open('latexy-offline', 3)
      const count = await new Promise<number>((resolve) => {
        request.onsuccess = () => {
          const tx = request.result.transaction('compiled-pdfs', 'readonly')
          const get = tx.objectStore('compiled-pdfs').count()
          get.onsuccess = () => resolve(get.result)
          get.onerror = () => resolve(-1)
        }
        request.onerror = () => resolve(-1)
      })
      return { owner, count }
    })).toEqual({ owner: null, count: 0 })
  })

  test('account switch purges old drafts and reconnect only flushes the current owner', async ({ page }) => {
    let owner = 'offline-owner-a'
    const flushedResumeIds: string[] = []
    await page.route('**/api/auth/get-session', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ session: { token: `token-${owner}` }, user: { id: owner, email: `${owner}@example.com`, name: owner } }),
    }))
    await page.route((url) => url.pathname.startsWith('/resumes/'), async (route) => {
      const routedResumeId = route.request().url().split('/resumes/')[1].split('?')[0]
      if (route.request().method() === 'PUT') {
        flushedResumeIds.push(routedResumeId)
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      }
      // Legacy offline rows without a base snapshot are conflict-checked
      // against the current server source before they may be flushed.
      if (route.request().method() === 'GET' && routedResumeId === 'resume-b') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'resume-b', user_id: owner, title: 'B', latex_content: 'B' }),
        })
      }
      if (route.request().method() !== 'GET' || routedResumeId !== RESUME_ID) {
        return route.continue()
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: RESUME_ID,
          user_id: owner,
          title: 'Offline Resume',
          latex_content: 'offline source',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          document_type: 'resume',
          metadata: {},
        }),
      })
    })
    await page.route('**/ws/**', (route) => route.abort())

    await page.goto('/platform', { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible()
    await page.evaluate(async () => {
      const request = indexedDB.open('latexy-offline', 3)
      await new Promise<void>((resolve, reject) => {
        request.onsuccess = () => {
          const db = request.result
          const tx = db.transaction('drafts', 'readwrite')
          tx.objectStore('drafts').put({ key: JSON.stringify(['offline-owner-a', 'resume-a']), ownerId: 'offline-owner-a', resumeId: 'resume-a', title: 'A', latexContent: 'A', savedAt: new Date(), syncStatus: 'pending' })
          tx.objectStore('drafts').put({ key: JSON.stringify(['offline-owner-b', 'resume-b']), ownerId: 'offline-owner-b', resumeId: 'resume-b', title: 'B', latexContent: 'B', savedAt: new Date(), syncStatus: 'pending' })
          tx.oncomplete = () => { db.close(); resolve() }
          tx.onerror = () => reject(tx.error)
        }
        request.onerror = () => reject(request.error)
      })
    })

    owner = 'offline-owner-b'
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('button', { name: 'Open account menu' })).toBeVisible()
    await expect.poll(() => page.evaluate(async () => {
      const request = indexedDB.open('latexy-offline', 3)
      return await new Promise<string[]>((resolve) => {
        request.onsuccess = () => {
          const db = request.result
          const tx = db.transaction('drafts', 'readonly')
          const get = tx.objectStore('drafts').getAll()
          get.onsuccess = () => { db.close(); resolve(get.result.map((item) => item.ownerId)) }
          get.onerror = () => resolve([])
        }
        request.onerror = () => resolve([])
      })
    })).toEqual(['offline-owner-b'])

    // Seed both owners after B is confirmed, then exercise the editor's
    // reconnect path. Its owner-scoped query must submit B only.
    await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText('LaTeX editor').first()).toBeVisible({ timeout: 30_000 })
    await page.evaluate(async () => {
      const request = indexedDB.open('latexy-offline', 3)
      await new Promise<void>((resolve, reject) => {
        request.onsuccess = () => {
          const db = request.result
          const tx = db.transaction('drafts', 'readwrite')
          tx.objectStore('drafts').put({ key: JSON.stringify(['offline-owner-a', 'resume-a']), ownerId: 'offline-owner-a', resumeId: 'resume-a', title: 'A', latexContent: 'A', savedAt: new Date(), syncStatus: 'pending' })
          tx.objectStore('drafts').put({ key: JSON.stringify(['offline-owner-b', 'resume-b']), ownerId: 'offline-owner-b', resumeId: 'resume-b', title: 'B', latexContent: 'B', savedAt: new Date(), syncStatus: 'pending' })
          tx.oncomplete = () => { db.close(); resolve() }
          tx.onerror = () => reject(tx.error)
        }
        request.onerror = () => reject(request.error)
      })
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: false })
      window.dispatchEvent(new Event('offline'))
      await new Promise((resolve) => setTimeout(resolve, 250))
      Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
      window.dispatchEvent(new Event('online'))
    })
    await expect.poll(() => page.evaluate(async () => {
      const request = indexedDB.open('latexy-offline', 3)
      return await new Promise<string[]>((resolve) => {
        request.onsuccess = () => {
          const db = request.result
          const tx = db.transaction('drafts', 'readonly')
          const get = tx.objectStore('drafts').getAll()
          get.onsuccess = () => { db.close(); resolve(get.result.filter((item) => item.syncStatus === 'pending').map((item) => item.ownerId)) }
          get.onerror = () => resolve([])
        }
        request.onerror = () => resolve([])
      })
    })).toEqual(['offline-owner-a'])
    expect(flushedResumeIds.length).toBeGreaterThan(0)
    expect(flushedResumeIds.every((resumeId) => resumeId === 'resume-b')).toBe(true)
  })
})
