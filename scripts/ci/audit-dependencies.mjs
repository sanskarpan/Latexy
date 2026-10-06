import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const mitigatedGhsa = 'GHSA-vfj7-8cjw-p6xm'

// The registry reports the original braces version even after pnpm applies our
// depth-limiting patch. Recognize only this exact finding, after independently
// testing the installed dependency. Never suppress a package or severity class.
export function classifyAudit(report) {
  if (!report || typeof report.advisories !== 'object' || report.advisories === null ||
      Array.isArray(report.advisories) || !report.metadata?.vulnerabilities) {
    throw new Error('Unrecognized dependency audit response')
  }
  const findings = Object.values(report.advisories)
  const counts = report.metadata.vulnerabilities
  const severities = ['info', 'low', 'moderate', 'high', 'critical']
  if (severities.some(level => !Number.isSafeInteger(counts[level]) || counts[level] < 0) ||
      severities.reduce((sum, level) => sum + counts[level], 0) !== findings.length) {
    throw new Error('Incomplete dependency audit response')
  }
  const mitigated = findings.filter(advisory =>
    advisory.github_advisory_id === mitigatedGhsa &&
    advisory.module_name === 'braces' && advisory.severity === 'high' &&
    Array.isArray(advisory.findings) && advisory.findings.length > 0 &&
    advisory.findings.every(finding => finding.version === '3.0.3')
  )
  return { mitigated: mitigated.length, unresolved: findings.length - mitigated.length }
}

function main() {
  const regression = spawnSync(process.execPath, ['--test', 'scripts/ci/braces-depth.test.cjs'], {
    cwd: root, stdio: 'inherit', timeout: 30_000,
  })
  if (regression.status !== 0 || regression.error) {
    throw new Error('Installed braces mitigation regression failed')
  }
  const audit = spawnSync('pnpm', ['audit', '--json'], {
    cwd: root, encoding: 'utf8', timeout: 120_000, maxBuffer: 10 * 1024 * 1024,
  })
  if (audit.error || ![0, 1].includes(audit.status)) {
    throw new Error('Dependency registry audit could not complete')
  }
  const result = classifyAudit(JSON.parse(audit.stdout))
  console.log(`Dependency audit: ${result.unresolved} unresolved; ${result.mitigated} exact braces advisory mitigated by tested installed patch.`)
  if (result.unresolved > 0) process.exitCode = 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { main() } catch (error) {
    console.error(error instanceof SyntaxError ? 'Invalid dependency registry audit response' : error.message)
    process.exitCode = 1
  }
}
