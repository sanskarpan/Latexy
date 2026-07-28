/**
 * AUDIT-ONLY: interactive / event-driven flows against a live backend.
 *
 * Proves (or disproves) whether real user actions produce real results:
 * compile -> WebSocket events -> PDF in the UI, ATS scoring completion,
 * auto-save, and how many requests a single page load fires (rate-limit budget).
 */
import { test, expect, Page, BrowserContext } from '@playwright/test'
import fs from 'fs'

const ALICE = { email: 'audit.alice@example.com', password: 'AuditPassw0rd!alice' }

async function login(context: BrowserContext) {
  const res = await context.request.post('/api/auth/sign-in/email', {
    data: { email: ALICE.email, password: ALICE.password },
  })
  expect(res.ok(), `login failed: ${res.status()}`).toBeTruthy()
}

type Net = { method: string; url: string; status: number }

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

test('requests fired by one dashboard load (rate-limit budget)', async ({ browser }) => {
  test.setTimeout(180_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  const net: Net[] = []
  trackNet(page, net)
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  const api = net.filter((n) => n.url.includes(':8030'))
  console.log(`\n=== BACKEND REQUESTS FROM ONE /dashboard LOAD: ${api.length} ===`)
  const counts = new Map<string, number>()
  for (const a of api) {
    const key = `${a.method} ${a.url.replace(/http:\/\/localhost:8030/, '').split('?')[0]} [${a.status}]`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  ;[...counts.entries()].sort((x, y) => y[1] - x[1]).forEach(([k, v]) => console.log(`  ${v}x ${k}`))
  const limited = api.filter((a) => a.status === 429)
  console.log(`429s during a single page load: ${limited.length}`)
  await ctx.close()
})

test('anonymous /try: compile a resume end-to-end and watch WS events', async ({ browser }) => {
  test.setTimeout(420_000)
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  const frames: string[] = []
  const net: Net[] = []
  trackWs(page, frames)
  trackNet(page, net)

  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(5000)
  await page.screenshot({ path: '/tmp/audit_shots/try_initial.png', fullPage: true })

  const bodyText = await page.evaluate(() => document.body.innerText)
  console.log('\n=== /try page text (first 1200 chars) ===\n' + bodyText.slice(0, 1200))

  // Find the compile affordance by accessible name.
  const candidates = ['Compile', 'Preview', 'Build', 'Generate PDF', 'Run']
  let clicked = ''
  for (const name of candidates) {
    const btn = page.getByRole('button', { name: new RegExp(name, 'i') }).first()
    if (await btn.count() > 0 && await btn.isVisible().catch(() => false)) {
      await btn.click().catch(() => {})
      clicked = name
      break
    }
  }
  console.log('clicked compile-ish button:', clicked || 'NONE FOUND')

  const allButtons = await page.getByRole('button').all()
  const names: string[] = []
  for (const b of allButtons.slice(0, 60)) {
    const t = (await b.textContent().catch(() => '')) ?? ''
    const al = (await b.getAttribute('aria-label').catch(() => '')) ?? ''
    if (t.trim() || al) names.push((t.trim() || al).slice(0, 40))
  }
  console.log('buttons present on /try:', JSON.stringify(names))

  await page.waitForTimeout(35_000)
  await page.screenshot({ path: '/tmp/audit_shots/try_after_compile.png', fullPage: true })

  const compileCalls = net.filter((n) => /compile|jobs/.test(n.url) && n.url.includes(':8030'))
  console.log('\n=== compile-related backend calls ===')
  compileCalls.forEach((c) => console.log(`  ${c.status} ${c.method} ${c.url.replace('http://localhost:8030', '')}`))

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
  fs.writeFileSync('/tmp/audit_try_frames.json', JSON.stringify({ frames, compileCalls }, null, 2))
  await ctx.close()
})

test('authenticated editor: compile + ATS score, does the UI ever finish?', async ({ browser }) => {
  test.setTimeout(600_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  const frames: string[] = []
  const net: Net[] = []
  trackWs(page, frames)
  trackNet(page, net)

  // Grab a resume id
  const r = await ctx.request.get('http://localhost:8030/resumes/')
  const body = await r.json().catch(() => ({}))
  const list = Array.isArray(body) ? body : body.resumes ?? body.items ?? []
  const id = list[0]?.id
  console.log('editing resume:', id)
  test.skip(!id, 'no resume')

  await page.goto(`/workspace/${id}/edit`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(8000)
  await page.screenshot({ path: '/tmp/audit_shots/editor_initial.png', fullPage: true })

  const txt = await page.evaluate(() => document.body.innerText)
  console.log('\n=== editor page text (first 1500) ===\n' + txt.slice(0, 1500))

  const btns: string[] = []
  for (const b of (await page.getByRole('button').all()).slice(0, 80)) {
    const t = ((await b.textContent().catch(() => '')) ?? '').trim()
    const al = (await b.getAttribute('aria-label').catch(() => '')) ?? ''
    if (t || al) btns.push((t || al).slice(0, 45))
  }
  console.log('\nbuttons in editor:', JSON.stringify(btns))

  // Try to trigger a compile
  for (const name of ['Compile', 'Preview', 'Build']) {
    const b = page.getByRole('button', { name: new RegExp(`^${name}`, 'i') }).first()
    if (await b.count() > 0 && await b.isVisible().catch(() => false)) {
      console.log('clicking', name)
      await b.click().catch(() => {})
      break
    }
  }
  await page.waitForTimeout(40_000)
  await page.screenshot({ path: '/tmp/audit_shots/editor_after_compile.png', fullPage: true })

  console.log('\n=== WS FRAMES (authenticated editor) ===')
  frames.slice(0, 80).forEach((f) => console.log('  ' + f))
  if (!frames.length) console.log('  (NO WEBSOCKET ACTIVITY AT ALL)')

  console.log('\n=== backend calls ===')
  const seen = new Map<string, number>()
  net.filter((n) => n.url.includes(':8030')).forEach((n) => {
    const k = `${n.status} ${n.method} ${n.url.replace('http://localhost:8030', '').split('?')[0]}`
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
  fs.writeFileSync('/tmp/audit_editor_frames.json', JSON.stringify({ frames, net: [...seen] }, null, 2))
  await ctx.close()
})
