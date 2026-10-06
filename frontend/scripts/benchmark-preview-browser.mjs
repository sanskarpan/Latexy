import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const frontendUrl = 'http://localhost:5361'
const backendUrl = 'http://127.0.0.1:8530'
const fieldFirst = process.env.ENGINE_QA_FIELD_FIRST === '1'
const folder = resolve(process.cwd(), '../docs/audits/resume-engine')
await mkdir(folder, { recursive: true })
const report = {
  measured_at_utc: new Date().toISOString(), frontend_url: frontendUrl, backend_url: backendUrl,
  compiler: 'pdflatex', environment: 'isolated local CPU Celery, warm seed image, fresh browser context',
  scenario: fieldFirst ? 'fresh guest saves a field before first PDF' : 'one guest renders, repeats source, then saves a field',
  limitations: ['Development Next and local backend, not production or Modal latency', 'Three functional samples do not support percentile claims'],
  samples: [], failures: [], console_errors: [], quota_cooldown_waits: [],
}
const browser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  globalThis.qaPage = page
  await page.route('**/api/auth/get-session', route => route.fulfill({ json: null }))
  const metrics = []; const jobs = []; const geometries = []; const states = []; const errors = []; const requests = []; const failedRequests = []
  const httpTimings = []; const eventTimings = []; const requestStarts = new WeakMap()
  let previewFingerprint = null
  let submittedFingerprint = null
  report.diagnostics = { jobs, states, errors, geometry: geometries, requests, failedRequests, httpTimings, eventTimings }
  page.on('websocket', ws => ws.on('framereceived', frame => {
    try {
      const event = JSON.parse(String(frame.payload)).event
      if (event && ['job.started', 'job.completed', 'artifact.ready'].includes(event.type)) eventTimings.push({ type: event.type, job_id: event.job_id, observed_at_utc: new Date().toISOString(), server_timestamp: event.timestamp })
    } catch {}
  }))
  page.on('requestfailed', request => { const url = new URL(request.url()); failedRequests.push({ origin: url.origin, path: url.pathname, error: request.failure()?.errorText }) })
  page.on('request', request => {
    requestStarts.set(request, Date.now())
    const url = new URL(request.url()); if (['127.0.0.1', 'localhost'].includes(url.hostname) && request.resourceType() === 'fetch') requests.push({ origin: url.origin, path: url.pathname, method: request.method() })
    if (url.origin === backendUrl && url.pathname === '/jobs/submit') submittedFingerprint = request.postDataJSON().device_fingerprint ?? null
    if (url.origin === backendUrl && url.pathname.includes('/preview/')) {
      const fingerprint = request.headers()['x-device-fingerprint'] ?? null
      if (!url.pathname.endsWith('/geometry') && !url.pathname.endsWith('/synctex')) previewFingerprint = fingerprint
      const entry = requests.at(-1)
      if (entry?.path === url.pathname) Object.assign(entry, { fingerprint_present: Boolean(fingerprint), fingerprint_matches_pdf: fingerprint === previewFingerprint, fingerprint_matches_admission: fingerprint === submittedFingerprint })
    }
    if (request.url() === backendUrl + '/telemetry/frontend') {
      try {
        const body = request.postDataJSON()
        if (['PDF_USER_ACTION_PAINT', 'PDF_RENDER_PAINT'].includes(body.name)) metrics.push({ name: body.name, value_ms: body.value })
      } catch {}
    }
  })
  page.on('response', async response => {
    try {
      if (response.url().startsWith(backendUrl)) httpTimings.push({ path: new URL(response.url()).pathname, status: response.status(), duration_ms: Date.now() - (requestStarts.get(response.request()) ?? Date.now()) })
      if (response.url() === backendUrl + '/jobs/submit' && response.request().method() === 'POST') jobs.push({ status: response.status(), body: await response.json() })
      if (response.url().startsWith(backendUrl) && response.url().endsWith('/state')) { const body = await response.json(); states.push({ http: response.status(), status: body.status, stage: body.stage, has_artifact: Boolean(body.artifact) }) }
      if (response.url().startsWith(backendUrl) && response.status() >= 400) errors.push({ path: new URL(response.url()).pathname, status: response.status() })
      if (response.url().includes('/preview/') && response.url().endsWith('/geometry') && response.ok()) {
        const body = await response.json()
        geometries.push({ box_count: body.boxes?.length ?? 0, omission_count: body.omissions?.length ?? 0 })
      }
    } catch {}
  })
  page.on('pageerror', error => report.failures.push({ type: 'browser_runtime', message: error.message }))
  page.on('console', message => {
    if (message.type() !== 'error') return
    const text = message.text().slice(0, 2000)
    report.console_errors.push(text)
    if (/TypeError|ReferenceError|ErrorBoundary|above error occurred/.test(text)) report.failures.push({ type: 'browser_console', message: text })
  })
  await page.goto(frontendUrl + '/try', { waitUntil: 'domcontentloaded', timeout: 240000 })
  await page.getByRole('heading', { name: 'Edit your resume' }).waitFor({ timeout: 30000 })
  // This field is fetched by the mounted client, unlike the SSR heading.
  await page.getByRole('button', { name: /^Experience · bullet Built internal design system used across 6 product surfaces/ }).waitFor({ timeout: 60000 })
  if (await page.locator('.monaco-editor').count()) throw new Error('Source editor mounted in Resume mode')
  async function waitFor(check, timeout = 90000) {
    const start = Date.now()
    while (!check()) {
      if (Date.now() - start > timeout) throw new Error('Preview did not reach first paint')
      await new Promise(resolve => setTimeout(resolve, 100))
    }
  }
  async function sample(name, action) {
    const before = metrics.length; const jobBefore = jobs.length; const start = Date.now()
    await action()
    if (process.env.ENGINE_QA_DIAGNOSTIC === '1') { await new Promise(resolve => setTimeout(resolve, 7000)); process.stdout.write(JSON.stringify({ requests, jobs, failedRequests }) + '\n'); throw new Error('Diagnostic capture complete') }
    await waitFor(() => metrics.slice(before).some(metric => metric.name === 'PDF_USER_ACTION_PAINT'))
    await page.locator('.react-pdf__Page__canvas').first().waitFor({ state: 'visible' })
    report.samples.push({ name, observed_wall_ms: Date.now() - start,
      user_action_to_paint_ms: metrics.slice(before).find(metric => metric.name === 'PDF_USER_ACTION_PAINT').value_ms,
      verified_blob_to_paint_ms: metrics.slice(before).find(metric => metric.name === 'PDF_RENDER_PAINT')?.value_ms ?? null,
      admission_http_status: jobs[jobBefore]?.status ?? null, geometry: geometries.at(-1) ?? null })
    process.stdout.write(JSON.stringify({ completed_sample: report.samples.at(-1) }) + '\n')
    for (let i = 0; i < 300 && !(await page.getByRole('button', { name: 'Update PDF', exact: true }).isEnabled()); i++) await new Promise(resolve => setTimeout(resolve, 100))
  }
  async function respectGuestCooldown(name) {
    if (!submittedFingerprint) throw new Error('No admitted guest identity for cooldown check')
    const response = await context.request.get(backendUrl + '/public/trial-status?fingerprint=' + encodeURIComponent(submittedFingerprint))
    if (!response.ok()) throw new Error('Guest status could not be checked before next action')
    const status = await response.json()
    // This endpoint exposes lastUsed, while the admission endpoint enforces
    // trial_service.COOLDOWN_PERIOD (300 seconds); waitTime is not in its DTO.
    const lastUsed = Date.parse(status.lastUsed ?? '')
    const milliseconds = status.waitTime != null ? Number(status.waitTime) * 1000
      : Number.isFinite(lastUsed) ? Math.max(0, 300000 - (Date.now() - lastUsed)) : 0
    const seconds = Math.ceil(milliseconds / 1000) + 1
    if (seconds > 361) throw new Error('Guest cooldown exceeds the documented probe bound')
    if (seconds <= 1) return
    report.quota_cooldown_waits.push({ before_sample: name, seconds })
    process.stdout.write(JSON.stringify({ respecting_guest_cooldown_seconds: seconds, before_sample: name }) + '\n')
    let remaining = seconds * 1000
    while (remaining > 0) { const interval = Math.min(30000, remaining); await new Promise(resolve => setTimeout(resolve, interval)); remaining -= interval }
  }
  if (!fieldFirst) {
    await sample('starter-first-render', () => page.getByRole('button', { name: 'Update PDF', exact: true }).click())
    await respectGuestCooldown('identical-source-cache')
    await sample('identical-source-cache', () => page.getByRole('button', { name: 'Update PDF', exact: true }).click())
  }
  await page.getByRole('button', { name: /^Experience · bullet Built internal design system used across 6 product surfaces/ }).click()
  await page.getByLabel('Experience · bullet').fill('Built internal design system used across 8 product surfaces')
  if (!fieldFirst) await respectGuestCooldown('saved-field-update')
  await sample(fieldFirst ? 'saved-field-first-render' : 'saved-field-update', () => page.getByRole('button', { name: 'Save field', exact: true }).click())
  report.geometry_overlay_buttons = await page.getByRole('button', { name: /^Edit resume field:/ }).count()
  if (!report.geometry_overlay_buttons) throw new Error('Shipped starter did not expose verified PDF field geometry')
  if (report.geometry_overlay_buttons) {
    await page.getByRole('button', { name: /^Edit resume field:/ }).first().focus()
    await page.keyboard.press('Enter')
    await page.getByRole('textbox').first().waitFor({ state: 'visible' })
    report.geometry_keyboard_selection = true
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: 'PDF', exact: true }).click()
    await page.getByRole('button', { name: /^Edit resume field:/ }).first().click()
    await page.getByRole('heading', { name: 'Edit your resume' }).waitFor({ state: 'visible' })
    report.geometry_mobile_selection_opens_fields = true
    await page.screenshot({ path: resolve(folder, 'guest-real-pdf-mobile-fields.png'), fullPage: false })
    await page.setViewportSize({ width: 1440, height: 1000 })
  }
  if (jobs.length !== (fieldFirst ? 1 : 3)) throw new Error(`Unexpected admission count: ${jobs.length}`)
  if (await page.locator('.monaco-editor').count()) throw new Error('Source editor mounted after plain field save')
  await page.screenshot({ path: resolve(folder, 'guest-real-pdf-preview.png'), fullPage: false })
  await page.getByRole('button', { name: 'Source', exact: true }).click()
  await page.locator('.monaco-editor').waitFor({ state: 'visible', timeout: 60000 })
  report.source_mode_loaded_on_demand = true
} catch (error) {
  report.failures.push({ type: 'probe', message: error.message }); process.exitCode = 1
  try { await globalThis.qaPage.screenshot({ path: resolve(folder, 'guest-real-pdf-failure.png'), fullPage: false }) } catch {}
} finally {
  await browser.close()
  await writeFile(resolve(folder, 'preview-browser-benchmark.json'), JSON.stringify(report, null, 2) + '\n')
  process.stdout.write(JSON.stringify({ samples: report.samples, failures: report.failures }) + '\n')
}
