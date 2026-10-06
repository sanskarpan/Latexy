/**
 * AUDIT-ONLY: edge cases and sad paths a real user hits.
 */
import { test, expect, BrowserContext, Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

const ALICE = { email: 'audit.alice@example.com', password: 'AuditPassw0rd!alice' }
const BE = process.env.AUDIT_BE ?? 'http://localhost:8030'

async function login(ctx: BrowserContext) {
  const r = await ctx.request.post('/api/auth/sign-in/email', { data: ALICE })
  expect(r.ok()).toBeTruthy()
}

async function pageText(page: Page) {
  return (await page.evaluate(() => document.body?.innerText ?? '')).replace(/\s+/g, ' ').trim()
}

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  await mkdir('/tmp/audit_shots', { recursive: true })
})

test('sad path: nonexistent / malformed resume ids in the URL', async ({ browser }) => {
  test.setTimeout(300_000)
  const ctx = await browser.newContext()
  await login(ctx)
  const cases = [
    ['/workspace/00000000-0000-0000-0000-000000000000/edit', 'valid-uuid but nonexistent'],
    ['/workspace/not-a-uuid/edit', 'malformed id'],
    ['/workspace/..%2F..%2Fetc%2Fpasswd/edit', 'traversal-ish id'],
    ['/workspace/00000000-0000-0000-0000-000000000000/optimize', 'nonexistent optimize'],
    ['/workspace/builder/00000000-0000-0000-0000-000000000000', 'nonexistent builder'],
  ]
  for (const [url, label] of cases) {
    const page = await ctx.newPage()
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
    expect(helpful, `${label} did not explain how to recover`).toBe(true)
    expect(errs, `${label} raised uncaught browser errors`).toEqual([])
    await page.screenshot({ path: `/tmp/audit_shots/sad_${label.replace(/\W+/g, '_')}.png` })
    await page.close()
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
    const errs: string[] = []
    page.on('pageerror', (error) => errs.push(error.message))
    await page.goto(`/r/${encodeURIComponent(tok)}`, { waitUntil: 'domcontentloaded' }).catch(() => {})
    await page.waitForTimeout(3500)
    const t = await pageText(page)
    console.log(`\n### share ${label}: url=${page.url()}`)
    console.log(`   text: ${t.slice(0, 250)}`)
    expect(t).toMatch(/link unavailable|revoked|does not exist|not available|page could not be found|link may be broken/i)
    expect(errs, `${label} raised uncaught browser errors`).toEqual([])
  }
  await ctx.close()
})

test('share link happy path: anonymous visitor can view a shared resume', async ({ browser }) => {
  test.setTimeout(300_000)
  const actx = await browser.newContext()
  await login(actx)
  // A share link serves the latest compiled artifact, not raw LaTeX. Compile a
  // realistic fixture first so this test is deterministic even when the most
  // recently edited resume is one of the deliberately tiny security fixtures.
  const list = await (await actx.request.get(`${BE}/resumes/`)).json()
  const arr = Array.isArray(list) ? list : list.resumes ?? []
  const candidate = arr.find((resume: { latex_content?: string }) =>
    (resume.latex_content?.length ?? 0) >= 200,
  )
  test.skip(!candidate, 'no realistic resume fixture')
  if (!candidate) return
  const id = candidate.id
  const compile = await actx.request.post(`${BE}/jobs/submit`, {
    data: {
      job_type: 'latex_compilation',
      latex_content: candidate.latex_content,
      metadata: { resume_id: id },
    },
  })
  const compileBody = await compile.json().catch(() => ({}))
  expect(compile.ok(), `fixture compile failed: ${JSON.stringify(compileBody)}`).toBe(true)
  await expect.poll(async () => {
    const state = await actx.request.get(`${BE}/jobs/${compileBody.job_id}/state`)
    return (await state.json()).status
  }, { timeout: 180_000 }).toBe('completed')

  // create a fresh share link
  const sres = await actx.request.post(`${BE}/resumes/${id}/share`, { data: {} })
  const sbody = await sres.json().catch(() => ({}))
  const token = sbody.share_token ?? sbody.token
  console.log('share create ->', sres.status(), JSON.stringify(sbody).slice(0, 250))
  expect(sres.ok(), `share creation failed: ${JSON.stringify(sbody)}`).toBe(true)
  expect(token).toEqual(expect.any(String))

  // anonymous context
  const anon = await browser.newContext()
  const page = await anon.newPage()
  const errs: string[] = []
  page.on('pageerror', (e) => errs.push(e.message))
  const bad: string[] = []
  page.on('response', (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.url().replace(BE, '')}`) })

  await page.goto(`/r/${token}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)
  const t = await pageText(page)
  const sharedApi = await anon.request.get(`${BE}/share/${token}`)
  const sharedBody = await sharedApi.json().catch(() => ({}))
  console.log('\n### shared view as anonymous')
  console.log('   text:', t.slice(0, 500))
  console.log('   shows resume owner content:', /Alice Auditor|ExampleCorp/i.test(t))
  console.log('   failed requests:', JSON.stringify(bad.slice(0, 8)))
  console.log('   page errors:', JSON.stringify(errs.slice(0, 3)))
  expect(sharedApi.ok(), `new share token was not immediately readable: ${JSON.stringify(sharedBody)}`).toBe(true)
  expect(t).toContain(sharedBody.resume_title)
  expect(errs).toEqual([])
  await page.screenshot({ path: '/tmp/audit_shots/share_view.png', fullPage: true })

  // revoke, then re-check
  const revoke = await actx.request.delete(`${BE}/resumes/${id}/share`)
  expect(revoke.ok()).toBe(true)
  await page.goto(`/r/${token}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)
  const t2 = await pageText(page)
  console.log('\n### after revoke, same link')
  console.log('   still leaks content:', /Alice Auditor|ExampleCorp/i.test(t2))
  console.log('   text:', t2.slice(0, 250))
  expect(t2).toMatch(/link unavailable|revoked|does not exist|not available/i)
  expect(t2).not.toContain(sharedBody.resume_title)
  const revokedApi = await anon.request.get(`${BE}/share/${token}`)
  expect(revokedApi.status()).toBe(404)
  await anon.close()
  await actx.close()
})

test('trial system: anonymous compile usage and cooldown are enforced per fingerprint', async ({ browser }) => {
  test.setTimeout(600_000)
  // Fresh anonymous context => fresh fingerprint
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(4000)

  const readTrials = async () => {
    const t = await pageText(page)
    const m = t.match(/\btrials\s+(\d+|∞)\b/i)
    expect(m, `could not parse trial counter from: ${t.slice(0, 300)}`).not.toBeNull()
    return m?.[1] ?? ''
  }
  const starting = Number(await readTrials())
  expect(starting).toBeGreaterThan(0)

  const fingerprint = await page.evaluate(() => localStorage.getItem('latexy_device_fp'))
  expect(fingerprint).toEqual(expect.any(String))
  const status = await ctx.request.get(
    `${BE}/public/trial-status?fingerprint=${encodeURIComponent(fingerprint!)}`,
  )
  console.log('GET /public/trial-status ->', status.status(), (await status.text()).slice(0, 300))
  expect(status.ok()).toBe(true)

  const btn = page.getByRole('button', { name: /recompile/i }).first()
  await expect(btn).toBeEnabled()
  const firstCompile = page.waitForResponse(
    (response) => response.url().includes('/jobs/submit') && response.request().method() === 'POST',
  )
  await btn.click()
  expect((await firstCompile).status()).toBe(200)
  await expect.poll(async () => Number(await readTrials())).toBe(starting - 1)

  // A second immediate request must be stopped by the server-side five-minute
  // cooldown; the counter must not be charged for the rejected attempt.
  await expect(btn).toBeEnabled({ timeout: 120_000 })
  const secondCompile = page.waitForResponse(
    (response) => response.url().includes('/jobs/submit') && response.request().method() === 'POST',
  )
  await btn.click()
  const cooldown = await secondCompile
  expect(cooldown.status()).toBe(429)
  expect(await cooldown.text()).toMatch(/wait|cooldown/i)
  await expect.poll(async () => Number(await readTrials())).toBe(starting - 1)
  await page.screenshot({ path: '/tmp/audit_shots/trial_exhausted.png', fullPage: true })

  // The documented anonymous model is per device fingerprint. A new browser
  // context therefore starts with its own full quota; signup is the stronger
  // identity boundary, while the backend still enforces per-IP request limits.
  const ctx2 = await browser.newContext()
  const p2 = await ctx2.newPage()
  await p2.goto('/try', { waitUntil: 'domcontentloaded' })
  await p2.waitForTimeout(4000)
  const t2 = await pageText(p2)
  const m2 = t2.match(/\btrials\s+(\d+)\b/i)
  expect(m2, `fresh context trial counter was missing: ${t2.slice(0, 300)}`).not.toBeNull()
  expect(Number(m2?.[1])).toBe(3)
  await ctx2.close()
  await ctx.close()
})
