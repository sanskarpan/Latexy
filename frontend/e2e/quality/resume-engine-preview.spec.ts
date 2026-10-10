import { expect, test, type WebSocketRoute } from './quality-test'
import { createHash } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { captureClipboardText, mockEngineAncillaryApi, readMonacoSource } from './engine-fixtures'
import { applyGuestBulletPatch, GUEST_ORIGINAL_BULLET, projectGuestBullet } from './guest-engine-fixture'

if (process.env.ENGINE_QA_CHROME === '1') test.use({ channel: 'chrome' })

const digest = (text: string) => createHash('sha256').update(text).digest('hex')
const original = 'Built internal design system used across 6 product surfaces'
function samplePdf(text = original) {
  const content = `BT /F1 10 Tf 40 740 Td (${text}) Tj ET`
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${content.length} >>\nstream\n${content}\nendstream`]
  let pdf = '%PDF-1.4\n'; const offsets = [0]
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n` })
  const start = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`
  return Buffer.from(pdf)
}
test('guest Resume mode edits plain fields and submits exactly one quota-governed preview', async ({ page }) => {
  test.setTimeout(240000)
  const errors: string[] = []; const submissions: Record<string, unknown>[] = []
  const scoreSources: string[] = []
  const pdfRendererChunks: Array<{ url: string; transferMs: number }> = []
  let rendererReadyAt = 0
  let firstAdmissionAt = 0
  const scriptRequestStarts = new WeakMap<object, number>()
  page.on('request', request => {
    if (request.resourceType() === 'script') scriptRequestStarts.set(request, Date.now())
  })
  page.on('response', async response => {
    if (response.request().resourceType() !== 'script' || !response.ok()) return
    const body = await response.text().catch(() => '')
    // This marker is in the actual react-pdf/PDF.js browser bundle, not the
    // lightweight ReactPdfClient export shim.
    if (!body.includes('AnnotationLayer') || !body.includes('GlobalWorkerOptions')) return
    const startedAt = scriptRequestStarts.get(response.request())
    if (startedAt !== undefined) pdfRendererChunks.push({ url: new URL(response.url()).pathname, transferMs: Date.now() - startedAt })
  })
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close({ code: 1000, reason: 'Contract test uses state recovery' }))
  page.on('pageerror', error => errors.push(error.message))
  await mockEngineAncillaryApi(page)
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: null }))
  await page.route('**/config/feature-flags', route => route.fulfill({ json: {} }))
  await page.route('**/ats/quick-score', route => {
    scoreSources.push(route.request().postDataJSON().latex_content)
    return route.fulfill({ json: { score: 49, grade: 'D', sections_found: ['experience'], missing_sections: [], keyword_match_percent: null } })
  })
  await page.route('**/tenants/resolve-host**', route => route.fulfill({ json: { tenant: null } }))
  await page.route('**/public/trial-status**', route => route.fulfill({ json: { usageCount: 0, remainingUses: 3, blocked: false, canUse: true, trialLimit: 3 } }))
  await page.route('**/public/engine/document', async route => {
    const { latex_content } = route.request().postDataJSON()
    await route.fulfill({ json: { document: projectGuestBullet(latex_content), latex_content } })
  })
  await page.route('**/public/engine/document/patch', async route => {
    const body = route.request().postDataJSON()
    expect(body.expected_source_sha256).toBe(digest(body.latex_content))
    expect(body.patches[0].expected_node_revision).toBe(digest(GUEST_ORIGINAL_BULLET))
    await route.fulfill({ json: applyGuestBulletPatch(body) })
  })
  await page.route('**/jobs/submit', async route => {
    submissions.push(route.request().postDataJSON())
    firstAdmissionAt = Date.now()
    await route.fulfill({ json: { success: true, job_id: 'guest-preview', message: 'Queued' } })
  })
  await page.route('**/jobs/guest-preview/state', route => route.fulfill({ json: { status: 'processing', stage: 'latex_compilation', percent: 20, last_updated: Date.now() / 1000 } }))
  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Edit your resume' })).toBeVisible()
  await expect.poll(() => scoreSources.length, { timeout: 6000 }).toBe(1)
  await expect(page.locator('.monaco-editor')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Copy LaTeX source' })).toHaveCount(0)
  await expect.poll(() => pdfRendererChunks.length, { timeout: 30000 }).toBeGreaterThan(0)
  rendererReadyAt = Date.now()
  await page.getByRole('button', { name: `Experience · bullet ${GUEST_ORIGINAL_BULLET}`, exact: true }).click()
  await page.getByLabel('Experience · bullet').fill('Built internal design system used across 8 product surfaces')
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => submissions.length).toBe(1)
  await expect.poll(() => scoreSources.length, { timeout: 6000 }).toBe(2)
  expect(scoreSources[1]).toContain('across 8 product surfaces')
  expect(firstAdmissionAt).toBeGreaterThanOrEqual(rendererReadyAt)
  expect(submissions[0].job_type).toBe('latex_compilation')
  expect(submissions[0].latex_content).toContain('across 8 product surfaces')
  expect(submissions[0].latex_content).toBe(scoreSources[0].replace(GUEST_ORIGINAL_BULLET, 'Built internal design system used across 8 product surfaces'))
  expect(scoreSources[1]).toBe(submissions[0].latex_content)
  expect(submissions[0].device_fingerprint).toBeTruthy()
  await expect(page.getByRole('button', { name: 'Save field', exact: true })).toBeDisabled()
  await expect(page.locator('.monaco-editor')).toHaveCount(0)
  expect(errors).toEqual([])
  if (process.env.ENGINE_QA_EVIDENCE === '1') {
    const folder = resolve(process.cwd(), '../docs/audits/resume-engine')
    await mkdir(folder, { recursive: true })
    await page.screenshot({ path: resolve(folder, 'guest-resume-mode.png'), fullPage: true })
  }
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 60000 })
  // WebKit/Firefox do not expose Chromium's clipboard permission grant.
  // Capture the real Copy button's write at the browser API boundary instead.
  await captureClipboardText(page)
  await page.getByRole('button', { name: 'Copy LaTeX source', exact: true }).click()
  await expect.poll(() => page.evaluate(() => (window as typeof window & { copiedLatex?: string }).copiedLatex)).toContain('across 8 product surfaces')
  await page.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect(page.locator('.monaco-editor')).toHaveCount(0)
  expect(scoreSources).toHaveLength(2)
  expect(errors).toEqual([])
})

test('managed review keeps provisional candidates separate and applies authoritative decisions', async ({ page }) => {
  test.setTimeout(240000)
  await page.setViewportSize({ width: 1280, height: 900 })
  const runtimeErrors: string[] = []
  page.on('pageerror', error => runtimeErrors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && /TypeError|ReferenceError|ErrorBoundary/.test(message.text())) runtimeErrors.push(message.text().slice(0, 1800)) })
  const resumeId = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
  const second = 'Mentored 4 engineers and introduced measurable review standards'
  const firstSuggestion = original + '.'; const secondSuggestion = second + '.'
  const baseSource = `\\documentclass{article}\n\\begin{document}\n\\begin{itemize}\n\\item ${original}\n\\item ${second}\n\\end{itemize}\n\\end{document}`
  let authority = baseSource; let revision = 1; let finalReview = false; let socket: WebSocketRoute | null = null
  const decisions: Record<string, 'accepted' | 'rejected'> = {}
  const admissions: Record<string, unknown>[] = []; const decisionBodies: Record<string, unknown>[] = []
  const compilations = new Map<string, { source: string; revision: number }>()
  const doc = (source = authority, contentRevision = revision) => ({ document_id: resumeId, source_mode: 'managed', content_revision: contentRevision,
    source_sha256: digest(source), structured_version: 1, template_id: 'test-managed', opaque_blocks: [],
    nodes: [original, second].map((text, index) => {
      const current = source.includes(text + '.') ? text + '.' : text
      return { node_id: `bullet-${index}`, node_revision: digest(current), section: 'Experience', kind: 'bullet', text: current,
        source_span: { start: source.indexOf(current), end: source.indexOf(current) + current.length }, editable: true, ai_editable: true }
    }) })
  const patches = [firstSuggestion, secondSuggestion].map((text, index) => ({ patch_id: `patch-${index}`, operation: 'replace_text', node_id: `bullet-${index}`,
    expected_node_revision: digest(index ? second : original), original_text: index ? second : original, text,
    reason: 'Improve sentence punctuation without changing the evidence.', evidence_ids: [], requirement_ids: [], validation: {} }))
  const candidateSource = baseSource.replace(original, firstSuggestion).replace(second, secondSuggestion)
  const artifact = (jobId: string) => {
    const compiled = compilations.get(jobId)
    const source = compiled?.source ?? candidateSource; const contentRevision = compiled?.revision ?? 1
    const pdf = samplePdf(source.includes(firstSuggestion) ? firstSuggestion : original)
    return { job_id: jobId, artifact_id: digest(jobId + source), source_sha256: digest(source), document_id: resumeId, content_revision: contentRevision,
      branch: compiled ? 'draft' : 'candidate', owner_epoch: 1, compiler: 'pdflatex', settings_sha256: digest('settings'), pdf_sha256: createHash('sha256').update(pdf).digest('hex'),
      pdf_size: pdf.length, page_count: 1, preview_url: `/download/${jobId}/preview/${digest(jobId + source)}`, geometry_url: `/download/${jobId}/preview/${digest(jobId + source)}/geometry` }
  }
  await mockEngineAncillaryApi(page, 'engine-owner')
  await page.route('**/ws/ticket', route => route.fulfill({ json: { ticket: 'contract-ticket' } }))
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: { session: { token: 'contract-owner-token' }, user: { id: 'engine-owner', email: 'engine-owner@example.com', name: 'Engine Owner' } } }))
  await page.route('**/macros', route => route.fulfill({ json: [] }))
  await page.route('**/resumes/engine/providers', route => route.fulfill({ json: {
    default: { provider: 'openai', model: 'contract-model', source: 'platform', ready: true },
    providers: [{ provider: 'anthropic', key_available: true, models: ['contract-exact-model-a', 'contract-exact-model-b'] }],
  } }))
  await page.route(`**/resumes/${resumeId}`, route => route.fulfill({ json: { id: resumeId, user_id: 'engine-owner', title: 'Managed contract resume', latex_content: authority,
    document_type: 'resume', metadata: {}, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z' } }))
  await page.route(`**/resumes/${resumeId}/engine/import`, route => route.fulfill({ status: 404, json: { detail: 'No original upload' } }))
  await page.route(`**/resumes/${resumeId}/engine/document`, route => {
    if (route.request().method() === 'PATCH') return route.fulfill({ status: 409, json: { detail: 'A newer field revision exists' } })
    return route.fulfill({ json: { document: doc(), latex_content: authority } })
  })
  await page.route(`**/resumes/${resumeId}/engine/optimize`, async route => {
    admissions.push(route.request().postDataJSON()); await route.fulfill({ json: { success: true, job_id: 'semantic-run', message: 'Queued' } })
  })
  await page.route(`**/resumes/${resumeId}/engine/runs/semantic-run`, route => route.fulfill({ json: {
    run_id: 'semantic-run', document_id: resumeId, base_revision: 1, source_sha256: digest(baseSource), effort: 'deep',
    status: finalReview ? 'completed' : 'running', job_status: finalReview ? 'completed' : 'processing', acceptance_ready: finalReview,
    document: doc(baseSource, 1), budget: { requests: 1, usage_unknown: false }, decisions: { patches: decisions },
    result: finalReview ? { candidate_source_sha256: digest(candidateSource), patches, warnings: [], missing_evidence: ['jd.' + digest('design systems and mentoring'), 'jd.' + digest('unmapped'), 'Add a measurable outcome.'], requirements: { requirements: [{ requirement_id: 'jd.' + digest('design systems and mentoring'), excerpt: 'design systems and mentoring' }] } } : null,
    pdf_quality: finalReview ? { status: 'unavailable', pdf_sha256: artifact('semantic-run').pdf_sha256, source_sha256: digest(candidateSource), page_count: 1, warnings: ['Font embedding could not be checked.'] } : undefined,
  } }))
  await page.route(`**/resumes/${resumeId}/engine/runs/semantic-run/decisions`, async route => {
    const body = route.request().postDataJSON(); decisionBodies.push(body)
    expect(body.expected_content_revision).toBe(revision); expect(body.expected_source_sha256).toBe(digest(authority))
    for (const id of body.reject_patch_ids) decisions[id] = 'rejected'
    for (const id of body.accept_patch_ids) { decisions[id] = 'accepted'; authority = authority.replace(original, firstSuggestion); revision++ }
    await route.fulfill({ json: { run_id: 'semantic-run', decisions: { patches: decisions, complete_acceptance: false, accepted_source_sha256: digest(authority), accepted_content_revision: revision }, document: doc(), latex_content: authority } })
  })
  await page.route('**/jobs/submit', async route => {
    const body = route.request().postDataJSON(); const id = `accepted-${compilations.size + 1}`
    compilations.set(id, { source: body.latex_content, revision }); await route.fulfill({ json: { success: true, job_id: id } })
  })
  await page.route('**/jobs/*/state', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2]
    return route.fulfill({ json: { status: id === 'semantic-run' && !finalReview ? 'processing' : 'completed', stage: '', percent: 100,
      artifact: id === 'semantic-run' && !finalReview ? null : artifact(id), last_updated: Date.now() / 1000 } })
  })
  await page.route('**/jobs/*/result', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2]
    return route.fulfill({ json: { success: true, job_id: id, result: { success: true, job_id: id, pdf_job_id: id, compilation_time: .01 } } })
  })
  await page.route('**/download/*/preview/*', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2]; const source = compilations.get(id)?.source ?? candidateSource
    return route.fulfill({ contentType: 'application/pdf', body: samplePdf(source.includes(firstSuggestion) ? firstSuggestion : original) })
  })
  await page.route('**/download/*/preview/*/geometry', route => {
    const id = new URL(route.request().url()).pathname.split('/')[2]; const a = artifact(id); const compiled = compilations.get(id)
    const node = doc(compiled?.source ?? baseSource, compiled?.revision ?? 1).nodes[0]
    return route.fulfill({ json: { schema_version: 1, coordinate_system: 'pdf_points_top_left', artifact_id: a.artifact_id, source_sha256: a.source_sha256,
      pdf_sha256: a.pdf_sha256, document_id: resumeId, content_revision: a.content_revision, branch: a.branch,
      pages: [{ page: 1, width: 612, height: 792, rotation: 0 }], boxes: [{ ...node, page: 1, x: 40, y: 42, width: 310, height: 12 }], omissions: [] } })
  })
  await page.routeWebSocket('**/ws/jobs**', ws => {
    socket = ws
    ws.onMessage(message => {
      const body = JSON.parse(String(message))
      if (body.type === 'subscribe' && body.job_id === 'semantic-run') ws.send(JSON.stringify({ type: 'event', stream_id: '1-0', event: { type: 'patch.ready', event_id: '1-0', sequence: 1,
        timestamp: Date.now() / 1000, job_id: 'semantic-run', run_id: 'semantic-run', document_id: resumeId, content_revision: 1, source_sha256: digest(baseSource), branch: 'candidate', patch: patches[0], provisional: true } }))
    })
  })
  await page.goto(`/workspace/${resumeId}/edit`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: 'Edit your resume', exact: true }).waitFor()
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByLabel('Target job').fill('Software engineering with design systems and mentoring')
  await page.getByRole('button', { name: 'deep', exact: true }).click()
  await page.getByLabel('Review provider', { exact: true }).selectOption('anthropic')
  await expect(page.getByRole('button', { name: 'Find suggestions', exact: true })).toBeDisabled()
  await page.getByLabel('Review model', { exact: true }).selectOption('contract-exact-model-b')
  await page.getByRole('button', { name: 'Find suggestions', exact: true }).click()
  await expect.poll(() => admissions.length).toBe(1)
  expect(admissions[0]).toMatchObject({ effort: 'deep', expected_content_revision: 1, expected_source_sha256: digest(baseSource), provider: 'anthropic', provider_model: 'contract-exact-model-b' })
  await expect(page.getByText('Early suggestions · final checks are still running.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Accept', exact: true })).toHaveCount(0)
  expect(authority).toBe(baseSource)
  finalReview = true
  socket!.send(JSON.stringify({ type: 'event', stream_id: '2-0', event: { ...artifact('semantic-run'), type: 'artifact.ready', event_id: '2-0', sequence: 2, timestamp: Date.now() / 1000 } }))
  socket!.send(JSON.stringify({ type: 'event', stream_id: '3-0', event: { type: 'job.completed', event_id: '3-0', sequence: 3, timestamp: Date.now() / 1000,
    job_id: 'semantic-run', pdf_job_id: 'semantic-run', changes_made: [], ats_score: null, ats_details: null, compilation_time: .01, optimization_time: .01, tokens_used: 0 } }))
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  await expect(page.locator('.react-pdf__Page__canvas')).toBeVisible({ timeout: 60000 })
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Accept', exact: true })).toHaveCount(2)
  await expect(page.getByText('design systems and mentoring', { exact: true })).toBeVisible()
  await expect(page.getByText('Add supporting experience for this job requirement.', { exact: true })).toBeVisible()
  await expect(page.getByText('Add a measurable outcome.', { exact: true })).toBeVisible()
  await expect(page.getByText('jd.' + digest('design systems and mentoring'), { exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Candidate PDF checks' })).toContainText('PDF checks were unavailable.')
  await expect(page.getByRole('region', { name: 'Candidate PDF checks' })).toContainText('Font embedding could not be checked.')
  await expect(page.getByRole('button', { name: 'Accept', exact: true }).first()).toBeEnabled()
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  await expect(page.locator('.react-pdf__Page__canvas')).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('AI candidate preview · review and accept suggestions before exporting.', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Edit resume field:/ })).toHaveCount(0)
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  await page.getByRole('button', { name: /^PDF/ }).last().click()
  const exportWarning = page.getByText('Compile your current resume before downloading. Review AI suggestions before accepting them.', { exact: true })
  const exportToast = page.locator('[data-sonner-toast]').filter({ has: exportWarning })
  await expect(exportWarning).toBeVisible()
  // The expected denial toast can cover Reject; hovering it pauses auto-dismiss.
  // Close that specific warning through the real UI before the next interaction.
  await exportToast.getByRole('button', { name: 'Close toast', exact: true }).click()
  await expect(exportToast).toHaveCount(0)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  const rejectedSuggestion = page.getByRole('article').filter({ has: page.getByText(secondSuggestion, { exact: true }) })
  const acceptedSuggestion = page.getByRole('article').filter({ has: page.getByText(firstSuggestion, { exact: true }) })
  await rejectedSuggestion.getByRole('button', { name: 'Reject', exact: true }).click()
  await expect.poll(() => decisionBodies.length).toBe(1)
  expect(decisions['patch-1']).toBe('rejected'); expect(authority).toBe(baseSource)
  // Request receipt precedes React's authoritative decision update. Wait for
  // that specific card to settle before accepting the remaining suggestion.
  await expect(rejectedSuggestion.getByText('rejected', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Accept', exact: true })).toHaveCount(1)
  await expect(acceptedSuggestion.getByRole('button', { name: 'Accept', exact: true })).toBeEnabled()
  await acceptedSuggestion.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect.poll(() => decisionBodies.length).toBe(2)
  expect(authority).toBe(baseSource.replace(original, firstSuggestion)); expect(revision).toBe(2)
  // Opening the saved editor already admits a first preview. A reject-all
  // rebuild may coalesce with the immediately following accepted draft.
  await expect.poll(() => [...compilations.values()].slice(-1)[0]?.source).toBe(authority)
  expect(compilations.size).toBeLessThanOrEqual(3)
  await page.getByRole('button', { name: 'Preview', exact: true }).click()
  await expect(page.getByRole('button', { name: `Edit resume field: ${firstSuggestion}`, exact: true })).toBeVisible({ timeout: 30000 })
  const acceptedDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export', exact: true }).click()
  await page.getByRole('button', { name: /^PDF/ }).last().click()
  expect((await acceptedDownload).suggestedFilename()).toMatch(/\.pdf$/)
  await page.getByRole('button', { name: `Edit resume field: ${firstSuggestion}`, exact: true }).click()
  await page.getByLabel('Experience · bullet').fill('A stale manual edit')
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect(page.getByText('This field could not be saved. Another edit may have changed it. Refresh the resume and try again.', { exact: true })).toBeVisible()
  expect(authority).toBe(baseSource.replace(original, firstSuggestion))
  await expect(page.locator('.monaco-editor')).toHaveCount(0)
  expect(runtimeErrors).toEqual([])

  // A source edit made while an accepted field response is in flight must
  // survive that response, even when the user switches editing modes.
  let releaseField!: () => void; let fieldStarted = false
  const fieldResponse = new Promise<void>((resolve) => { releaseField = resolve })
  const serverFieldSource = authority.replace(firstSuggestion, 'Server accepted field text')
  await page.route(`**/resumes/${resumeId}/engine/document`, async route => {
    if (route.request().method() !== 'PATCH') return route.fulfill({ json: { document: doc(), latex_content: authority } })
    fieldStarted = true
    await fieldResponse
    await route.fulfill({ json: { document: doc(serverFieldSource, revision + 1), latex_content: serverFieldSource } })
  })
  await page.getByRole('textbox').first().fill('Server accepted field text')
  await page.getByRole('button', { name: 'Save field', exact: true }).click()
  await expect.poll(() => fieldStarted).toBe(true)
  try {
    await page.getByRole('button', { name: 'Source', exact: true }).click()
    await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 60000 })
    const codeInput = page.locator('.monaco-editor .inputarea, .monaco-editor .native-edit-context')
    await expect(codeInput).toHaveCount(1)
    await codeInput.focus()
    await page.keyboard.press('Control+End')
    await page.keyboard.press('Enter')
    await page.keyboard.type('% Newer local source edit')
    await expect.poll(() => readMonacoSource(page)).toContain('% Newer local source edit')
    const completedField = page.waitForResponse((response) => response.request().method() === 'PATCH'
      && response.url().endsWith(`/resumes/${resumeId}/engine/document`))
    releaseField()
    await completedField
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
    await expect.poll(() => readMonacoSource(page)).toContain('% Newer local source edit')
    expect(runtimeErrors).toEqual([])
  } finally { releaseField() }
})

test('verified PDF field supports keyboard selection and mobile field pane', async ({ page }) => {
  test.setTimeout(240000)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.routeWebSocket('**/ws/jobs**', socket => socket.close({ code: 1000, reason: 'Contract test uses state recovery' }))
  const pdf = samplePdf(GUEST_ORIGINAL_BULLET); const pdfSha = createHash('sha256').update(pdf).digest('hex')
  let source = ''; let fingerprint = ''
  const traffic = { admissions: 0, states: 0, pdf: 0 }
  const artifactId = digest('immutable-test-artifact')
  const artifact = () => ({ job_id: 'mapped-preview', artifact_id: artifactId, source_sha256: digest(source), pdf_sha256: pdfSha,
    pdf_size: pdf.length, page_count: 1, document_id: 'guest', content_revision: 1, branch: 'draft', owner_epoch: 1,
    compiler: 'pdflatex', settings_sha256: digest('test-settings'), preview_url: `/download/mapped-preview/preview/${artifactId}`,
    geometry_url: `/download/mapped-preview/preview/${artifactId}/geometry` })
  await mockEngineAncillaryApi(page)
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: null }))
  await page.route('**/public/trial-status**', route => route.fulfill({ json: { usageCount: 0, remainingUses: 3, blocked: false, canUse: true, trialLimit: 3 } }))
  await page.route('**/public/engine/document', async route => { source = route.request().postDataJSON().latex_content; await route.fulfill({ json: { document: projectGuestBullet(source), latex_content: source } }) })
  await page.route('**/jobs/submit', async route => { traffic.admissions++; const body = route.request().postDataJSON(); source = body.latex_content; fingerprint = body.device_fingerprint; await route.fulfill({ json: { success: true, job_id: 'mapped-preview' } }) })
  await page.route('**/jobs/mapped-preview/state', route => { traffic.states++; return route.fulfill({ json: { status: 'completed', stage: '', percent: 100, artifact: artifact(), last_updated: Date.now() / 1000 } }) })
  await page.route('**/jobs/mapped-preview/result', route => route.fulfill({ json: { success: true, job_id: 'mapped-preview', result: { success: true, job_id: 'mapped-preview', pdf_job_id: 'mapped-preview', compilation_time: .01 } } }))
  await page.route(`**/download/mapped-preview/preview/${artifactId}`, async route => {
    traffic.pdf++
    expect(route.request().headers()['x-device-fingerprint']).toBe(fingerprint)
    await route.fulfill({ contentType: 'application/pdf', body: pdf })
  })
  await page.route(`**/download/mapped-preview/preview/${artifactId}/geometry`, async route => {
    expect(route.request().headers()['x-device-fingerprint']).toBe(fingerprint)
    const node = projectGuestBullet(source).nodes[0]
    await route.fulfill({ json: { schema_version: 1, coordinate_system: 'pdf_points_top_left', artifact_id: artifactId,
      source_sha256: digest(source), pdf_sha256: pdfSha, document_id: 'guest', content_revision: 1, branch: 'draft',
      pages: [{ page: 1, width: 612, height: 792, rotation: 0 }],
      boxes: [{ ...node, page: 1, x: 40, y: 42, width: 300, height: 12 }], omissions: [] } })
  })
  await page.goto('/try', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: `Experience · bullet ${GUEST_ORIGINAL_BULLET}`, exact: true }).waitFor()
  await page.getByRole('button', { name: 'Update PDF', exact: true }).click()
  await expect.poll(() => traffic.admissions, { message: 'Manual update must admit a job' }).toBe(1)
  await expect.poll(() => traffic.states, { message: 'Closed socket must recover via state' }).toBeGreaterThan(0)
  await expect.poll(() => traffic.pdf, { message: 'Recovered immutable artifact must fetch bytes' }).toBeGreaterThan(0)
  await expect(page.locator('.react-pdf__Page__canvas')).toBeVisible({ timeout: 60000 })
  const overlay = page.getByRole('button', { name: `Edit resume field: ${GUEST_ORIGINAL_BULLET}`, exact: true })
  await expect(overlay).toBeVisible()
  await overlay.focus(); await page.keyboard.press('Enter')
  await expect(page.getByLabel('Experience · bullet')).toHaveValue(GUEST_ORIGINAL_BULLET)
  await expect(page.getByRole('heading', { name: 'Edit your resume' })).toBeVisible()
  await expect(page.locator('.monaco-editor')).toHaveCount(0)
})
