import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import path from 'node:path'
import { expect, it } from 'vitest'

it('collects both real hydration proofs through the actual Playwright loader without launching a browser', () => {
  const frontendRoot = process.cwd()
  const requireFromFrontend = createRequire(path.join(frontendRoot, 'package.json'))
  const output = execFileSync(process.execPath, [
    requireFromFrontend.resolve('@playwright/test/cli'), 'test', '--list',
    '--config=playwright.hydration.config.ts', '--reporter=json',
  ], { cwd: frontendRoot, encoding: 'utf8', timeout: 20_000, maxBuffer: 1024 * 1024 })
  const report = JSON.parse(output) as {
    errors: unknown[]
    suites: Array<{ specs: Array<{ title: string; tests: Array<{ results: unknown[] }> }> }>
  }
  expect(report.errors).toEqual([])
  const specs = report.suites.flatMap(suite => suite.specs)
  expect(specs.map(spec => spec.title).sort()).toEqual([
    'pinned Next host replay reproduces #418 and the upstream cursor backport preserves SSR nodes',
    'real Better Auth SSR snapshot stays stable for a late consumer and refreshes safely',
  ])
  expect(specs.flatMap(spec => spec.tests).map(test => test.results)).toEqual([[], []])
}, 25_000)
