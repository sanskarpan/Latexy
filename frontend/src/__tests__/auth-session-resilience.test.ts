import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const AUTH_SYNC = read('../components/AuthSync.tsx')
const AUTH_GUARD = read('../hooks/useRequireAuth.ts')
const HEADER = read('../components/GlobalHeader.tsx')

describe('session refresh resilience', () => {
  it('does not clear API or WebSocket authentication on an indeterminate session response', () => {
    expect(AUTH_SYNC).toContain('if (!unauthorized && (isPending || isRefetching || error)) return')
    expect(AUTH_SYNC.indexOf('if (!unauthorized && (isPending || isRefetching || error)) return'))
      .toBeLessThan(AUTH_SYNC.indexOf('apiClient.setAuthToken(token)'))
    expect(AUTH_SYNC).toContain('[session, isPending, isRefetching, error, unauthorized]')
  })

  it('keeps the last confirmed guarded session through pending, refetching and error states', () => {
    expect(AUTH_GUARD).toContain('lastKnownSessionRef')
    expect(AUTH_GUARD).toContain('(isPending || isRefetching || error) ? lastKnownSessionRef.current : null')
    expect(AUTH_GUARD).toContain('!isPending && !isRefetching && !error')
    expect(AUTH_GUARD).toContain('session: effectiveSession')
  })

  it('clears the header identity after authoritative 401 or a confirmed empty response', () => {
    expect(HEADER).toContain('!sessionPending && !sessionRefetching && !sessionError')
    expect(HEADER).toContain('const effectiveSession = unauthorized ? null :')
    expect(HEADER).toContain('(sessionPending || sessionRefetching || sessionError) ? lastKnownSessionRef.current : null')
  })
})

async function authHarness(sync = false) {
  vi.resetModules()
  const known = { user: { id: 'owner-A' }, session: { token: 'owner-token' } }
  type State = { data: typeof known | null; isPending: boolean; isRefetching?: boolean; error: unknown }
  type Atom = { value: State & { isRefetching: boolean; refetch: () => Promise<void> }; set: (next: Atom['value']) => void }
  let state: State = { data: known, isPending: false, isRefetching: false, error: null }
  let atom: Atom | null = null; let index = 0
  const slots: Array<{ ref?: { current: unknown }; deps?: unknown[] }> = []
  const queued = new Map<number, () => void>()
  vi.doMock('react', async original => ({ ...await original<typeof import('react')>(),
    useRef: (current: unknown) => { const at = index++; slots[at] ??= {}; slots[at].ref ??= { current }; return slots[at].ref },
    useEffect: (effect: () => void, next: unknown[]) => {
      const at = index++; const previous = slots[at]?.deps; slots[at] ??= {}
      if (!previous || next.some((value, position) => !Object.is(value, previous[position]))) { slots[at].deps = next; queued.set(at, effect) }
    },
  }))
  const router = { push: vi.fn() }
  vi.doMock('next/navigation', () => ({ useRouter: () => router }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => atom?.value ?? state }))
  let apiToken: string | null = null
  const api = { setAuthToken: vi.fn((next: string | null) => { apiToken = next }), markAuthResolved: vi.fn(), getAuthToken: () => apiToken }
  const ws = { setAuthenticated: vi.fn() }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('@/lib/ws-client', () => ({ wsClient: ws }))
  vi.stubGlobal('navigator', { onLine: true })
  vi.stubGlobal('window', { location: { pathname: '/workspace/resume-A/edit' } })
  vi.stubGlobal('document', { cookie: '' })
  const { useRequireAuth } = await import('@/hooks/useRequireAuth')
  function GuardProbe() { return useRequireAuth() }
  const { AuthSync } = await import('@/components/AuthSync')
  const flush = () => { const effects = [...queued.values()]; queued.clear(); effects.forEach(effect => effect()) }
  return { known, router, api, ws, flush, state: (next: State) => { state = next }, render: (flushEffects = true) => {
    index = 0; const result = GuardProbe(); if (sync) AuthSync(); if (flushEffects) flush(); return result
  }, useActualSessionAtom: async () => {
    const sessionModule = path.join(path.dirname(createRequire(import.meta.url).resolve('better-auth/client')), 'session-atom.mjs')
    const { getSessionAtom } = await import(pathToFileURL(sessionModule).href)
    let release!: (response: { data: typeof known | null; error: { status: number; message: string } | null }) => void
    const response = new Promise<{ data: typeof known | null; error: { status: number; message: string } | null }>(resolve => { release = resolve })
    const fetch = vi.fn(() => response)
    const created = getSessionAtom(fetch, {}) as { session: Atom }; atom = created.session
    atom.set({ ...atom.value, data: known, isPending: false, isRefetching: false, error: null })
    return { atom, release, fetch }
  } }
}
afterEach(() => {
  for (const moduleName of ['react', 'next/navigation', '@/lib/auth-client', '@/lib/api-client', '@/lib/ws-client']) vi.doUnmock(moduleName)
  vi.unstubAllGlobals(); vi.resetModules()
})

describe('confirmed-session guard authenticated refetch semantics', () => {
  it.each([null, undefined, {}, { status: '401' }, { statusCode: 401 }, { status: 403 }, { status: 503 }])('does not classify %j as authoritative unauthenticated', error => {
    expect(isConfirmedSessionUnauthorized(error)).toBe(false)
  })
  it('recognizes only numeric HTTP401 and rejects a stale accompanying session synchronously', async () => {
    expect(isConfirmedSessionUnauthorized({ status: 401 })).toBe(true)
    const h = await authHarness(); h.render()
    h.state({ data: h.known, isPending: false, isRefetching: false, error: { status: 401, message: 'Expired' } })
    expect(h.render(false).session).toBeNull(); h.flush()
    expect(h.router.push).toHaveBeenCalledExactlyOnceWith('/login?redirect=%2Fworkspace%2Fresume-A%2Fedit')
  })
  it('returns refetching independently while the exact known session remains stable and cold pending stays false', async () => {
    const h = await authHarness(); expect(h.render().session).toBe(h.known)
    h.state({ data: h.known, isPending: false, isRefetching: true, error: null })
    const refreshing = h.render()
    expect(refreshing.session).toBe(h.known); expect(refreshing.isPending).toBe(false); expect(refreshing.isRefetching).toBe(true)
    expect(h.router.push).not.toHaveBeenCalled()
    h.state({ data: h.known, isPending: false, isRefetching: false, error: null })
    expect(h.render().isRefetching).toBe(false); expect(h.router.push).not.toHaveBeenCalled()
  })

  it('preserves known owner through missing-data refetch and defers an empty-session redirect until refetch ends', async () => {
    const h = await authHarness(); h.render()
    h.state({ data: null, isPending: false, isRefetching: true, error: null })
    expect(h.render().session).toBe(h.known); expect(h.router.push).not.toHaveBeenCalled()
    h.state({ data: null, isPending: false, isRefetching: false, error: null })
    expect(h.render().session).toBeNull()
    expect(h.router.push).toHaveBeenCalledExactlyOnceWith('/login?redirect=%2Fworkspace%2Fresume-A%2Fedit')
  })

  it('preserves known owner through cold pending and error, and defaults an absent mock refetch flag to false', async () => {
    const h = await authHarness(); h.render()
    h.state({ data: null, isPending: true, error: null }); let result = h.render()
    expect(result.session).toBe(h.known); expect(result.isPending).toBe(true); expect(result.isRefetching).toBe(false)
    h.state({ data: null, isPending: false, error: new Error('Transient fetch error') }); result = h.render()
    expect(result.session).toBe(h.known); expect(result.isPending).toBe(false); expect(h.router.push).not.toHaveBeenCalled()
  })

  it.each([401, 503])('runs installed Better Auth%s through the actual guard and API/WS AuthSync publication path', async status => {
    const h = await authHarness(true); const actual = await h.useActualSessionAtom(); h.render()
    expect(h.api.getAuthToken()).toBe('owner-token'); expect(h.ws.setAuthenticated).toHaveBeenLastCalledWith(true)
    const completion = actual.atom.value.refetch(); await Promise.resolve(); h.render()
    expect(actual.atom.value.data).toBe(h.known); expect(actual.atom.value.isPending).toBe(false)
    expect(actual.atom.value.isRefetching).toBe(true); expect(h.api.setAuthToken).toHaveBeenCalledOnce()
    actual.release({ data: null, error: { status, message: `Synthetic ${status}` } }); await completion
    const resolved = h.render(false)
    if (status === 401) {
      expect(actual.atom.value.data).toBeNull(); expect(resolved.session).toBeNull()
      h.flush(); expect(h.api.getAuthToken()).toBeNull(); expect(h.ws.setAuthenticated).toHaveBeenLastCalledWith(false)
      expect(h.api.markAuthResolved).toHaveBeenCalledTimes(2); expect(h.router.push).toHaveBeenCalledOnce()
    } else {
      expect(actual.atom.value.data).toBe(h.known); expect(resolved.session).toBe(h.known)
      h.flush(); expect(h.api.getAuthToken()).toBe('owner-token'); expect(h.api.setAuthToken).toHaveBeenCalledOnce()
      expect(h.ws.setAuthenticated).toHaveBeenCalledOnce(); expect(h.router.push).not.toHaveBeenCalled()
    }
  })
})
