import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

if (process.env.LATEXY_PRODUCTION_AUDIT !== '1') throw new Error('Explicit production audit opt-in required')
const api = 'https://sanskarpandey2004--latexy-backend-fastapi-app.modal.run'
const origin = 'https://latexy.xyz'
const folder = resolve(process.env.LATEXY_AUDIT_DIR ?? '../docs/audits/resume-engine/production-2026-10-08')
await mkdir(folder, { recursive: true })
const sourceFile = await readFile(new URL('../src/lib/latex-templates.ts', import.meta.url), 'utf8')
// Only execute this checked-in constant module, never remote/user content.
const source = new Function(sourceFile.replaceAll('export const ', 'const ') + '; return DEMO_RESUME_TEMPLATE')()
const report = { measured_at_utc: new Date().toISOString(), origin, api, scope: 'Sequential public API probes with synthetic starter; no paid models, authentication or quota bypass',
  limitations: ['Three samples are diagnostic, not a p95 certification', 'HTTP includes client transport and backend; no server span attribution'], samples: [] }
async function probe(name, path, options = {}, base = api) {
  const start = performance.now()
  try {
    const response = await fetch(base + path, { ...options, signal: AbortSignal.timeout(30000) })
    const headersMs = performance.now() - start
    const text = await response.text()
    let body
    try { body = JSON.parse(text) } catch {}
    const row = { name, path, status: response.status, headers_ms: headersMs, complete_ms: performance.now() - start, bytes: Buffer.byteLength(text),
      cache: response.headers.get('x-vercel-cache'), server_timing: response.headers.get('server-timing'),
      success: body?.success, cached: body?.cached, server_processing_seconds: body?.processing_time,
      error_detail: response.status >= 400 ? String(body?.detail ?? text.slice(0, 180)).slice(0, 200) : undefined }
    if (name.includes('identity') || name === 'health') row.identity = body
    if (name === 'template-list' && Array.isArray(body)) row.item_count = body.length
    if (name === 'quick-score') row.score = body?.score
    report.samples.push(row)
    process.stdout.write(JSON.stringify(row) + '\n')
  } catch (error) { report.samples.push({ name, path, elapsed_ms: performance.now() - start, error: error.message }) }
  await writeFile(resolve(folder, 'production-operations.json'), JSON.stringify(report, null, 2) + '\n')
}
const json = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
await probe('frontend-identity', '/api/deployment-identity', {}, origin)
await probe('health', '/health')
await probe('ready', '/readyz')
await probe('job-health', '/jobs/health')
for (let i = 0; i < 3; i++) {
  await probe('template-list', '/templates/')
  await probe('template-categories', '/templates/categories')
  await probe('quick-score', '/ats/quick-score', json({ latex_content: source }))
}
for (const [filename, content, type] of [['synthetic-starter.tex', source, 'application/x-tex'],
  ['synthetic-resume.txt', 'Alex Example\nalex@example.com\nSummary\nSoftware engineer building tools.\nExperience\nEngineer, Example Company, 2022 - Present\nBuilt internal tools.\nSkills\nPython, PostgreSQL\n', 'text/plain']]) {
  const form = new FormData(); form.append('file', new Blob([content], { type }), filename)
  await probe('parse-' + type, '/formats/parse', { method: 'POST', body: form })
}
const upload = new FormData(); upload.append('file', new Blob([source], { type: 'application/x-tex' }), 'synthetic-starter.tex')
await probe('tex-passthrough', '/formats/upload', { method: 'POST', body: upload })
await probe('no-code-projection', '/public/engine/document', json({ latex_content: source }))
for (const path of ['/icon.svg', '/favicon.ico', '/icons/apple-touch-icon.png']) await probe('brand-asset', path, {}, origin)
