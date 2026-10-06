import { spawnSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const mitigatedGhsa = 'GHSA-vfj7-8cjw-p6xm'
const severities = ['info', 'low', 'moderate', 'high', 'critical']
const MAX_ADVISORIES = 1000
const MAX_FINDINGS_PER_ADVISORY = 100
const MAX_FIELD_LENGTH = 160
const versionPattern = /^[0-9A-Za-z][0-9A-Za-z.+_-]{0,127}$/
const packagePattern = /^(?:@[A-Za-z0-9._-]+\/)?[A-Za-z0-9._-]+$/
const ghsaPattern = /^GHSA-[A-Za-z0-9-]{1,120}$/

function boundedString(value, label, pattern) {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_FIELD_LENGTH ||
      !pattern.test(value)) {
    throw new Error(`Invalid dependency audit ${label}`)
  }
  return value
}

function auditCounts(report) {
  const counts = report.metadata.vulnerabilities
  if (!counts || typeof counts !== 'object' || Array.isArray(counts) ||
      severities.some(level => !Number.isSafeInteger(counts[level]) || counts[level] < 0)) {
    throw new Error('Incomplete dependency audit response')
  }
  return Object.fromEntries(severities.map(level => [level, counts[level]]))
}

function normalizedAdvisory(advisory) {
  if (!advisory || typeof advisory !== 'object' || Array.isArray(advisory) ||
      !Array.isArray(advisory.findings) || advisory.findings.length > MAX_FINDINGS_PER_ADVISORY) {
    throw new Error('Invalid dependency audit advisory')
  }
  const packageName = boundedString(advisory.module_name, 'package', packagePattern)
  const ghsa = boundedString(advisory.github_advisory_id, 'GHSA', ghsaPattern)
  if (!severities.includes(advisory.severity)) throw new Error('Invalid dependency audit severity')
  const lockedVersions = advisory.findings.map((finding) => {
    if (!finding || typeof finding !== 'object' || Array.isArray(finding)) {
      throw new Error('Invalid dependency audit finding')
    }
    return boundedString(finding.version, 'locked version', versionPattern)
  })
  const mitigated = ghsa === mitigatedGhsa && packageName === 'braces' &&
    advisory.severity === 'high' && lockedVersions.length > 0 &&
    lockedVersions.every(version => version === '3.0.3')
  return {
    package: packageName,
    ghsa,
    severity: advisory.severity,
    lockedVersions: [...new Set(lockedVersions)].sort(),
    mitigated,
  }
}

export function summarizeAudit(report) {
  if (!report || typeof report.advisories !== 'object' || report.advisories === null ||
      Array.isArray(report.advisories) || !report.metadata ||
      typeof report.metadata !== 'object') {
    throw new Error('Unrecognized dependency audit response')
  }
  const advisories = Object.values(report.advisories)
  if (advisories.length > MAX_ADVISORIES) throw new Error('Dependency audit response exceeds supported bounds')
  const counts = auditCounts(report)
  if (severities.reduce((sum, level) => sum + counts[level], 0) !== advisories.length) {
    throw new Error('Incomplete dependency audit response')
  }
  const findings = advisories.map(normalizedAdvisory)
  const actualCounts = Object.fromEntries(severities.map(level => [
    level, findings.filter(finding => finding.severity === level).length,
  ]))
  if (severities.some(level => counts[level] !== actualCounts[level])) {
    throw new Error('Contradictory dependency audit severity counts')
  }
  const mitigated = findings.filter(finding => finding.mitigated).length
  return {
    counts,
    advisoryCount: findings.length,
    mitigatedCount: mitigated,
    unresolvedCount: findings.length - mitigated,
    findings,
  }
}

// The registry reports the original braces version even after pnpm applies our
// depth-limiting patch. Recognize only this exact finding, after independently
// testing the installed dependency. Never suppress a package or severity class.
export function classifyAudit(report) {
  const result = summarizeAudit(report)
  return { mitigated: result.mitigatedCount, unresolved: result.unresolvedCount }
}

function errorSummary(code) {
  return { schemaVersion: 1, status: 'error', error: { code } }
}

function writeSummary(reportPath, summary) {
  if (!reportPath) return
  writeFileSync(reportPath, `${JSON.stringify(summary, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
}

function logFinding(finding, logger) {
  logger(`Dependency audit finding: ${JSON.stringify({
    package: finding.package,
    ghsa: finding.ghsa,
    severity: finding.severity,
    lockedVersions: finding.lockedVersions,
    mitigated: finding.mitigated,
  })}`)
}

export function runAudit({
  spawn = spawnSync,
  cwd = root,
  reportPath = process.env.DEPENDENCY_AUDIT_REPORT_PATH,
  logger = message => console.log(message),
} = {}) {
  const fail = (code) => {
    const summary = errorSummary(code)
    writeSummary(reportPath, summary)
    throw new Error(code)
  }

  const regression = spawn(process.execPath, ['--test', 'scripts/ci/braces-depth.test.cjs'], {
    cwd, stdio: 'inherit', timeout: 30_000,
  })
  if (regression.error || regression.status !== 0) fail('Installed braces mitigation regression failed')
  const audit = spawn('pnpm', ['audit', '--json'], {
    cwd, encoding: 'utf8', timeout: 120_000, maxBuffer: 10 * 1024 * 1024,
  })
  if (audit.error || ![0, 1].includes(audit.status)) fail('Dependency registry audit could not complete')
  let result
  try {
    result = summarizeAudit(JSON.parse(audit.stdout))
  } catch {
    fail('Invalid dependency registry audit response')
  }
  const summary = {
    schemaVersion: 1,
    status: result.unresolvedCount === 0 ? 'pass' : 'unresolved',
    counts: result.counts,
    advisoryCount: result.advisoryCount,
    mitigatedCount: result.mitigatedCount,
    unresolvedCount: result.unresolvedCount,
    findings: result.findings,
  }
  writeSummary(reportPath, summary)
  for (const finding of result.findings) logFinding(finding, logger)
  logger(`Dependency audit summary: ${JSON.stringify({
    status: summary.status,
    advisoryCount: summary.advisoryCount,
    mitigatedCount: summary.mitigatedCount,
    unresolvedCount: summary.unresolvedCount,
  })}`)
  return summary
}

export function main(options) {
  const summary = runAudit(options)
  if (summary.unresolvedCount > 0) process.exitCode = 1
  return summary
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { main() } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
