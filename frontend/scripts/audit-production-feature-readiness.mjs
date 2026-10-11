import { chromium } from '@playwright/test'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

if (process.env.LATEXY_PRODUCTION_AUDIT !== '1' || !process.env.LATEXY_QA_CREDENTIAL_FILE) throw new Error('Production opt-in and private QA session required')
const credentials = JSON.parse(await readFile(process.env.LATEXY_QA_CREDENTIAL_FILE, 'utf8'))
const prior = JSON.parse(await readFile(process.env.LATEXY_AUDIT_ACCOUNT_REPORT, 'utf8'))
if (!/^\/workspace\/[a-f0-9-]+\/edit$/.test(prior.resume_path ?? '')) throw new Error('Verified synthetic resume path required')
const resume = prior.resume_path.replace(/\/edit$/, '')
const folder = resolve(process.env.LATEXY_AUDIT_DIR)
await mkdir(folder, { recursive: true })
const report = { measured_at_utc: new Date().toISOString(), scope: 'UI navigation for the authorized synthetic account; normal automatic previews may compile; heading readiness is not completion of all actions',
  pages: [], http: [], failures: [], console_errors: [] }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: process.env.LATEXY_QA_CREDENTIAL_FILE + '.state.json', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const starts = new WeakMap()
const clean = value => String(value).replaceAll(credentials.email, '[test account]').replace(/Bearer\s+\S+/gi, '[redacted]').replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[redacted JWT]')
const safe = value => { const url = new URL(value); return { origin: url.origin, path: url.pathname } }
page.on('request', request => starts.set(request, Date.now()))
page.on('response', response => {
  const request = response.request()
  if (!response.url().includes('modal.run') && !response.url().includes('/api/auth/')) return
  report.http.push({ ...safe(response.url()), method: request.method(), status: response.status(), headers_ms: Date.now() - (starts.get(request) ?? Date.now()), observed_at_utc: new Date().toISOString() })
})
page.on('requestfailed', request => report.failures.push({ ...safe(request.url()), error: request.failure()?.errorText }))
page.on('pageerror', error => report.failures.push({ runtime_error: clean(error.message) }))
page.on('console', message => { if (message.type() === 'error') report.console_errors.push(clean(message.text()).slice(0, 500)) })
try {
  for (const [name, path] of [['library', '/workspace'], ['cover-letter', resume + '/cover-letter'], ['career', resume + '/career'],
    ['optimization', resume + '/optimize'], ['tracker', '/tracker'], ['settings', '/settings'], ['billing', '/billing'], ['guided-builder', '/workspace/builder/new']]) {
    const start = Date.now()
    try {
      const navigation = await page.goto('https://latexy.xyz' + path, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await page.locator('h1').first().waitFor({ state: 'visible', timeout: 30000 })
      const row = { name, path, status: navigation?.status(), heading_ms: Date.now() - start, heading: await page.locator('h1').first().innerText(), final_path: new URL(page.url()).pathname }
      await page.screenshot({ path: resolve(folder, name + '.png') })
      await writeFile(resolve(folder, name + '.txt'), clean(await page.locator('body').innerText()))
      report.pages.push(row)
      process.stdout.write(JSON.stringify(row) + '\n')
    } catch (error) { report.pages.push({ name, path, elapsed_ms: Date.now() - start, error: clean(error.message).slice(0, 250) }) }
    await writeFile(resolve(folder, 'feature-readiness.json'), JSON.stringify(report, null, 2) + '\n')
  }
} finally {
  await writeFile(resolve(folder, 'feature-readiness.json'), JSON.stringify(report, null, 2) + '\n')
  await browser.close()
}
