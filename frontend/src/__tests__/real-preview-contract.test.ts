import { readFileSync } from 'node:fs'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { FIRST_USE_ENGINE_RESUME_TEMPLATE } from '../lib/first-use-resume'
import {
  firstEditableBullet, guestCooldownMilliseconds, isLocalPreviewResource, localHttpOrigin,
  previewBrowserLaunchOptions, readDemoSource,
} from '../../scripts/real-preview-contract.mjs'

describe('credential-free real preview harness', () => {
  it('allows only explicit loopback HTTP origins', () => {
    for (const origin of ['http://localhost:5180', 'http://127.0.0.1:8030', 'http://[::1]:8030']) {
      expect(localHttpOrigin(origin)).toBe(origin)
    }
    for (const origin of [undefined, '', 'https://example.com', 'http://example.com',
      'http://user:password@127.0.0.1:8030', 'http://127.0.0.1:8030/',
      'http://127.0.0.1:8030/jobs', 'http://127.0.0.1:8030?token=secret']) {
      expect(() => localHttpOrigin(origin)).toThrow(/local HTTP origin/)
    }
  })

  it('uses the shipped demo source rather than obsolete hardcoded field text', async () => {
    expect(await readDemoSource()).toBe(FIRST_USE_ENGINE_RESUME_TEMPLATE)
    expect(firstEditableBullet(await readDemoSource())).toBe('Guided new customers through onboarding and answered questions about their account.')
    expect(() => firstEditableBullet('no bullet')).toThrow(/no plain editable bullet/)
  })

  it('matches JavaScript template-literal line endings on CRLF checkouts', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'latexy-demo-source-'))
    try {
      const filename = join(directory, 'first-use-resume.ts')
      await writeFile(filename, 'export const FIRST_USE_ENGINE_RESUME_TEMPLATE = String.raw`first\r\nsecond\rthird\\nkept\\rkept`')
      expect(await readDemoSource(filename)).toBe('first\nsecond\nthird\\nkept\\rkept')
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  })

  it('recognizes local PDF blob/data loads without allowing remote network or blob origins', () => {
    for (const resource of ['blob:http://127.0.0.1:5180/pdf', 'data:application/pdf;base64,JVBERi0=',
      'about:blank', 'ws://127.0.0.1:8030/ws/jobs']) expect(isLocalPreviewResource(resource)).toBe(true)
    for (const resource of ['https://example.com', 'wss://example.com/ws/jobs',
      'blob:https://example.com/pdf', 'file:///tmp/document.pdf',
      'http://user:password@127.0.0.1:8030']) expect(isLocalPreviewResource(resource)).toBe(false)
  })

  it('waits the normal cooldown and fails closed on missing/bypassed trial accounting', () => {
    const now = Date.parse('2026-10-11T00:05:00Z')
    const status = { blocked: false, remainingUses: 2, trialLimit: 3, usageCount: 1, lastUsed: '2026-10-11T00:00:00Z' }
    expect(guestCooldownMilliseconds(status, now)).toBe(1_000)
    expect(guestCooldownMilliseconds(status, now - 300_000)).toBe(301_000)
    for (const update of [{ blocked: true }, { remainingUses: 0 }, { trialLimit: 100 },
      { usageCount: 0 }, { lastUsed: null }, { lastUsed: 'invalid' }, { lastUsed: '2026-10-11T01:00:00Z' }]) {
      expect(() => guestCooldownMilliseconds({ ...status, ...update }, now)).toThrow()
    }
  })

  it('uses managed Chromium without mocks, retries, traces or a second server', () => {
    expect(previewBrowserLaunchOptions()).toEqual({ headless: true })
    const config = readFileSync(new URL('../../playwright.real-preview.config.ts', import.meta.url), 'utf8')
    expect(config).toContain('workers: 1')
    expect(config).toContain('retries: 0')
    expect(config).toContain("trace: 'off'")
    expect(config).toContain("outputFile: resolve(evidence, 'real-preview.xml')")
    expect(config).not.toContain('webServer:')
    expect(config).not.toContain("channel: 'chrome'")
    const benchmark = readFileSync(new URL('../../scripts/benchmark-preview-browser.mjs', import.meta.url), 'utf8')
    expect(benchmark).toContain('chromium.launch(previewBrowserLaunchOptions())')
    expect(benchmark).toContain('firstEditableBullet(await readDemoSource(')
    expect(benchmark).not.toContain('Built internal design system')
    expect(benchmark).not.toContain('page.route(')
    expect(benchmark).toContain('functional samples do not support percentile claims')
    expect(benchmark).toContain('if (report.failures.length) process.exitCode = 1')
  })

  it('keeps exact artifact and keyboard selection checks for wrapped semantic hit targets', () => {
    const spec = readFileSync(new URL('../../e2e/real-preview/compile-preview.spec.ts', import.meta.url), 'utf8')
    const studio = readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8')
    for (const label of ['Automatically update the PDF after edits', 'Update PDF preview']) {
      expect(studio).toContain(`aria-label="${label}"`)
      expect(spec).toContain(`name: '${label}', exact: true`)
    }
    expect(spec).not.toContain("name: 'Auto-compile on change'")
    expect(spec).not.toContain("name: 'Update PDF',")
    expect(spec).toContain('expect(semanticFieldHitTarget(page, expectedBullet)).toBeVisible()')
    expect(spec).toContain('await semanticFieldHitTarget(page, originalBullet).focus()')
    expect(spec).toContain("await page.keyboard.press('Enter')")
    expect(spec).toContain("getByLabel('Experience · bullet')).toHaveValue(originalBullet)")
    expect(spec).toContain('expect(digest(pdf.body)).toBe(artifact.pdf_sha256)')
    expect(spec).toContain('expect(geometry.source_sha256).toBe(artifact.source_sha256)')
    expect(spec).not.toMatch(/\.route\(|routeWebSocket\(/)
  })
})
