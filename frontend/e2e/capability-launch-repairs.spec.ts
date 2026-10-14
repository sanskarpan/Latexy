import { readFileSync } from 'node:fs'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installMockWorkboxRegistration } from './helpers/mock-workbox-registration'

// Real production React/DOM and Better Auth notifications; synthetic HTTP only.
// This does not exercise server grants, PostgreSQL, DNS, AI, PDF compilation or providers.
const backendOrigin = new URL(process.env.PLAYWRIGHT_API_URL ?? process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT ?? '5181') + 2000}`).origin
const RESUME_ID = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
const SOURCE = '\\documentclass{article}\n\\begin{document}\nOwned recovery source.\n\\end{document}'
// These are already-composed effective grants. Every omitted optional key denies.
const INTERVIEW_FEATURES = { c01: true, e02: true, e03: true }
const TENANT_FEATURES = { f10: true, f11: true }
const TEMPLATE_FEATURES = { b01: true, b04: true, b05: true, c01: true }

test.use({ serviceWorkers: 'block' })
const pageErrors = new WeakMap<Page, string[]>()
test.beforeEach(async ({ page }) => {
  await installMockWorkboxRegistration(page)
  const errors: string[] = []; pageErrors.set(page, errors)
  page.on('pageerror', error => errors.push(error.message))
})
test.afterEach(({ page }) => {
  expect(pageErrors.get(page), 'Uncaught browser errors, including React hydration failures').toEqual([])
})

function deferred() {
  let release!: () => void
  const promise = new Promise<void>(resolve => { release = resolve })
  return { promise, release }
}

async function settleFrame(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
}

async function fixture(page: Page, grants: Record<string, boolean>, initialOwner: string | null = 'owner-a') {
  const state = { owner: initialOwner, incarnation: 0, authError: false, features: { ...grants }, authCalls: 0, authOwners: [] as Array<string | null> }
  await page.addInitScript(() => {
    localStorage.setItem('latexy_auto_compile', 'false')
    localStorage.setItem('latexy_onboarding_completed', 'true')
  })
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); const path = url.pathname
    if (path === '/api/auth/get-session') {
      state.authCalls += 1; state.authOwners.push(state.owner)
      if (state.authError) return route.fulfill({ status: 503, json: { detail: 'Synthetic temporary auth failure' } })
      return route.fulfill({ json: state.owner ? {
        session: { id: `session-${state.owner}-${state.incarnation}`, userId: state.owner, token: `fixture-${state.owner}-${state.incarnation}`, expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: state.owner, email: `${state.owner}@example.test`, name: state.owner },
      } : null })
    }
    if (path.startsWith('/api/')) return route.fulfill({ json: {} })
    if (url.origin !== backendOrigin) return route.continue()
    if (path === '/config/entitlements') return route.fulfill({ json: { features: state.features } })
    // Exercise the source editor here; a 403 is an authorization error and
    // deliberately does not enable the legacy source fallback.
    if (path === '/public/engine/capabilities') return route.fulfill({ status: 404, json: { detail: 'Synthetic engine unsupported' } })
    if (path === '/config/feature-flags') return route.fulfill({ json: { billing: false } })
    if (path === '/me') return route.fulfill({ json: { id: state.owner, role: 'admin', plan: 'team', preferences: {} } })
    if (path === `/resumes/${RESUME_ID}`) return route.fulfill({ json: { id: RESUME_ID, user_id: state.owner, title: 'Owned source', latex_content: SOURCE, access_role: 'owner', created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:00Z' } })
    if (path.includes('/checkpoints') || path.includes('/comments') || path.includes('/collaborators') || path.includes('/suggestions') || path === '/macros' || path === '/jobs') return route.fulfill({ json: [] })
    if (path.endsWith('/academic-cv-report')) return route.fulfill({ json: { is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 } })
    if (path.startsWith('/tenants/')) return route.fulfill({ json: { tenant: null } })
    if (path === '/subscription/current') return route.fulfill({ json: { userId: state.owner, planId: 'team', planName: 'Team', status: 'active', features: {} } })
    if (path === '/ats/quick-score') return route.fulfill({ json: { score: 70, grade: 'C', sections_found: [], missing_sections: [] } })
    if (path === '/ws/ticket') return route.fulfill({ status: 403, json: { detail: 'Synthetic socket disabled' } })
    if (path.startsWith('/analytics') || path.startsWith('/public/trial') || ['/trial/status', '/github/status', '/dropbox/status', '/telemetry/frontend'].includes(path)) return route.fulfill({ json: {} })
    return route.fulfill({ status: 403, json: { detail: `Unmocked fixture endpoint: ${path}` } })
  })
  await page.routeWebSocket('**/ws/**', socket => socket.close())
  const backendRoute = (matches: (path: string) => boolean, handler: (route: Route) => Promise<unknown>) =>
    page.route(url => url.origin === backendOrigin && matches(url.pathname), handler)
  const refreshGrants = async (changes: Record<string, boolean>) => {
    Object.assign(state.features, changes)
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/config/entitlements')
    await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
    await response
  }
  const refreshSession = async () => {
    const calls = state.authCalls
    await page.evaluate(() => {
      const message = JSON.stringify({ event: 'session', data: { trigger: 'test-owner-switch' } })
      localStorage.setItem('better-auth.message', message)
      window.dispatchEvent(new StorageEvent('storage', { key: 'better-auth.message', newValue: message }))
    })
    await expect.poll(() => state.authCalls).toBeGreaterThan(calls)
  }
  return { state, backendRoute, refreshGrants, refreshSession, switchOwner: async (owner: string) => {
    state.owner = owner; state.incarnation += 1; await refreshSession()
  } }
}

function tenantFor(owner: string, incarnation = 0) {
  return {
    id: `tenant-${owner}`, owner_id: owner, slug: `tenant-${owner}`, name: `${owner} tenant ${incarnation}`,
    logo_url: null, primary_color: '#19375d', custom_domain: `${owner}-${incarnation}.example.test`, domain_verified: false,
    max_members: 50, plan_id: 'agency', active: true, created_at: '2026-10-13T00:00:00Z',
  }
}

type Fixture = Awaited<ReturnType<typeof fixture>>
async function tenants(page: Page, h: Fixture, hold?: 'list' | 'details' | 'patch') {
  const gate = deferred(); const started = deferred(); const finished = deferred()
  let held = false
  const patches: Record<string, unknown>[] = []
  const records = new Map<string, ReturnType<typeof tenantFor>>()
  let dnsCalls = 0; let removalCalls = 0
  await h.backendRoute(path => path.startsWith('/tenants/') && path !== '/tenants/resolve-host', async route => {
    const path = new URL(route.request().url()).pathname; const method = route.request().method()
    // Capture the owner before the deferred response, like a real admitted request.
    const owner = h.state.owner!; const incarnation = h.state.incarnation
    const recordKey = `${owner}:${incarnation}`
    const current = records.get(recordKey) ?? tenantFor(owner, incarnation)
    records.set(recordKey, current)
    const shouldHold = !held && owner === 'owner-a' && incarnation === 0 && (
      (hold === 'list' && path === '/tenants/my') ||
      (hold === 'details' && path.endsWith('/members') && method === 'GET') ||
      (hold === 'patch' && method === 'PATCH')
    )
    if (shouldHold) { held = true; started.release(); await gate.promise }
    if (path === '/tenants/my') await route.fulfill({ json: [current] })
    else if (path.endsWith('/members') && method === 'GET') await route.fulfill({ json: [{ user_id: `member-${owner}`, email: `${owner}-member-${incarnation}@example.test`, name: `${owner} member ${incarnation}`, role: 'member', joined_at: '2026-10-13T00:00:00Z' }] })
    else if (path.endsWith('/stats')) await route.fulfill({ json: { member_count: 1 } })
    else if (path.endsWith('/cohorts')) await route.fulfill({ json: [] })
    else if (path.endsWith('/domain/verify')) {
      dnsCalls += 1
      await route.fulfill({ json: { domain: current.custom_domain, verified: true, txt_record_name: '_latexy.example.test', txt_record_value: 'fixture-verification', instructions: 'Synthetic DNS proof.' } })
    } else if (method === 'DELETE' && path.includes('/members/')) { removalCalls += 1; await route.fulfill({ status: 204 }) }
    else if (method === 'PATCH') {
      const patch = route.request().postDataJSON() as Record<string, unknown>; patches.push(patch)
      const domain = typeof patch.custom_domain === 'string' ? patch.custom_domain.trim().toLowerCase().replace(/\.$/, '') : patch.custom_domain
      const updated = { ...current, ...patch, ...(Object.prototype.hasOwnProperty.call(patch, 'custom_domain') ? { custom_domain: domain } : {}) } as ReturnType<typeof tenantFor>
      records.set(recordKey, updated)
      await route.fulfill({ json: updated })
    } else await route.fulfill({ status: 403, json: { detail: `Unmocked tenant mutation ${path}` } })
    if (shouldHold) finished.release()
  })
  return { gate, started, finished, patches, dnsCalls: () => dnsCalls, removalCalls: () => removalCalls }
}

const domainInput = (page: Page) => page.getByPlaceholder('resumes.acme.com')

test('E03 live revocation retains local answers and admitted feedback while hiding new actions', async ({ page }) => {
  const h = await fixture(page, INTERVIEW_FEATURES)
  h.state.features.e03 = false
  const gate = deferred(); const started = deferred(); const finished = deferred()
  let simulations = 0
  await h.backendRoute(path => path === `/resumes/${RESUME_ID}/interview-prep`, route => route.fulfill({ json: [{
    id: '22222222-2222-2222-2222-222222222222', resume_id: RESUME_ID, user_id: 'owner-a',
    job_description: null, company_name: null, role_title: null, generation_job_id: null,
    questions: [{ category: 'behavioral', question: 'Describe a reliability improvement.', what_interviewer_assesses: 'Evidence' }],
    created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:00Z',
  }] }))
  await h.backendRoute(path => path.endsWith('/simulate'), async route => {
    simulations += 1; started.release(); await gate.promise
    expect(route.request().postDataJSON()).toEqual({ mode: 'coach', answers: [{ question_index: 0, answer: 'I led a retry redesign that reduced failed jobs by thirty percent.' }] })
    await route.fulfill({ json: { mode: 'coach', feedback: [{ question_index: 0, score: 84, strengths: ['Concrete example'], improvements: ['Quantify scope'], suggested_outline: ['Context', 'Action', 'Result'] }], average_score: 84, overall_feedback: 'Admitted feedback remains available.' } })
    finished.release()
  })
  try {
    await page.goto(`/workspace/${RESUME_ID}/edit`)
    await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
    await page.getByRole('button', { name: /^More$/i }).click()
    await page.getByRole('menuitem', { name: /^Interview Prep$/i }).click()
    await expect(page.getByText('Describe a reliability improvement.', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /Start Coach session/ })).toHaveCount(0)
    await h.refreshGrants({ e03: true })
    await page.getByRole('button', { name: /Start Coach session/ }).click()
    const answer = page.getByRole('textbox', { name: 'Answer to question 1' })
    await answer.fill('I led a retry redesign that reduced failed jobs by thirty percent.')
    await h.refreshGrants({ e03: false })
    await expect(page.getByRole('button', { name: 'Finish session', exact: true })).toHaveCount(0)
    await expect(answer).toHaveValue('I led a retry redesign that reduced failed jobs by thirty percent.')
    expect(simulations).toBe(0)
    await h.refreshGrants({ e03: true })
    await page.getByRole('button', { name: 'Finish session', exact: true }).click(); await started.promise
    await h.refreshGrants({ e02: false, e03: false }); gate.release(); await finished.promise
    await expect(page.getByText('Answer feedback', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'View session summary' }).click()
    await expect(page.getByText('Practice score 84/100')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start another session' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'New', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeVisible()
    expect(simulations).toBe(1)
    await h.refreshGrants({ e03: true })
    await page.getByRole('button', { name: 'Start another session' }).click()
    await expect(page.getByRole('button', { name: /Start Coach session/ })).toBeVisible()
  } finally { gate.release() }
})

function interviewPrepFor(owner: string, incarnation = 0) {
  return {
    id: '22222222-2222-2222-2222-222222222222', resume_id: RESUME_ID, user_id: owner,
    job_description: null, company_name: null, role_title: `${owner} prep ${incarnation}`, generation_job_id: null,
    questions: [{ category: 'behavioral', question: `${owner} question ${incarnation}`, what_interviewer_assesses: 'Evidence' }],
    created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:00Z',
  }
}

async function openInterview(page: Page) {
  await page.getByRole('button', { name: /^More$/i }).click()
  await page.getByRole('menuitem', { name: /^Interview Prep$/i }).click()
}

async function savedInterview(h: Fixture) {
  await h.backendRoute(path => path === `/resumes/${RESUME_ID}/interview-prep`, route =>
    route.fulfill({ json: [interviewPrepFor(h.state.owner!, h.state.incarnation)] }))
}

// Entry is allowed by either independent grant. Recovery never creates a new AI action.
test('E03-only saved prep survives refresh loading and both-off denial with read/delete recovery', async ({ page }) => {
  const h = await fixture(page, { c01: true, e02: false, e03: true }); await savedInterview(h)
  let generations = 0; let simulations = 0; let deletions = 0
  const refreshGate = deferred(); const refreshStarted = deferred()
  let holdRefresh = false
  await h.backendRoute(path => path === '/config/entitlements', async route => {
    const features = { ...h.state.features }
    if (holdRefresh) { holdRefresh = false; refreshStarted.release(); await refreshGate.promise }
    await route.fulfill({ json: { features } })
  })
  await h.backendRoute(path => path === '/interview-prep/generate' || path.endsWith('/simulate') || path === '/interview-prep/22222222-2222-2222-2222-222222222222', async route => {
    if (route.request().method() === 'DELETE') { deletions += 1; await route.fulfill({ status: 204 }); return }
    if (new URL(route.request().url()).pathname.endsWith('/simulate')) simulations += 1
    else generations += 1
    await route.fulfill({ status: 403, json: { detail: 'No new AI request is authorized by this fixture' } })
  })
  try {
    await page.goto(`/workspace/${RESUME_ID}/edit`); await openInterview(page)
    await expect(page.getByText('owner-a question 0', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'New', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: /Start Coach session/ }).click()
    const answer = page.getByRole('textbox', { name: 'Answer to question 1' })
    await answer.fill('An owned answer preserved throughout grant refresh and denial.')
    holdRefresh = true
    const refreshing = h.refreshGrants({ e03: false })
    await refreshStarted.promise
    await expect(answer).toHaveValue('An owned answer preserved throughout grant refresh and denial.')
    await expect(page.getByRole('button', { name: 'Finish session', exact: true })).toHaveCount(0)
    refreshGate.release(); await refreshing
    await expect(answer).toHaveValue('An owned answer preserved throughout grant refresh and denial.')
    await expect(page.getByRole('button', { name: /Generate Screening Practice|Finish session|Start another session/ })).toHaveCount(0)
    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByText('owner-a question 0', { exact: true })).toHaveCount(0)
    await expect(page.getByText(/New interview-prep generation is unavailable/)).toBeVisible()
    expect({ generations, simulations, deletions }).toEqual({ generations: 0, simulations: 0, deletions: 1 })
  } finally { refreshGate.release() }
})

test('E02 draft and E03 answer survive same-owner auth failure and token refresh', async ({ page }) => {
  const h = await fixture(page, INTERVIEW_FEATURES); await savedInterview(h)
  await page.goto(`/workspace/${RESUME_ID}/edit`); await openInterview(page)
  await page.getByRole('button', { name: 'New', exact: true }).click()
  const jobDescription = page.getByPlaceholder('Paste the job description here for tailored questions…')
  await jobDescription.fill('Owned role description with an unsaved preparation draft.')
  h.state.authError = true; await h.refreshSession()
  await expect(jobDescription).toHaveValue('Owned role description with an unsaved preparation draft.')
  await expect(page.getByRole('button', { name: 'Generate Screening Practice', exact: true })).toHaveCount(0)
  h.state.authError = false; h.state.incarnation += 1; await h.refreshSession()
  await expect(page.getByRole('button', { name: 'Generate Screening Practice', exact: true })).toBeVisible()
  await expect(jobDescription).toHaveValue('Owned role description with an unsaved preparation draft.')
  await page.locator('select').filter({ has: page.locator('option[value="22222222-2222-2222-2222-222222222222"]') }).selectOption('22222222-2222-2222-2222-222222222222')
  await page.getByRole('button', { name: /Start Coach session/ }).click()
  const answer = page.getByRole('textbox', { name: 'Answer to question 1' })
  await answer.fill('An owned simulation answer that survives a new same-owner token.')
  h.state.incarnation += 1; await h.refreshSession()
  await expect(page.getByRole('button', { name: 'Finish session', exact: true })).toBeVisible()
  await expect(answer).toHaveValue('An owned simulation answer that survives a new same-owner token.')
})

for (const recovery of ['generation draft', 'simulation answer'] as const) {
  test(`E02/E03 ${recovery} stays readable while new actions wait for the latest resume refresh`, async ({ page }) => {
    const h = await fixture(page, INTERVIEW_FEATURES); await savedInterview(h)
    const gate = deferred(); const started = deferred(); const finished = deferred()
    let holdNextRead = false; let resumeReads = 0; let generations = 0; let evaluations = 0
    await h.backendRoute(path => path === `/resumes/${RESUME_ID}`, async route => {
      resumeReads += 1
      if (holdNextRead) {
        holdNextRead = false; started.release(); await gate.promise
        await route.fulfill({ status: 503, json: { detail: 'Controlled latest resume refresh failure' } })
        finished.release(); return
      }
      await route.fulfill({ json: { id: RESUME_ID, user_id: h.state.owner, title: 'Owned source', latex_content: SOURCE,
        access_role: 'owner', created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:00Z' } })
    })
    await h.backendRoute(path => path === '/interview-prep/generate' || path.endsWith('/simulate'), async route => {
      if (new URL(route.request().url()).pathname.endsWith('/simulate')) {
        evaluations += 1
        await route.fulfill({ json: { mode: 'coach', feedback: [{ question_index: 0, score: 84, strengths: ['Latest source confirmed'], improvements: ['Scope'], suggested_outline: ['Context'] }], average_score: 84, overall_feedback: 'Allowed after the latest resume refresh succeeds.' } })
      } else {
        generations += 1
        await route.fulfill({ json: { success: true, prep_id: '33333333-3333-3333-3333-333333333333', job_id: '44444444-4444-4444-4444-444444444444', message: 'Synthetic generation admitted' } })
      }
    })
    try {
      await page.goto(`/workspace/${RESUME_ID}/edit`); await openInterview(page)
      const recoveringGeneration = recovery === 'generation draft'
      if (recoveringGeneration) await page.getByRole('button', { name: 'New', exact: true }).click()
      else await page.getByRole('button', { name: /Start Coach session/ }).click()
      const draft = recoveringGeneration ? page.getByPlaceholder('Paste the job description here for tailored questions…')
        : page.getByRole('textbox', { name: 'Answer to question 1' })
      const ownedText = 'A valid owned draft that stays visible while the latest resume load is pending or failed.'
      await draft.fill(ownedText)
      holdNextRead = true; h.state.incarnation += 1; await h.refreshSession(); await started.promise
      // Fully resolve the effective grants while the separate resume read stays pending.
      await h.refreshGrants({ e02: true, e03: true })
      await expect(draft).toHaveValue(ownedText)
      await expect(page.getByRole('button', { name: /^(Generate Screening Practice|Finish session|New)$/ })).toHaveCount(0)
      expect({ generations, evaluations }).toEqual({ generations: 0, evaluations: 0 })
      gate.release(); await finished.promise
      await expect(page.getByRole('alert').filter({ hasText: 'Controlled latest resume refresh failure' })).toBeVisible()
      await expect(draft).toHaveValue(ownedText)
      await expect(page.getByRole('button', { name: /^(Generate Screening Practice|Finish session|New)$/ })).toHaveCount(0)
      expect({ generations, evaluations }).toEqual({ generations: 0, evaluations: 0 })
      h.state.incarnation += 1; await h.refreshSession()
      const action = page.getByRole('button', { name: recoveringGeneration ? 'Generate Screening Practice' : 'Finish session', exact: true })
      await expect(action).toBeVisible()
      await expect(draft).toHaveValue(ownedText)
      expect(resumeReads).toBeGreaterThanOrEqual(3)
      await action.click()
      await expect.poll(() => recoveringGeneration ? generations : evaluations).toBe(1)
      expect(recoveringGeneration ? evaluations : generations).toBe(0)
    } finally { gate.release() }
  })
}

for (const transition of ['A→B', 'A→B→A', 'logout→A'] as const) {
  test(`E03 admitted feedback and local draft cannot cross ${transition}`, async ({ page }) => {
    const h = await fixture(page, INTERVIEW_FEATURES); await savedInterview(h)
    const gate = deferred(); const started = deferred(); const finished = deferred()
    let evaluations = 0
    await h.backendRoute(path => path.endsWith('/simulate'), async route => {
      evaluations += 1; started.release(); await gate.promise
      await route.fulfill({ json: { mode: 'coach', feedback: [{ question_index: 0, score: 84, strengths: ['Old owner private strength'], improvements: ['Scope'], suggested_outline: ['Context'] }], average_score: 84, overall_feedback: 'Old owner private feedback' } })
      finished.release()
    })
    try {
      await page.goto(`/workspace/${RESUME_ID}/edit`); await openInterview(page)
      await page.getByRole('button', { name: /Start Coach session/ }).click()
      await page.getByRole('textbox', { name: 'Answer to question 1' }).fill('Old owner private draft longer than twenty characters.')
      await page.getByRole('button', { name: 'Finish session', exact: true }).click(); await started.promise
      if (transition === 'logout→A') {
        h.state.owner = null; await h.refreshSession(); await expect(page).toHaveURL(/\/login/)
        h.state.owner = 'owner-a'; h.state.incarnation += 1
        await page.goto(`/workspace/${RESUME_ID}/edit`)
      } else {
        await h.switchOwner('owner-b')
        await expect.poll(() => page.evaluate(() => (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
        if (transition === 'A→B→A') await h.switchOwner('owner-a')
      }
      await openInterview(page)
      const current = interviewPrepFor(h.state.owner!, h.state.incarnation)
      await expect(page.getByText(current.questions[0].question, { exact: true })).toBeVisible()
      gate.release(); await finished.promise; await settleFrame(page)
      await expect(page.getByText('Old owner private strength', { exact: true })).toHaveCount(0)
      await expect(page.getByText('Old owner private feedback', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('textbox', { name: 'Answer to question 1' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: /Start Coach session/ })).toBeVisible()
      expect(evaluations).toBe(1)
    } finally { gate.release() }
  })
}

test('tenant F10/F11 toggle independently and preserve domain/member removal recovery', async ({ page }) => {
  const h = await fixture(page, TENANT_FEATURES); const t = await tenants(page, h)
  h.state.features.f10 = false
  await page.goto('/admin/tenant')
  await expect(domainInput(page)).toHaveValue('owner-a-0.example.test')
  for (const name of ['+ New Tenant', 'Save Branding', 'Create cohort', 'Invite']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Verify DNS', exact: true })).toBeEnabled()
  await domainInput(page).fill(' NEW.EXAMPLE.TEST. ')
  await page.getByRole('button', { name: 'Save Domain', exact: true }).click()
  await expect(domainInput(page)).toHaveValue('new.example.test')
  expect(t.patches).toEqual([{ custom_domain: 'NEW.EXAMPLE.TEST.' }])
  await page.getByRole('button', { name: 'Verify DNS', exact: true }).click()
  await expect(page.getByText('Domain verified', { exact: true })).toBeVisible(); expect(t.dnsCalls()).toBe(1)
  await h.refreshGrants({ f10: true, f11: false })
  await expect(page.getByRole('button', { name: 'Save Domain', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^(Verify|Recheck) DNS$/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Save Branding', exact: true }).click()
  await expect.poll(() => t.patches.length).toBe(2)
  expect(t.patches[1]).toEqual({ name: 'owner-a tenant 0', logo_url: null, primary_color: '#19375d' })
  await h.refreshGrants({ f10: false, f11: false })
  await expect(page.getByRole('button', { name: 'Remove Domain', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Remove Domain', exact: true }).click()
  await expect(domainInput(page)).toHaveValue('')
  expect(t.patches[2]).toEqual({ custom_domain: null })
  await page.getByRole('button', { name: 'Remove', exact: true }).click()
  await expect(page.getByText('owner-a-member-0@example.test', { exact: true })).toHaveCount(0)
  expect(t.removalCalls()).toBe(1)
})

for (const hold of ['list', 'details', 'patch'] as const) for (const roundTrip of [false, true]) {
  test(`tenant ${hold} response stays with its admitted owner after ${roundTrip ? 'A→B→A' : 'A→B'}`, async ({ page }) => {
    const h = await fixture(page, TENANT_FEATURES); const t = await tenants(page, h, hold)
    try {
      await page.goto('/admin/tenant')
      if (hold === 'patch') {
        await expect(domainInput(page)).toHaveValue('owner-a-0.example.test')
        await domainInput(page).fill('late-old-a.example.test')
        await page.getByRole('button', { name: 'Save Domain', exact: true }).click()
      }
      await t.started.promise
      if (hold === 'patch') {
        await expect(page.getByRole('button', { name: 'Save Branding', exact: true })).toBeDisabled()
        await expect(page.getByRole('button', { name: 'Remove Domain', exact: true })).toBeDisabled()
      }
      await h.switchOwner('owner-b')
      await expect(page.getByRole('button', { name: 'owner-b tenant 1', exact: true })).toBeVisible()
      await expect(domainInput(page)).toHaveValue('owner-b-1.example.test')
      if (roundTrip) {
        await h.switchOwner('owner-a')
        await expect(page.getByRole('button', { name: 'owner-a tenant 2', exact: true })).toBeVisible()
        await expect(domainInput(page)).toHaveValue('owner-a-2.example.test')
      }
      t.gate.release(); await t.finished.promise; await settleFrame(page)
      await expect(page.getByRole('button', { name: 'owner-a tenant 0', exact: true })).toHaveCount(0)
      await expect(page.getByText('owner-a-member-0@example.test', { exact: true })).toHaveCount(0)
      await expect(domainInput(page)).toHaveValue(roundTrip ? 'owner-a-2.example.test' : 'owner-b-1.example.test')
      await expect(page.locator('html')).not.toHaveAttribute('data-tenant-name', 'owner-a tenant 0')
      await expect(page.getByText('Domain saved', { exact: true })).toHaveCount(0)
      expect(t.patches).toHaveLength(hold === 'patch' ? 1 : 0)
    } finally { t.gate.release() }
  })
}

test('tenant same-owner auth failure/token refresh retains a valid unsaved domain draft', async ({ page }) => {
  const h = await fixture(page, TENANT_FEATURES); const t = await tenants(page, h)
  await page.goto('/admin/tenant'); await expect(domainInput(page)).toHaveValue('owner-a-0.example.test')
  await domainInput(page).fill('unsaved.example.test')
  h.state.authError = true; await h.refreshSession()
  await expect(domainInput(page)).toHaveValue('unsaved.example.test')
  await expect(page.getByRole('button', { name: 'Save Domain', exact: true })).toHaveCount(0)
  expect(t.patches).toHaveLength(0)
  h.state.authError = false; h.state.incarnation += 1; await h.refreshSession()
  await expect(page.getByRole('button', { name: 'Save Domain', exact: true })).toBeEnabled()
  await expect(domainInput(page)).toHaveValue('unsaved.example.test')
  await page.getByRole('button', { name: 'Save Domain', exact: true }).click()
  await expect.poll(() => t.patches).toEqual([{ custom_domain: 'unsaved.example.test' }])
})

const templateRows = ['professional', 'academic', 'regional', 'presentation'].map((category, index) => ({
  id: `11111111-1111-1111-1111-${String(index + 1).padStart(12, '0')}`, category,
  name: `${category} template`, category_label: category, description: 'Fixture template', tags: [],
  sort_order: index, document_type: category === 'presentation' ? 'presentation' : category === 'academic' ? 'academic_cv' : 'resume',
  thumbnail_url: null, pdf_url: null, latex_content: SOURCE,
}))
async function templates(h: Fixture, holdUse = false) {
  let catalogCalls = 0; let useCalls = 0
  const gate = deferred(); const started = deferred(); const finished = deferred()
  await h.backendRoute(path => path === '/templates' || path.startsWith('/templates/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/templates' || path === '/templates/') { catalogCalls += 1; return route.fulfill({ json: templateRows }) }
    if (path === '/templates/categories') return route.fulfill({ json: templateRows.map(row => ({ category: row.category, label: row.category, count: 1 })) })
    if (path.endsWith('/use')) {
      useCalls += 1; started.release(); if (holdUse) await gate.promise
      await route.fulfill({ json: { resume_id: RESUME_ID, title: 'Owned source' } }); finished.release(); return
    }
    return route.fulfill({ json: templateRows.find(row => path.endsWith(row.id)) })
  })
  return { gate, started, finished, catalogCalls: () => catalogCalls, useCalls: () => useCalls }
}

for (const authenticated of [false, true]) test(`B05 masks cached specialty cards/previews live and retains regular source download (authenticated=${authenticated})`, async ({ page }) => {
  const h = await fixture(page, TEMPLATE_FEATURES, authenticated ? 'owner-a' : null); const t = await templates(h)
  await page.goto('/templates')
  await expect(page.getByRole('button', { name: 'Preview academic template', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: 'Search templates' }).fill('template')
  await page.getByRole('button', { name: 'academic (1)', exact: true }).click()
  await page.getByRole('button', { name: 'Preview academic template', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'academic template', exact: true })).toBeVisible()
  await h.refreshGrants({ b05: false })
  await expect(page.getByRole('dialog')).toHaveCount(0)
  for (const category of ['academic', 'regional', 'presentation']) {
    await expect(page.getByRole('button', { name: `Preview ${category} template`, exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: `${category} (1)`, exact: true })).toHaveCount(0)
  }
  await expect(page.getByRole('button', { name: 'All (1)', exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Search templates' })).toHaveValue('template')
  expect(t.catalogCalls()).toBe(1); expect(t.useCalls()).toBe(0)
  await page.getByRole('button', { name: 'Preview professional template', exact: true }).click()
  const regular = page.getByRole('dialog', { name: 'professional template', exact: true })
  await expect(regular).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await regular.getByRole('button', { name: '.tex', exact: true }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('professional template.tex')
  expect(readFileSync((await download.path())!, 'utf8')).toBe(SOURCE)
  await regular.getByRole('button', { name: 'Close preview' }).click()
  await h.refreshGrants({ b05: true })
  await expect(page.getByRole('button', { name: 'Preview academic template', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preview professional template', exact: true })).toHaveCount(0)
  expect(t.catalogCalls()).toBe(1)
})

test('B05 revocation preserves the owned outcome of an already-admitted specialty creation', async ({ page }) => {
  const h = await fixture(page, TEMPLATE_FEATURES); const t = await templates(h, true)
  try {
    await page.goto('/templates')
    const academicCard = page.getByRole('heading', { name: 'academic template', exact: true }).locator('..').locator('..')
    await academicCard.getByRole('button', { name: 'Use Template', exact: true }).click(); await t.started.promise
    await h.refreshGrants({ b05: false })
    await expect(page.getByRole('button', { name: 'Preview academic template', exact: true })).toHaveCount(0)
    t.gate.release(); await t.finished.promise
    await expect(page).toHaveURL(new RegExp(`/workspace/${RESUME_ID}/edit$`))
    expect(t.useCalls()).toBe(1)
  } finally { t.gate.release() }
})


test('B05-disabled regular authenticated template creation remains permitted', async ({ page }) => {
  const h = await fixture(page, TEMPLATE_FEATURES); const t = await templates(h)
  h.state.features.b05 = false
  await page.goto('/templates')
  await expect(page.getByRole('button', { name: 'Preview academic template', exact: true })).toHaveCount(0)
  const regularCard = page.getByRole('heading', { name: 'professional template', exact: true }).locator('..').locator('..')
  await regularCard.getByRole('button', { name: 'Use Template', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/workspace/${RESUME_ID}/edit$`))
  expect(t.useCalls()).toBe(1)
})
