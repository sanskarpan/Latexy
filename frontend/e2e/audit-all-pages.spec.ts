/**
 * AUDIT-ONLY spec (not part of the normal suite).
 *
 * Walks every real page in the app as a genuinely authenticated user against a
 * live backend, and records: console errors, uncaught exceptions, failed network
 * requests, and whether the page rendered meaningful content or a blank/error
 * screen. Nothing is mocked — this is the "does the product actually work" pass.
 */
import { test, expect, Page, BrowserContext } from '@playwright/test'
import fs from 'fs'

const BE = process.env.AUDIT_BE ?? 'http://localhost:8030'
const ALICE = { email: 'audit.alice@example.com', password: 'AuditPassw0rd!alice' }

type Problem = {
  page: string
  kind: 'console' | 'pageerror' | 'requestfailed' | 'httperror' | 'blank' | 'errorui' | 'timeout'
  detail: string
}

const problems: Problem[] = []
const OUT = '/tmp/audit_pages.json'

function record(p: Problem) {
  problems.push(p)
}

/** Noise we do not want to report as product defects. */
function isNoise(text: string) {
  return (
    /favicon/i.test(text) ||
    /Download the React DevTools/i.test(text) ||
    /\[Fast Refresh\]/i.test(text) ||
    /webpack-hmr|_next\/static\/webpack|hot-update/i.test(text) ||
    /React Router Future Flag/i.test(text)
  )
}

function attach(page: Page, label: string) {
  page.on('console', (m) => {
    if (m.type() !== 'error' && m.type() !== 'warning') return
    const t = m.text()
    if (isNoise(t)) return
    record({ page: label, kind: 'console', detail: `[${m.type()}] ${t.slice(0, 400)}` })
  })
  page.on('pageerror', (e) => {
    record({ page: label, kind: 'pageerror', detail: String(e.message).slice(0, 400) })
  })
  page.on('requestfailed', (r) => {
    const f = r.failure()?.errorText ?? ''
    if (isNoise(r.url()) || /ERR_ABORTED/.test(f)) return
    record({ page: label, kind: 'requestfailed', detail: `${r.method()} ${r.url().slice(0, 160)} :: ${f}` })
  })
  page.on('response', (r) => {
    if (r.status() < 400) return
    if (isNoise(r.url())) return
    // 401 on a public page is meaningful signal, so keep it.
    record({ page: label, kind: 'httperror', detail: `${r.status()} ${r.request().method()} ${r.url().slice(0, 170)}` })
  })
}

/** Log in through the real Better Auth endpoint and persist cookies in the context. */
async function login(context: BrowserContext) {
  const res = await context.request.post('/api/auth/sign-in/email', {
    data: { email: ALICE.email, password: ALICE.password },
  })
  if (!res.ok()) {
    const body = await res.text()
    throw new Error(`login failed ${res.status()}: ${body.slice(0, 300)}`)
  }
}

let RESUME_ID = ''

test.beforeAll(async ({ playwright }) => {
  // Grab a resume id owned by Alice so workspace/* routes have real data.
  const ctx = await playwright.request.newContext({ baseURL: 'http://localhost:5180' })
  await ctx.post('/api/auth/sign-in/email', { data: { email: ALICE.email, password: ALICE.password } })
  const state = await ctx.storageState()
  const cookie = state.cookies.find((c) => c.name === 'better-auth.session_token')
  const r = await ctx.get(`${BE}/resumes/`, {
    headers: { Cookie: `better-auth.session_token=${cookie?.value ?? ''}` },
  })
  if (r.ok()) {
    const body = await r.json()
    const list = Array.isArray(body) ? body : body.resumes ?? body.items ?? []
    RESUME_ID = list[0]?.id ?? ''
  }
  console.log('AUDIT using RESUME_ID =', RESUME_ID || '(none found)')
  await ctx.dispose()
})

/** Every route a user can reach. `auth` marks pages that require a session. */
const ROUTES: { path: string; label: string; auth: boolean }[] = [
  { path: '/', label: 'landing', auth: false },
  { path: '/login', label: 'login', auth: false },
  { path: '/signup', label: 'signup', auth: false },
  { path: '/pricing', label: 'pricing', auth: false },
  { path: '/faq', label: 'faq', auth: false },
  { path: '/resources', label: 'resources', auth: false },
  { path: '/updates', label: 'updates', auth: false },
  { path: '/platform', label: 'platform', auth: false },
  { path: '/templates', label: 'templates', auth: false },
  { path: '/try', label: 'try (anonymous editor)', auth: false },
  { path: '/dashboard', label: 'dashboard', auth: true },
  { path: '/workspace', label: 'workspace list', auth: true },
  { path: '/workspace/new', label: 'workspace new', auth: true },
  { path: '/workspace/history', label: 'workspace history', auth: true },
  { path: '/workspace/merge', label: 'workspace merge', auth: true },
  { path: '/workspace/cover-letters', label: 'cover letters', auth: true },
  { path: '/workspace/builder/new', label: 'builder new', auth: true },
  { path: '/workspaces', label: 'workspaces (team)', auth: true },
  { path: '/tracker', label: 'tracker', auth: true },
  { path: '/settings', label: 'settings', auth: true },
  { path: '/billing', label: 'billing', auth: true },
  { path: '/byok', label: 'byok', auth: true },
  { path: '/developer', label: 'developer', auth: true },
  { path: '/admin', label: 'admin', auth: true },
  { path: '/admin/tenant', label: 'admin tenant', auth: true },
]

const RESUME_ROUTES = [
  { path: (id: string) => `/workspace/${id}/edit`, label: 'resume edit' },
  { path: (id: string) => `/workspace/${id}/optimize`, label: 'resume optimize' },
  { path: (id: string) => `/workspace/${id}/cover-letter`, label: 'resume cover-letter' },
  { path: (id: string) => `/workspace/${id}/career`, label: 'resume career' },
  { path: (id: string) => `/workspace/${id}/batch-tailor`, label: 'resume batch-tailor' },
  { path: (id: string) => `/workspace/builder/${id}`, label: 'builder edit' },
]

async function visit(page: Page, url: string, label: string) {
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 })
  } catch (e) {
    record({ page: label, kind: 'timeout', detail: `goto failed: ${String(e).slice(0, 250)}` })
    return
  }
  // Let client-side data fetching settle.
  await page.waitForTimeout(3500)

  const body = await page.evaluate(() => ({
    text: (document.body?.innerText ?? '').trim(),
    html: (document.body?.innerHTML ?? '').length,
  }))

  if (body.text.length < 40) {
    record({ page: label, kind: 'blank', detail: `rendered only ${body.text.length} chars of text (html ${body.html}b): ${JSON.stringify(body.text.slice(0, 120))}` })
  }

  // Next.js error overlay / generic crash UI
  const crash = /Application error: a client-side exception|Unhandled Runtime Error|This page could not be found|Internal Server Error|something went wrong/i
  if (crash.test(body.text)) {
    record({ page: label, kind: 'errorui', detail: body.text.slice(0, 300).replace(/\s+/g, ' ') })
  }

  await page.screenshot({ path: `/tmp/audit_shots/${label.replace(/[^a-z0-9]+/gi, '_')}.png`, fullPage: false }).catch(() => {})
}

test.describe.configure({ mode: 'serial' })

test('audit: anonymous pages', async ({ browser }) => {
  test.setTimeout(600_000)
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  for (const r of ROUTES.filter((x) => !x.auth)) {
    attach(page, `ANON ${r.label}`)
    await visit(page, r.path, `ANON ${r.label}`)
  }
  await ctx.close()
})

test('audit: authenticated pages', async ({ browser }) => {
  test.setTimeout(900_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  for (const r of ROUTES.filter((x) => x.auth)) {
    attach(page, `AUTH ${r.label}`)
    await visit(page, r.path, `AUTH ${r.label}`)
  }
  await ctx.close()
})

test('audit: resume-scoped pages', async ({ browser }) => {
  test.setTimeout(900_000)
  test.skip(!RESUME_ID, 'no resume available')
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  for (const r of RESUME_ROUTES) {
    attach(page, `AUTH ${r.label}`)
    await visit(page, r.path(RESUME_ID), `AUTH ${r.label}`)
  }
  await ctx.close()
})

test('audit: protected routes redirect when anonymous', async ({ browser }) => {
  test.setTimeout(300_000)
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  const leaks: string[] = []
  for (const r of ROUTES.filter((x) => x.auth)) {
    await page.goto(r.path, { waitUntil: 'domcontentloaded' }).catch(() => {})
    await page.waitForTimeout(1500)
    const url = page.url()
    const txt = (await page.evaluate(() => document.body?.innerText ?? '')).slice(0, 200)
    const redirected = /\/login|\/signup/.test(url)
    if (!redirected) {
      leaks.push(`${r.path} -> stayed at ${url} :: ${txt.replace(/\s+/g, ' ').slice(0, 120)}`)
    }
  }
  fs.writeFileSync('/tmp/audit_authgate.json', JSON.stringify(leaks, null, 2))
  console.log('\n=== PROTECTED ROUTES NOT REDIRECTING ANONYMOUS USERS ===')
  leaks.forEach((l) => console.log('  ' + l))
  await ctx.close()
})

test.afterAll(() => {
  fs.mkdirSync('/tmp/audit_shots', { recursive: true })
  fs.writeFileSync(OUT, JSON.stringify(problems, null, 2))

  const byPage = new Map<string, Problem[]>()
  for (const p of problems) {
    if (!byPage.has(p.page)) byPage.set(p.page, [])
    byPage.get(p.page)!.push(p)
  }
  console.log('\n\n============ PAGE AUDIT RESULTS ============')
  console.log(`total problems: ${problems.length} across ${byPage.size} pages\n`)
  for (const [pg, list] of byPage) {
    console.log(`\n### ${pg}  (${list.length})`)
    const seen = new Set<string>()
    for (const p of list) {
      const k = p.kind + p.detail.slice(0, 120)
      if (seen.has(k)) continue
      seen.add(k)
      console.log(`   [${p.kind}] ${p.detail}`)
    }
  }
})
