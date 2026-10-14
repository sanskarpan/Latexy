import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const source = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
it('collects D14 browser controls in the canonical capability gate with strict fixture errors', () => {
  expect(source('../../playwright.capabilities.config.ts')).toContain("'d14-child-controls.spec.ts'")
  const fixture = source('../../e2e/d14-child-controls.spec.ts')
  expect(fixture).toContain('await installMockWorkboxRegistration(page)')
  expect(fixture).toContain("page.on('pageerror', error => errors.push(error))")
  expect(fixture).toContain('expect(pageErrors.get(page) ?? []).toEqual([])')
  expect(fixture).toContain("path === '/public/engine/capabilities'")
  expect(fixture).toContain("status: 404")
})
it('runs actual HTTP denials in a dedicated fixture-backed CI gate without requiring a browser', () => {
  expect(source('../../playwright.d14-http.config.ts')).toContain("'d14-http-admission.spec.ts'")
  const script = source('../../../scripts/ci/d14-http-admission.sh')
  expect(script).toContain('D14_BROWSER_FIXTURE=1')
  expect(script).toContain('D14_HTTP_BACKEND_URL=')
  expect(script).toContain('--config=playwright.d14-http.config.ts')
  expect(source('../../../.github/workflows/ci.yml')).toContain('bash scripts/ci/d14-http-admission.sh')
})
