import { expect, test, type Page } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { FIRST_USE_ENGINE_RESUME_TEMPLATE } from '../../src/lib/first-use-resume'
import { parseSynctex, synctexHasMappableSource } from '../../src/lib/synctex-parser'
import { firstEditableBullet, guestCooldownMilliseconds, localHttpOrigin } from '../../scripts/real-preview-contract.mjs'
import { digest, extractReceivedPdfText, isAdmissionRequest, normalizedText, observeRealPreview, semanticFieldHitTarget } from './observe-real-preview'

const apiOrigin = localHttpOrigin(process.env.REAL_PREVIEW_API_URL)
const originalBullet = firstEditableBullet(FIRST_USE_ENGINE_RESUME_TEMPLATE)
const finalBullet = 'Verified latest customer support workflow.'
type Observed = Awaited<ReturnType<typeof observeRealPreview>>

async function renderedPdfText(page: Page) {
  return normalizedText((await page.locator('.react-pdf__Page__textContent span').allTextContents()).join(' '))
}

async function assertRenderedArtifact(page: Page, observed: Observed, admissionIndex: number,
  expectedSource: string, expectedBullet: string) {
  await expect.poll(() => observed.admissions.length, { timeout: 30_000 }).toBe(admissionIndex + 1)
  const admission = observed.admissions[admissionIndex]
  expect(admission.status).toBe(200)
  expect(admission.jobType).toBe('latex_compilation')
  // Compare hashes so a failing report never prints the submitted source.
  expect(digest(admission.source)).toBe(digest(expectedSource))
  expect(Boolean(admission.fingerprint)).toBe(true)
  await expect.poll(() => observed.artifacts.has(admission.jobId), { timeout: 90_000 }).toBe(true)
  const artifact = observed.artifacts.get(admission.jobId)!
  expect(artifact.source_sha256).toBe(digest(expectedSource))
  expect(artifact.branch).toBe('draft')
  expect(artifact.compiler).toBe('pdflatex')
  expect(artifact.pdf_size).toBeGreaterThan(0)
  expect(artifact.page_count).toBe(1)
  await expect.poll(() => observed.completedState(admission.jobId), { timeout: 90_000, intervals: [500, 1_000, 2_000] }).toBe('completed')
  await expect.poll(() => observed.events.some(event => event.jobId === admission.jobId && event.type === 'job.completed'), { timeout: 30_000 }).toBe(true)

  for (const kind of ['pdf', 'geometry', 'synctex'] as const) {
    await expect.poll(() => Boolean(observed.preview(admission.jobId, artifact.artifact_id, kind)), { timeout: 60_000 }).toBe(true)
    expect(observed.preview(admission.jobId, artifact.artifact_id, kind)!.fingerprint === admission.fingerprint).toBe(true)
  }
  const pdf = observed.preview(admission.jobId, artifact.artifact_id, 'pdf')!
  const geometry = observed.preview(admission.jobId, artifact.artifact_id, 'geometry')!.geometry!
  const synctex = observed.preview(admission.jobId, artifact.artifact_id, 'synctex')!
  expect(pdf.body.length).toBe(artifact.pdf_size)
  expect(digest(pdf.body)).toBe(artifact.pdf_sha256)
  expect(await extractReceivedPdfText(pdf.body)).toContain(expectedBullet)
  expect(geometry.artifact_id).toBe(artifact.artifact_id)
  expect(geometry.source_sha256).toBe(artifact.source_sha256)
  expect(geometry.pdf_sha256).toBe(artifact.pdf_sha256)
  expect(geometry.branch).toBe('draft')
  expect(geometry.boxes.some(box => box.text === expectedBullet)).toBe(true)
  const pageHeights = Object.fromEntries(geometry.pages.map(value => [value.page, value.height]))
  expect(synctexHasMappableSource(parseSynctex(synctex.body.toString('utf8'), pageHeights), 'resume.tex')).toBe(true)

  await expect(page.locator('.react-pdf__Page__canvas').first()).toBeVisible({ timeout: 60_000 })
  await expect.poll(() => renderedPdfText(page), { timeout: 60_000 }).toContain(expectedBullet)
  // Visible canvas alone can be empty or stale. The text layer above must be
  // the expected revision, and at least some rendered pixels must contain ink.
  const canvasPainted = await page.locator('.react-pdf__Page__canvas').first().evaluate(canvas => {
    const element = canvas as HTMLCanvasElement
    if (!element.width || !element.height) return false
    const context = element.getContext('2d')
    if (!context) return false
    const pixels = context.getImageData(0, 0, element.width, element.height).data
    for (let offset = 0; offset < pixels.length; offset += 16) {
      if (pixels[offset + 3] > 0 && Math.min(pixels[offset], pixels[offset + 1], pixels[offset + 2]) < 200) return true
    }
    return false
  })
  expect(canvasPainted).toBe(true)
  // A semantic field can wrap into multiple verified line boxes, each with
  // the same exact label. Every match still belongs to the checked artifact.
  await expect(semanticFieldHitTarget(page, expectedBullet)).toBeVisible()
  await observed.settle()
  return { source_sha256: artifact.source_sha256, pdf_sha256: artifact.pdf_sha256,
    artifact_id: artifact.artifact_id, pdf_bytes: pdf.body.length, page_count: artifact.page_count,
    admission_http_status: admission.status, terminal_status: 'completed', websocket_artifact: true,
    websocket_completed: true, canvas_painted: true, expected_text_rendered: true,
    geometry_boxes: geometry.boxes.length, synctex_mappable: true,
    pdf_geometry_synctex_fingerprint_matches: true }
}

async function replaceSourceThroughEditor(page: Page, source: string) {
  const input = page.locator('.monaco-editor .inputarea, .monaco-editor .native-edit-context')
  await expect(input).toHaveCount(1)
  await input.focus()
  await page.keyboard.press('ControlOrMeta+A')
  await page.keyboard.insertText(source)
  // The shipped test runtime exposes a read-only observation of the actual
  // editor model. All mutations above go through browser keyboard input.
  await expect.poll(() => page.evaluate(() => {
    const editor = (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor
    return editor?.getValue()
  }).then(value => value === undefined ? '' : digest(value))).toBe(digest(source))
}

test('normal guest compiles the shipped source and renders only the latest exact edited artifact', async ({ page }) => {
  const observed = await observeRealPreview(page, apiOrigin)
  const started = Date.now()
  const samples: Awaited<ReturnType<typeof assertRenderedArtifact>>[] = []
  let cooldownMilliseconds = 0
  let passed = false
  try {
    const health = await page.request.get(`${apiOrigin}/health`)
    expect(health.status()).toBe(200)
    await page.goto('/try', { waitUntil: 'domcontentloaded' })
    const session = await page.request.get('/api/auth/get-session')
    expect(session.status()).toBe(200)
    expect(await session.json()).toBeNull()
    await expect(page.getByRole('button', { name: `Experience · bullet ${originalBullet}`, exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.monaco-editor')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Automatically update the PDF after edits', exact: true }).first()).toHaveAttribute('aria-pressed', 'false')
    const admissionRequest = page.waitForRequest(request => isAdmissionRequest(request, apiOrigin))
    await page.getByRole('button', { name: 'Update PDF preview', exact: true }).click()
    await admissionRequest
    samples.push(await assertRenderedArtifact(page, observed, 0, FIRST_USE_ENGINE_RESUME_TEMPLATE, originalBullet))

    // The geometry control is a real PDF hit target, including keyboard use.
    await semanticFieldHitTarget(page, originalBullet).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByLabel('Experience · bullet')).toHaveValue(originalBullet)
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 60_000 })
    const finalSource = FIRST_USE_ENGINE_RESUME_TEMPLATE.replace(originalBullet, finalBullet)
    await replaceSourceThroughEditor(page, FIRST_USE_ENGINE_RESUME_TEMPLATE.replace(originalBullet, 'Obsolete intermediate support workflow.'))
    await replaceSourceThroughEditor(page, finalSource)
    await page.getByRole('button', { name: 'Resume', exact: true }).click()
    await expect(page.getByRole('button', { name: `Experience · bullet ${finalBullet}`, exact: true })).toBeVisible()
    // Stale PDF geometry cannot edit the newer source while it waits to compile.
    await expect(page.getByRole('button', { name: /^Edit resume field:/ })).toHaveCount(0)
    expect(observed.admissions.length).toBe(1)

    const fingerprint = observed.admissions[0].fingerprint
    const trialResponse = await page.request.get(`${apiOrigin}/public/trial-status`, { params: { fingerprint } })
    expect(trialResponse.status()).toBe(200)
    const trial = await trialResponse.json()
    expect(trial.usageCount).toBe(1)
    cooldownMilliseconds = guestCooldownMilliseconds(trial)
    // No flag overrides, quota resets, fingerprint rotation or DB time edits.
    // Two admissions remain within the normal three-use fresh-guest allowance.
    await page.waitForTimeout(cooldownMilliseconds)
    await page.getByRole('button', { name: 'Update PDF preview', exact: true }).click()
    samples.push(await assertRenderedArtifact(page, observed, 1, finalSource, finalBullet))
    expect(observed.admissions[1].fingerprint === fingerprint).toBe(true)
    expect(samples[1].source_sha256).not.toBe(samples[0].source_sha256)
    expect(samples[1].pdf_sha256).not.toBe(samples[0].pdf_sha256)
    expect(await renderedPdfText(page)).not.toContain(originalBullet)
    expect(await renderedPdfText(page)).not.toContain('Obsolete intermediate support workflow.')
    expect(await extractReceivedPdfText(observed.preview(observed.admissions[1].jobId, samples[1].artifact_id, 'pdf')!.body)).not.toContain(originalBullet)
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await expect(page.getByTitle('SyncTeX enabled — Ctrl+click PDF to jump to source')).toBeVisible()
    const finalTrial = await page.request.get(`${apiOrigin}/public/trial-status`, { params: { fingerprint } })
    expect((await finalTrial.json()).usageCount).toBe(2)
    expect(observed.admissions).toHaveLength(2)
    expect(observed.runtimeErrors).toEqual([])
    expect(observed.captureErrors).toEqual([])
    expect(observed.externalRequestCount()).toBe(0)
    passed = true
  } finally {
    await observed.dispose()
    const evidenceDir = resolve(process.env.CI_ISOLATED_EVIDENCE_DIR ?? 'test-results/real-preview')
    await mkdir(evidenceDir, { recursive: true })
    await writeFile(resolve(evidenceDir, 'browser-proof.json'), JSON.stringify({
      success: passed && observed.captureErrors.length === 0, scenario: 'normal-guest-initial-and-latest-source', measured_at_utc: new Date().toISOString(),
      elapsed_ms: Date.now() - started, normal_guest_cooldown_ms: cooldownMilliseconds,
      samples, admission_count: observed.admissions.length, runtime_error_count: observed.runtimeErrors.length,
      capture_error_count: observed.captureErrors.length, external_request_count: observed.externalRequestCount(),
      artifact_transfers: observed.transferDiagnostics(),
      limitations: ['Two isolated functional samples; no production SLO or percentile claim.',
        'Test-local original-response clone observation can perturb timing; no latency acceptance claim.',
        'Saved-owner authentication and AI/provider flows are not exercised.'],
    }, null, 2) + '\n', { mode: 0o600 })
    if (passed && observed.captureErrors.length) throw new Error('Original browser capture did not settle and clean up successfully')
  }
})
