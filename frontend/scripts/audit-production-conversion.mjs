import { chromium } from '@playwright/test'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

if (process.env.LATEXY_PRODUCTION_AUDIT !== '1' || process.env.LATEXY_AUDIT_CONVERSION !== '1' || !process.env.LATEXY_QA_CREDENTIAL_FILE) throw new Error('Explicit normal-quota production conversion opt-in required')
const api = 'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run'
const folder = resolve(process.env.LATEXY_AUDIT_DIR)
await mkdir(folder, { recursive: true })
const report = { measured_at_utc: new Date().toISOString(), scope: 'One synthetic TXT to LaTeX conversion using the authorized account and ordinary quota; no BYOK key, role changes or payment', requests: [], states: [] }
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ storageState: process.env.LATEXY_QA_CREDENTIAL_FILE + '.state.json' })
try {
  const sessionResponse = await context.request.get('https://latexy.xyz/api/auth/get-session')
  const session = await sessionResponse.json()
  if (!session?.session?.token) throw new Error('Normal QA session unavailable')
  const headers = { Authorization: 'Bearer ' + session.session.token }
  const started = Date.now()
  const content = 'Alex Example\nalex@example.com\nSummary\nSoftware engineer building accessible tools.\nExperience\nEngineer, Example Company, 2022 - Present\nBuilt internal tools used by 20 colleagues.\nEducation\nExample University, BS Computer Science, 2022\nSkills\nPython, PostgreSQL, TypeScript\n'
  const existing = process.env.LATEXY_AUDIT_EXISTING_JOB
  if (existing && !/^[a-f0-9-]{36}$/.test(existing)) throw new Error('Invalid synthetic job ID')
  let body, accepted = true
  if (existing) {
    body = { job_id: existing }
    report.scope = 'Follow-up polling of the previously authorized synthetic conversion; no new model request or quota charge'
  } else {
    const upload = await context.request.post(api + '/formats/upload', { headers, timeout: 60000,
      multipart: { file: { name: 'synthetic-resume.txt', mimeType: 'text/plain', buffer: Buffer.from(content) } } })
    report.requests.push({ path: '/formats/upload', status: upload.status(), elapsed_ms: Date.now() - started })
    body = await upload.json()
    accepted = upload.ok()
  }
  if (!accepted || !body.job_id) {
    report.error = String(body.detail ?? 'No conversion job').slice(0, 200)
  } else {
    report.job_id = body.job_id
    for (let count = 0; count < (existing ? 5 : 60); count++) {
      const at = Date.now()
      const response = await context.request.get(api + '/jobs/' + body.job_id + '/state', { headers, timeout: 30000 })
      const state = await response.json()
      report.requests.push({ path: '/jobs/' + body.job_id + '/state', status: response.status(), elapsed_ms: Date.now() - at })
      report.states.push({ elapsed_ms: Date.now() - started, status: state.status, stage: state.stage, percent: state.percent })
      if (['completed', 'failed', 'cancelled'].includes(state.status)) {
        report.terminal_ms = Date.now() - started
        report.terminal_status = state.status
        if (state.status === 'completed') {
          const resultResponse = await context.request.get(api + '/jobs/' + body.job_id + '/result', { headers, timeout: 30000 })
          const result = await resultResponse.json()
          const payload = result.result ?? result
          report.result_status = resultResponse.status()
          report.has_latex = typeof payload.latex_content === 'string' && payload.latex_content.includes('\\begin{document}')
        }
        break
      }
      await writeFile(resolve(folder, 'conversion-latency.json'), JSON.stringify(report, null, 2) + '\n')
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
    if (!report.terminal_status) report.error = 'Bounded polling ended without a terminal result'
  }
} catch (error) { report.error = error.message.replace(/Bearer\s+\S+/gi, '[redacted]').slice(0, 250) }
finally {
  await writeFile(resolve(folder, 'conversion-latency.json'), JSON.stringify(report, null, 2) + '\n')
  await browser.close()
  process.stdout.write(JSON.stringify({ requests: report.requests.length, terminal_ms: report.terminal_ms, terminal_status: report.terminal_status, has_latex: report.has_latex, error: report.error }) + '\n')
}
