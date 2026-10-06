import { expect, test, type Page, type Route } from '@playwright/test'

const RESUME_ID = 'variant-race-resume'
const OWNER_A = 'variant-owner-a'
const OWNER_B = 'variant-owner-b'

type Owner = 'A' | 'B'
type OwnerState = { current: Owner; token?: string; sessionStatus?: number }
type VariantRouteState = Owner[] & { variantLoads: number }

const visibility = {
  hidden_sections: [],
  hidden_entries: {},
  hidden_list_items: {},
}

function variantResponse(owner: Owner) {
  const userId = owner === 'A' ? OWNER_A : OWNER_B
  return {
    resume: {
      id: RESUME_ID,
      user_id: userId,
      title: `${userId} variant`,
      latex_content: '\\documentclass{article}',
      is_template: false,
      tags: [],
      parent_resume_id: 'variant-race-master',
      variant_count: 0,
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-01T00:00:00Z',
      selected_template_id: 'variant-race-template',
      content_source: 'builder_variant',
      builder_status: 'active',
      structured_content: null,
      structured_version: 1,
      variant_visibility: visibility,
    },
    source_resume_id: 'variant-race-master',
    source_title: `${userId} master`,
    source_content: {
      basics: { name: userId, label: '', email: `${userId}@example.invalid`, phone: '', location: '', website: '', linkedin: '', github: '', summary: '' },
      experience: [], education: [], projects: [], skills: [], certifications: [], awards: [], languages: [], interests: [],
      section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'],
      hidden_sections: [],
    },
    effective_content: {
      basics: { name: userId, label: '', email: `${userId}@example.invalid`, phone: '', location: '', website: '', linkedin: '', github: '', summary: '' },
      experience: [], education: [], projects: [], skills: [], certifications: [], awards: [], languages: [], interests: [],
      section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'],
      hidden_sections: [],
    },
    visibility,
    metrics: { completeness_score: 100, page_estimate: 1, warnings: [], missing_sections: [] },
    preview: { template_family: 'minimal', sections: [] },
    template_family: 'minimal',
  }
}

async function settleClient(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  }))
}

async function mockVariant(
  page: Page,
  owner: OwnerState,
  onSave: (route: Route) => Promise<void>,
  onLoad?: (route: Route) => Promise<void>,
) {
  const sessionOwners = [] as unknown as VariantRouteState
  sessionOwners.variantLoads = 0
  await page.addInitScript(() => {
    const state = window as Window & { __variantSaveBodyReads?: number; __variantSessionBodyReads?: number }
    state.__variantSaveBodyReads = 0
    state.__variantSessionBodyReads = 0
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init)
      const request = input instanceof Request ? input : new Request(input, init)
      const path = new URL(request.url, window.location.href).pathname
      if (request.method.toUpperCase() === 'GET' && path.endsWith('/api/auth/get-session')) {
        const markSessionBodyRead = () => { state.__variantSessionBodyReads = (state.__variantSessionBodyReads ?? 0) + 1 }
        const originalJson = response.json.bind(response)
        const originalText = response.text.bind(response)
        response.json = async () => {
          const body = await originalJson()
          markSessionBodyRead()
          return body
        }
        response.text = async () => {
          const body = await originalText()
          markSessionBodyRead()
          return body
        }
        return response
      }
      if (request.method.toUpperCase() !== 'PATCH' || !path.endsWith('/variant-visibility')) return response
      const markBodyRead = () => { state.__variantSaveBodyReads = (state.__variantSaveBodyReads ?? 0) + 1 }
      const originalJson = response.json.bind(response)
      const originalText = response.text.bind(response)
      response.json = async () => {
        const body = await originalJson()
        markBodyRead()
        return body
      }
      response.text = async () => {
        const body = await originalText()
        markBodyRead()
        return body
      }
      return response
    }
  })
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url())
    const baseOrigin = new URL(test.info().project.use.baseURL!).origin
    if (route.request().method() === 'GET' && url.origin === baseOrigin && !url.pathname.startsWith('/api/')) {
      return route.continue()
    }
    return route.abort()
  })
  await page.route('**/api/auth/get-session', (route) => {
    sessionOwners.push(owner.current)
    const status = owner.sessionStatus ?? 200
    owner.sessionStatus = undefined
    const body = status === 200
      ? {
          session: { id: `variant-session-${owner.current}`, userId: owner.current === 'A' ? OWNER_A : OWNER_B, token: owner.token ?? `variant-token-${owner.current}` },
          user: { id: owner.current === 'A' ? OWNER_A : OWNER_B, email: `${owner.current}@example.invalid`, name: owner.current },
        }
      : { detail: 'Transient session refresh failed' }
    return route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })
  await page.route((url) => ['/config/feature-flags', '/config/entitlements'].includes(url.pathname), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"tenant":null}' }))
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/variant-visibility`, async (route) => {
    if (route.request().method() === 'PATCH') return onSave(route)
    sessionOwners.variantLoads += 1
    if (onLoad) return onLoad(route)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse(owner.current)) })
  })
  await page.route('**/ws/**', (route) => route.abort())
  return sessionOwners
}

async function waitForSaveBodyRead(page: Page) {
  await expect.poll(() => page.evaluate(() => (window as Window & { __variantSaveBodyReads?: number }).__variantSaveBodyReads ?? 0)).toBeGreaterThan(0)
  await settleClient(page)
}

async function waitForSessionBodyRead(page: Page, previousReads: number) {
  await expect.poll(() => page.evaluate(() => (window as Window & { __variantSessionBodyReads?: number }).__variantSessionBodyReads ?? 0)).toBeGreaterThan(previousReads)
  await settleClient(page)
}

async function notifySessionChange(page: Page) {
  await page.evaluate(() => {
    const message = JSON.stringify({ event: 'session', data: { trigger: 'variant-owner-race' } })
    localStorage.setItem('better-auth.message', message)
    window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
  })
}

async function switchOwner(page: Page, owner: OwnerState, next: Owner, sessionOwners: Owner[]) {
  const previousCalls = sessionOwners.length
  owner.current = next
  await notifySessionChange(page)
  await expect.poll(() => sessionOwners.length).toBeGreaterThan(previousCalls)
}

test.describe('linked variant owner save diagnostic', () => {
  test('initial visibility load failure can retry after the owner epoch is ready', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    const pageErrors: string[] = []
    let loadAttempts = 0
    page.on('pageerror', (error) => pageErrors.push(error.message))
    await mockVariant(
      page,
      owner,
      async (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) }),
      async (route) => {
        loadAttempts += 1
        if (loadAttempts === 1) {
          await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Initial visibility load failed' }) })
          return
        }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) })
      },
    )

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Linked variant could not be loaded' })).toBeVisible()
    await expect(page.locator('p[role="alert"]')).toContainText('HTTP 503')
    await page.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    expect(loadAttempts).toBe(2)
    expect(pageErrors).toEqual([])
  })

  test('same-owner token refresh preserves the edited draft without reloading variant data', async ({ page }) => {
    const owner: OwnerState = { current: 'A', token: 'variant-token-A-1' }
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const sessionOwners = await mockVariant(
      page,
      owner,
      async (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) }),
    )

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    const priorSessionReads = await page.evaluate(() => (window as Window & { __variantSessionBodyReads?: number }).__variantSessionBodyReads ?? 0)
    const priorVariantLoads = sessionOwners.variantLoads
    const priorSessionCalls = sessionOwners.length
    await page.getByLabel('Variant title').fill('A draft survives token refresh')

    owner.token = 'variant-token-A-2'
    await notifySessionChange(page)
    await expect.poll(() => sessionOwners.length).toBeGreaterThan(priorSessionCalls)
    await waitForSessionBodyRead(page, priorSessionReads)

    await expect(page.getByLabel('Variant title')).toHaveValue('A draft survives token refresh')
    expect(sessionOwners.variantLoads).toBe(priorVariantLoads)
    expect(pageErrors).toEqual([])
  })

  test('same-owner transient session failure and recovery preserve the edited draft', async ({ page }) => {
    const owner: OwnerState = { current: 'A', token: 'variant-token-A-1' }
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const sessionOwners = await mockVariant(
      page,
      owner,
      async (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) }),
    )

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A draft survives session retry')
    const priorVariantLoads = sessionOwners.variantLoads

    let priorSessionReads = await page.evaluate(() => (window as Window & { __variantSessionBodyReads?: number }).__variantSessionBodyReads ?? 0)
    let priorSessionCalls = sessionOwners.length
    owner.sessionStatus = 503
    await notifySessionChange(page)
    await expect.poll(() => sessionOwners.length).toBeGreaterThan(priorSessionCalls)
    await waitForSessionBodyRead(page, priorSessionReads)
    await expect(page.getByLabel('Variant title')).toHaveValue('A draft survives session retry')
    expect(sessionOwners.variantLoads).toBe(priorVariantLoads)

    priorSessionReads = await page.evaluate(() => (window as Window & { __variantSessionBodyReads?: number }).__variantSessionBodyReads ?? 0)
    priorSessionCalls = sessionOwners.length
    owner.sessionStatus = 200
    owner.token = 'variant-token-A-3'
    await notifySessionChange(page)
    await expect.poll(() => sessionOwners.length).toBeGreaterThan(priorSessionCalls)
    await waitForSessionBodyRead(page, priorSessionReads)
    await expect(page.getByLabel('Variant title')).toHaveValue('A draft survives session retry')
    expect(sessionOwners.variantLoads).toBe(priorVariantLoads)
    expect(pageErrors).toEqual([])
  })

  test('unmounted deferred rejection does not surface after leaving the variant page', async ({ page }) => {
    const owner: OwnerState = { current: 'A' }
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    let release!: () => void
    let saveStarted = false
    let saveSettled = false
    const gate = new Promise<void>((resolve) => { release = resolve })
    await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Unmounted variant save failed' }) })
      saveSettled = true
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A unmounted variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)

    await page.getByRole('link', { name: 'Advanced editor' }).click()
    await expect(page).toHaveURL(new RegExp(`/workspace/${RESUME_ID}/edit$`))
    release()
    await expect.poll(() => saveSettled).toBe(true)
    await settleClient(page)

    expect(pageErrors).toEqual([])
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Unmounted variant save failed' })).toHaveCount(0)
  })

  test('same-owner deferred visibility save completes normally', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    let release!: () => void
    let saveStarted = false
    const gate = new Promise<void>((resolve) => { release = resolve })
    const sessionOwners = await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) })
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: 'Choose what this variant includes' })).toBeVisible()
    await page.getByLabel('Variant title').fill('A saved variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)
    release()
    await waitForSaveBodyRead(page)
    await expect(page.getByText('Variant visibility saved')).toBeVisible()
    await settleClient(page)
    expect(pageErrors).toEqual([])
    expect(sessionOwners).toContain('A')
  })

  test('same-owner deferred rejection remains visible', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    let release!: () => void
    let saveStarted = false
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const gate = new Promise<void>((resolve) => { release = resolve })
    await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Same-owner visibility save failed' }) })
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A rejected variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)
    const saveResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'PATCH',
    )
    release()
    const completedSave = await saveResponse
    await completedSave.finished()
    await waitForSaveBodyRead(page)

    expect(pageErrors).toEqual([])
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Same-owner visibility save failed' })).toBeVisible()
  })

  test('deferred A rejection is not surfaced after the variant loads for B', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    let release!: () => void
    let saveStarted = false
    const gate = new Promise<void>((resolve) => { release = resolve })
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const sessionOwners = await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Owner A deferred save failed' }) })
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A pending variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)

    const bLoad = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'GET',
    )
    await switchOwner(page, owner, 'B', sessionOwners)
    const bResponse = await bLoad
    await bResponse.finished()
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_B} variant`)
    await settleClient(page)

    const saveResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'PATCH',
    )
    release()
    const completedSave = await saveResponse
    await completedSave.finished()
    await waitForSaveBodyRead(page)

    expect(pageErrors).toEqual([])
    const staleErrorToastCount = await page.locator('[data-sonner-toast]').evaluateAll((elements) => elements.filter((element) => element.textContent?.includes('Owner A deferred save failed')).length)
    expect(staleErrorToastCount).toBe(0)
  })

  test('deferred A success is not surfaced after A→B→A owner epochs', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    let release!: () => void
    let saveStarted = false
    const gate = new Promise<void>((resolve) => { release = resolve })
    const sessionOwners = await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) })
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A pending variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)

    for (const next of ['B', 'A'] as const) {
      const load = page.waitForResponse((response) =>
        response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'GET',
      )
      await switchOwner(page, owner, next, sessionOwners)
      const response = await load
      await response.finished()
      await expect(page.getByLabel('Variant title')).toHaveValue(`${next === 'A' ? OWNER_A : OWNER_B} variant`)
      await settleClient(page)
    }

    const saveResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'PATCH',
    )
    release()
    const completedSave = await saveResponse
    await completedSave.finished()
    await waitForSaveBodyRead(page)

    expect(pageErrors).toEqual([])
    await expect(page.getByText('Earlier visibility saved; newer edits remain unsaved')).not.toBeVisible()
  })

  test('deferred A success is not surfaced after an A→B owner switch', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    let release!: () => void
    let saveStarted = false
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const gate = new Promise<void>((resolve) => { release = resolve })
    const sessionOwners = await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(variantResponse('A')) })
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A pending variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)

    const bLoad = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'GET',
    )
    await switchOwner(page, owner, 'B', sessionOwners)
    const bResponse = await bLoad
    await bResponse.finished()
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_B} variant`)
    await settleClient(page)

    const saveResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'PATCH',
    )
    release()
    const completedSave = await saveResponse
    await completedSave.finished()
    await waitForSaveBodyRead(page)

    expect(pageErrors).toEqual([])
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Earlier visibility saved; newer edits remain unsaved' })).toHaveCount(0)
  })

  test('deferred A rejection is not surfaced after A→B→A owner epochs', async ({ page }) => {
    const owner = { current: 'A' as Owner }
    let release!: () => void
    let saveStarted = false
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const gate = new Promise<void>((resolve) => { release = resolve })
    const sessionOwners = await mockVariant(page, owner, async (route) => {
      saveStarted = true
      await gate
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'ABA owner A deferred save failed' }) })
    })

    await page.goto(`/workspace/variant/${RESUME_ID}`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Variant title')).toHaveValue(`${OWNER_A} variant`)
    await page.getByLabel('Variant title').fill('A pending variant')
    await page.getByRole('button', { name: 'Save visibility' }).click()
    await expect.poll(() => saveStarted).toBe(true)

    for (const next of ['B', 'A'] as const) {
      const load = page.waitForResponse((response) =>
        response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'GET',
      )
      await switchOwner(page, owner, next, sessionOwners)
      const response = await load
      await response.finished()
      await expect(page.getByLabel('Variant title')).toHaveValue(`${next === 'A' ? OWNER_A : OWNER_B} variant`)
      await settleClient(page)
    }

    const saveResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/resumes/${RESUME_ID}/variant-visibility`) && response.request().method() === 'PATCH',
    )
    release()
    const completedSave = await saveResponse
    await completedSave.finished()
    await waitForSaveBodyRead(page)

    expect(pageErrors).toEqual([])
    await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'ABA owner A deferred save failed' })).toHaveCount(0)
  })
})
