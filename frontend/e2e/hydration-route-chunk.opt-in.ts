import { expect, test, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { installMockWorkboxRegistration } from './helpers/mock-workbox-registration'

test.use({ serviceWorkers: 'block', locale: 'en-US' })
test.setTimeout(90_000)
// The shared Workbox shim below prevents blocked-service-worker API shape
// errors; this diagnostic does not exercise real service-worker/PWA lifecycle.

const SETTINGS_CHUNK = /\/_next\/static\/chunks\/app\/settings\/page-[^/]+\.js$/
const FIXTURE_OWNER = {
  id: 'hydration-fixture-owner',
  email: 'hydration-fixture@example.test',
  name: 'Hydration Fixture Owner',
}

type Arm = 'auth-first' | 'route-first'
type LocaleStorage = 'agree' | 'different'
type Observation = { atMs: number; event: string; details?: Record<string, unknown> }

function settingsApiResponse(path: string): Record<string, unknown> | null {
  if (path === '/me') {
    return { id: FIXTURE_OWNER.id, email: FIXTURE_OWNER.email, plan: 'free', role: 'user', preferences: { theme: 'light' } }
  }
  if (path === '/config/feature-flags') {
    return { trial_limits: true, deep_analysis_trial: true, compile_timeouts: true, task_priority: true, billing: true, upgrade_ctas: true }
  }
  if (path === '/config/entitlements') return { features: {} }
  if (path === '/settings/notifications') {
    return { job_completed: true, job_failed: true, share_viewed: false, weekly_digest: false, tracker_updates: true, comment_mentions: true }
  }
  if (path === '/github/status') return { connected: false, username: null, public_import: false, private_sync: false }
  if (path === '/zotero/status') return { connected: false, username: null, user_id: null }
  if (path === '/mendeley/status') return { connected: false, name: null }
  if (path === '/dropbox/status') return { connected: false, display_name: null, account_id: null }
  if (path === '/google-drive/status') return { connected: false, scope: null }
  if (path === '/tenants/current-context') return { tenant: null }
  if (path === '/tenants/resolve-host') return { tenant: null }
  if (path === '/trial/status') return { eligible: false, status: 'inactive' }
  return null
}

async function runBarrier(page: Page, arm: Arm, localeStorage: LocaleStorage) {
  const startedAt = Date.now()
  const observations: Observation[] = []
  const pageErrors: string[] = []
  const pageErrorDetails: Array<{ message: string; stack: string | null }> = []
  const unexpectedRequests: string[] = []
  let initialDocumentCaptured = false
  let initialHtmlReadCompleted = false
  let heldSettingsChunkCount = 0
  let heldSettingsChunkUrl: string | null = null
  let releaseSettingsChunk!: () => void
  let releaseAuthResponse!: () => void
  let resolveSettingsChunkRequest!: () => void
  let resolveAuthRequest!: () => void
  let resolveSettingsChunkResponse!: () => void
  let resolveInitialHtmlRead!: () => void

  const settingsChunkGate = new Promise<void>((resolve) => { releaseSettingsChunk = resolve })
  const authResponseGate = new Promise<void>((resolve) => { releaseAuthResponse = resolve })
  const settingsChunkRequested = new Promise<void>((resolve) => { resolveSettingsChunkRequest = resolve })
  const authRequested = new Promise<void>((resolve) => { resolveAuthRequest = resolve })
  const settingsChunkResponse = new Promise<void>((resolve) => { resolveSettingsChunkResponse = resolve })
  const initialHtmlRead = new Promise<void>((resolve) => { resolveInitialHtmlRead = resolve })
  const observe = (event: string, details?: Record<string, unknown>) => {
    observations.push({ atMs: Date.now() - startedAt, event, ...(details ? { details } : {}) })
  }

  page.on('pageerror', (error) => {
    pageErrors.push(error.message)
    pageErrorDetails.push({ message: error.message, stack: error.stack ?? null })
    observe('page-error', { message: error.message, stack: error.stack ?? null })
  })
  page.on('domcontentloaded', () => observe('dom-content-loaded'))
  page.on('response', (response) => {
    if (response.request().resourceType() === 'document' && !initialDocumentCaptured) {
      initialDocumentCaptured = true
      observe('initial-document-response', { status: response.status() })
      void response.text().then((html) => {
        observe('initial-server-html', {
          characters: html.length,
          sha256: createHash('sha256').update(html).digest('hex'),
          hasMainShell: /<main[^>]*id=["']main-content["']/.test(html),
          hasLoadingSettings: html.includes('Loading settings'),
          flightScriptCount: (html.match(/self\.__next_f\.push/g) ?? []).length,
        })
      }).catch((error: unknown) => {
        observe('initial-server-html-read-failed', { message: error instanceof Error ? error.message : String(error) })
      }).finally(() => {
        initialHtmlReadCompleted = true
        resolveInitialHtmlRead()
      })
    }
    if (heldSettingsChunkUrl && response.url() === heldSettingsChunkUrl) {
      observe('settings-route-chunk-response', { status: response.status() })
      resolveSettingsChunkResponse()
    }
  })

  await installMockWorkboxRegistration(page)
  await page.addInitScript((locale: string) => {
    localStorage.setItem('latexy-ui-locale', locale)
  }, localeStorage === 'agree' ? 'en' : 'hi')

  const appBaseUrl = new URL(test.info().project.use.baseURL as string)
  const appOrigin = appBaseUrl.origin
  const qualityPort = Number(process.env.PLAYWRIGHT_QUALITY_PORT || appBaseUrl.port || 5182)
  const backendUrl = process.env.PLAYWRIGHT_API_URL
    ?? process.env.PLAYWRIGHT_BACKEND_URL
    ?? `http://127.0.0.1:${qualityPort + 2000}`
  const backendOrigin = new URL(backendUrl).origin
  await page.routeWebSocket('**/*', (socket) => {
    observe('websocket-blocked')
    socket.close()
  })
  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname

    if (url.origin === appOrigin && request.method() === 'GET' && request.resourceType() === 'script' && SETTINGS_CHUNK.test(pathname)) {
      heldSettingsChunkCount += 1
      heldSettingsChunkUrl = url.href
      observe('settings-route-chunk-request-held', { count: heldSettingsChunkCount, pathname })
      resolveSettingsChunkRequest()
      await settingsChunkGate
      await route.continue()
      observe('settings-route-chunk-released', { count: heldSettingsChunkCount })
      return
    }

    if (url.origin === appOrigin && request.method() === 'GET' && pathname === '/api/auth/get-session') {
      observe('auth-session-request-held', { method: request.method() })
      resolveAuthRequest()
      await authResponseGate
      await route.fulfill({
        json: {
          session: { id: 'hydration-fixture-session', token: 'synthetic-hydration-token', userId: FIXTURE_OWNER.id },
          user: FIXTURE_OWNER,
        },
      })
      observe('auth-session-response-fulfilled')
      return
    }

    if (url.origin === appOrigin && request.method() === 'GET' && pathname === '/api/auth/passkey/list-user-passkeys') {
      observe('synthetic-api-response', { method: request.method(), pathname })
      await route.fulfill({ json: [] })
      return
    }

    if (url.origin === appOrigin && request.method() === 'GET' && pathname === '/api/referral') {
      observe('synthetic-api-response', { method: request.method(), pathname })
      await route.fulfill({
        json: {
          available: false,
          scope: 'personal',
          message: 'Referrals unavailable in this synthetic browser fixture.',
          share_code: null,
          your_attribution: null,
          referral_summary: { total: 0, captured: 0, qualified: 0, reversed: 0 },
          reward_summary: { issued: 0, pending: 0, reversed: 0, issued_extension_days: 0 },
          policy_configured: false,
        },
      })
      return
    }

    const syntheticGet = url.origin === backendOrigin && request.method() === 'GET' ? settingsApiResponse(pathname) : null
    if (syntheticGet !== null) {
      observe('synthetic-api-response', { method: request.method(), pathname })
      await route.fulfill({ json: syntheticGet })
      return
    }
    if ((url.origin === appOrigin || url.origin === backendOrigin) && pathname === '/telemetry/frontend' && request.method() === 'POST') {
      observe('synthetic-telemetry-response', { method: request.method(), pathname })
      await route.fulfill({ status: 204, body: '' })
      return
    }

    const isAllowedShellGet = url.origin === appOrigin
      && request.method() === 'GET'
      && !pathname.startsWith('/api/')
    if (isAllowedShellGet) {
      await route.continue()
      return
    }

    unexpectedRequests.push(`${request.method()} ${url.origin}${pathname}`)
    observe('unexpected-request-aborted', { method: request.method(), origin: url.origin, pathname })
    await route.abort()
  })

  try {
    await page.goto('/settings', { waitUntil: 'domcontentloaded' })
    await Promise.all([authRequested, settingsChunkRequested, initialHtmlRead])
    const initialDom = await page.evaluate(() => ({
      headerText: document.querySelector('header')?.innerText ?? '',
      mainText: document.querySelector<HTMLElement>('#main-content')?.innerText ?? '',
    }))
    observe('initial-dom-snapshot', initialDom)

    if (arm === 'auth-first') {
      releaseAuthResponse()
      observe('auth-first-release-requested')
      const accountTrigger = page.locator('header button[aria-haspopup="menu"]')
      await expect(accountTrigger).toBeVisible()
      await expect(accountTrigger).toContainText('Hydration')
      await accountTrigger.click()
      await expect(page.getByRole('menu').getByText(FIXTURE_OWNER.email)).toBeVisible()
      observe('authenticated-owner-observed-in-root-header-before-route-release')
      await page.keyboard.press('Escape')
      const beforeRouteRelease = await page.evaluate(() => ({
        headerText: document.querySelector('header')?.innerText ?? '',
        mainText: document.querySelector<HTMLElement>('#main-content')?.innerText ?? '',
      }))
      observe('auth-first-dom-before-route-release', beforeRouteRelease)
      releaseSettingsChunk()
      observe('auth-first-route-release-requested')
    } else {
      releaseSettingsChunk()
      observe('route-first-route-release-requested')
      await settingsChunkResponse
      await page.waitForLoadState('load')
      const settingsContentHydrated = await page.waitForFunction(() => {
        const main = document.querySelector('#main-content')
        if (!main) return false
        const nodes = Array.from(main.querySelectorAll<HTMLElement>('*'))
        const loadingNode = nodes.find((node) => node.innerText.trim() === 'Loading settings…')
        if (!loadingNode) return false
        return Object.getOwnPropertyNames(loadingNode).some((key) => key.startsWith('__reactProps$') || key.startsWith('__reactFiber$'))
      }, undefined, { timeout: 12_000 }).then(() => true).catch(() => false)
      if (!settingsContentHydrated) {
        throw new Error('Barrier precondition failed: could not observe React ownership on the settings loading node while auth remained held')
      }
      observe('settings-route-react-owned-node-observed-before-auth-release')
      const beforeAuthRelease = await page.evaluate(() => ({
        headerText: document.querySelector('header')?.innerText ?? '',
        mainText: document.querySelector<HTMLElement>('#main-content')?.innerText ?? '',
      }))
      observe('route-first-dom-before-auth-release', beforeAuthRelease)
      releaseAuthResponse()
      observe('route-first-auth-release-requested')
    }

    await expect(page.locator('header button[aria-haspopup="menu"]')).toContainText('Hydration')
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
    await expect.poll(() => heldSettingsChunkCount).toBe(1)
    await expect.poll(() => unexpectedRequests).toEqual([])
    await expect.poll(() => pageErrors).toEqual([])
    observe('final-dom-snapshot', await page.evaluate(() => ({
      headerText: document.querySelector('header')?.innerText ?? '',
      mainText: document.querySelector<HTMLElement>('#main-content')?.innerText ?? '',
    })))
  } finally {
    releaseAuthResponse()
    releaseSettingsChunk()
    if (!initialDocumentCaptured) {
      observe('initial-server-html-not-captured')
    } else {
      let htmlReadTimer: ReturnType<typeof setTimeout> | undefined
      await Promise.race([
        initialHtmlRead,
        new Promise<void>((resolve) => {
          htmlReadTimer = setTimeout(() => {
            observe('initial-server-html-read-timeout')
            resolve()
          }, 2_000)
        }),
      ])
      if (htmlReadTimer !== undefined) clearTimeout(htmlReadTimer)
      if (initialHtmlReadCompleted) observe('initial-server-html-read-completed')
    }
    await test.info().attach('hydration-route-chunk-timeline', {
      body: Buffer.from(JSON.stringify({ arm, localeStorage, heldSettingsChunkCount, heldSettingsChunkUrl, observations, pageErrors, pageErrorDetails, unexpectedRequests }, null, 2)),
      contentType: 'application/json',
    })
  }
}

for (const localeStorage of ['agree', 'different'] as const) {
  test(`settings auth-first route-chunk barrier with ${localeStorage} locale storage`, async ({ page }) => {
    await runBarrier(page, 'auth-first', localeStorage)
  })
  test(`settings route-first auth barrier with ${localeStorage} locale storage`, async ({ page }) => {
    await runBarrier(page, 'route-first', localeStorage)
  })
}
