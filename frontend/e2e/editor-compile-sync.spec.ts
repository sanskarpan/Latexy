import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { gunzipSync } from 'node:zlib'
import { execFileSync } from 'node:child_process'
import { installMockWorkboxRegistration } from './helpers/mock-workbox-registration'

const RESUME_ID = '5e735a58-a439-4976-93ef-0718d06919ea'
const SOURCE = readFileSync(join(__dirname, 'fixtures/compile-sync/resume.tex'), 'utf8')

test.use({ serviceWorkers: 'block' })

// A valid Letter PDF with the native fixture's source-line baselines.
// Local acceptance can additionally use the actual native pdfTeX PDF/SyncTeX.
function fixturePdf(): Buffer {
  const nativeDir = process.env.EDITOR_SYNC_NATIVE_FIXTURE_DIR
  if (nativeDir) return readFileSync(join(nativeDir, 'resume.pdf'))
  const stream = 'BT /F1 10 Tf 148.712 657.235382 Td (First line.) Tj 0 -11.955166 Td (Second line.) Tj ET'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = objects.map((object, index) => {
    const offset = Buffer.byteLength(pdf)
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
    return offset
  })
  const xref = Buffer.byteLength(pdf)
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}`
  pdf += `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(pdf)
}

function fixtureSynctex(): string {
  const nativeDir = process.env.EDITOR_SYNC_NATIVE_FIXTURE_DIR
  if (nativeDir) return gunzipSync(readFileSync(join(nativeDir, 'resume.synctex.gz'))).toString()
  return readFileSync(join(__dirname, 'fixtures/compile-sync/resume.synctex'), 'utf8')
}

function fixturePageDimensions() {
  const nativeDir = process.env.EDITOR_SYNC_NATIVE_FIXTURE_DIR
  if (!nativeDir) return { width: 612, height: 792 }
  const info = execFileSync('pdfinfo', [join(nativeDir, 'resume.pdf')], { encoding: 'utf8' })
  const dimensions = info.match(/Page size:\s*([\d.]+) x ([\d.]+) pts/)
  if (!dimensions) throw new Error('Native fixture must expose its actual PDF page dimensions')
  return { width: Number(dimensions[1]), height: Number(dimensions[2]) }
}

async function installFixture(page: Page) {
  await installMockWorkboxRegistration(page)
  const submitted: Array<{ latex_content: string; job_type: string }> = []
  const unknown: string[] = []
  const errors: string[] = []
  const submittedAt: number[] = []
  const synctexOverrides = new Map<string, string>()
  const subscribers = new Map<string, () => void>()
  let sequence = 0
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    localStorage.setItem('latexy_auto_compile', 'false')
    localStorage.setItem('latexy_high_contrast', 'false')
  })
  // All app backend traffic is synthetic. Unknown traffic fails closed.
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/auth/get-session') {
      return route.fulfill({ json: { session: { token: 'editor-fixture-token' }, user: { id: 'editor-fixture-owner', email: 'editor-fixture@example.test', name: 'Editor fixture' } } })
    }
    if (url.origin === new URL(page.url() === 'about:blank' ? test.info().project.use.baseURL! : page.url()).origin) return route.continue()
    if (path === `/resumes/${RESUME_ID}`) {
      return route.fulfill({ json: { id: RESUME_ID, user_id: 'editor-fixture-owner', access_role: 'owner', title: 'Compile and SyncTeX fixture', latex_content: SOURCE, metadata: {}, created_at: '2026-10-06T00:00:00Z', updated_at: '2026-10-06T00:00:00Z' } })
    }
    if (path === '/jobs/submit') {
      submitted.push(route.request().postDataJSON())
      submittedAt.push(Date.now())
      return route.fulfill({ json: { success: true, job_id: `editor-fixture-job-${submitted.length}`, message: 'Started' } })
    }
    if (/^\/download\/editor-fixture-job-\d+\/synctex$/.test(path)) {
      const jobId = path.split('/')[2]
      return route.fulfill({ contentType: 'text/plain', body: synctexOverrides.get(jobId) ?? fixtureSynctex() })
    }
    if (/^\/download\/editor-fixture-job-\d+$/.test(path)) return route.fulfill({ contentType: 'application/pdf', body: fixturePdf() })
    if (/^\/jobs\/editor-fixture-job-\d+\/state$/.test(path)) return route.fulfill({ json: { status: 'processing', stage: 'latex_compilation', percent: 10, last_updated: Date.now() / 1000 } })
    if (path === '/ws/ticket') return route.fulfill({ status: 201, json: { ticket: 'editor-fixture-ticket', expires_in: 30 } })
    if (path.includes('/checkpoints') || path.includes('/comments') || path.includes('/collaborators') || path.includes('/suggestions') || path === '/resumes/stats') return route.fulfill({ json: [] })
    if (path === '/ats/quick-score') return route.fulfill({ json: { score: 70, grade: 'C', sections_found: [], missing_sections: [] } })
    if (path === '/config/entitlements' && route.request().method() === 'GET') return route.fulfill({ json: { features: {} } })
    if (path === '/tenants/resolve-host' && route.request().method() === 'GET') return route.fulfill({ json: { tenant: null } })
    if (path === '/macros' && route.request().method() === 'GET') return route.fulfill({ json: [] })
    if (path === '/subscription/current' && route.request().method() === 'GET') return route.fulfill({ json: { userId: 'editor-fixture-owner', planId: 'free', planName: 'Free', status: 'active', features: { compilations: 10, optimizations: 3, historyRetention: 7, prioritySupport: false, apiAccess: false } } })
    if (path === '/ai/confidence-score' && route.request().method() === 'POST') return route.fulfill({ json: { overall: 70, writing_quality: 70, completeness: 70, quantification: 70, formatting: 70, section_order: 70, grade: 'C', improvements: [], cached: false } })
    if (path.endsWith('/academic-cv-report')) return route.fulfill({ json: { is_academic_cv: false, detected_sections: [], estimated_pages: 1, confidence: 0 } })
    if (['/me', '/config/feature-flags', '/trial/status', '/github/status', '/dropbox/status', '/tenants/current-context', '/telemetry/frontend'].includes(path) || path.startsWith('/analytics') || path.startsWith('/public/trial')) return route.fulfill({ json: {} })
    unknown.push(`${route.request().method()} ${path}`)
    return route.abort()
  })
  await page.routeWebSocket('**/ws/jobs**', ws => {
    ws.onMessage(raw => {
      const message = JSON.parse(String(raw))
      if (message.type === 'ping') return ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
      if (message.type !== 'subscribe') return
      const jobId = String(message.job_id)
      ws.send(JSON.stringify({ type: 'subscribed', job_id: jobId, replayed_count: 0 }))
      subscribers.set(jobId, () => ws.send(JSON.stringify({ type: 'event', event: { type: 'job.completed', job_id: jobId, event_id: `editor-fixture-${++sequence}`, sequence, timestamp: Date.now() / 1000, pdf_job_id: jobId, ats_score: 70, ats_details: {}, changes_made: [], compilation_time: 1, optimization_time: 0, tokens_used: 0, page_count: 1 } })))
    })
  })
  await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor?.getValue())).toBe(SOURCE)
  return {
    submitted, submittedAt, synctexOverrides, unknown, errors,
    async complete(index: number) {
      const jobId = `editor-fixture-job-${index}`
      await expect.poll(() => subscribers.has(jobId)).toBe(true)
      subscribers.get(jobId)!()
      await expect(page.locator('.react-pdf__Page__canvas').first()).toBeVisible()
      await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeEnabled()
    },
  }
}

async function appendText(page: Page, text: string) {
  await page.evaluate(value => {
    const editor = (window as any).__latexyMonacoEditor
    const model = editor.getModel()
    const line = Math.max(3, model.getLineCount() - 2)
    const column = model.getLineMaxColumn(line)
    editor.executeEdits('compile-sync-test', [{ range: { startLineNumber: line, startColumn: column, endLineNumber: line, endColumn: column }, text: value }])
  }, text)
}

test('coalesces typing, retains busy edits, and does not repeat a matching manual compile', async ({ page }) => {
  const fixture = await installFixture(page)
  // Keep Monaco's input/animation timers real. Exact deadline/cadence boundaries
  // are tested with injected timers in the scheduler unit suite; freezing the
  // entire browser clock prevents Monaco from settling native keyboard input.
  await page.getByRole('button', { name: 'Auto-compile on change', exact: true }).click()
  await page.evaluate(() => {
    const editor = (window as any).__latexyMonacoEditor
    const model = editor.getModel()
    editor.setPosition({ lineNumber: 5, column: model.getLineMaxColumn(5) })
    editor.focus()
  })
  const words = Array.from({ length: 60 }, (_, index) => ` word${index}`).join('')
  await page.keyboard.type(words)
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor.getValue())).toBe(SOURCE.replace('Second line.', `Second line.${words}`))
  expect(fixture.submitted).toHaveLength(0)
  await page.waitForTimeout(3_500)
  expect(fixture.submitted).toHaveLength(0)
  await expect.poll(() => fixture.submitted.length).toBe(1)
  expect(fixture.submitted[0].job_type).toBe('latex_compilation')
  expect(fixture.submitted[0].latex_content).toBe(SOURCE.replace('Second line.', `Second line.${words}`))
  await appendText(page, ' pending latest')
  await page.waitForTimeout(15_000)
  expect(fixture.submitted).toHaveLength(1)
  await fixture.complete(1)
  await expect.poll(() => fixture.submitted.length).toBe(2)
  expect(fixture.submitted[1].latex_content).toContain('pending latest')
  await fixture.complete(2)
  await page.getByRole('button', { name: 'Auto-compile on change', exact: true }).click()
  await appendText(page, ' manually compiled')
  await page.getByRole('button', { name: 'Compile', exact: true }).click()
  await expect.poll(() => fixture.submitted.length).toBe(3)
  await fixture.complete(3)
  await page.getByRole('button', { name: 'Auto-compile on change', exact: true }).click()
  await page.waitForTimeout(12_000)
  expect(fixture.submitted).toHaveLength(3)
  expect(fixture.unknown).toEqual([])
  expect(fixture.errors).toEqual([])
})

test('divider actions, modifier clicks, and repeat highlights synchronize the actual PDF without navigation', async ({ page }) => {
  const fixture = await installFixture(page)
  const initialUrl = page.url()
  await page.getByRole('button', { name: 'Compile', exact: true }).click()
  await expect.poll(() => fixture.submitted.length).toBe(1)
  await fixture.complete(1)
  await page.evaluate(() => (window as any).__latexyMonacoEditor.setPosition({ lineNumber: 3, column: 1 }))
  const forward = page.getByRole('button', { name: 'Show source line 3 in PDF', exact: true })
  await expect(forward).toBeEnabled()
  expect(await page.locator('[data-synctex-highlight]').count()).toBe(0)
  await forward.click()
  await expect(page.locator('[data-synctex-highlight]')).toBeVisible()
  await page.waitForTimeout(2_100)
  await expect(page.locator('[data-synctex-highlight]')).toHaveCount(0)
  await forward.click()
  await expect(page.locator('[data-synctex-highlight]')).toBeVisible()
  const pdf = page.locator('.react-pdf__Page[data-page-number="1"]')
  const bounds = await pdf.boundingBox()
  expect(bounds).not.toBeNull()
  const dimensions = fixturePageDimensions()
  const position = { x: 170 * bounds!.width / dimensions.width, y: 134.764618 * bounds!.height / dimensions.height }
  await page.evaluate(() => (window as any).__latexyMonacoEditor.setPosition({ lineNumber: 1, column: 1 }))
  await pdf.click({ position })
  expect(await page.evaluate(() => (window as any).__latexyMonacoEditor.getPosition().lineNumber)).toBe(1)
  const reverse = page.getByRole('button', { name: 'Show source line 3', exact: true })
  await expect(reverse).toBeEnabled()
  await reverse.click()
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor.getPosition().lineNumber)).toBe(3)
  await expect(page.locator('.synctex-highlight').first()).toBeVisible()
  await page.waitForTimeout(2_100)
  await reverse.click()
  await expect(page.locator('.synctex-highlight').first()).toBeVisible()
  await page.evaluate(() => (window as any).__latexyMonacoEditor.setPosition({ lineNumber: 1, column: 1 }))
  await pdf.click({ position, modifiers: ['Control'] })
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor.getPosition().lineNumber)).toBe(3)
  await page.evaluate(() => (window as any).__latexyMonacoEditor.setPosition({ lineNumber: 1, column: 1 }))
  await pdf.dblclick({ position })
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor.getPosition().lineNumber)).toBe(3)
  await page.waitForTimeout(2_100)
  await page.locator('.view-line').filter({ hasText: 'First line.' }).click({ modifiers: ['Control'] })
  await expect(page.locator('[data-synctex-highlight]')).toBeVisible()
  await page.evaluate(() => (window as any).__latexyMonacoEditor.setPosition({ lineNumber: 1, column: 1 }))
  await pdf.click({ position, modifiers: ['Meta'] })
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor.getPosition().lineNumber)).toBe(3)

  // The late-mounted viewer observes panel resizing and still maps the actual
  // PDF coordinates after zoom. Arrow keyboard activation must not resize it.
  const separator = page.getByRole('separator', { name: 'Resize editor and preview panes' })
  await separator.focus()
  const originalWidth = Number(await separator.getAttribute('aria-valuenow'))
  await separator.press('ArrowLeft')
  await expect.poll(async () => Number(await separator.getAttribute('aria-valuenow'))).toBe(originalWidth + 16)
  await reverse.focus()
  await reverse.press('Enter')
  await expect.poll(async () => Number(await separator.getAttribute('aria-valuenow'))).toBe(originalWidth + 16)
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Reset zoom to 100%', exact: true })).toHaveText('115%')
  await expect.poll(async () => (await pdf.boundingBox())!.width).toBeGreaterThan(bounds!.width)
  const zoomed = (await pdf.boundingBox())!
  await page.evaluate(() => (window as any).__latexyMonacoEditor.setPosition({ lineNumber: 1, column: 1 }))
  await pdf.click({ position: { x: 170 * zoomed.width / dimensions.width, y: 134.764618 * zoomed.height / dimensions.height }, modifiers: ['Meta'] })
  await expect.poll(() => page.evaluate(() => (window as any).__latexyMonacoEditor.getPosition().lineNumber)).toBe(3)
  // A manually enlarged panel must be clamped when the viewport shrinks, and
  // the accessible separator maximum must reflect that new viewport.
  await separator.focus()
  for (let index = 0; index < 25; index++) await separator.press('ArrowLeft')
  await page.setViewportSize({ width: 1000, height: 720 })
  await expect(separator).toHaveAttribute('aria-valuemax', '700')
  await expect(separator).toHaveAttribute('aria-valuenow', '700')
  expect(page.url()).toBe(initialUrl)
  expect(fixture.unknown).toEqual([])
  expect(fixture.errors).toEqual([])
})

test('bounds automatic cadence even after a fast compile and cancels pending work when disabled', async ({ page }) => {
  const fixture = await installFixture(page)
  const auto = page.getByRole('button', { name: 'Auto-compile on change', exact: true })
  await auto.click()
  await appendText(page, ' first automatic')
  await expect.poll(() => fixture.submitted.length).toBe(1)
  await appendText(page, ' newest automatic')
  await fixture.complete(1)
  await expect.poll(() => fixture.submitted.length).toBe(2)
  // Server receipt timing includes small transport/React scheduling variance;
  // the injected-timer unit test asserts the exact 10,000ms boundary.
  expect(fixture.submittedAt[1] - fixture.submittedAt[0]).toBeGreaterThanOrEqual(9_800)
  expect(fixture.submitted[1].latex_content).toContain('newest automatic')
  await fixture.complete(2)
  await appendText(page, ' queued while disabled')
  await auto.click()
  await page.waitForTimeout(12_000)
  expect(fixture.submitted).toHaveLength(2)
  expect(fixture.unknown).toEqual([])
  expect(fixture.errors).toEqual([])
})

test('retains the prior PDF while busy and disables stale selections if the new artifact has no mapping', async ({ page }) => {
  const fixture = await installFixture(page)
  await page.getByRole('button', { name: 'Compile', exact: true }).click()
  await fixture.complete(1)
  const pdf = page.locator('.react-pdf__Page[data-page-number="1"]')
  const dimensions = fixturePageDimensions()
  const bounds = (await pdf.boundingBox())!
  await pdf.click({ position: { x: 170 * bounds.width / dimensions.width, y: 134.764618 * bounds.height / dimensions.height } })
  await expect(page.getByRole('button', { name: 'Show source line 3', exact: true })).toBeEnabled()
  fixture.synctexOverrides.set('editor-fixture-job-2', '')
  await page.getByRole('button', { name: 'Auto-compile on change', exact: true }).click()
  await appendText(page, ' edited content')
  await expect.poll(() => fixture.submitted.length).toBe(2)
  await expect(page.locator('.react-pdf__Page__canvas').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Compiling…', exact: true })).toBeDisabled()
  await fixture.complete(2)
  await expect(page.getByRole('button', { name: 'Show the selected source line in PDF', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Select a PDF location mapped to source', exact: true })).toBeDisabled()
  await expect(page.locator('[data-synctex-highlight]')).toHaveCount(0)
  expect(fixture.unknown).toEqual([])
  expect(fixture.errors).toEqual([])
})
