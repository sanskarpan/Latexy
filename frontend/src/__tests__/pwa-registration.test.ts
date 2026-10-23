import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { createContext, runInContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'
import { registerOptionalWorker } from '@/lib/pwa-registration'

const require = createRequire(import.meta.url)
const fromPwa = createRequire(require.resolve('@ducanh2912/next-pwa'))
const source = readFileSync(fromPwa.resolve('workbox-window/build/workbox-window.prod.umd.js'), 'utf8')
const settle = () => new Promise<void>(resolve => setImmediate(resolve))

function realWorkbox(result: 'valid' | 'undefined' | 'denied') {
  const registration = { scope: 'http://localhost:5195/', active: null, waiting: null, installing: null,
    addEventListener() {}, update: async () => undefined }
  const register = vi.fn(async () => {
    if (result === 'denied') throw new DOMException('Service workers denied by policy', 'SecurityError')
    return result === 'valid' ? registration : undefined
  })
  const scope = {
    URL, Promise, Set, Map, setTimeout, clearTimeout, console, performance,
    location: new URL('http://localhost:5195/'),
    document: { baseURI: 'http://localhost:5195/', readyState: 'complete' },
    navigator: { serviceWorker: { controller: null, addEventListener() {}, register } },
  }
  const context = createContext(scope)
  context.window = scope
  context.self = scope
  runInContext(source, context, { timeout: 1_000 })
  const Workbox = (context.workbox as { Workbox: new (url: string) => { register(): Promise<unknown> } }).Workbox
  return { workbox: new Workbox('/sw.js'), register, registration }
}

describe('optional production worker registration', () => {
  it('preserves the actual installed Workbox receiver and successful registration', async () => {
    const { workbox, register, registration } = realWorkbox('valid')
    const actual = workbox.register.bind(workbox)
    let returned: Promise<unknown> | undefined
    workbox.register = function () { returned = actual(); return returned }
    registerOptionalWorker(workbox)
    await settle()
    expect(register).toHaveBeenCalledOnce()
    await expect(returned).resolves.toBe(registration)
  })

  it.each(['undefined', 'denied'] as const)('contains the real Workbox rejection for %s registration', async result => {
    const { workbox, register } = realWorkbox(result)
    registerOptionalWorker(workbox)
    await settle()
    expect(register).toHaveBeenCalledOnce()
    // Vitest fails the test on an unhandled rejection. No registration is
    // fabricated and no global rejection listener is installed.
  })

  it('contains a synchronous registration policy throw', () => {
    const register = vi.fn(() => { throw new DOMException('Blocked', 'SecurityError') })
    expect(() => registerOptionalWorker({ register })).not.toThrow()
    expect(register).toHaveBeenCalledOnce()
  })

  it('attempts a rejected instance once across repeated mount-effect setup', async () => {
    const workbox = { register: vi.fn(() => Promise.reject(new Error('Denied'))) }
    registerOptionalWorker(workbox)
    registerOptionalWorker(workbox)
    await settle()
    registerOptionalWorker(workbox)
    expect(workbox.register).toHaveBeenCalledOnce()
  })

  it('does not let one failed instance suppress a fresh Workbox instance', async () => {
    const first = { register: vi.fn(() => Promise.reject(new Error('Denied'))) }
    const second = { register: vi.fn(() => Promise.resolve(undefined)) }
    registerOptionalWorker(first)
    registerOptionalWorker(second)
    await settle()
    expect(first.register).toHaveBeenCalledOnce()
    expect(second.register).toHaveBeenCalledOnce()
  })

  it('handles unsupported or missing worker globals without polling or registration', () => {
    for (const value of [undefined, null, false, {}, { register: null }]) {
      expect(() => registerOptionalWorker(value)).not.toThrow()
    }
  })
})
