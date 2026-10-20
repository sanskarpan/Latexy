/** Live auth, API, browser and accepted-PDF identity; disposable local services only. */
import { expect, test, type BrowserContext } from '@playwright/test'
import { createHash, randomUUID } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { Pool } from 'pg'

test.skip(!process.env.PLAYWRIGHT_REQUIRE_BACKEND, 'Requires explicitly started isolated local services')
test.setTimeout(420_000)

test('public sharing survives policy recovery, isolates accounts and permanently revokes old tokens', async ({ browser, baseURL }) => {
  const frontend = baseURL!
  const backend = process.env.NEXT_PUBLIC_API_URL!
  const database = new URL((process.env.DATABASE_URL ?? '').replace('postgresql+asyncpg:', 'postgresql:'))
  for (const url of [new URL(frontend), new URL(backend), database]) {
    if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) throw new Error('Acceptance requires loopback services')
  }
  if (!database.pathname.endsWith('_test') || process.env.OPENAI_API_KEY || process.env.RESEND_API_KEY || process.env.DEPLOY_TARGET === 'modal') {
    throw new Error('Acceptance requires an isolated test database and no live providers')
  }
  const storageMode = process.env.SHARING_ACCEPTANCE_STORAGE_MODE ?? 'docker'
  const storageEndpoint = process.env.SHARING_ACCEPTANCE_STORAGE_ENDPOINT ?? ''
  const storageBucket = process.env.SHARING_ACCEPTANCE_STORAGE_BUCKET ?? ''
  const publicStorage = new URL(process.env.SHARING_ACCEPTANCE_PUBLIC_STORAGE_ENDPOINT ?? storageEndpoint)
  const storage = new URL(storageEndpoint)
  for (const endpoint of [storage, publicStorage]) {
    const hosts = storageMode === 'docker' ? ['localhost', '127.0.0.1', '[::1]', 'storage', 'host.docker.internal'] : ['localhost', '127.0.0.1', '[::1]']
    if (endpoint.protocol !== 'http:' || !hosts.includes(endpoint.hostname) || !endpoint.port || Number(endpoint.port) < 1024 || endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname !== '/') {
      throw new Error('Sharing acceptance requires isolated storage endpoints')
    }
  }
  if (!['host', 'docker'].includes(storageMode) || process.env.SHARING_ACCEPTANCE_DISPOSABLE !== '1' || !/^latexy-sharing-[a-f0-9]{32}$/.test(storageBucket)) {
    throw new Error('Sharing acceptance requires explicit disposable storage and a per-run bucket')
  }
  const pool = new Pool({ connectionString: database.toString() })
  const contexts: BrowserContext[] = []
  const ids: string[] = []
  const admin = await browser.newContext()
  const owner = await browser.newContext()
  const stranger = await browser.newContext()
  const viewer = await browser.newContext()
  contexts.push(admin, owner, stranger, viewer)
  async function signup(context: BrowserContext, label: string) {
    const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
      timeout: 120_000,
      headers: { Origin: frontend },
      data: { name: `Synthetic sharing ${label}`, email: `test_share_${randomUUID()}@example.test`, password: `Synthetic-${randomUUID()}!` },
    })
    expect(response.status(), await response.text()).toBe(200)
    const account = await response.json()
    ids.push(account.user.id)
    return { id: account.user.id as string, headers: { Authorization: `Bearer ${account.token}` } }
  }
  try {
    const a = await signup(admin, 'administrator')
    const o = await signup(owner, 'owner')
    const s = await signup(stranger, 'unrelated')
    await pool.query("UPDATE users SET role='admin' WHERE id=$1", [a.id])
    await pool.query("UPDATE users SET role='user',subscription_plan='pro_annual',subscription_status='active' WHERE id=ANY($1::uuid[])", [[o.id, s.id]])
    async function policy(axis: 'global' | 'role' | 'family' | 'sku', key: string, enabled: boolean) {
      const path = axis === 'global' ? `kill-switch/${key}` : axis === 'role' ? 'roles' : 'matrix'
      const data = axis === 'global' ? { feature_key: key, enabled }
        : axis === 'role' ? { role: 'user', feature_key: key, enabled }
        : { plan_family: axis === 'family' ? 'pro' : 'pro_annual', feature_key: key, enabled }
      const response = await admin.request.patch(`${backend}/admin/entitlements/${path}`, { headers: a.headers, data })
      expect(response.status(), await response.text()).toBe(200)
    }
    for (const key of ['collaboration', 'f01', 'f03', 'resume_builder', 'b01', 'c01']) {
      for (const axis of ['global', 'role', 'family', 'sku'] as const) await policy(axis, key, true)
    }
    const created = await owner.request.post(`${backend}/resumes/`, { headers: o.headers, data: {
      title: 'Synthetic accepted sharing document', latex_content: '\\documentclass{article}\\begin{document}Synthetic sharing acceptance\\end{document}',
    } })
    expect(created.status(), await created.text()).toBe(201)
    const resume = await created.json()
    // A real PDF is stored in synthetic S3. No API response or browser request is mocked.
    const job = randomUUID()
    const key = `compilations/${job}/accepted.pdf`
    const pdf = readFileSync('../backend/test/fixtures/accepted-sharing.pdf')
    const seedScript = readFileSync('../scripts/ci/sharing-storage-fixture.py', 'utf8')
    const fixture = JSON.stringify({ mode: storageMode, endpoint: storageEndpoint, bucket: storageBucket,
      origin: frontend, key, pdf: pdf.toString('base64') })
    if (storageMode === 'host') {
      execFileSync(process.env.SHARING_ACCEPTANCE_PYTHON ?? 'python', ['-c', seedScript, fixture], {
        cwd: '../backend', encoding: 'utf8', timeout: 60_000,
      })
    } else {
      execFileSync('docker', ['exec', '-e', 'SHARING_ACCEPTANCE_DISPOSABLE=1',
        process.env.SHARING_ACCEPTANCE_API_CONTAINER ?? 'latexy-share1920-api', 'python', '-c', seedScript, fixture],
      { encoding: 'utf8', timeout: 60_000 })
    }
    expect(pdf.subarray(0, 5).toString()).toBe('%PDF-')
    const digest = createHash('sha256').update(pdf).digest('hex')
    await pool.query('INSERT INTO compilations(id,resume_id,user_id,job_id,status,pdf_path,pdf_size,artifact_accepted,artifact_branch) VALUES($1,$2,$3,$4,$5,$6,$7,true,$8)',
      [randomUUID(), resume.id, o.id, job, 'completed', key, pdf.length, 'draft'])
    const shared = await owner.request.post(`${backend}/resumes/${resume.id}/share`, { headers: o.headers, data: { review_comments: true } })
    expect(shared.status(), await shared.text()).toBe(200)
    const token = (await shared.json()).share_token
    const page = await viewer.newPage()
    async function publicPdf(liveToken: string) {
      const response = await viewer.request.get(`${backend}/share/${liveToken}`)
      expect(response.status(), await response.text()).toBe(200)
      const body = await response.json()
      expect(body.share_token).toBe(liveToken)
      const artifactUrl = new URL(body.pdf_url)
      expect(artifactUrl.origin).toBe(publicStorage.origin)
      const artifactHost = artifactUrl.host
      if (artifactUrl.hostname === 'host.docker.internal') artifactUrl.hostname = '127.0.0.1'
      // Keep the signed S3 Host while reaching the loopback-only published port.
      const artifact = await viewer.request.get(artifactUrl.toString(), { headers: { Host: artifactHost } })
      expect(artifact.status(), await artifact.text()).toBe(200)
      expect(artifact.headers()['content-type']).toContain('application/pdf')
      expect(createHash('sha256').update(await artifact.body()).digest('hex')).toBe(digest)
      await page.goto(`${frontend}/r/${liveToken}`)
      await expect(page.getByText('Synthetic accepted sharing document', { exact: true })).toBeVisible()
      const browserBytes = await page.evaluate(async (url: string) => {
        const response = await fetch(url)
        if (!response.ok) throw new Error(`PDF returned ${response.status}`)
        return Array.from(new Uint8Array(await response.arrayBuffer()))
      }, body.pdf_url)
      expect(createHash('sha256').update(Buffer.from(browserBytes)).digest('hex')).toBe(digest)
      if (body.review_comments) {
        await expect(page.getByTestId('review-pdf-page').locator('canvas').first()).toBeVisible({ timeout: 20_000 })
      }
      await expect(page.getByRole('heading', { name: /Something broke/ })).toHaveCount(0)
    }
    await publicPdf(token)
    await page.screenshot({ path: 'sharing-enabled-browser.png', fullPage: true })
    for (const method of ['get', 'put', 'delete'] as const) {
      const path = method === 'delete' ? `/resumes/${resume.id}/share` : `/resumes/${resume.id}`
      const response = await stranger.request[method](`${backend}${path}`, {
        headers: s.headers, ...(method === 'put' ? { data: { latex_content: 'cross-account write', expected_latex_content: resume.latex_content } } : {}),
      })
      expect(response.status(), await response.text()).toBe(404)
    }
    const strangerShare = await stranger.request.post(`${backend}/resumes/${resume.id}/share`, { headers: s.headers })
    expect(strangerShare.status()).toBe(404)
    const strangerPage = await stranger.newPage()
    const strangerList = strangerPage.waitForResponse(response => new URL(response.url()).pathname === '/resumes/' && response.request().method() === 'GET', { timeout: 120_000 })
    await strangerPage.goto(`${frontend}/workspace`)
    expect((await strangerList).status()).toBe(200)
    await expect(strangerPage.getByText('Synthetic accepted sharing document', { exact: true })).toHaveCount(0)
    for (const [axis, key] of [['role', 'f01'], ['family', 'f01'], ['sku', 'f01'], ['global', 'f01'], ['global', 'collaboration']] as const) {
      await policy(axis, key, false)
      expect((await viewer.request.get(`${backend}/share/${token}`)).status()).toBe(404)
      expect((await owner.request.post(`${backend}/resumes/${resume.id}/share`, { headers: o.headers })).status()).toBe(403)
      await page.reload()
      await expect(page.getByRole('heading', { name: 'Link unavailable' })).toBeVisible()
      await policy(axis, key, true)
      await publicPdf(token)
    }
    await policy('global', 'collaboration', false)
    const revokeReview = await owner.request.post(`${backend}/resumes/${resume.id}/share`, { headers: o.headers, data: { review_comments: false } })
    expect(revokeReview.status()).toBe(200)
    expect((await revokeReview.json()).review_comments).toBe(false)
    expect((await owner.request.get(`${backend}/resumes/${resume.id}`, { headers: o.headers })).status()).toBe(200)
    const ownerPage = await owner.newPage()
    await ownerPage.goto(`${frontend}/workspace`)
    await ownerPage.getByRole('dialog', { name: 'Welcome to Latexy' }).getByRole('button', { name: 'Skip', exact: true }).click()
    const ownerCard = ownerPage.locator('article').filter({ hasText: 'Synthetic accepted sharing document' })
    await expect(ownerCard).toBeVisible()
    await ownerCard.getByRole('button', { name: 'More actions' }).click()
    await ownerPage.getByRole('button', { name: 'Manage share link' }).click()
    await ownerPage.getByRole('button', { name: 'Revoke link', exact: true }).click()
    const revoked = ownerPage.waitForResponse(response => new URL(response.url()).pathname === `/resumes/${resume.id}/share` && response.request().method() === 'DELETE')
    await ownerPage.getByRole('button', { name: 'Revoke permanently' }).click()
    expect((await revoked).status()).toBe(204)
    await policy('global', 'collaboration', true)
    expect((await viewer.request.get(`${backend}/share/${token}`)).status()).toBe(404)
    const replacement = await owner.request.post(`${backend}/resumes/${resume.id}/share`, { headers: o.headers })
    expect(replacement.status()).toBe(200)
    const replacementToken = (await replacement.json()).share_token
    expect(replacementToken).not.toBe(token)
    await publicPdf(replacementToken)
    expect((await viewer.request.get(`${backend}/share/${token}`)).status()).toBe(404)
    await page.goto(`${frontend}/r/${token}`)
    await expect(page.getByRole('heading', { name: 'Link unavailable' })).toBeVisible()
    await page.screenshot({ path: 'sharing-revoked-browser.png', fullPage: true })
    await test.info().attach('accepted-pdf-identity', { body: JSON.stringify({ sha256: digest, bytes: pdf.length, checks: 'role/family/SKU/global/parent: enabled200 -> disabled404 -> recovered200; revoked old token404' }), contentType: 'application/json' })
  } finally {
    // This database is disposable; test-created accounts are still cleaned for reruns.
    if (ids.length) await pool.query('DELETE FROM users WHERE id=ANY($1::uuid[])', [ids])
    await pool.end()
    await Promise.all(contexts.map(context => context.close()))
  }
})
