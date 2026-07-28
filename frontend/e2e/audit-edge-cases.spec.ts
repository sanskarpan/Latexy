/**
 * AUDIT-ONLY: edge cases and sad paths a real user hits.
 */
import { test, expect, BrowserContext, Page } from '@playwright/test'

const ALICE = { email: 'audit.alice@example.com', password: 'AuditPassw0rd!alice' }

async function login(ctx: BrowserContext) {
  const r = await ctx.request.post('/api/auth/sign-in/email', { data: ALICE })
  expect(r.ok()).toBeTruthy()
}

async function pageText(page: Page) {
  return (await page.evaluate(() => document.body?.innerText ?? '')).replace(/\s+/g, ' ').trim()
}

test.describe.configure({ mode: 'serial' })

test('sad path: nonexistent / malformed resume ids in the URL', async ({ browser }) => {
  test.setTimeout(300_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const page = await ctx.newPage()
  const cases = [
    ['/workspace/00000000-0000-0000-0000-000000000000/edit', 'valid-uuid but nonexistent'],
    ['/workspace/not-a-uuid/edit', 'malformed id'],
    ['/workspace/..%2F..%2Fetc%2Fpasswd/edit', 'traversal-ish id'],
    ['/workspace/00000000-0000-0000-0000-000000000000/optimize', 'nonexistent optimize'],
    ['/workspace/builder/00000000-0000-0000-0000-000000000000', 'nonexistent builder'],
  ]
  for (const [url, label] of cases) {
    const errs: string[] = []
    page.on('pageerror', (e) => errs.push(e.message))
    await page.goto(url, { waitUntil: 'domcontentloaded' }).catch(() => {})
    await page.waitForTimeout(4000)
    const t = await pageText(page)
    const helpful = /not found|doesn't exist|does not exist|no longer available|go back|return to/i.test(t)
    console.log(`\n### ${label} (${url})`)
    console.log(`   url now: ${page.url()}`)
    console.log(`   shows a helpful not-found message: ${helpful}`)
    console.log(`   uncaught page errors: ${errs.length ? JSON.stringify(errs.slice(0, 2)) : 'none'}`)
    console.log(`   text: ${t.slice(0, 260)}`)
    await page.screenshot({ path: `/tmp/audit_shots/sad_${label.replace(/\W+/g, '_')}.png` })
  }
  await ctx.close()
})

test('sad path: invalid and revoked share tokens', async ({ browser }) => {
  test.setTimeout(300_000)
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  for (const [tok, label] of [
    ['totally-invalid-token-xyz', 'invalid token'],
    ['', 'empty token'],
    ['../../etc/passwd', 'traversal token'],
  ]) {
    await page.goto(`/r/${encodeURIComponent(tok)}`, { waitUntil: 'domcontentloaded' }).catch(() => {})
    await page.waitForTimeout(3500)
    const t = await pageText(page)
    console.log(`\n### share ${label}: url=${page.url()}`)
    console.log(`   text: ${t.slice(0, 250)}`)
  }
  await ctx.close()
})

test('share link happy path: anonymous visitor can view a shared resume', async ({ browser }) => {
  test.setTimeout(300_000)
  const actx = await browser.newContext()
  await login(actx)
  // create a fresh share link
  const list = await (await actx.request.get('http://localhost:8030/resumes/')).json()
  const arr = Array.isArray(list) ? list : list.resumes ?? []
  const id = arr[0]?.id
  test.skip(!id, 'no resume')
  const sres = await actx.request.post(`http://localhost:8030/resumes/${id}/share`, { data: {} })
  const sbody = await sres.json().catch(() => ({}))
  const token = sbody.share_token ?? sbody.token
  console.log('share create ->', sres.status(), JSON.stringify(sbody).slice(0, 250))
  test.skip(!token, 'no share token')

  // anonymous context
  const anon = await browser.newContext()
  const page = await anon.newPage()
  const errs: string[] = []
  page.on('pageerror', (e) => errs.push(e.message))
  const bad: string[] = []
  page.on('response', (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().replace('http://localhost:8030', '')}`) })

  await page.goto(`/r/${token}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  const t = await pageText(page)
  console.log('\n### shared view as anonymous')
  console.log('   text:', t.slice(0, 500))
  console.log('   shows resume owner content:', /Alice Auditor|ExampleCorp/i.test(t))
  console.log('   failed requests:', JSON.stringify(bad.slice(0, 8)))
  console.log('   page errors:', JSON.stringify(errs.slice(0, 3)))
  await page.screenshot({ path: '/tmp/audit_shots/share_view.png', fullPage: true })

  // revoke, then re-check
  await actx.request.delete(`http://localhost:8030/resumes/${id}/share`)
  await page.goto(`/r/${token}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  const t2 = await pageText(page)
  console.log('\n### after revoke, same link')
  console.log('   still leaks content:', /Alice Auditor|ExampleCorp/i.test(t2))
  console.log('   text:', t2.slice(0, 250))
  await anon.close()
  await actx.close()
})

test('trial system: anonymous compile limit and whether it is bypassable', async ({ browser }) => {
  test.setTimeout(600_000)
  // Fresh anonymous context => fresh fingerprint
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)

  const readTrials = async () => {
    const t = await pageText(page)
    const m = t.match(/TRIALS LEFT\s*(\d+)/i)
    return m ? m[1] : `unparsed(${t.match(/TRIALS[^|]{0,30}/i)?.[0] ?? '?'})`
  }
  console.log('trials at start:', await readTrials())

  const status = await ctx.request.get('http://localhost:8030/public/trial-status')
  console.log('GET /public/trial-status ->', status.status(), (await status.text()).slice(0, 300))

  // Compile repeatedly and watch the counter / the block
  for (let i = 1; i <= 5; i++) {
    const btn = page.getByRole('button', { name: /^Compile/i }).first()
    if (await btn.count() === 0) { console.log('no compile button'); break }
    const disabled = await btn.isDisabled().catch(() => false)
    console.log(`\nattempt ${i}: button disabled=${disabled}, trials left=${await readTrials()}`)
    if (disabled) { console.log('  -> blocked by UI'); break }
    await btn.click().catch(() => {})
    await page.waitForTimeout(18_000)
    const t = await pageText(page)
    const blocked = /trial|limit|sign up|upgrade|exhausted/i.test(t)
    console.log(`  after compile: trials=${await readTrials()}, mentions limit/upsell=${blocked}`)
  }
  await page.screenshot({ path: '/tmp/audit_shots/trial_exhausted.png', fullPage: true })

  // Can a brand-new context (new fingerprint) get fresh trials? -> bypass check
  const ctx2 = await browser.newContext()
  const p2 = await ctx2.newPage()
  await p2.goto('/try', { waitUntil: 'domcontentloaded' })
  await p2.waitForTimeout(4000)
  const t2 = await pageText(p2)
  const m2 = t2.match(/TRIALS LEFT\s*(\d+)/i)
  console.log('\n### fresh browser context trials left:', m2?.[1] ?? 'unparsed')
  console.log('   (if this resets to the full quota, the trial gate is bypassable by clearing storage)')
  await ctx2.close()
  await ctx.close()
})
