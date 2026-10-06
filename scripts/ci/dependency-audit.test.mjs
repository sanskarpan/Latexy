import assert from 'node:assert/strict'
import test from 'node:test'
import { classifyAudit } from './audit-dependencies.mjs'

const known = {
  github_advisory_id: 'GHSA-vfj7-8cjw-p6xm', module_name: 'braces', severity: 'high',
  findings: [{ version: '3.0.3', paths: ['frontend>micromatch>braces'] }],
}
const report = (...advisories) => ({
  advisories: Object.fromEntries(advisories.map((value, index) => [index, value])),
  metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: advisories.length, critical: 0 } },
})

test('accepts an empty successful report without manufacturing a mitigation', () => {
  assert.deepEqual(classifyAudit(report()), { mitigated: 0, unresolved: 0 })
})
test('recognizes only the exact patched version and advisory', () => {
  assert.deepEqual(classifyAudit(report(known)), { mitigated: 1, unresolved: 0 })
  for (const change of [
    { github_advisory_id: 'GHSA-another-advisory' }, { module_name: 'another-package' },
    { findings: [{ version: '3.0.2' }] }, { findings: [] }, { findings: null },
  ]) {
    assert.deepEqual(classifyAudit(report({ ...known, ...change })), { mitigated: 0, unresolved: 1 })
  }
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
})
