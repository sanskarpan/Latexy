import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'

const workflow = readFileSync(new URL('../../../.github/workflows/ci.yml', import.meta.url), 'utf8')

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('original quality failure evidence', () => {
  it.each([undefined, '1'])('retains failed traces independently of retry policy with CI=%s', async ci => {
    vi.stubEnv('CI', ci)
    vi.resetModules()
    // Loading a Playwright config does not start its server or browser.
    const { default: config } = await import('../../playwright.quality.config')

    expect(config.testDir).toBe('./e2e/quality')
    expect(config.use?.trace).toBe('retain-on-failure')
    expect(config.use?.screenshot).toBe('only-on-failure')
    expect(config.use?.serviceWorkers).toBe('block')
    expect(config.outputDir).toBe('test-results/quality')
    expect(config.projects?.map(project => project.name)).toEqual([
      'desktop-chromium', 'desktop-firefox', 'desktop-webkit',
      'mobile-chromium', 'mobile-webkit',
    ])
    for (const project of config.projects ?? []) {
      // Every required engine inherits the failed-run evidence policy.
      expect(project.use?.trace).toBeUndefined()
    }
  })

  it('keeps the required zero-retry result and bounded upload of its original evidence', () => {
    expect(workflow).toMatch(/- name: Audit desktop and mobile browser quality\s+run: pnpm test:quality --retries=0/)
    const upload = workflow.match(/- name: Upload browser quality evidence[\s\S]*?(?=\n  [\w-]+:)/)?.[0]
    expect(upload).toBeDefined()
    expect(upload).toContain("if: ${{ !cancelled() }}")
    expect(upload).toContain('frontend/playwright-quality-report')
    expect(upload).toContain('frontend/test-results/quality')
    expect(upload).toMatch(/retention-days: 14\b/)
  })
})
