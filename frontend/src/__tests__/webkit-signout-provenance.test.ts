import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'
import {
  candidatePrefetchUrl, classifySignOutPageErrors, connectionPolicyUnrestricted, installSignOutProvenance,
  type NavigationLedger, type SignOutNavigation,
} from '../../e2e/helpers/webkit-signout-provenance'

const origin = 'http://localhost:5182'
const url = `${origin}/terms?_rsc=synthetic`
const stack = `Fetch API cannot load ${url} due to access control checks.\n    at fetch (app.js:1:1)`

type Evidence = Parameters<typeof classifySignOutPageErrors>[0] & { ledger: NavigationLedger; navigation: SignOutNavigation }

function evidence(): Evidence {
  return {
    browserName: 'webkit', appOrigin: origin, runId: 'test-run',
    navigation: { documentId: 'old', intentAt: 100, connectionPolicyUnrestricted: true, postSucceededAt: 200, replacementStartedAt: 210, replacementCommittedAt: 250 },
    ledger: {
      version: 1 as const, runId: 'test-run', overflow: false,
      documents: [
        { id: 'old', url: `${origin}/platform`, startedAt: 10, hiddenAt: 240, signOutIntentAt: 100,
          fetches: [{ url, at: 215, method: 'GET', signalAborted: false, keepalive: false, metaPolicyUnrestricted: true }], windowErrors: [] as Array<{ kind: string; at: number }> },
        { id: 'new', url: `${origin}/`, startedAt: 245, hiddenAt: null, signOutIntentAt: null, fetches: [], windowErrors: [] },
      ],
    },
    errors: [{ name: 'Fetch API cannot load http', message: `/localhost:5182/terms?_rsc=synthetic due to access control checks.`, stack, url: `${origin}/platform`, observedAt: 220 }],
    browserRequestUrls: [] as string[],
  }
}

describe('strict WebKit sign-out refusal classification', () => {
  it.each(['/terms', '/byok'])('classifies only positively proven %s provisional refusal and retains the raw error', path => {
    const input = evidence()
    const candidate = `${origin}${path}?_rsc=synthetic`
    input.ledger.documents[0].fetches[0].url = candidate
    input.errors[0].message = `/localhost:5182${path}?_rsc=synthetic due to access control checks.`
    input.errors[0].stack = stack.replace('/terms?', `${path}?`)
    const result = classifySignOutPageErrors(input)
    expect(result.unclassified).toEqual([])
    expect(result.classified).toHaveLength(1)
    expect(result.classified[0].error).toBe(input.errors[0])
    expect(input.errors).toHaveLength(1)
  })

  const negatives: Array<[string, (input: ReturnType<typeof evidence>) => void]> = [
    ['Chromium', i => { i.browserName = 'chromium' }],
    ['Firefox', i => { i.browserName = 'firefox' }],
    ['another run', i => { i.ledger.runId = 'other' }],
    ['overflowed ledger', i => { i.ledger.overflow = true }],
    ['stale document intent', i => { i.navigation.documentId = 'stale' }],
    ['intent mismatch', i => { i.ledger.documents[0].signOutIntentAt = 90 }],
    ['restricted or unknown connection policy', i => { i.navigation.connectionPolicyUnrestricted = false }],
    ['aborted sign-out', i => { i.navigation.postSucceededAt = null }],
    ['failed/no replacement', i => { i.navigation.replacementStartedAt = null }],
    ['uncommitted replacement', i => { i.navigation.replacementCommittedAt = null }],
    ['unpersisted old document end', i => { i.ledger.documents[0].hiddenAt = null }],
    ['wrong destination', i => { i.ledger.documents[1].url = `${origin}/login` }],
    ['intermediate stale document', i => { i.ledger.documents.splice(1, 0, { ...i.ledger.documents[1], id: 'intermediate', url: `${origin}/byok` }) }],
    ['wrong old document URL', i => { i.errors[0].url = `${origin}/byok` }],
    ['pre-navigation error', i => { i.errors[0].observedAt = 205 }],
    ['post-pagehide error', i => { i.errors[0].observedAt = 241 }],
    ['post-commit error', i => { i.navigation.replacementCommittedAt = 219 }],
    ['fetch before navigation', i => { i.ledger.documents[0].fetches[0].at = 205 }],
    ['error before fetch', i => { i.ledger.documents[0].fetches[0].at = 225 }],
    ['already aborted fetch', i => { i.ledger.documents[0].fetches[0].signalAborted = true }],
    ['keepalive request', i => { i.ledger.documents[0].fetches[0].keepalive = true }],
    ['new restrictive meta policy', i => { i.ledger.documents[0].fetches[0].metaPolicyUnrestricted = false }],
    ['POST fetch', i => { i.ledger.documents[0].fetches[0].method = 'POST' }],
    ['browser dispatched request/CORS or redirect failure', i => { i.browserRequestUrls.push(url) }],
    ['transport ledger bound reached', i => { i.browserRequestUrls = Array(128).fill('bounded') }],
    ['no fetch attempt', i => { i.ledger.documents[0].fetches = [] }],
    ['missing original stack', i => { i.errors[0].stack = '' }],
    ['application Error shape', i => { i.errors[0].name = 'Error' }],
    ['unexpected message', i => { i.errors[0].message += ' altered' }],
    ['genuine window exception', i => { i.ledger.documents[0].windowErrors.push({ kind: 'error', at: 218 }) }],
    ['genuine unhandled rejection', i => { i.ledger.documents[0].windowErrors.push({ kind: 'unhandledrejection', at: 218 }) }],
    ['CSP refusal', i => { i.ledger.documents[0].windowErrors.push({ kind: 'securitypolicyviolation', at: 218 }) }],
    ['destination window exception', i => { i.ledger.documents[1].windowErrors.push({ kind: 'error', at: 260 }) }],
  ]
  it.each(negatives)('rejects %s', (_label, mutate) => {
    const input = evidence(); mutate(input)
    const result = classifySignOutPageErrors(input)
    expect(result.classified).toEqual([])
    expect(result.unclassified).toEqual(input.errors)
  })

  it('fails closed without instrumentation or explicit sign-out intent', () => {
    const input = evidence()
    expect(classifySignOutPageErrors({ ...input, ledger: null }).unclassified).toEqual(input.errors)
    expect(classifySignOutPageErrors({ ...input, navigation: null }).unclassified).toEqual(input.errors)
  })

  it.each([
    'https://another.example/terms?_rsc=synthetic',
    'http://user:synthetic-password@localhost:5182/terms?_rsc=synthetic',
    'http://user@localhost:5182/terms?_rsc=synthetic',
    'http://:synthetic-password@localhost:5182/terms?_rsc=synthetic',
    `${origin}/api/auth/sign-out?_rsc=synthetic`,
    `${origin}/privacy?_rsc=synthetic`,
    `${origin}/terms?token=secret&_rsc=synthetic`,
    `${origin}/terms?_rsc=synthetic&_rsc=duplicate`,
    `${origin}/terms?_rsc=synthetic#fragment`,
    `${origin}/terms`,
  ])('never admits a cross-origin/API/unproven/query-bearing candidate: %s', raw => {
    expect(candidatePrefetchUrl(raw, origin)).toBeNull()
    const input = evidence()
    input.errors[0].stack = `Fetch API cannot load ${raw} due to access control checks.`
    input.ledger.documents[0].fetches[0].url = raw
    expect(classifySignOutPageErrors(input).classified).toEqual([])
  })
})

describe('connection policy proof is conservative across combined headers', () => {
  it.each(['', "frame-ancestors 'none'; base-uri 'self'; object-src 'none'", "frame-ancestors 'none', base-uri 'self'; object-src 'none'"])(
    'accepts only absent policy or the known shipped baseline: %s', value => expect(connectionPolicyUnrestricted(value)).toBe(true),
  )
  it.each([
    "img-src 'self', connect-src 'self'",
    "frame-ancestors 'none', default-src 'self'",
    "frame-ancestors 'none'; connect-src 'none'",
    "frame-ancestors 'none'; CoNnEcT-sRc 'self'",
    "frame-ancestors 'none',connect-src 'none'; object-src 'none'",
    "frame-ancestors 'none, connect-src self'",
    "frame-ancestors 'none',",
    "frame-ancestors 'none'; unknown-directive safe",
    "base-uri\u00a0'self'",
    "base-uri 'self'\nconnect-src 'none'",
    'x'.repeat(2_049),
  ])('denies restrictive, unknown, quoted/combined or ambiguous policies: %s', value => expect(connectionPolicyUnrestricted(value)).toBe(false))
})

describe('actual serialized browser recorder', () => {
  function recorder(metaPolicies: Array<{ httpEquiv: string; content: string }> = []) {
    const storage = new Map<string, string>()
    const events = new Map<string, () => void>()
    const nativeCalls: unknown[][] = []
    const window = { fetch: function (...args: unknown[]) { nativeCalls.push(args); return Promise.resolve('native result') } }
    const context = { window, location: { origin, pathname: '/platform', href: `${origin}/platform` },
      sessionStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) },
      crypto: { randomUUID: () => 'old' }, Date, URL, Headers, Request,
      document: { querySelectorAll: () => metaPolicies },
      addEventListener: (name: string, listener: () => void) => events.set(name, listener),
    }
    runInNewContext(`(${installSignOutProvenance.toString()})({storageKey:'test-key',runId:'test-run'})`, context)
    return { storage, events, nativeCalls, window: window as typeof window & { __latexySignOutProvenance: { arm(): unknown } },
      ledger: () => JSON.parse(storage.get('test-key')!) as NavigationLedger }
  }

  it('retains native return/arguments, records only bounded public prefetch metadata and persists pagehide', async () => {
    const r = recorder()
    r.window.__latexySignOutProvenance.arm()
    const init = { headers: { RSC: '1', 'Next-Router-Prefetch': '1' } }
    expect(await r.window.fetch(url, init)).toBe('native result')
    expect(r.nativeCalls).toEqual([[url, init]])
    expect(r.ledger().documents[0].fetches[0]).toMatchObject({ url, method: 'GET', signalAborted: false })
    r.events.get('pagehide')!()
    expect(r.ledger().documents[0].hiddenAt).toBeTypeOf('number')
  })

  it('records real window exceptions, rejections and CSP violations without changing them', () => {
    const r = recorder()
    for (const kind of ['error', 'unhandledrejection', 'securitypolicyviolation']) r.events.get(kind)!()
    expect(r.ledger().documents[0].windowErrors.map(event => event.kind)).toEqual(['error', 'unhandledrejection', 'securitypolicyviolation'])
  })

  it('excludes unrelated query values, credentials, bodies and API requests', async () => {
    const r = recorder()
    await r.window.fetch(`${origin}/api/auth/sign-out?token=secret`, { method: 'POST', body: 'private-body', headers: { Authorization: 'private-token' } })
    await r.window.fetch(`${url}&private=secret`, { headers: { RSC: '1', 'Next-Router-Prefetch': '1' } })
    await r.window.fetch('http://user:synthetic-password@localhost:5182/terms?_rsc=synthetic', { headers: { RSC: '1', 'Next-Router-Prefetch': '1' } })
    expect(r.ledger().documents[0].fetches).toEqual([])
    expect(JSON.stringify(r.ledger())).not.toMatch(/private|secret|Authorization|synthetic-password|user:/)
    expect(r.nativeCalls).toHaveLength(3)
  })

  it('denies any enforced meta CSP, including combined, quoted or changed policies', async () => {
    const r = recorder([{ httpEquiv: 'Content-Security-Policy', content: "img-src 'self', connect-src 'self'" }])
    await r.window.fetch(url, { headers: { RSC: '1', 'Next-Router-Prefetch': '1' } })
    expect(r.ledger().documents[0].fetches[0].metaPolicyUnrestricted).toBe(false)
  })

  it('bounds recording and marks saturation unusable', async () => {
    const r = recorder()
    for (let count = 0; count < 130; count++) await r.window.fetch(url, { headers: { RSC: '1', 'Next-Router-Prefetch': '1' } })
    expect(r.ledger().documents[0].fetches).toHaveLength(128)
    expect(r.ledger().overflow).toBe(true)
    for (let count = 0; count < 20; count++) r.events.get('error')!()
    expect(r.ledger().documents[0].windowErrors).toHaveLength(16)
  })
})
