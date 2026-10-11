import { chromium } from '@playwright/test'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

if (process.env.LATEXY_PRODUCTION_AUDIT !== '1' || !process.env.LATEXY_QA_CREDENTIAL_FILE) throw new Error('Production opt-in and private test credential path required')
const credentials = JSON.parse(await readFile(process.env.LATEXY_QA_CREDENTIAL_FILE, 'utf8'))
const folder = resolve(process.env.LATEXY_AUDIT_DIR ?? '../docs/audits/resume-engine/production-2026-10-08/account')
await mkdir(folder, { recursive: true })
const report = { measured_at_utc: new Date().toISOString(), origin: 'https://latexy.xyz',
  scope: 'Authorized newly created minimal-role test account; no customer records, role changes, payment or paid model requests',
  http: [], failures: [], console_errors: [], operations: [], events: [] }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const starts = new WeakMap()
const safe = value => { const url = new URL(value); return { origin: url.origin, path: url.pathname } }
const clean = value => String(value).replace(/Bearer\s+\S+/gi, 'Bearer [redacted]').replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[redacted JWT]').replaceAll(credentials.email, '[test account]')
page.on('request', req => starts.set(req, Date.now()))
page.on('requestfailed', req => report.failures.push({ ...safe(req.url()), method: req.method(), error: req.failure()?.errorText }))
page.on('response', response => {
  const req = response.request(); const headers = response.headers()
  report.http.push({ ...safe(response.url()), status: response.status(), method: req.method(), type: req.resourceType(),
    response_headers_ms: Date.now() - (starts.get(req) ?? Date.now()),
    allow_origin: headers['access-control-allow-origin'], allow_headers: headers['access-control-allow-headers'],
    request_header_names: Object.keys(req.headers()).sort() })
})
page.on('console', msg => { if (msg.type() === 'error') report.console_errors.push(clean(msg.text()).slice(0, 800)) })
page.on('pageerror', error => report.failures.push({ runtime_error: clean(error.message) }))
page.on('websocket', ws => ws.on('framereceived', frame => {
  try {
    const data = JSON.parse(String(frame.payload)); const event = data.event ?? data
    report.events.push({ type: event.type, job_id: event.job_id, server_timestamp: event.timestamp,
      observed_at_utc: new Date().toISOString(), stage: event.stage, compilation_time: event.compilation_time,
      optimization_time: event.optimization_time, error_code: event.error_code })
  } catch {}
}))
try {
  await page.goto('https://latexy.xyz/login', { waitUntil: 'load', timeout: 60000 })
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(credentials.email)
  await page.getByRole('textbox', { name: 'Password', exact: true }).fill(credentials.password)
  const loginAt = Date.now()
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.waitForURL('**/workspace', { timeout: 60000 })
  report.operations.push({ name: 'login-navigation', elapsed_ms: Date.now() - loginAt })
  const skip = page.getByRole('button', { name: 'Skip', exact: true })
  if (await skip.isVisible()) await skip.click()
  await page.getByRole('heading', { name: 'Resume Library', exact: true }).waitFor({ timeout: 60000 })
  // Wait for either the loaded list/empty state or the actual error, not networkidle.
  await page.getByText('Workspace unavailable', { exact: true }).or(page.getByText('No resumes found', { exact: true })).waitFor({ timeout: 30000 }).catch(() => {})
  // Onboarding can hydrate after the workspace shell and its data.
  if (await skip.isVisible()) await skip.click()
  await page.screenshot({ path: resolve(folder, 'workspace.png') })
  await writeFile(resolve(folder, 'workspace.txt'), clean(await page.locator('body').innerText()))
  const newAt = Date.now()
  await page.getByRole('link', { name: 'New Resume', exact: true }).click()
  await page.waitForURL('**/workspace/new', { timeout: 30000 })
  await page.getByRole('heading', { name: 'Create Resume', exact: true }).waitFor({ timeout: 60000 })
  report.operations.push({ name: 'new-resume-form-ready', elapsed_ms: Date.now() - newAt })
  await page.screenshot({ path: resolve(folder, 'new-resume.png') })
  await writeFile(resolve(folder, 'new-resume.txt'), clean(await page.locator('body').innerText()))
  await context.storageState({ path: process.env.LATEXY_QA_CREDENTIAL_FILE + '.state.json' })
  if (process.env.LATEXY_AUDIT_CREATE_RESUME === '1') {
    await page.getByPlaceholder('Senior Backend Engineer – Q3 2026', { exact: true }).fill('Latency QA 2026-10-08')
    const createAt = Date.now()
    await page.getByRole('button', { name: 'Start from Blank', exact: true }).click()
    await page.waitForURL(/\/workspace\/[^/]+\/edit/, { timeout: 60000 })
    await page.getByRole('button', { name: /^(Recompile|Compile|Update PDF)$/ }).first().waitFor({ timeout: 60000 })
    report.operations.push({ name: 'create-blank-and-editor-ready', elapsed_ms: Date.now() - createAt })
    report.resume_path = new URL(page.url()).pathname
    await page.screenshot({ path: resolve(folder, 'saved-editor.png') })
    await writeFile(resolve(folder, 'saved-editor.txt'), clean(await page.locator('body').innerText()))
    if (process.env.LATEXY_AUDIT_COMPILE === '1') {
      const started = Date.now()
      await page.getByRole('button', { name: /^(Recompile|Compile|Update PDF)$/ }).first().click()
      await page.locator('.react-pdf__Page__canvas').first().waitFor({ state: 'visible', timeout: 120000 })
      await page.waitForFunction(() => { const c = document.querySelector('.react-pdf__Page__canvas'); return c && c.width > 0 && c.height > 0 })
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      report.operations.push({ name: 'saved-resume-compile-visible-canvas', elapsed_ms: Date.now() - started })
      await page.screenshot({ path: resolve(folder, 'saved-pdf.png') })
    }
  }
  report.final_url = page.url()
} catch (error) { report.failures.push({ probe: clean(error.message).slice(0, 350) }); process.exitCode = 1 }
finally {
  await writeFile(resolve(folder, 'account-latency.json'), JSON.stringify(report, null, 2) + '\n')
  await browser.close()
  process.stdout.write(JSON.stringify({ operations: report.operations, failures: report.failures, console_errors: report.console_errors }) + '\n')
}
