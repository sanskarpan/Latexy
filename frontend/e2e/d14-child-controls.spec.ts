import { expect, test, type Page } from '@playwright/test'
import { installMockWorkboxRegistration } from './helpers/mock-workbox-registration'

const ID = 'ffffffff-ffff-ffff-ffff-fffffffffff4'
const SOURCE = '\\documentclass{article}\n\\begin{document}\nKeep this source.\n\\end{document}'
const leaves = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image'] as const
const paths = ['/ai/generate-latex', '/ai/generate-table', '/ai/generate-table-image', '/ai/generate-math', '/ai/generate-math-image']
const all = { c01: true, c05: true, compile: true, d14: true, ai_writing: true, ...Object.fromEntries(leaves.map(key => [key, true])) }
const backendOrigin = new URL(process.env.PLAYWRIGHT_API_URL ?? process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT ?? '5181') + 2000}`).origin
test.use({ serviceWorkers: 'block' })
const pageErrors = new WeakMap<Page, Error[]>()
test.beforeEach(async ({ page }) => {
  const errors: Error[] = []; pageErrors.set(page, errors)
  page.on('pageerror', error => errors.push(error))
  await installMockWorkboxRegistration(page)
})
test.afterEach(async ({ page }) => { expect(pageErrors.get(page) ?? []).toEqual([]) })

async function fixture(page: Page, role = 'user') {
  let features = { ...all }; let owner = 'A'; let authCalls = 0; let sessionVersion = 0; let sourceCalls = 0
  const requests: string[] = []
  let responseGate: Promise<void> | null = null
  let sourceGate: Promise<void> | null = null; let sourceFailed = false
  let sessionGate: Promise<void> | null = null
  let sessionStatus = 200
  await page.addInitScript(() => { localStorage.setItem('latexy_auto_compile', 'false'); localStorage.setItem('latexy_onboarding_completed', 'true') })
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); const path = url.pathname
    if (path === '/api/auth/get-session') {
      authCalls += 1
      const data = { session: { token: `${owner}-token-${sessionVersion}` }, user: { id: owner, email: `${owner}@example.test`, name: owner } }
      const status = sessionStatus
      if (route.request().method() === 'GET' && sessionGate) await sessionGate
      if (status !== 200) return route.fulfill({ status, json: { code: status === 401 ? 'UNAUTHORIZED' : 'TEMPORARY_FAILURE', message: `Synthetic session ${status}` } })
      return route.fulfill({ json: data })
    }
    if (path.startsWith('/api/')) return route.fulfill({ json: {} })
    if (url.origin !== backendOrigin) return route.continue()
    if (path === '/public/engine/capabilities') return route.fulfill({ status: 404, json: { detail: 'Synthetic source-editor fallback' } })
    if (path === '/config/entitlements') return route.fulfill({ json: { features } })
    if (path === '/config/feature-flags') return route.fulfill({ json: { billing: false } })
    if (path === '/me') return route.fulfill({ json: { id: owner, role, preferences: {} } })
    if (path === `/resumes/${ID}`) {
      sourceCalls += 1
      if (sourceGate) await sourceGate
      if (sourceFailed) return route.fulfill({ status: 503, json: { detail: 'Synthetic source reload failed' } })
      return route.fulfill({ json: { id: ID, user_id: owner, title: `Owner ${owner} source`, latex_content: SOURCE, access_role: 'owner', created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:00Z' } })
    }
    if (paths.includes(path)) {
      requests.push(path)
      if (responseGate) await responseGate
      return route.fulfill({ json: { latex: `\\textbf{${path.split('/').pop()}}`, cached: false, rows: 2, columns: 2, source: path.endsWith('image') ? 'image' : 'text', display_mode: 'display' } })
    }
    if (path.includes('/checkpoints') || path.includes('/comments') || path.includes('/collaborators') || path.includes('/suggestions') || path === '/macros' || path === '/jobs') return route.fulfill({ json: [] })
    if (path.endsWith('/academic-cv-report')) return route.fulfill({ json: { is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 } })
    if (path.startsWith('/tenants/')) return route.fulfill({ json: { tenant: null } })
    if (path === '/subscription/current') return route.fulfill({ json: { userId: owner, planId: 'free', planName: 'Free', status: 'active', features: {} } })
    if (path === '/ats/quick-score') return route.fulfill({ json: { score: 70, grade: 'C', sections_found: [], missing_sections: [] } })
    if (path === '/ws/ticket') return route.fulfill({ status: 403, json: { detail: 'Synthetic socket disabled' } })
    if (path.startsWith('/analytics') || path.startsWith('/public/trial') || ['/trial/status', '/github/status', '/dropbox/status', '/telemetry/frontend'].includes(path)) return route.fulfill({ json: {} })
    return route.fulfill({ status: 403, json: { detail: `Unmocked D14 fixture endpoint: ${path}` } })
  })
  await page.routeWebSocket('**/ws/**', socket => socket.close())
  const refresh = async () => {
    const updated = page.waitForResponse(response => new URL(response.url()).pathname === '/config/entitlements')
    await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await updated
  }
  const refreshSession = async (rotateToken = true) => {
    if (rotateToken) sessionVersion += 1
    const before = authCalls
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'd14-test-session-refresh' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => authCalls).toBeGreaterThan(before)
  }
  return { requests, setFeatures: (next: Partial<Record<string, boolean>>) => { features = { ...all, ...next } },
    gate: (next: Promise<void> | null) => { responseGate = next }, refresh,
    sourceGate: (next: Promise<void> | null, failed = false) => { sourceGate = next; sourceFailed = failed },
    sessionGate: (next: Promise<void> | null) => { sessionGate = next },
    sessionStatus: (next: number) => { sessionStatus = next },
    sourceCalls: () => sourceCalls, refreshSession,
    switchOwner: async (next: string) => {
      owner = next; await refreshSession()
      await expect(page.locator('header input[placeholder="Untitled"]')).toHaveValue(`Owner ${next} source`)
    } }
}

async function openPanel(page: Page, navigate = true) {
  if (navigate) {
    await page.goto(`/workspace/${ID}/edit`)
    await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue()), { timeout: 60_000 }).toBe(SOURCE)
  }
  await page.getByRole('button', { name: /^More$/i }).click()
  const item = page.getByRole('menuitem', { name: /^(Generate|Recover) LaTeX$/ })
  await item.focus(); await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Generate LaTeX' })).toBeVisible()
}
async function configure(page: Page, leaf: typeof leaves[number]) {
  const region = page.getByRole('region', { name: 'Generate LaTeX' })
  await region.getByRole('tab', { name: leaf.includes('table') ? 'Table' : leaf.includes('math') ? 'Math' : 'Describe', exact: true }).click()
  if (leaf.endsWith('image')) await region.locator('input[type=file]').setInputFiles({ name: 'sample.png', mimeType: 'image/png', buffer: Buffer.from('89504e470d0a1a0a', 'hex') })
  else await region.getByRole('textbox').fill(leaf === 'd14_latex' ? 'Create a heading' : leaf.includes('table') ? 'A,B\n1,2' : 'x squared')
  return region.getByRole('button', { name: leaf === 'd14_latex' ? 'Generate fragment' : leaf.includes('table') ? 'Generate table' : 'Generate math', exact: true })
}

for (const role of ['user', 'support', 'admin']) test(`D14 five branches independently hide and enable for synthetic ${role}`, async ({ page }) => {
  const f = await fixture(page, role); await openPanel(page)
  for (const [index, leaf] of leaves.entries()) {
    const generate = await configure(page, leaf)
    f.setFeatures({ [leaf]: false }); await f.refresh()
    await expect(generate).toHaveCount(0)
    expect(f.requests).toHaveLength(index)
    f.setFeatures({ [leaf]: true }); await f.refresh()
    await expect(generate).toBeEnabled(); await generate.press('Enter')
    await expect(page.getByText(`\\textbf{${paths[index].split('/').pop()}}`, { exact: true })).toBeVisible()
    expect(f.requests).toEqual(paths.slice(0, index + 1))
  }
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
})

test('admitted response survives leaf OFF while retry and C01 insertion remain independently denied', async ({ page }) => {
  const f = await fixture(page); let release!: () => void
  f.gate(new Promise<void>(resolve => { release = resolve }))
  await openPanel(page); await (await configure(page, 'd14_latex')).click()
  await expect.poll(() => f.requests.length).toBe(1)
  f.setFeatures({ d14_latex: false }); await f.refresh(); release()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate fragment again' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Copy fragment' })).toBeEnabled()
  f.setFeatures({ d14_latex: false, c01: false }); await f.refresh()
  await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
  f.setFeatures({ d14_latex: false, c01: true }); await f.refresh()
  await page.getByRole('button', { name: 'Insert at cursor' }).click()
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toContain('\\textbf{generate-latex}')
  expect(f.requests).toHaveLength(1)
})

test('real editor preserves admitted recovery through same-owner source loading, failure and token rotation', async ({ page }) => {
  const f = await fixture(page); let releaseGeneration!: () => void; let releaseSource!: () => void
  f.gate(new Promise<void>(resolve => { releaseGeneration = resolve }))
  await openPanel(page); await (await configure(page, 'd14_latex')).click()
  await expect.poll(() => f.requests.length).toBe(1)
  const before = f.sourceCalls()
  f.sourceGate(new Promise<void>(resolve => { releaseSource = resolve }), true)
  await f.refreshSession()
  await expect.poll(f.sourceCalls).toBeGreaterThan(before)
  await expect(page.getByRole('status').filter({ hasText: 'Saved generator recovery is available' })).toBeVisible()
  releaseGeneration()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Copy fragment' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Generate fragment again' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
  releaseSource()
  await expect(page.getByRole('alert').filter({ hasText: 'Document reload failed:' })).toBeVisible()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
  f.sourceGate(null); await f.refreshSession()
  await expect(page.getByRole('button', { name: 'Insert at cursor' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Generate fragment again' })).toBeEnabled()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  expect(f.requests).toHaveLength(1)
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
})

test('actual authenticated GET-session refetch holds stable recovery and blocks D14 until the subsequent source reload succeeds', async ({ page }) => {
  const f = await fixture(page); let releaseSession!: () => void; let releaseSource!: () => void
  await openPanel(page); await (await configure(page, 'd14_latex')).click()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  const before = f.sourceCalls()
  f.sessionGate(new Promise<void>(resolve => { releaseSession = resolve }))
  f.sourceGate(new Promise<void>(resolve => { releaseSource = resolve }))
  try {
    // The response is unchanged, so Better Auth keeps its exact data object.
    // While GET is held it sets isRefetching=true with isPending=false.
    await f.refreshSession(false)
    await expect(page.getByRole('status').filter({ hasText: 'Saved generator recovery is available' })).toBeVisible()
    await expect(page.getByText('Create a heading', { exact: true })).toBeVisible()
    await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Copy fragment' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Generate fragment again' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
    expect(f.sourceCalls()).toBe(before); expect(f.requests).toHaveLength(1)
    releaseSession()
    await expect.poll(f.sourceCalls).toBeGreaterThan(before)
    await expect(page.getByRole('button', { name: 'Generate fragment again' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
    await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
    releaseSource()
    await expect(page.getByRole('button', { name: 'Generate fragment again' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Insert at cursor' })).toBeEnabled()
    await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
    expect(f.requests).toHaveLength(1)
    expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
  } finally {
    releaseSession(); releaseSource(); f.sessionGate(null); f.sourceGate(null)
  }
})

test('authoritative GET-session401 purges owned D14 recovery and redirects without re-admitting generation', async ({ page }) => {
  const f = await fixture(page); let releaseSession!: () => void
  await openPanel(page); await (await configure(page, 'd14_latex')).click()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  f.sessionStatus(401); f.sessionGate(new Promise<void>(resolve => { releaseSession = resolve }))
  try {
    await f.refreshSession(false)
    await expect(page.getByRole('button', { name: 'Generate fragment again' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
    releaseSession()
    await expect(page).toHaveURL(/\/login\?redirect=/)
    await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('region', { name: 'Generate LaTeX' })).toHaveCount(0)
    expect(f.requests).toHaveLength(1)
  } finally { releaseSession(); f.sessionGate(null) }
})

for (const ancestor of ['d14', 'ai_writing']) test(`owned D14 recovery survives ${ancestor} revocation and tab revisit`, async ({ page }) => {
  const f = await fixture(page); await openPanel(page); await (await configure(page, 'd14_latex')).click()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  f.setFeatures({ [ancestor]: false }); await f.refresh()
  await expect(page.getByRole('button', { name: 'Generate fragment again' })).toHaveCount(0)
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  await openPanel(page, false)
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Copy fragment' })).toBeEnabled()
  expect(f.requests).toHaveLength(1)
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
})

test('late A response cannot reappear or insert after A to B to A', async ({ page }) => {
  const f = await fixture(page); let release!: () => void
  f.gate(new Promise<void>(resolve => { release = resolve }))
  await openPanel(page); await (await configure(page, 'd14_latex')).click()
  await expect.poll(() => f.requests.length).toBe(1)
  await f.switchOwner('B'); await f.switchOwner('A')
  release()
  await openPanel(page, false)
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Insert at cursor' })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
})

test('replacement and repeated keyboard activation cannot leak an old branch response', async ({ page }) => {
  const f = await fixture(page); let release!: () => void
  f.gate(new Promise<void>(resolve => { release = resolve }))
  await openPanel(page); const generate = await configure(page, 'd14_latex')
  await generate.press('Enter'); await expect.poll(() => f.requests.length).toBe(1)
  await expect(page.getByRole('button', { name: 'Generating…' })).toBeDisabled()
  await page.getByRole('tab', { name: 'Math', exact: true }).click()
  release(); await expect(page.getByRole('button', { name: 'Generate math' })).toBeVisible()
  await expect(page.getByText('\\textbf{generate-latex}', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
})
