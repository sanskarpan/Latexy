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
]

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
) {
  fail('The production Chromium step contract changed')
}

if (!Array.isArray(manifest.suites) || JSON.stringify(manifest.suites) !== JSON.stringify(requiredSuites)) {
  fail('Manifest suites differ from the required owner-regression inventory')
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

    const runMarker = '        run: >-\n'
    const runStart = stepBlock.indexOf(runMarker)
    const command = runStart < 0 ? '' : stepBlock.slice(runStart + runMarker.length)
    const selectedSuites = [...command.matchAll(/\be2e\/[\w./-]+\.spec\.ts\b/g)].map(match => match[0])
    if (JSON.stringify(selectedSuites) !== JSON.stringify(requiredSuites)) {
      fail('Workflow selection differs from the required suite manifest')
    }

    for (const contract of [
      `PLAYWRIGHT_SERVER_MODE: ${step.serverMode}`,
      `--project=${step.project}`,
      `--workers=${step.workers}`,
      `--retries=${step.retries}`,
      '--trace=on',
      '--reporter=line',
      `--output=${step.outputDirectory}`,
    ]) {
      if (!stepBlock.includes(contract)) fail(`Workflow step is missing required contract: ${contract}`)
    }
  }
}

if (process.exitCode) process.exit(process.exitCode)
console.log(`[owner-regression-manifest] Verified ${requiredSuites.length} required Chromium production-bundle suites`)
