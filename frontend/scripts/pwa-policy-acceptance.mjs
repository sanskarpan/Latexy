import { readFile, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { spawn } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const POLICY_TITLES = [
  'public UI survives a blocked service worker without a registration',
  'public UI survives a service-worker registration denied by browser policy',
]

export function verifyPolicyReport(report) {
  const stats = report?.stats
  if (!stats || stats.expected !== 2 || stats.unexpected !== 0 || stats.skipped !== 0 || stats.flaky !== 0 ||
      !Array.isArray(report.errors) || report.errors.length) throw new Error('Worker policy acceptance requires 2 passed, zero skipped/failed/flaky cases')
  const specs = []
  function visit(suite) {
    specs.push(...(suite.specs ?? []))
    for (const child of suite.suites ?? []) visit(child)
  }
  for (const suite of report.suites ?? []) visit(suite)
  const titles = new Set(specs.map(spec => spec.title))
  if (specs.length !== 2 || titles.size !== 2 || POLICY_TITLES.some(title => !titles.has(title))) {
    throw new Error('Worker policy acceptance requires both distinct policy cases')
  }
  for (const spec of specs) {
    const test = spec.tests?.[0]
    if (spec.file?.replaceAll('\\', '/').split('/').at(-1) !== 'pwa-registration-policy.spec.ts' ||
        !spec.ok || spec.tests?.length !== 1 || test.projectName !== 'chromium-pwa-policy' ||
        test.expectedStatus !== 'passed' || test.results?.length !== 1 || test.results[0].status !== 'passed' ||
        (test.results[0].retry ?? 0) !== 0) {
      throw new Error('Worker policy acceptance contains incomplete, wrong-scope or retried evidence')
    }
  }
  return { passed: 2, failed: 0, skipped: 0, scope: 'isolated production public UI; optional worker registration denied; no deployed owner/provider acceptance' }
}

async function main() {
  const frontend = dirname(dirname(fileURLToPath(import.meta.url)))
  const reportPath = join(frontend, 'test-results/pwa-policy/report.json')
  await rm(reportPath, { force: true })
  const require = createRequire(import.meta.url)
  const child = spawn(process.execPath, [require.resolve('@playwright/test/cli'), 'test', '--config=playwright.pwa-policy.config.ts'], {
    cwd: frontend, env: process.env, stdio: 'inherit',
  })
  const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', resolve) })
  if (code !== 0) throw new Error('Worker policy browser run failed; no acceptance claim')
  console.log(JSON.stringify(verifyPolicyReport(JSON.parse(await readFile(reportPath, 'utf8')))))
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) await main()
