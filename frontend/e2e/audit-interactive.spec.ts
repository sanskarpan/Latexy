/**
 * AUDIT-ONLY: interactive / event-driven flows against a live backend.
 *
 * Proves (or disproves) whether real user actions produce real results:
 * compile -> WebSocket events -> PDF in the UI, ATS scoring completion,
 * auto-save, and how many requests a single page load fires (rate-limit budget).
 */
import { test, expect, Page, BrowserContext } from '@playwright/test'
import fs from 'fs'
import os from 'os'
import path from 'path'

const ALICE = { email: 'audit.alice@example.com', password: 'AuditPassw0rd!alice' }
const BE = process.env.AUDIT_BE ?? 'http://localhost:8030'
const backendOrigin = new URL(BE).origin
const AUDIT_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'latexy-interactive-audit-'))
const SHOT_DIR = path.join(AUDIT_DIR, 'screenshots')

async function login(context: BrowserContext) {
  const res = await context.request.post('/api/auth/sign-in/email', {
    data: { email: ALICE.email, password: ALICE.password },
  })
  expect(res.ok(), `login failed: ${res.status()}`).toBeTruthy()
}

type Net = { method: string; url: string; status: number }

function isBackendUrl(url: string) {
  try {
    return new URL(url).origin === backendOrigin
  } catch {
    return false
  }
}

function backendPath(url: string) {
  const parsed = new URL(url)
  return `${parsed.pathname}${parsed.search}`
}

function trackNet(page: Page, sink: Net[]) {
  page.on('response', async (r) => {
    sink.push({ method: r.request().method(), url: r.url(), status: r.status() })
  })
}

/** Capture WS frames the page actually receives. */
function trackWs(page: Page, frames: string[]) {
  page.on('websocket', (ws) => {
    frames.push(`>>> WS OPEN ${ws.url()}`)
    ws.on('framereceived', (f) => {
      const d = typeof f.payload === 'string' ? f.payload : f.payload.toString()
      frames.push(`<-- ${d.slice(0, 500)}`)
    })
    ws.on('framesent', (f) => {
      const d = typeof f.payload === 'string' ? f.payload : f.payload.toString()
      frames.push(`--> ${d.slice(0, 300)}`)
    })
    ws.on('close', () => frames.push(`<<< WS CLOSED ${ws.url()}`))
    ws.on('socketerror', (e) => frames.push(`!!! WS ERROR ${e}`))
  })
}

test.describe.configure({ mode: 'serial' })

test.beforeAll(() => {
  fs.mkdirSync(SHOT_DIR, { mode: 0o700 })
})

test('requests fired by one dashboard load (rate-limit budget)', async ({ browser }) => {
  test.setTimeout(180_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  const net: Net[] = []
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  trackNet(page, net)
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  const api = net.filter((n) => isBackendUrl(n.url))
  console.log(`\n=== BACKEND REQUESTS FROM ONE /dashboard LOAD: ${api.length} ===`)
  const counts = new Map<string, number>()
  for (const a of api) {
    const key = `${a.method} ${new URL(a.url).pathname} [${a.status}]`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  ;[...counts.entries()].sort((x, y) => y[1] - x[1]).forEach(([k, v]) => console.log(`  ${v}x ${k}`))
  const limited = api.filter((a) => a.status === 429)
  console.log(`429s during a single page load: ${limited.length}`)
  expect(api.length, 'dashboard made no backend requests').toBeGreaterThan(0)
  expect(limited, 'dashboard exhausted a rate-limit bucket').toEqual([])
  expect(api.filter((request) => request.status >= 500), 'dashboard received a server error').toEqual([])
  expect(pageErrors, 'dashboard raised uncaught browser errors').toEqual([])
  await ctx.close()
})

test('anonymous /try: compile a resume end-to-end and watch WS events', async ({ browser }) => {
  test.setTimeout(420_000)
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  const frames: string[] = []
  const net: Net[] = []
  const pageErrors: string[] = []
  trackWs(page, frames)
  trackNet(page, net)
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)
  await page.screenshot({ path: path.join(SHOT_DIR, 'try_initial.png'), fullPage: true })

  const bodyText = await page.evaluate(() => document.body.innerText)
  console.log('\n=== /try page text (first 1200 chars) ===\n' + bodyText.slice(0, 1200))

  const compileButton = page.getByRole('button', { name: /^(re)?compile\b/i }).first()
  await expect(compileButton).toBeVisible()
  await expect(compileButton).toBeEnabled()
  const submitted = page.waitForResponse(
    (response) => response.url().includes('/jobs/submit') && response.request().method() === 'POST',
  )
  await compileButton.click()
  expect((await submitted).status()).toBe(200)

  const allButtons = await page.getByRole('button').all()
  const names: string[] = []
  for (const b of allButtons.slice(0, 60)) {
    const t = (await b.textContent().catch(() => '')) ?? ''
    const al = (await b.getAttribute('aria-label').catch(() => '')) ?? ''
    if (t.trim() || al) names.push((t.trim() || al).slice(0, 40))
  }
  console.log('buttons present on /try:', JSON.stringify(names))

  await expect(page.locator('.react-pdf__Page__canvas').first()).toBeVisible({ timeout: 180_000 })
  await page.screenshot({ path: path.join(SHOT_DIR, 'try_after_compile.png'), fullPage: true })

  const compileCalls = net.filter((n) => /compile|jobs/.test(n.url) && isBackendUrl(n.url))
  console.log('\n=== compile-related backend calls ===')
  compileCalls.forEach((c) => console.log(`  ${c.status} ${c.method} ${backendPath(c.url)}`))

  console.log('\n=== WS FRAMES OBSERVED ===')
  frames.slice(0, 60).forEach((f) => console.log('  ' + f))
  if (!frames.length) console.log('  (NO WEBSOCKET ACTIVITY AT ALL)')

  // Did a PDF ever render?
  const pdfPresent = await page.evaluate(() => {
    const has = (sel: string) => !!document.querySelector(sel)
    return {
      canvas: document.querySelectorAll('canvas').length,
      iframe: document.querySelectorAll('iframe').length,
      embed: has('embed') || has('object'),
      textMentionsError: /error|failed/i.test(document.body.innerText),
    }
  })
  console.log('\npdf surface after compile:', JSON.stringify(pdfPresent))
  expect(compileCalls.some((request) => request.status === 200 && request.url.includes('/jobs/submit'))).toBe(true)
  expect(compileCalls.filter((request) => request.status >= 400)).toEqual([])
  expect(frames.some((frame) => /completed/i.test(frame)), 'no terminal completion arrived over WebSocket').toBe(true)
  expect(pdfPresent.canvas).toBeGreaterThan(0)
  expect(pdfPresent.textMentionsError).toBe(false)
  expect(pageErrors).toEqual([])
  fs.writeFileSync(path.join(AUDIT_DIR, 'audit_try_frames.json'), JSON.stringify({ frames, compileCalls }, null, 2), { mode: 0o600 })
  await ctx.close()
})

test('authenticated editor: compile + ATS score, does the UI ever finish?', async ({ browser }) => {
  test.setTimeout(600_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  const frames: string[] = []
  const net: Net[] = []
  const pageErrors: string[] = []
  trackWs(page, frames)
  trackNet(page, net)
  page.on('pageerror', (error) => pageErrors.push(error.message))

  // Grab a resume id
  const r = await ctx.request.get(`${BE}/resumes/`)
  const body = await r.json().catch(() => ({}))
  const list = Array.isArray(body) ? body : body.resumes ?? body.items ?? []
  // The editor intentionally skips initial compile and quick ATS scoring for
  // tiny documents. Pick a realistic fixture so this audit exercises both
  // pipelines instead of hanging on a short security-test résumé.
  const candidate = list.find((resume: { latex_content?: string }) =>
    (resume.latex_content?.length ?? 0) >= 200,
  )
  const id = candidate?.id
  console.log('editing resume:', id)
  test.skip(!id, 'no resume')

  // The editor intentionally auto-compiles a loaded résumé. Install every
  // listener before navigation so a fast local worker cannot finish before the
  // assertion starts observing the network.
  const submitted = page.waitForResponse(
    (response) => response.url().includes('/jobs/submit') && response.request().method() === 'POST',
  )
  const quickScore = page.waitForResponse(
    (response) => response.url().includes('/ats/quick-score') && response.request().method() === 'POST',
  )
  const synctex = page.waitForResponse(
    (response) => /\/download\/[^/]+\/synctex$/.test(new URL(response.url()).pathname),
  )
  await page.goto(`/workspace/${id}/edit`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(8000)
  await page.screenshot({ path: path.join(SHOT_DIR, 'editor_initial.png'), fullPage: true })

  const txt = await page.evaluate(() => document.body.innerText)
  console.log('\n=== editor page text (first 1500) ===\n' + txt.slice(0, 1500))

  const btns: string[] = []
  for (const b of (await page.getByRole('button').all()).slice(0, 80)) {
    const t = ((await b.textContent().catch(() => '')) ?? '').trim()
    const al = (await b.getAttribute('aria-label').catch(() => '')) ?? ''
    if (t || al) btns.push((t || al).slice(0, 45))
  }
  console.log('\nbuttons in editor:', JSON.stringify(btns))

  expect((await submitted).status()).toBe(200)
  await expect(page.locator('.react-pdf__Page__canvas').first()).toBeVisible({ timeout: 180_000 })
  expect((await quickScore).status()).toBe(200)
  expect((await synctex).status()).toBe(200)
  await expect(page.getByText(/Ctrl\+click to sync/i)).toBeVisible({ timeout: 30_000 })
  await page.screenshot({ path: path.join(SHOT_DIR, 'editor_after_compile.png'), fullPage: true })

  console.log('\n=== WS FRAMES (authenticated editor) ===')
  frames.slice(0, 80).forEach((f) => console.log('  ' + f))
  if (!frames.length) console.log('  (NO WEBSOCKET ACTIVITY AT ALL)')

  console.log('\n=== backend calls ===')
  const seen = new Map<string, number>()
  net.filter((n) => isBackendUrl(n.url)).forEach((n) => {
    const k = `${n.status} ${n.method} ${new URL(n.url).pathname}`
    seen.set(k, (seen.get(k) ?? 0) + 1)
  })
  ;[...seen.entries()].sort((a, b) => b[1] - a[1]).forEach(([k, v]) => console.log(`  ${v}x ${k}`))

  // Look for a spinner still spinning / stuck progress
  const stuck = await page.evaluate(() => {
    const t = document.body.innerText
    return {
      mentionsCompiling: /compiling|processing|scoring|analyzing|in progress/i.test(t),
      mentionsError: /error|failed|something went wrong/i.test(t),
      spinners: document.querySelectorAll('[class*="animate-spin"],[role="progressbar"]').length,
    }
  })
  console.log('\nUI state after 40s:', JSON.stringify(stuck))
  const backendFailures = net.filter((request) => isBackendUrl(request.url) && request.status >= 400)
  expect(backendFailures).toEqual([])
  expect(frames.some((frame) => /completed/i.test(frame)), 'no terminal completion arrived over WebSocket').toBe(true)
  expect(stuck.mentionsCompiling).toBe(false)
  expect(stuck.mentionsError).toBe(false)
  expect(pageErrors).toEqual([])
  fs.writeFileSync(path.join(AUDIT_DIR, 'audit_editor_frames.json'), JSON.stringify({ frames, net: [...seen] }, null, 2), { mode: 0o600 })
  await ctx.close()
})
