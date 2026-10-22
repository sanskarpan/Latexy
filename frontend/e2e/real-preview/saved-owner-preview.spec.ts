/** Actual isolated auth/UI/API/worker/storage/PDF bytes; no intercepted routes. */
import { expect, test, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { Pool } from 'pg'
import { localHttpOrigin, isLocalPreviewResource } from '../../scripts/real-preview-contract.mjs'
import { isolatedPreviewDatabase, ownedPdfCapture } from '../../scripts/saved-owner-preview-contract.mjs'
import { installBrowserPdfCapture, type BrowserPdfCapture, type PdfCaptureController } from './capture-browser-pdf'
import { digest, extractReceivedPdfText, normalizedText, isAdmissionRequest } from './observe-real-preview'

const apiOrigin = localHttpOrigin(process.env.REAL_PREVIEW_API_URL)
const frontendOrigin = localHttpOrigin(process.env.REAL_PREVIEW_BASE_URL)

async function signupThroughUi(page: Page) {
  await page.goto('/signup?redirect=/workspace/builder/new')
  await page.locator('#name').fill('Synthetic renderer owner')
  await page.locator('#email').fill(`test_real_renderer_${randomUUID()}@example.invalid`)
  const password = `Synthetic-${randomUUID()}!`
  await page.locator('#password').fill(password)
  await page.locator('#confirm').fill(password)
  await page.locator('form button[type="submit"]').click()
  await expect(page).toHaveURL(/\/workspace\/builder\/new$/, { timeout: 60_000 })
  // Complete the real optional tour through its ordinary dismiss action.
  const tour = page.getByRole('dialog')
  if (await tour.waitFor({ state: 'visible', timeout: 5_000 }).then(() => true, () => false)) {
    await tour.getByRole('button', { name: /^Skip/ }).first().click()
    await expect(tour).toBeHidden()
  }
  const value = await page.evaluate(async () => (await fetch('/api/auth/get-session')).json())
  expect(Boolean(value?.user?.id && value?.session?.token)).toBe(true)
  // Observe the real UI-issued fixture session, keeping it in memory only.
  // APIRequestContext has different Secure-cookie handling than Chromium on
  // loopback; explicit session headers mirror the app's authenticated API reads.
  return { id: value.user.id as string, headers: { Authorization: `Bearer ${value.session.token}` } }
}

test('ordinary saved owner previews and downloads the stored default Lua revision', async ({ page, browser }) => {
  const pool = new Pool({ connectionString: isolatedPreviewDatabase(process.env.PLAYWRIGHT_DATABASE_URL),
    connectionTimeoutMillis: 5_000, statement_timeout: 10_000,
    options: '-c default_transaction_read_only=on' })
  const captures: Array<{ jobId: string; body: Buffer }> = []
  const admissions: Array<{ source: string; compiler: string; resumeId: string; jobId: string; status: number }> = []
  const pending = new Set<Promise<void>>()
  const errors: string[] = []
  let external = 0
  let settingsUpdates = 0
  let success = false
  let proof: Record<string, unknown> = {}
  const runtimeErrors: string[] = []
  const binding = await page.exposeBinding('__latexyObserveOwnedPdf', async (_origin, value: BrowserPdfCapture) => {
    try { captures.push(ownedPdfCapture(value)) } catch { errors.push('owned_pdf_capture_failed') }
  })
  const init = await page.addInitScript(installBrowserPdfCapture, { apiOrigin,
    bindingName: '__latexyObserveOwnedPdf', maxBytes: 20 * 1024 * 1024,
    maxCaptures: 2, deadlineMs: 10_000, ownedDownloads: true })
  page.on('pageerror', error => runtimeErrors.push(error.name))
  page.on('request', request => {
    if (!isLocalPreviewResource(request.url())) external++
    const url = new URL(request.url())
    if (url.origin === apiOrigin && /^\/resumes\/[^/]+\/settings$/.test(url.pathname)
      && ['PATCH', 'PUT', 'POST'].includes(request.method())) settingsUpdates++
  })
  page.on('response', response => {
    if (!isAdmissionRequest(response.request(), apiOrigin)) return
    const operation = (async () => {
      const request = response.request().postDataJSON()
      const result = await response.json()
      admissions.push({ source: request.latex_content, compiler: request.compiler,
        resumeId: request.metadata?.resume_id, jobId: result.job_id, status: response.status() })
    })().catch(() => { errors.push('owned_admission_capture_failed') }).finally(() => pending.delete(operation))
    pending.add(operation)
  })
  const peer = await browser.newContext({ baseURL: frontendOrigin })
  try {
    const ownerSession = await signupThroughUi(page)
    const owner = ownerSession.id
    const role = await pool.query('SELECT role FROM users WHERE id=$1', [owner])
    expect(role.rows.map(row => row.role)).toEqual(['user'])
    await page.getByLabel('Resume Title', { exact: true }).fill('Synthetic saved-owner renderer acceptance')
    await page.getByRole('button', { name: /Start my r.sum./ }).click()
    await expect(page).toHaveURL(/\/workspace\/builder\/[a-f0-9-]{36}$/, { timeout: 30_000 })
    const resumeId = new URL(page.url()).pathname.split('/').pop()!
    const autosaved = page.waitForResponse(response => {
      const request = response.request()
      if (new URL(response.url()).pathname !== `/resumes/${resumeId}/builder/v1` || request.method() !== 'PATCH') return false
      const basics = request.postDataJSON()?.structured_content?.basics
      return basics?.name === 'Synthetic Owner Latest' && basics?.summary === 'Verified saved owner default Lua workflow.'
    })
    await page.getByLabel('Full Name').fill('Synthetic Owner Latest')
    await page.getByLabel('Summary', { exact: true }).fill('Verified saved owner default Lua workflow.')
    expect((await autosaved).status()).toBe(200)
    await expect(page.getByText('All changes saved', { exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByLabel('Full Name')).toHaveValue('Synthetic Owner Latest')
    await expect(page.getByLabel('Summary', { exact: true })).toHaveValue('Verified saved owner default Lua workflow.')
    const savedResponse = await page.request.get(`${apiOrigin}/resumes/${resumeId}/builder/v1`, { headers: ownerSession.headers })
    expect(savedResponse.status()).toBe(200)
    const saved = await savedResponse.json()
    expect(saved.resume.metadata.compiler).toBe('lualatex')
    expect(saved.resume.user_id).toBe(owner)
    expect(admissions).toHaveLength(0)
    // Do not update settings, select a compiler, fabricate a job, or modify the
    // request. The ordinary control must use the saved creation default.
    await page.getByRole('button', { name: 'Preview PDF', exact: true }).click()
    await expect.poll(() => admissions.length, { timeout: 30_000 }).toBe(1)
    const admission = admissions[0]
    expect(admission.status).toBe(200)
    expect(admission.resumeId).toBe(resumeId)
    expect(admission.compiler).toBe(saved.resume.metadata.compiler)
    expect(digest(admission.source)).toBe(digest(saved.resume.latex_content))
    await expect.poll(() => captures.length, { timeout: 180_000 }).toBe(1)
    const preview = captures[0]
    expect(preview.jobId).toBe(admission.jobId)
    const durable = await pool.query(`SELECT f.state, f.user_id::text AS owner, f.resume_id::text AS resume,
      f.pdf_size, f.pdf_sha256, f.pdf_path, f.result_payload, c.status,
      c.artifact_accepted, c.pdf_path AS compilation_pdf_path
      FROM job_finalizations f JOIN compilations c ON c.id=f.compilation_id WHERE f.job_id=$1`, [admission.jobId])
    expect(durable.rowCount).toBe(1)
    const row = durable.rows[0]
    expect(row.state).toBe('completed')
    expect(row.status).toBe('completed')
    expect(row.artifact_accepted).toBe(true)
    expect(row.owner).toBe(owner)
    expect(row.resume).toBe(resumeId)
    expect(row.pdf_size).toBe(preview.body.length)
    expect(row.pdf_sha256).toBe(digest(preview.body))
    expect(Boolean(row.pdf_path && row.pdf_path === row.compilation_pdf_path)).toBe(true)
    const artifact = row.result_payload.artifact
    expect(artifact.artifact_id).toMatch(/^[a-f0-9]{64}$/)
    expect(artifact.compiler).toBe('lualatex')
    expect(artifact.source_sha256).toBe(digest(saved.resume.latex_content))
    expect(artifact.pdf_sha256).toBe(digest(preview.body))
    // This accepted-artifact reader uses the private render store rather than
    // the builder's cached Blob or its legacy transport download.
    const acceptedPreviewPath = `/download/${admission.jobId}/preview/${artifact.artifact_id}`
    const acceptedPreview = await page.request.get(`${apiOrigin}${acceptedPreviewPath}`, { headers: ownerSession.headers })
    expect(acceptedPreview.status()).toBe(200)
    const acceptedPreviewHash = digest(await acceptedPreview.body())
    expect(acceptedPreviewHash).toBe(digest(preview.body))
    const canvas = page.getByTestId('builder-pdf-preview').locator('.react-pdf__Page__canvas').first()
    await expect(canvas).toBeVisible({ timeout: 60_000 })
    expect(await canvas.evaluate(node => {
      const element = node as HTMLCanvasElement
      const context = element.getContext('2d')
      if (!context || !element.width || !element.height) return false
      const bytes = context.getImageData(0, 0, element.width, element.height).data
      return bytes.some((value, index) => index % 4 !== 3 && value < 200 && bytes[index - index % 4 + 3] > 0)
    })).toBe(true)
    await expect.poll(async () => normalizedText((await page.locator('.react-pdf__Page__textContent span').allTextContents()).join(' '))).toContain('Synthetic Owner Latest')
    expect(await extractReceivedPdfText(preview.body)).toContain('Verified saved owner default Lua workflow.')
    const downloadEvent = page.waitForEvent('download')
    await page.getByRole('region', { name: 'Final PDF preview' }).getByRole('button', { name: 'Download PDF', exact: true }).first().click()
    const download = await downloadEvent
    const stream = await download.createReadStream()
    if (!stream) throw new Error('Saved-owner download stream is unavailable')
    const chunks: Buffer[] = []
    for await (const chunk of stream) chunks.push(Buffer.from(chunk))
    const downloadedPdfHash = digest(Buffer.concat(chunks))
    expect(downloadedPdfHash).toBe(digest(preview.body))
    expect(await download.failure()).toBeNull()
    await Promise.all([...pending])
    expect(admissions).toHaveLength(1)
    const otherSignup = await peer.request.post('/api/auth/sign-up/email', {
      headers: { Origin: frontendOrigin }, data: { name: 'Synthetic unrelated renderer owner',
        email: `test_real_renderer_peer_${randomUUID()}@example.invalid`, password: `Synthetic-${randomUUID()}!` },
    })
    expect(otherSignup.ok()).toBe(true)
    const peerAccount = await otherSignup.json()
    expect(peerAccount.user.id).not.toBe(owner)
    expect(Boolean(peerAccount.token)).toBe(true)
    const peerHeaders = { Authorization: `Bearer ${peerAccount.token}` }
    // Prove this is a valid ordinary unrelated owner, not an anonymous denial.
    expect((await peer.request.get(`${apiOrigin}/resumes/`, { headers: peerHeaders })).status()).toBe(200)
    for (const path of [`/resumes/${resumeId}/builder/v1`, `/jobs/${admission.jobId}/result`, `/download/${admission.jobId}`, acceptedPreviewPath]) {
      const denied = await peer.request.get(`${apiOrigin}${path}`, { headers: peerHeaders })
      expect([403, 404]).toContain(denied.status())
    }
    const dbCounts = await pool.query('SELECT count(*)::int AS jobs FROM job_finalizations WHERE user_id=$1', [owner])
    expect(dbCounts.rows[0].jobs).toBe(1)
    expect(settingsUpdates).toBe(0)
    proof = { compiler: artifact.compiler, stored_default_verified: true, source_saved_and_reloaded: true,
      source_sha256: artifact.source_sha256, pdf_sha256: digest(preview.body), pdf_bytes: preview.body.length,
      artifact_id: artifact.artifact_id, admitted_source_sha256: digest(admission.source),
      saved_source_sha256: digest(saved.resume.latex_content), durable_source_sha256: artifact.source_sha256,
      preview_pdf_sha256: digest(preview.body), downloaded_pdf_sha256: downloadedPdfHash,
      accepted_preview_pdf_sha256: acceptedPreviewHash, private_preview_bytes_match: true,
      compiler_settings_override_used: false, compiler_settings_update_count: settingsUpdates,
      durable_artifact_accepted: true, canvas_painted: true, expected_text_rendered: true,
      preview_download_bytes_match: true, download_admission_count_unchanged: true, unrelated_owner_denied: true }
    expect(runtimeErrors).toEqual([])
    expect(errors).toEqual([])
    expect(external).toBe(0)
    success = true
  } finally {
    try {
      await Promise.all([...pending])
      const captureErrors = await page.evaluate(async () => {
        const controller = (window as typeof window & { __latexyRealPreviewCapture?: PdfCaptureController }).__latexyRealPreviewCapture
        return controller ? controller.settle() : []
      })
      errors.push(...captureErrors)
      await page.evaluate(() => (window as typeof window & { __latexyRealPreviewCapture?: PdfCaptureController }).__latexyRealPreviewCapture?.cleanup())
    } catch { errors.push('owned_pdf_observer_cleanup_failed') }
    // Keep the original assertion failure; cleanup failures still invalidate
    // the redacted proof and fail an otherwise successful scenario.
    for (const operation of [() => init.dispose(), () => binding.dispose(), () => peer.close(), () => pool.end()]) {
      try { await operation() } catch { errors.push('owned_fixture_cleanup_failed') }
    }
    const evidenceDir = resolve(process.env.CI_ISOLATED_EVIDENCE_DIR ?? 'test-results/real-preview')
    await mkdir(evidenceDir, { recursive: true })
    await writeFile(resolve(evidenceDir, 'owner-browser-proof.json'), JSON.stringify({
      ...proof, success: success && errors.length === 0, scenario: 'normal-saved-owner-default-lua',
      measured_at_utc: new Date().toISOString(), admission_count: admissions.length,
      runtime_error_count: runtimeErrors.length, capture_error_count: errors.length, external_request_count: external,
      limitations: ['Isolated ordinary synthetic owner only; not live production acceptance or a latency SLO.'],
    }, null, 2) + '\n', { mode: 0o600 })
    if (success && errors.length) throw new Error('Saved-owner original-response observer did not clean up')
  }
})
