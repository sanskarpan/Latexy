import { readFile, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const expectedFiles = new Set(['pwa-production.spec.ts', 'pwa-worker-lifecycle.spec.ts', 'offline-compiled-pdf.spec.ts'])
export const EXPECTED_PWA_CASES = 12
export const EXPECTED_PWA_TITLES = [
  'installs a lean worker, excludes private caches, and serves the offline fallback',
  'activates a real generated worker update while retaining the offline fallback',
  'never persists synthetic owner API or PDF responses in the active worker cache',
  'restores the owner-scoped latest PDF after a cold offline reload and uses download fallback',
  'hides a stale PDF when the remembered owner changes during cold fallback loading',
  'hides the reader when storage is cleared after it has shown a PDF',
  'rejects malformed and oversized cached PDFs without exposing them',
  'does not execute HTML from a PDF-header cached Blob',
  'does not create a partial v3 database when no offline store exists',
  'handles malformed workspace route encoding without crashing the fallback',
  'logout clears the owner marker and cached PDFs',
  'account switch purges old drafts and reconnect only flushes the current owner',
]

export function verifyPwaReport(report) {
  const stats = report?.stats
  if (!stats || stats.expected !== EXPECTED_PWA_CASES || stats.unexpected !== 0 || stats.skipped !== 0 || stats.flaky !== 0 ||
      !Array.isArray(report.errors) || report.errors.length) throw new Error('PWA acceptance requires 12 passed, zero skipped/failed/flaky cases')
  const specs = []
  function visit(suite) {
    for (const spec of suite.specs ?? []) specs.push(spec)
    for (const child of suite.suites ?? []) visit(child)
  }
  for (const suite of report.suites ?? []) visit(suite)
  const files = new Set(specs.map(spec => spec.file.replaceAll('\\', '/').split('/').at(-1)))
  if (specs.length !== EXPECTED_PWA_CASES || files.size !== expectedFiles.size || [...files].some(file => !expectedFiles.has(file))) {
    throw new Error('PWA acceptance report has missing or unexpected selected specs')
  }
  const titles = new Set(specs.map(spec => spec.title))
  if (titles.size !== EXPECTED_PWA_CASES || EXPECTED_PWA_TITLES.some(title => !titles.has(title))) {
    throw new Error('PWA acceptance report has missing or duplicate lifecycle/owner cases')
  }
  for (const spec of specs) {
    const index = EXPECTED_PWA_TITLES.indexOf(spec.title)
    const expectedFile = index === 0 ? 'pwa-production.spec.ts'
      : index < 3 ? 'pwa-worker-lifecycle.spec.ts' : 'offline-compiled-pdf.spec.ts'
    if (spec.file.replaceAll('\\', '/').split('/').at(-1) !== expectedFile) {
      throw new Error('PWA acceptance case is attributed to an unexpected spec')
    }
    if (!spec.ok || spec.tests?.length !== 1 || spec.tests[0].projectName !== 'chromium-pwa' ||
        spec.tests[0].expectedStatus !== 'passed' || spec.tests[0].results?.length !== 1 || spec.tests[0].results[0].status !== 'passed') {
      throw new Error('PWA acceptance contains incomplete or retried test evidence')
    }
  }
  return { passed: EXPECTED_PWA_CASES, skipped: 0, failed: 0, files: [...files].sort(),
    scope: 'local production worker; synthetic account/API fixtures; no installed-device or deployed-provider acceptance' }
}

async function main() {
  const frontend = dirname(dirname(fileURLToPath(import.meta.url)))
  const reportPath = join(frontend, 'test-results/pwa/report.json')
  // A failed launcher must never certify stale evidence from a previous run.
  await rm(reportPath, { force: true })
  const require = createRequire(import.meta.url)
  const cli = require.resolve('@playwright/test/cli')
  const child = spawn(process.execPath, [cli, 'test', '--config=playwright.pwa.config.ts'], {
    cwd: frontend, env: process.env, stdio: 'inherit',
  })
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject)
    child.once('exit', code => resolve(code))
  })
  if (code !== 0) throw new Error('PWA browser run failed; no acceptance claim')
  const report = JSON.parse(await readFile(reportPath, 'utf8'))
  console.log(JSON.stringify(verifyPwaReport(report)))
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) await main()
