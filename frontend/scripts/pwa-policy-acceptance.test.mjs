import { test } from 'node:test'
import assert from 'node:assert/strict'
import { POLICY_TITLES, verifyPolicyReport } from './pwa-policy-acceptance.mjs'

function passedReport() {
  return { stats: { expected: 2, unexpected: 0, skipped: 0, flaky: 0 }, errors: [],
    suites: [{ specs: POLICY_TITLES.map(title => ({ title, file: 'pwa-registration-policy.spec.ts', ok: true,
      tests: [{ projectName: 'chromium-pwa-policy', expectedStatus: 'passed', results: [{ status: 'passed' }] }] })) }] }
}

test('worker policy gate accepts both exact completed cases', () => {
  assert.equal(verifyPolicyReport(passedReport()).passed, 2)
})

test('worker policy gate rejects missing, skipped, failed, duplicate, retried or wrong-scope evidence', () => {
  for (const mutate of [
    report => { report.stats.expected = 0 },
    report => { report.stats.unexpected = 1 },
    report => { report.stats.skipped = 1 },
    report => { report.stats.flaky = 1 },
    report => { report.errors.push({ message: 'Server failed' }) },
    report => { report.suites[0].specs.pop() },
    report => { report.suites[0].specs[0].title = POLICY_TITLES[1] },
    report => { report.suites[0].specs[0].file = 'pwa-production.spec.ts' },
    report => { report.suites[0].specs[0].ok = false },
    report => { report.suites[0].specs[0].tests[0].projectName = 'chromium-pwa' },
    report => { report.suites[0].specs[0].tests[0].expectedStatus = 'failed' },
    report => { report.suites[0].specs[0].tests[0].results[0].status = 'skipped' },
    report => { report.suites[0].specs[0].tests[0].results.push({ status: 'passed' }) },
    report => { report.suites[0].specs[0].tests[0].results[0].retry = 1 },
  ]) {
    const report = passedReport()
    mutate(report)
    assert.throws(() => verifyPolicyReport(report))
  }
})
