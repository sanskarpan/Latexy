import { existsSync, readFileSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(fileURLToPath(new URL('../../', import.meta.url)))
const manifestPath = new URL('./owner-regression-manifest.json', import.meta.url)
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))

// This fixed inventory deliberately makes the manifest itself fail closed: a
// suite cannot disappear just by being removed from both the manifest and CI.
const requiredSuites = [
  'e2e/editor-compile-sync.spec.ts',
  'e2e/resume-builder.spec.ts',
  'e2e/builder-capabilities.spec.ts',
  'e2e/billing-developer.spec.ts',
  'e2e/settings-provider-action-owner-isolation.spec.ts',
  'e2e/onboarding-owner-isolation.spec.ts',
  'e2e/settings-preferences-owner-race.spec.ts',
  'e2e/settings-legacy-callback-owner-isolation.spec.ts',
  'e2e/personal-dictionary-owner-isolation.spec.ts',
  'e2e/settings-passkey-owner-isolation.spec.ts',
  'e2e/linked-variant-owner-race.spec.ts',
  'e2e/compiler-selector-keyboard.spec.ts',
  'e2e/builder-saved-owner-race.spec.ts',
]
const requiredSuiteCaseCounts = [5, 8, 13, 10, 10, 9, 12, 19, 6, 8, 10, 1, 7]
const expectedCaseCount = requiredSuiteCaseCounts.reduce((total, count) => total + count, 0)
const addedCases = [{
  suite: 'e2e/compiler-selector-keyboard.spec.ts',
  title: 'C07 saved owner selects a compiler with keyboard navigation and one settings write',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'does not apply a deferred owner-A autosave after the authenticated owner switches to B',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'same-owner autosave still applies its accepted terminal response',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'rearms a dirty same-owner autosave after verification interrupts an in-flight save',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'does not apply a deferred owner-A force-reattach after the authenticated owner switches to B',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'C25 saved owner recovers current local JSON across capability denial without new effects or cross-scope drafts',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'B08 rechecks live admission after awaited compatibility and saves the retained revision once on regrant',
}, {
  suite: 'e2e/builder-saved-owner-race.spec.ts',
  title: 'B08 and C01 let an admitted save settle but pause the queued newer revision until both grants return',
}]

function fail(message) {
  console.error(`[owner-regression-manifest] ${message}`)
  process.exitCode = 1
}

if (manifest.version !== 1 || manifest.job !== 'cross-browser-quality') {
  fail('Unsupported manifest version or CI job')
}

const step = manifest.step
if (
  !step
  || step.id !== 'editor-owner-regressions'
  || step.name !== 'Verify guided builder, compile cadence and source-PDF synchronization'
  || step.serverMode !== 'production'
  || step.project !== 'chromium'
  || step.workers !== 1
  || step.retries !== 0
  || step.outputDirectory !== 'test-results/editor-compile-sync'
  || step.resultFile !== 'test-results/editor-compile-sync/results.json'
) {
  fail('The production Chromium step contract changed')
}

if (!Array.isArray(manifest.suites) || JSON.stringify(manifest.suites) !== JSON.stringify(requiredSuites)) {
  fail('Manifest suites differ from the required owner-regression inventory')
}
if (manifest.expectedCaseCount !== expectedCaseCount
  || JSON.stringify(manifest.addedCases) !== JSON.stringify(addedCases)
  || JSON.stringify(manifest.suiteCaseCounts) !== JSON.stringify(Object.fromEntries(
    requiredSuites.map((suite, index) => [suite, requiredSuiteCaseCounts[index]]),
  ))) {
  fail('Manifest case inventory must retain all original 116 cases plus both exact builder entitlement-admission cases')
}

const frontendRoot = resolve(repoRoot, 'frontend')
for (const suite of requiredSuites) {
  const suitePath = resolve(frontendRoot, suite)
  if (!suitePath.startsWith(`${frontendRoot}${sep}`) || !existsSync(suitePath)) {
    fail(`Required suite is missing or outside frontend: ${suite}`)
  }
}

const workflow = readFileSync(resolve(repoRoot, '.github/workflows/ci.yml'), 'utf8').replace(/\r\n/g, '\n')
const jobStart = workflow.indexOf('  cross-browser-quality:\n')
if (jobStart < 0) {
  fail('Cross-Browser Quality job is missing')
} else {
  const afterJobHeader = jobStart + '  cross-browser-quality:\n'.length
  const nextJobMatch = /\n {2}[^ \n][^\n]*:\n/.exec(workflow.slice(afterJobHeader))
  const nextJob = nextJobMatch ? afterJobHeader + nextJobMatch.index : -1
  const job = workflow.slice(jobStart, nextJob < 0 ? undefined : nextJob)
  const idLine = `        id: ${step.id}\n`
  const idOffset = job.indexOf(idLine)
  if (idOffset < 0) {
    fail(`Step id ${step.id} is missing from ${manifest.job}`)
  } else {
    const stepStart = job.lastIndexOf('      - name: ', idOffset)
    const nextStep = job.indexOf('\n      - ', idOffset)
    const stepBlock = job.slice(stepStart, nextStep < 0 ? undefined : nextStep)
    const nameMatch = stepBlock.match(/^      - name: (.+)$/m)
    if (!nameMatch || nameMatch[1] !== step.name) {
      fail('The established owner-regression step name changed')
    }

    const runMarker = '        run: |\n'
    const runStart = stepBlock.indexOf(runMarker)
    const command = runStart < 0 ? '' : stepBlock.slice(runStart + runMarker.length)
    const selectedSuites = [...command.matchAll(/\be2e\/[\w./-]+\.spec\.ts\b/g)].map(match => match[0])
    if (JSON.stringify(selectedSuites) !== JSON.stringify(requiredSuites)) {
      fail('Workflow selection differs from the required suite manifest')
    }

    for (const contract of [
      `PLAYWRIGHT_SERVER_MODE: ${step.serverMode}`,
      `PLAYWRIGHT_JSON_OUTPUT_FILE: ${step.resultFile}`,
      `--project=${step.project}`,
      `--workers=${step.workers}`,
      `--retries=${step.retries}`,
      '--trace=on',
      '--reporter=line,json',
      `--output=${step.outputDirectory}`,
      'set -euo pipefail',
      `rm -f ${step.resultFile}`,
      `node ../scripts/ci/verify-owner-regression-manifest.mjs --report=${step.resultFile}`,
    ]) {
      if (!stepBlock.includes(contract)) fail(`Workflow step is missing required contract: ${contract}`)
    }
  }
}

function verifyReport(report) {
  if (!report || !Array.isArray(report.errors) || report.errors.length
    || report.stats?.expected !== expectedCaseCount || report.stats.skipped !== 0
    || report.stats.unexpected !== 0 || report.stats.flaky !== 0
    || !Array.isArray(report.config?.projects) || report.config.projects.length !== 1
    || report.config.projects[0].name !== step.project
    || report.config.projects[0].retries !== 0 || report.config.projects[0].repeatEach !== 1) {
    throw new Error('Report is missing, partial, skipped, retried, or failed')
  }
  const cases = []
  function walk(suite) {
    if (!Array.isArray(suite.specs ?? []) || !Array.isArray(suite.suites ?? [])) throw new Error('Malformed report suites')
    for (const spec of suite.specs ?? []) {
      const file = `e2e/${spec.file}`
      if (!requiredSuites.includes(file) || spec.ok !== true || typeof spec.title !== 'string'
        || !Array.isArray(spec.tests) || spec.tests.length !== 1) {
        throw new Error('Unexpected suite or malformed case')
      }
      const test = spec.tests[0]
      if (test.projectName !== step.project || test.expectedStatus !== 'passed' || test.status !== 'expected'
        || !Array.isArray(test.results) || test.results.length !== 1
        || test.results[0].status !== 'passed' || test.results[0].retry !== 0
        || test.results[0].error || !Array.isArray(test.results[0].errors) || test.results[0].errors.length) {
        throw new Error('Every selected case must pass once without skipping or retries')
      }
      cases.push({ file, title: spec.title, id: spec.id })
    }
    for (const nested of suite.suites ?? []) walk(nested)
  }
  if (!Array.isArray(report.suites)) throw new Error('Report suites are missing')
  for (const suite of report.suites) walk(suite)
  if (cases.length !== expectedCaseCount || cases.some(test => typeof test.id !== 'string' || !test.id)
    || new Set(cases.map(test => test.id)).size !== expectedCaseCount) {
    throw new Error('Report has missing or duplicate cases')
  }
  for (const [index, suite] of requiredSuites.entries()) {
    if (cases.filter(test => test.file === suite).length !== requiredSuiteCaseCounts[index]) {
      throw new Error(`Wrong terminal case count for ${suite}`)
    }
  }
  for (const expected of addedCases) {
    if (cases.filter(test => test.file === expected.suite && test.title === expected.title).length !== 1) {
      throw new Error('An exact required added case is missing or duplicated')
    }
  }
}

const arguments_ = process.argv.slice(2)
if (arguments_.length) {
  if (arguments_.length !== 1 || !arguments_[0].startsWith('--report=')) {
    fail('Expected a single --report=<Playwright JSON result> argument')
  } else {
    try {
      verifyReport(JSON.parse(readFileSync(resolve(arguments_[0].slice('--report='.length)), 'utf8')))
    } catch (error) {
      fail(`Terminal result verification failed: ${error.message}`)
    }
  }
}

if (process.exitCode) process.exit(process.exitCode)
console.log(`[owner-regression-manifest] Verified ${requiredSuites.length} required Chromium production-bundle suites`)
if (arguments_.length) console.log(`[owner-regression-manifest] Verified ${expectedCaseCount} passed cases; zero skips, retries or failures`)
