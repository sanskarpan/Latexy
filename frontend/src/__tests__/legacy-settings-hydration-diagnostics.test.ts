import { readFileSync } from 'node:fs'
import type { Page, Route } from '@playwright/test'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installLegacySettingsHydrationDiagnostics, instrumentPinnedLegacySettingsReact, LEGACY_SETTINGS_REACT_CHUNK } from '../../e2e/helpers/legacy-settings-hydration-diagnostics'

const pinnedSignature = 'var rP=null,rN=null,rL=!1,rT=null,r_=!1;function rD(e){var n=Error(i(418,"HTML",""));throw rU(rd(n,e)),rF}'

describe('failure-only synthetic Settings hydration diagnostic', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('matches only the pinned React chunk and fails closed on hook drift', () => {
    expect(LEGACY_SETTINGS_REACT_CHUNK.test('http://localhost:5184/_next/static/chunks/082d2186-2be66f8bc71d1842.js')).toBe(true)
    expect(LEGACY_SETTINGS_REACT_CHUNK.test('http://localhost:5184/_next/static/chunks/app/settings/page-abc.js')).toBe(false)
    expect(LEGACY_SETTINGS_REACT_CHUNK.test('http://localhost:5184/_next/static/chunks/a9f434d3-abc.js')).toBe(false)
    for (const source of ['', pinnedSignature.replace('function rD(e){', 'function changed(e){'),
      pinnedSignature + pinnedSignature, pinnedSignature.replace('rN=null', 'other=null'), 'x'.repeat(8 * 1024 * 1024 + 1)]) {
      expect(() => instrumentPinnedLegacySettingsReact(source)).toThrow(/absent or ambiguous/)
    }
  })

  it('preserves the original throw and records only bounded structural information', () => {
    const instrumented = instrumentPinnedLegacySettingsReact(pinnedSignature)
    expect(instrumented).toContain('var n=Error(i(418,"HTML",""));throw rU(rd(n,e)),rF}')
    expect(instrumented).toContain('d.hostClaims.length<8')
    expect(instrumented).toContain('chain.length<24')
    expect(instrumented).toContain('candidate:node(rN)')
    expect(instrumented).not.toMatch(/outerHTML|innerHTML|textContent|document\.cookie|localStorage|authToken|session\.token/)
  })

  it('opts into exactly one synthetic case without changing its zero-errors or owner gates', () => {
    const fixture = readFileSync(new URL('../../e2e/settings-legacy-callback-owner-isolation.spec.ts', import.meta.url), 'utf8')
    expect(fixture.match(/LEGACY_SETTINGS_HYDRATION_DIAGNOSTICS/g)).toHaveLength(1)
    expect(fixture).toContain("process.env.LEGACY_SETTINGS_HYDRATION_DIAGNOSTICS === '1'")
    expect(fixture).toContain('expect(fixture.pageErrors).toEqual([])')
    expect(fixture).toContain("tokenVersion: 'rotated-a'")
    expect(fixture).toContain('if (diagnostics) await diagnostics.attach(testInfo)')
    const helper = readFileSync(new URL('../../e2e/helpers/legacy-settings-hydration-diagnostics.ts', import.meta.url), 'utf8')
    expect(helper).toContain('maxRetries: 0')
    expect(helper).not.toMatch(/outerHTML|innerHTML|textContent|document\.cookie|localStorage|authToken|session\.token/)
  })

  it('caps forced errors and traverses at most twelve children for snapshots and mutation signatures', async () => {
    const nodes = Array.from({ length: 14 }, (_, index) => ({ nodeType: 1, nodeName: `SAFE${index}`, nextSibling: null as unknown }))
    nodes.forEach((node, index) => { node.nextSibling = nodes[index + 1] ?? null })
    Object.defineProperty(nodes[12], 'nodeName', { get: () => { throw new Error('Unbounded child traversal') } })
    const main = { firstChild: nodes[0] }
    let streamCount = 0
    let mutation = () => {}
    let error = (_event: { message: string }) => {}
    const fakeWindow: Record<string, unknown> = {
      addEventListener: (_name: string, callback: typeof error) => { error = callback },
      setTimeout: vi.fn(),
    }
    vi.stubGlobal('window', fakeWindow)
    vi.stubGlobal('Node', { COMMENT_NODE: 8 })
    vi.stubGlobal('document', {
      getElementById: () => main,
      querySelectorAll: (selector: string) => ({ length: selector === 'main' ? 1 : streamCount }),
      documentElement: { hasAttribute: () => false },
      addEventListener: vi.fn(),
    })
    vi.stubGlobal('MutationObserver', class {
      constructor(callback: () => void) { mutation = callback }
      observe() {}
      disconnect() {}
    })
    const page = { addInitScript: async (callback: () => void) => callback(), route: vi.fn() } as unknown as Page
    await installLegacySettingsHydrationDiagnostics(page)
    for (streamCount = 0; streamCount < 40; streamCount++) mutation()
    const state = fakeWindow.__legacySettingsHydrationDiagnostics as { snapshots: Array<{ mainChildKinds: unknown[]; event: string }> }
    expect(state.snapshots).toHaveLength(23)
    for (let index = 0; index < 100; index++) error({ message: 'Minified React error #418' })
    expect(state.snapshots).toHaveLength(24)
    expect(state.snapshots[state.snapshots.length - 1]?.event).toBe('react-host-mismatch')
    expect(state.snapshots.every(snapshot => snapshot.mainChildKinds.length === 12)).toBe(true)
  })

  it('uses the third wait argument and counts delivery before the browser can observe the hook', async () => {
    let handler: (route: Route) => Promise<void> = async () => {}
    const wait = vi.fn(async () => {})
    const page = { addInitScript: vi.fn(), url: () => 'http://localhost:5184/settings',
      route: async (_pattern: RegExp, callback: typeof handler) => { handler = callback },
      waitForFunction: wait } as unknown as Page
    const diagnostics = await installLegacySettingsHydrationDiagnostics(page)
    const fulfill = vi.fn(async () => { await diagnostics.verifyHookLoaded(1) })
    const abort = vi.fn()
    await handler({ request: () => ({ url: () => 'http://localhost:5184/_next/static/chunks/082d2186-2be66f8bc71d1842.js' }),
      fetch: vi.fn(async () => ({ ok: () => true, text: async () => pinnedSignature })), fulfill, abort } as unknown as Route)
    expect(abort).not.toHaveBeenCalled()
    expect(fulfill).toHaveBeenCalledOnce()
    expect(wait.mock.calls[0]).toEqual([expect.any(Function), undefined, { timeout: 15_000 }])
    await expect(diagnostics.verifyHookLoaded(2)).rejects.toThrow(/delivery could not be verified/)
  })

  it('refuses a chunk outside the current loopback origin without making a request', async () => {
    let handler: (route: Route) => Promise<void> = async () => {}
    const page = { addInitScript: vi.fn(), url: () => 'http://localhost:5184/settings',
      route: async (_pattern: RegExp, callback: typeof handler) => { handler = callback },
      waitForFunction: vi.fn() } as unknown as Page
    const diagnostics = await installLegacySettingsHydrationDiagnostics(page)
    const fetch = vi.fn()
    const abort = vi.fn()
    await handler({ request: () => ({ url: () => 'https://example.invalid/_next/static/chunks/082d2186-2be66f8bc71d1842.js' }),
      fetch, abort } as unknown as Route)
    expect(fetch).not.toHaveBeenCalled()
    expect(abort).toHaveBeenCalledExactlyOnceWith('failed')
    await expect(diagnostics.verifyHookLoaded(0)).rejects.toThrow(/delivery could not be verified/)
  })
})
