import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { classifyAudit, main, runAudit, summarizeAudit } from './audit-dependencies.mjs'

const known = {
  github_advisory_id: 'GHSA-vfj7-8cjw-p6xm', module_name: 'braces', severity: 'high',
  findings: [{ version: '3.0.3', paths: ['frontend>micromatch>braces'] }],
}
const report = (...advisories) => ({
  advisories: Object.fromEntries(advisories.map((value, index) => [index, value])),
  metadata: { vulnerabilities: {
    info: advisories.filter(value => value.severity === 'info').length,
    low: advisories.filter(value => value.severity === 'low').length,
    moderate: advisories.filter(value => value.severity === 'moderate').length,
    high: advisories.filter(value => value.severity === 'high').length,
    critical: advisories.filter(value => value.severity === 'critical').length,
  } },
})

test('accepts an empty successful report without manufacturing a mitigation', () => {
  assert.deepEqual(classifyAudit(report()), { mitigated: 0, unresolved: 0 })
})
test('recognizes only the exact patched version and advisory', () => {
  assert.deepEqual(classifyAudit(report(known)), { mitigated: 1, unresolved: 0 })
  for (const change of [
    { github_advisory_id: 'GHSA-another-advisory' }, { module_name: 'another-package' },
    { findings: [{ version: '3.0.2' }] }, { findings: [] },
  ]) {
    assert.deepEqual(classifyAudit(report({ ...known, ...change })), { mitigated: 0, unresolved: 1 })
  }
  assert.throws(() => classifyAudit(report({ ...known, findings: null })), /Invalid dependency audit advisory/)
})
test('never hides an additional finding on the same package', () => {
  assert.deepEqual(classifyAudit(report(known, { ...known, github_advisory_id: 'GHSA-new-braces-bug' })),
    { mitigated: 1, unresolved: 1 })
})
test('fails closed on malformed or incomplete registry responses', () => {
  for (const bad of [null, {}, { advisories: [] }, { ...report(), metadata: {} },
    { ...report(known), advisories: {} }, { ...report(), advisories: { hidden: known } }]) {
    assert.throws(() => classifyAudit(bad))
  }
  assert.throws(() => classifyAudit({
    ...report(known),
    metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 0, critical: 1 } },
  }), /Contradictory dependency audit severity counts/)
})

test('summarizes every finding, including repeated packages, without registry paths', () => {
  const second = {
    ...known,
    github_advisory_id: 'GHSA-second-braces',
    findings: [{ version: '3.0.2' }],
  }
  const summary = summarizeAudit(report(known, second))
  assert.equal(summary.advisoryCount, 2)
  assert.equal(summary.mitigatedCount, 1)
  assert.equal(summary.unresolvedCount, 1)
  assert.deepEqual(summary.findings.map(({ package: packageName, ghsa, lockedVersions }) =>
    ({ package: packageName, ghsa, lockedVersions })), [
    { package: 'braces', ghsa: 'GHSA-vfj7-8cjw-p6xm', lockedVersions: ['3.0.3'] },
    { package: 'braces', ghsa: 'GHSA-second-braces', lockedVersions: ['3.0.2'] },
  ])
  assert.equal('paths' in summary.findings[0], false)
})

test('writes a validated summary artifact and fixed-prefix JSON finding logs', () => {
  const reportPath = join(mkdtempSync(join(tmpdir(), 'latexy-audit-')), 'summary.json')
  const logs = []
  const calls = []
  const options = []
  const safeCwd = '/tmp/validated-dependency-audit-cwd'
  const result = runAudit({
    reportPath,
    cwd: safeCwd,
    logger: message => logs.push(message),
    spawn: (command, args, spawnOptions) => {
      calls.push([command, args])
      options.push(spawnOptions)
      return args[0] === '--test'
        ? { status: 0, error: undefined }
        : { status: 1, error: undefined, stdout: JSON.stringify(report(known, {
          ...known, github_advisory_id: 'GHSA-second-braces', findings: [{ version: '3.0.2' }],
        })) }
    },
  })
  const artifact = JSON.parse(readFileSync(reportPath, 'utf8'))
  assert.equal(result.status, 'unresolved')
  assert.equal(artifact.unresolvedCount, 1)
  assert.equal(artifact.findings.length, 2)
  assert.equal(calls.length, 2)
  assert.deepEqual(options.map(value => value.cwd), [safeCwd, safeCwd])
  assert.equal(logs.length, 3)
  for (const line of logs.slice(0, 2)) {
    const prefix = 'Dependency audit finding: '
    assert.equal(line.startsWith(prefix), true)
    assert.doesNotThrow(() => JSON.parse(line.slice(prefix.length)))
  }
  assert.equal(logs[2].startsWith('Dependency audit summary: '), true)
})

test('rejects newline or workflow-command injection in validated fields', () => {
  assert.throws(() => summarizeAudit(report({
    ...known,
    module_name: 'braces\n::error::forged',
  })), /Invalid dependency audit package/)
  assert.throws(() => summarizeAudit(report({
    ...known,
    github_advisory_id: 'GHSA-good\n::set-output name=x::bad',
  })), /Invalid dependency audit GHSA/)
})

test('writes an error-status artifact without inventing an empty audit result', () => {
  for (const [label, regressionResult, auditResult, message] of [
    ['regression', { status: 1, error: undefined }, { status: 0, error: undefined }, 'Installed braces mitigation regression failed'],
    ['invalid-json', { status: 0, error: undefined }, { status: 0, error: undefined, stdout: '{not-json' }, 'Invalid dependency registry audit response'],
    ['provider-error', { status: 0, error: undefined }, { status: 2, error: new Error('secret-provider-token') }, 'Dependency registry audit could not complete'],
  ]) {
    const reportPath = join(mkdtempSync(join(tmpdir(), `latexy-audit-${label}-`)), 'summary.json')
    assert.throws(() => runAudit({
      reportPath,
      spawn: (_command, args) => args[0] === '--test' ? regressionResult : auditResult,
    }), new RegExp(message))
    const artifact = JSON.parse(readFileSync(reportPath, 'utf8'))
    assert.deepEqual(artifact, { schemaVersion: 1, status: 'error', error: { code: message } })
    assert.equal('findings' in artifact, false)
    assert.equal(JSON.stringify(artifact).includes('secret-provider-token'), false)
  }
})

test('main returns a nonzero process status for unresolved findings', () => {
  const previousExitCode = process.exitCode
  process.exitCode = 0
  try {
    const unresolved = {
      ...known,
      github_advisory_id: 'GHSA-unresolved-braces',
      findings: [{ version: '3.0.2' }],
    }
    const summary = main({
      reportPath: join(mkdtempSync(join(tmpdir(), 'latexy-audit-main-')), 'summary.json'),
      logger: () => {},
      spawn: (_command, args) => args[0] === '--test'
        ? { status: 0, error: undefined }
        : { status: 1, error: undefined, stdout: JSON.stringify(report(known, unresolved)) },
    })
    assert.equal(summary.status, 'unresolved')
    assert.equal(process.exitCode, 1)
  } finally {
    process.exitCode = previousExitCode
  }
})

test('fails closed rather than truncating oversized responses', () => {
  const many = Object.fromEntries(Array.from({ length: 1001 }, (_, index) => [index, known]))
  assert.throws(() => summarizeAudit({
    advisories: many,
    metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 1001, critical: 0 } },
  }), /exceeds supported bounds/)
  assert.throws(() => summarizeAudit(report({
    ...known,
    findings: Array.from({ length: 101 }, () => ({ version: '3.0.3' })),
  })), /Invalid dependency audit advisory/)
})
