import { expect, test } from '@playwright/test'

const apiOrigin = new URL(process.env.PLAYWRIGHT_API_URL ?? process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT ?? '5181') + 2000}`).origin
const ID = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
const SOURCE = '\\documentclass{article}\n\\begin{document}\nSearchable text. Searchable text.\n\\end{document}'

test.use({ serviceWorkers: 'block' })
test('native find palette, selection shortcuts and stale actions respect capability revocation', async ({ page }) => {
  let features: Record<string, boolean> = {}
  await page.addInitScript(() => { localStorage.setItem('latexy_auto_compile', 'false'); localStorage.setItem('latexy_onboarding_completed', 'true') })
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); const path = url.pathname
    if (path === '/api/auth/get-session') return route.fulfill({ json: { session: { token: 'fixture-session' }, user: { id: 'owner', email: 'owner@example.test', name: 'Owner' } } })
    if (path.startsWith('/api/')) return route.fulfill({ json: {} })
    if (url.origin !== apiOrigin) return route.continue()
    if (path === '/config/entitlements') return route.fulfill({ json: { features } })
    if (path === '/config/feature-flags') return route.fulfill({ json: { billing: false } })
    if (path === '/me') return route.fulfill({ json: { id: 'owner', role: 'user', preferences: {} } })
    if (path === `/resumes/${ID}`) return route.fulfill({ json: { id: ID, user_id: 'owner', title: 'Search source', latex_content: SOURCE, access_role: 'owner', created_at: '2026-10-09T12:00:00Z', updated_at: '2026-10-09T12:00:00Z' } })
    if (path.includes('/checkpoints') || path.includes('/comments') || path.includes('/collaborators') || path.includes('/suggestions') || path === '/macros' || path === '/jobs') return route.fulfill({ json: [] })
    if (path.endsWith('/academic-cv-report')) return route.fulfill({ json: { is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 } })
    if (path.startsWith('/tenants/')) return route.fulfill({ json: { tenant: null } })
    if (path === '/subscription/current') return route.fulfill({ json: { userId: 'owner', planId: 'free', planName: 'Free', status: 'active', features: {} } })
    if (path.startsWith('/analytics') || path.startsWith('/public/trial') || ['/trial/status', '/github/status', '/dropbox/status', '/telemetry/frontend'].includes(path)) return route.fulfill({ json: {} })
    return route.fulfill({ status: 403, json: { detail: `Unmocked fixture endpoint: ${path}` } })
  })
  await page.routeWebSocket('**/ws/**', socket => socket.close())
  await page.goto(`/workspace/${ID}/edit`)
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue()), { timeout: 60_000 }).toBe(SOURCE)

  const visibleFindActions = () => page.evaluate(() => (window as any).__latexyMonacoEditor.getSupportedActions().filter((action: { id: string }) => /(?:actions\.find|MatchFindAction|SelectionMatchFindAction|startFindReplaceAction)/.test(action.id)).map((action: { id: string }) => action.id))
  await expect.poll(visibleFindActions).toEqual([])
  await page.evaluate(() => (window as any).__latexyMonacoEditor.focus())
  await page.keyboard.press('Control+F3')
  await page.keyboard.press('F3')
  await expect(page.locator('.find-widget.visible')).toHaveCount(0)
  await page.evaluate(() => (window as any).__latexyMonacoEditor.getAction('actions.find').run())
  await expect(page.locator('.find-widget.visible')).toHaveCount(0)

  features = { c03: true }
  await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
  await expect.poll(async () => (await visibleFindActions()).length).toBeGreaterThan(0)
  await page.evaluate(() => (window as any).__latexyMonacoEditor.getAction('actions.find').run())
  await expect(page.locator('.find-widget.visible')).toBeVisible()

  features = {}
  await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
  await expect(page.locator('.find-widget.visible')).toHaveCount(0)
  await expect.poll(visibleFindActions).toEqual([])
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor.getValue())).toBe(SOURCE)
  await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeEnabled()
})
