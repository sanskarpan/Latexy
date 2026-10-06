import { expect, test } from '@playwright/test'

const OWNER = 'local-upload-race-owner'
const TOKEN = 'local-upload-race-token'
const CREATED_ID = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
const CONTENT_A = '\\documentclass{article}\\begin{document}OLDER-A\\end{document}'
const CONTENT_B = '\\documentclass{article}\\begin{document}LATEST-B\\end{document}'

function session() {
  return {
    session: { id: 'session-local-upload-race', userId: OWNER, token: TOKEN, expiresAt: '2099-01-01T00:00:00Z' },
    user: { id: OWNER, email: `${OWNER}@example.invalid`, name: OWNER },
  }
}

async function mockNewResume(page: import('@playwright/test').Page) {
  const createBodies: Array<Record<string, unknown>> = []

  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session()) }))
  await page.route((url) => url.pathname === '/templates' || url.pathname === '/templates/', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/templates/categories', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.route((url) => url.pathname === '/config/feature-flags', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: OWNER, role: 'user' }),
    }))
  await page.route((url) => url.pathname === '/entitlements', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ features: {} }) }))
  await page.route((url) => url.pathname === '/resumes/' && url.pathname.endsWith('/'), async (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const body = route.request().postDataJSON() as Record<string, unknown>
    createBodies.push(body)
    return route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        id: CREATED_ID,
        user_id: OWNER,
        title: body.title,
        latex_content: body.latex_content,
        is_template: false,
      }),
    })
  })
  await page.route('**/ws/**', (route) => route.abort())
  return createBodies
}

async function installDeferredTexReads(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    const pending = new Map<string, Array<{ resolve: (content: string) => void; reject: (error: Error) => void }>>()
    const browserWindow = window as Window & {
      __releaseLocalTexRead?: (name: string, content: string) => void
      __rejectLocalTexRead?: (name: string) => void
    }
    browserWindow.__releaseLocalTexRead = (name, content) => {
      const read = pending.get(name)?.shift()
      if (!read) throw new Error(`No deferred read for ${name}`)
      read.resolve(content)
    }
    browserWindow.__rejectLocalTexRead = (name) => {
      const read = pending.get(name)?.shift()
      if (!read) throw new Error(`No deferred read for ${name}`)
      read.reject(new Error(`Synthetic read failure for ${name}`))
    }
    File.prototype.text = function text() {
      return new Promise<string>((resolve, reject) => {
        const reads = pending.get(this.name) ?? []
        reads.push({ resolve, reject })
        pending.set(this.name, reads)
      })
    }
  })
}

async function releaseTexRead(page: import('@playwright/test').Page, name: string, content: string) {
  await page.evaluate(({ fileName, fileContent }) => {
    const browserWindow = window as Window & {
      __releaseLocalTexRead?: (name: string, content: string) => void
    }
    browserWindow.__releaseLocalTexRead?.(fileName, fileContent)
  }, { fileName: name, fileContent: content })
}

async function rejectTexRead(page: import('@playwright/test').Page, name: string) {
  await page.evaluate((fileName) => {
    const browserWindow = window as Window & {
      __rejectLocalTexRead?: (name: string) => void
    }
    browserWindow.__rejectLocalTexRead?.(fileName)
  }, name)
}

async function selectLocalTex(page: import('@playwright/test').Page, name: string) {
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: 'application/x-tex',
    buffer: Buffer.from('deferred browser fixture'),
  })
}

async function clearPendingFile(page: import('@playwright/test').Page, name: string) {
  const reading = page.getByText(`Reading ${name}`)
  if (await reading.count()) {
    await expect(reading).toBeVisible()
    await page.getByRole('button', { name: 'Clear uploaded file' }).click()
  } else {
    // The sealed pre-fix bundle reports a direct read as loaded immediately;
    // retain this fallback only so the same diagnostic can go red there.
    const loaded = page.getByText('LaTeX file loaded')
    await expect(loaded).toBeVisible()
    await loaded.locator('xpath=ancestor::div[.//button][1]').getByRole('button').click()
  }
  await expect(page.locator('input[type="file"]')).toBeAttached()
}

async function settleClient(page: import('@playwright/test').Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
}

async function prepareImport(page: import('@playwright/test').Page) {
  await page.goto('/workspace/new', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('input[placeholder*="Senior Backend"]')).toBeVisible()
  await page.getByRole('heading', { name: 'Import File' }).click()
  await expect(page.locator('input[type="file"]')).toBeAttached()
}

test.describe('local LaTeX read ordering', () => {
  test('keeps the latest file when the older read resolves first', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installDeferredTexReads(page)
    const createBodies = await mockNewResume(page)
    await prepareImport(page)

    await selectLocalTex(page, 'local-a.tex')
    await clearPendingFile(page, 'local-a.tex')
    await selectLocalTex(page, 'local-b.tex')
    await releaseTexRead(page, 'local-a.tex', CONTENT_A)
    await releaseTexRead(page, 'local-b.tex', CONTENT_B)
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()

    await page.locator('input[placeholder*="Senior Backend"]').fill('Latest file control')
    const response = page.waitForResponse((candidate) => candidate.url().endsWith('/resumes/') && candidate.request().method() === 'POST')
    await page.getByRole('button', { name: 'Create Resume' }).click()
    const settledResponse = await response
    expect(settledResponse.status()).toBe(201)
    await settledResponse.finished()
    expect(createBodies[createBodies.length - 1]?.latex_content).toBe(CONTENT_B)
    expect(pageErrors).toEqual([])
  })

  test('ignores a later completion from an older cleared selection', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installDeferredTexReads(page)
    const createBodies = await mockNewResume(page)
    await prepareImport(page)

    await selectLocalTex(page, 'local-a.tex')
    await clearPendingFile(page, 'local-a.tex')
    await selectLocalTex(page, 'local-b.tex')
    await releaseTexRead(page, 'local-b.tex', CONTENT_B)
    await releaseTexRead(page, 'local-a.tex', CONTENT_A)
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()

    await page.locator('input[placeholder*="Senior Backend"]').fill('Stale read diagnostic')
    const response = page.waitForResponse((candidate) => candidate.url().endsWith('/resumes/') && candidate.request().method() === 'POST')
    await page.getByRole('button', { name: 'Create Resume' }).click()
    const settledResponse = await response
    expect(settledResponse.status()).toBe(201)
    await settledResponse.finished()
    expect(createBodies[createBodies.length - 1]?.latex_content).toBe(CONTENT_B)
    expect(pageErrors).toEqual([])
  })

  test('clear-only prevents a pending local read from restoring content', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installDeferredTexReads(page)
    await mockNewResume(page)
    await prepareImport(page)

    await selectLocalTex(page, 'local-a.tex')
    await clearPendingFile(page, 'local-a.tex')
    await releaseTexRead(page, 'local-a.tex', CONTENT_A)
    await settleClient(page)
    expect(await page.getByText(/File parsed — \d[\d,]* characters ready/).count()).toBe(0)
    expect(pageErrors).toEqual([])
  })

  test('rejected old local reads do not surface an error after clear', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installDeferredTexReads(page)
    await mockNewResume(page)
    await prepareImport(page)

    await selectLocalTex(page, 'local-a.tex')
    await clearPendingFile(page, 'local-a.tex')
    await rejectTexRead(page, 'local-a.tex')
    await settleClient(page)
    expect(await page.getByText('Error reading LaTeX file').count()).toBe(0)
    expect(pageErrors).toEqual([])
  })

  test('unmounting the uploader ignores a pending read', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installDeferredTexReads(page)
    await mockNewResume(page)
    await prepareImport(page)

    await selectLocalTex(page, 'local-a.tex')
    await expect(page.getByText(/Reading local-a\.tex|LaTeX file loaded/)).toBeVisible()
    await page.getByRole('heading', { name: 'Use Template' }).click()
    await releaseTexRead(page, 'local-a.tex', CONTENT_A)
    await settleClient(page)
    await page.getByRole('heading', { name: 'Import File' }).click()
    expect(await page.getByText(/File parsed — \d[\d,]* characters ready/).count()).toBe(0)

    await selectLocalTex(page, 'local-b.tex')
    await releaseTexRead(page, 'local-b.tex', CONTENT_B)
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()
    expect(pageErrors).toEqual([])
  })

  test('accepts an ordinary local LaTeX file', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await installDeferredTexReads(page)
    const createBodies = await mockNewResume(page)
    await prepareImport(page)

    await selectLocalTex(page, 'local-a.tex')
    await releaseTexRead(page, 'local-a.tex', CONTENT_A)
    await expect(page.getByText(/File parsed — \d[\d,]* characters ready/)).toBeVisible()
    await page.locator('input[placeholder*="Senior Backend"]').fill('Ordinary local import')
    const response = page.waitForResponse((candidate) => candidate.url().endsWith('/resumes/') && candidate.request().method() === 'POST')
    await page.getByRole('button', { name: 'Create Resume' }).click()
    const settledResponse = await response
    expect(settledResponse.status()).toBe(201)
    await settledResponse.finished()
    expect(createBodies[createBodies.length - 1]?.latex_content).toBe(CONTENT_A)
    expect(pageErrors).toEqual([])
  })
})
