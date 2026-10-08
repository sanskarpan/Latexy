import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

// Explicit opt-in: real guest quota is consumed, never mocked or reset.
if (process.env.LATEXY_PRODUCTION_AUDIT !== '1') throw new Error('Set LATEXY_PRODUCTION_AUDIT=1 to test the deployed site')
const origin = 'https://latexy.xyz'
const api = 'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run'
const folder = resolve(process.env.LATEXY_AUDIT_DIR ?? '../docs/audits/resume-engine/production-2026-10-08')
await mkdir(folder, { recursive: true })
const report = { measured_at_utc: new Date().toISOString(), origin, api,
  scope: 'Normal production guest, no authentication spoofing, no quota bypass, no paid AI requests',
  limitations: ['Single-browser observational run; no percentile or regional claims', 'Client and server clock offsets are unknown'],
  navigation: [], http: [], events: [], failures: [], inspection_errors: [], console_errors: [], samples: [], identities: {} }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
let page
const pending = new Set()
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  page = await context.newPage()
  const starts = new WeakMap()
  const safePath = value => { const url = new URL(value); return { origin: url.origin, path: url.pathname } }
  page.on('request', req => starts.set(req, Date.now()))
  page.on('requestfailed', req => report.failures.push({ ...safePath(req.url()), error: req.failure()?.errorText }))
  page.on('pageerror', error => report.failures.push({ runtime_error: error.message }))
  page.on('console', msg => { if (msg.type() === 'error') report.console_errors.push(msg.text().slice(0, 500)) })
  page.on('response', response => {
    const work = (async () => {
      const req = response.request()
      const row = { ...safePath(response.url()), method: req.method(), type: req.resourceType(), status: response.status(),
        response_headers_ms: Date.now() - (starts.get(req) ?? Date.now()) }
      report.http.push(row)
      if (row.path === '/jobs/submit' && req.method() === 'POST') {
        const body = await response.json()
        row.job_id = body.job_id
        row.admission_status = body.status
      }
      const complete = await Promise.race([response.finished().then(() => true), new Promise(resolve => setTimeout(() => resolve(false), 10000))])
      if (complete) row.response_complete_ms = Date.now() - (starts.get(req) ?? Date.now())
      else row.inspection_timeout = true
      row.network_timing = req.timing()
    })().catch(error => report.inspection_errors.push({ response_inspection: error.message.slice(0, 250) }))
    pending.add(work); work.finally(() => pending.delete(work))
  })
  page.on('websocket', ws => {
    const entry = { ...safePath(ws.url()), opened_at_utc: new Date().toISOString(), frames: [] }
    report.events.push(entry)
    ws.on('framereceived', frame => {
      try {
        const data = JSON.parse(String(frame.payload)); const event = data.event ?? data
        // Preserve timing and stage only; never source, tokens, fingerprints or credentials.
        entry.frames.push({ observed_at_utc: new Date().toISOString(), type: event.type,
          job_id: event.job_id, server_timestamp: event.timestamp, stage: event.stage,
          progress: event.progress, status: event.status, code: event.code })
      } catch {}
    })
    ws.on('close', () => { entry.closed_at_utc = new Date().toISOString() })
  })
  for (const [name, url] of [['frontend', origin + '/api/deployment-identity'], ['backend', api + '/health']]) {
    const start = Date.now()
    try {
      const response = await context.request.get(url, { timeout: 30000 })
      report.identities[name] = { status: response.status(), elapsed_ms: Date.now() - start, body: await response.json() }
    } catch (error) { report.identities[name] = { error: error.message.slice(0, 200), elapsed_ms: Date.now() - start } }
  }
  for (const path of ['/', '/platform', '/templates', '/pricing', '/resources', '/faq', '/try']) {
    const started = Date.now()
    await page.goto(origin + path, { waitUntil: 'load', timeout: 60000 })
    const nav = await page.evaluate(() => ({ navigation: performance.getEntriesByType('navigation').map(x => x.toJSON()),
      paint: performance.getEntriesByType('paint').map(x => x.toJSON()),
      images: [...document.images].map(x => ({ path: new URL(x.src).pathname, loaded: x.complete && x.naturalWidth > 0 })) }))
    report.navigation.push({ path, observed_load_ms: Date.now() - started, ...nav })
    process.stdout.write(JSON.stringify({ page: path, elapsed_ms: Date.now() - started }) + '\n')
  }
  await page.getByRole('button', { name: /^(Recompile|Update PDF)$/ }).waitFor({ state: 'visible', timeout: 60000 })
  await writeFile(resolve(folder, 'studio-before.txt'), await page.locator('body').innerText())
  await page.screenshot({ path: resolve(folder, 'studio-before.png') })
  if (process.env.LATEXY_AUDIT_COMPILE === '1') {
    const start = Date.now()
    await page.getByRole('button', { name: /^(Recompile|Update PDF)$/ }).click()
    process.stdout.write(JSON.stringify({ compile_started_at_utc: new Date(start).toISOString() }) + '\n')
    try {
      await page.locator('.react-pdf__Page__canvas').first().waitFor({ state: 'visible', timeout: 120000 })
      await page.waitForFunction(() => { const c = document.querySelector('.react-pdf__Page__canvas'); return c && c.width > 0 && c.height > 0 })
      // Width and visibility alone may precede rendering; the next paint is a bounded UI proxy.
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      report.samples.push({ name: 'starter-compile', action_to_visible_canvas_ms: Date.now() - start,
        paint_measurement: 'visible nonzero canvas followed by two animation frames; no app telemetry assumption' })
    } catch (error) { report.samples.push({ name: 'starter-compile', elapsed_ms: Date.now() - start, error: error.message.slice(0, 250) }) }
    await writeFile(resolve(folder, 'studio-after.txt'), await page.locator('body').innerText())
    await page.screenshot({ path: resolve(folder, 'studio-after.png') })
    process.stdout.write(JSON.stringify({ compile_sample: report.samples.at(-1) }) + '\n')
  }
  report.final_url = page.url()
  report.deployed_no_code_toggle = await page.getByRole('button', { name: 'Resume', exact: true }).count()
  report.loaded_monaco = await page.locator('.monaco-editor').count()
} catch (error) {
  report.failures.push({ probe: error.message })
  try { await page.screenshot({ path: resolve(folder, 'failure.png') }) } catch {}
  process.exitCode = 1
} finally {
  // Persist before cleanup too: a hung browser response must not lose measurements.
  await writeFile(resolve(folder, 'production-latency.json'), JSON.stringify(report, null, 2) + '\n')
  await Promise.race([Promise.allSettled([...pending]), new Promise(resolve => setTimeout(resolve, 11000))])
  await browser.close()
  await writeFile(resolve(folder, 'production-latency.json'), JSON.stringify(report, null, 2) + '\n')
  process.stdout.write(JSON.stringify({ identities: report.identities, samples: report.samples, failures: report.failures }) + '\n')
}
