import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { createContext, runInContext } from 'node:vm'
import type { Page } from '@playwright/test'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installMockWorkboxRegistration } from '../../e2e/helpers/mock-workbox-registration'

const require = createRequire(import.meta.url)
const requireFromPwa = createRequire(require.resolve('@ducanh2912/next-pwa'))
const workboxSource = readFileSync(requireFromPwa.resolve('workbox-window/build/workbox-window.prod.umd.js'), 'utf8')

afterEach(() => vi.unstubAllGlobals())

function workboxWithBlockedRegistration() {
  // Model Playwright's serviceWorkers:block result, not a real browser failure.
  // The actual installed production Workbox bundle executes without networking.
  const scope = {
    URL, Promise, Set, Map, setTimeout, clearTimeout, console, performance,
    location: new URL('http://localhost:5184/'),
    document: { baseURI: 'http://localhost:5184/', readyState: 'complete' },
    navigator: { serviceWorker: { controller: null, addEventListener: () => undefined, register: async () => undefined } },
  }
  const context = createContext(scope)
  context.window = scope
  context.self = scope
  runInContext(workboxSource, context, { timeout: 1_000 })
  const Workbox = (context.workbox as { Workbox: new (url: string) => { register(options: { immediate: boolean }): Promise<unknown> } }).Workbox
  return { scope, Workbox }
}

describe('strict launch browser fixture lifecycle', () => {
  it('collects launch repairs alongside D14 in the canonical zero-retry capability gate', async () => {
    const { default: config } = await import('../../playwright.capabilities.config')
    expect(config.testMatch).toEqual([
      'capability-controls.spec.ts', 'capability-launch-repairs.spec.ts',
      'd14-child-controls.spec.ts', 'capability-native-find.spec.ts', 'plan-catalog.spec.ts',
    ])
    expect(config.retries).toBe(0)
  })

  it('reproduces the blocked-registration mismatch and satisfies the real installed Workbox contract with the shared mock', async () => {
    const { scope, Workbox } = workboxWithBlockedRegistration()
    await expect(new Workbox('/sw.js').register({ immediate: true })).rejects.toThrow(/reading 'waiting'/)

    const addInitScript = vi.fn()
    await installMockWorkboxRegistration({ addInitScript } as unknown as Page)
    vi.stubGlobal('window', scope)
    vi.stubGlobal('navigator', scope.navigator)
    addInitScript.mock.calls[0][0]()

    await expect(new Workbox('/sw.js').register({ immediate: true })).resolves.toMatchObject({
      scope: 'http://localhost:5184/', waiting: null, installing: null, active: null,
    })
  })

  it('installs the registration shape before navigation while retaining strict page errors and real PWA coverage', () => {
    const suite = readFileSync(new URL('../../e2e/capability-launch-repairs.spec.ts', import.meta.url), 'utf8')
    expect(suite).toContain("test.use({ serviceWorkers: 'block' })")
    expect(suite).toMatch(/test\.beforeEach\(async \(\{ page \}\) => \{\s+await installMockWorkboxRegistration\(page\)/)
    expect(suite).toContain("page.on('pageerror', error => errors.push(error.message))")
    expect(suite).toContain("expect(pageErrors.get(page), 'Uncaught browser errors, including React hydration failures').toEqual([])")
    const realPwa = readFileSync(new URL('../../e2e/pwa-production.spec.ts', import.meta.url), 'utf8')
    expect(realPwa).not.toContain('installMockWorkboxRegistration')
    expect(realPwa).not.toContain("serviceWorkers: 'block'")
    expect(realPwa).toContain('navigator.serviceWorker.ready')
  })
})
