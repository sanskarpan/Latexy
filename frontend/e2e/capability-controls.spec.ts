import { expect, test, type Page } from '@playwright/test'

const backendOrigin = new URL(process.env.PLAYWRIGHT_API_URL ?? process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT ?? '5181') + 2000}`).origin
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { AdminEntitlementsState, EntitlementFeatureDef } from '../src/lib/api-client'
const ID = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
const SOURCE = '\\documentclass{article}\n\\begin{document}\nKeep this source.\n\\end{document}'
const catalog = JSON.parse(readFileSync(resolve(__dirname, '../../backend/app/core/capability_catalog.json'), 'utf8')) as EntitlementFeatureDef[]
const parents = [...new Set(catalog.map((item) => item.parent_key).filter(Boolean))].map((key) => ({ key: key!, label: key!, category: 'Parents', gateable: true }))
const registry = [...parents, ...catalog]
const families = ['free', 'basic', 'pro', 'byok', 'team']
const keys = [...families, 'pro_annual', 'basic_annual', 'byok_annual', 'student', 'weekly', 'lifetime']
test.use({ serviceWorkers: 'block' })
async function fixture(page: Page) {
  let features = Object.fromEntries(registry.map((item) => [item.key, true]))
  let failed = false
  const state: AdminEntitlementsState = { registry, plan_families: families, plan_keys: keys,
    plan_family_by_key: Object.fromEntries(keys.map((key) => [key, ['student', 'weekly', 'lifetime'].includes(key) ? 'pro' : key.split('_')[0]])),
    kill_switches: Object.fromEntries(registry.map((item) => [item.key, true])),
    matrix: Object.fromEntries(keys.map((key) => [key, Object.fromEntries(registry.map((item) => [item.key, true]))])),
  }
  await page.addInitScript(() => { localStorage.setItem('latexy_auto_compile', 'false'); localStorage.setItem('latexy_onboarding_completed', 'true') })
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url()); const path = url.pathname
    if (path === '/api/auth/get-session') return route.fulfill({ json: { session: { token: 'fixture-session' }, user: { id: 'owner', email: 'owner@example.test', name: 'Owner' } } })
    if (path.startsWith('/api/')) return route.fulfill({ json: {} })
    if (url.origin !== backendOrigin) return route.continue()
    if (path === '/config/entitlements') return route.fulfill({ status: failed ? 503 : 200, json: failed ? { detail: 'Synthetic failure' } : { features } })
    if (path === '/config/feature-flags') return route.fulfill({ json: { billing: false } })
    if (path === '/admin/feature-flags') return route.fulfill({ json: [{ key: 'billing', label: 'Billing', enabled: false }] })
    if (path === '/admin/entitlements') return route.fulfill({ json: state })
    if (path === '/me') return route.fulfill({ json: { id: 'owner', role: 'admin', preferences: {} } })
    if (path === `/resumes/${ID}`) return route.fulfill({ json: { id: ID, user_id: 'owner', title: 'Safe source', latex_content: SOURCE, access_role: 'owner', created_at: '2026-10-09T12:00:00Z', updated_at: '2026-10-09T12:00:00Z' } })
    if (path.includes('/checkpoints') || path.includes('/comments') || path.includes('/collaborators') || path.includes('/suggestions') || path === '/macros' || path === '/jobs') return route.fulfill({ json: [] })
    if (path.endsWith('/academic-cv-report')) return route.fulfill({ json: { is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 } })
    if (path.startsWith('/tenants/')) return route.fulfill({ json: { tenant: null } })
    if (path === '/subscription/current') return route.fulfill({ json: { userId: 'owner', planId: 'free', planName: 'Free', status: 'active', features: {} } })
    if (path === '/ats/quick-score') return route.fulfill({ json: { score: 70, grade: 'C', sections_found: [], missing_sections: [] } })
    if (path === '/ws/ticket') return route.fulfill({ status: 403, json: { detail: 'Synthetic socket disabled' } })
    if (path.startsWith('/analytics') || path.startsWith('/public/trial') || ['/trial/status', '/github/status', '/dropbox/status', '/telemetry/frontend'].includes(path)) return route.fulfill({ json: {} })
    return route.fulfill({ status: 403, json: { detail: `Unmocked fixture endpoint: ${path}` } })
  })
  await page.routeWebSocket('**/ws/**', (socket) => socket.close())
  return { state, setFeatures: (next: Record<string, boolean>) => { features = next }, fail: () => { failed = true }, refresh: () => page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated'))) }
}

test('admin searches all audited features and explains immutable and individual-plan controls', async ({ page }, testInfo) => {
  await fixture(page)
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: 'Capability inventory' })).toBeVisible()
  await expect(page.getByText('129 audited features', { exact: false })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search capabilities' }).fill('a02')
  await expect(page.getByText('Authentication, account verification and recovery are security baselines.')).toBeVisible()
  await expect(page.getByRole('switch')).toHaveCount(0)
  await page.getByRole('searchbox', { name: 'Search capabilities' }).fill('b03')
  await expect(page.getByRole('switch', { name: 'Cross-document search global kill-switch' })).toBeVisible()
  await page.getByRole('button', { name: 'Individual plans' }).click()
  await expect(page.getByRole('columnheader', { name: 'pro annual', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('capability-admin.png'), fullPage: true })
})

test('editor gates optional keyboard and toolbar features while preserving source and manual compile', async ({ page }, testInfo) => {
  const f = await fixture(page); f.setFeatures({})
  await page.goto(`/workspace/${ID}/edit`)
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue()), { timeout: 60_000 }).toBe(SOURCE)
  await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Auto-compile on change', exact: true })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Editor keybindings' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'LaTeX search presets' })).toHaveCount(0)
  await page.evaluate(() => (window as any).__latexyMonacoEditor.focus()); await page.keyboard.press('Control+f')
  await expect(page.locator('.find-widget.visible')).toHaveCount(0)
  f.setFeatures({ c03: true, c04: true, c06: true }); await f.refresh()
  await expect(page.getByRole('button', { name: 'LaTeX search presets' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Editor keybindings' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Auto-compile on change', exact: true })).toBeVisible()
  await page.evaluate(() => (window as any).__latexyMonacoEditor.focus()); await page.keyboard.press('Control+f')
  await expect(page.locator('.find-widget.visible')).toBeVisible(); await page.keyboard.press('Escape')
  f.fail(); await f.refresh()
  await expect(page.getByRole('button', { name: 'Auto-compile on change', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor.getValue())).toBe(SOURCE)
  await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeEnabled()
  await page.screenshot({ path: testInfo.outputPath('capability-editor.png'), fullPage: true })
})
