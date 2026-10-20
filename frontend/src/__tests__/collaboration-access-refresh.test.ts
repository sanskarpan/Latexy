import { afterEach, describe, expect, it, vi } from 'vitest'

type Effect = { deps?: unknown[]; cleanup?: () => void }
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function settle() { for (let i = 0; i < 12; i++) await Promise.resolve() }
async function harness() {
  vi.resetModules()
  let ownerId: string | null = 'owner'; let resumeId = 'A'; let token: string | null = 'token-a'; let capability = true; let apiToken: string | null = token
  let si = 0, ri = 0, ei = 0, ci = 0
  const state: unknown[] = []; const refs: { current: unknown }[] = []; const effects: Effect[] = []
  const callbacks: { value: unknown; deps: unknown[] }[] = []; let scheduled: (() => void)[] = []
  const requests: ReturnType<typeof deferred<{ access_role: 'owner' | 'editor' | 'viewer' }>>[] = []
  const roles: string[] = []
  const api = { getAuthToken: () => apiToken, getResume: vi.fn(() => { const req = deferred<{ access_role: 'owner' | 'editor' | 'viewer' }>(); requests.push(req); return req.promise }) }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('react', () => ({
    useState: (initial: unknown) => { const slot = si++; if (!(slot in state)) state[slot] = initial; return [state[slot], (value: unknown) => { state[slot] = value }] },
    useRef: (initial: unknown) => { const slot = ri++; return refs[slot] ??= { current: initial } },
    useCallback: (fn: unknown, deps: unknown[]) => { const slot = ci++; const old = callbacks[slot]; if (!old || deps.some((v, i) => v !== old.deps[i])) callbacks[slot] = { value: fn, deps }; return callbacks[slot].value },
    useEffect: (fn: () => void | (() => void), deps?: unknown[]) => {
      const slot = ei++; const old = effects[slot]
      if (old?.deps && deps && deps.every((v, i) => v === old.deps![i])) return
      scheduled.push(() => { old?.cleanup?.(); effects[slot] = { deps, cleanup: fn() || undefined } })
    },
  }))
  const listeners = new Map<string, () => void>()
  vi.stubGlobal('window', { addEventListener: (name: string, fn: () => void) => listeners.set(name, fn), removeEventListener: (name: string) => listeners.delete(name) })
  const { useCollaborationAccessRefresh } = await import('@/hooks/useCollaborationAccessRefresh')
  const TestComponent = () => { si = ri = ei = ci = 0; return useCollaborationAccessRefresh({ ownerId, resumeId, token, collaborationAllowed: capability, setRole: role => roles.push(role) }) }
  const flush = async () => { const next = scheduled; scheduled = []; next.forEach(fn => fn()); await settle() }
  return { requests, roles, api, render: TestComponent, flush,
    rotate: () => { token = 'token-b'; apiToken = token }, publish: (value: string | null) => { apiToken = value }, document: (id: string) => { resumeId = id }, signedOut: () => { ownerId = null; token = null },
    toggle: () => { capability = !capability }, focus: () => listeners.get('focus')?.(),
    unmount: () => effects.forEach(effect => effect.cleanup?.()),
  }
}

afterEach(() => { vi.doUnmock('react'); vi.doUnmock('@/lib/api-client'); vi.unstubAllGlobals(); vi.resetModules() })

describe('auth-scoped collaboration ACL refresh', () => {
  it('keeps initial and replaced scopes unresolved before effects run', async () => {
    const h = await harness(); expect(h.render().pending).toBe(true); await h.flush()
    h.requests[0].resolve({ access_role: 'owner' }); await settle(); expect(h.render().pending).toBe(false)
    h.document('B'); expect(h.render().pending).toBe(true)
  })
  it.each([null, 'old-token'])('fails closed without GET when API credential remains %s', async apiToken => {
    const h = await harness(); h.publish(apiToken); expect(h.render().pending).toBe(true); await h.flush()
    expect(h.requests).toHaveLength(0); expect(h.roles).toEqual(['viewer']); expect(h.render().pending).toBe(false)
  })
  it('allows AuthSync to publish the expected token during the deferred turn', async () => {
    const h = await harness(); h.publish(null); const view = h.render()
    const request = view.refresh('A'); h.publish('token-a'); await settle()
    expect(h.requests).toHaveLength(1); h.requests[0].resolve({ access_role: 'owner' }); await request
    expect(h.roles).toEqual(['owner']); expect(h.render().pending).toBe(false)
  })
  it('rotates a credential while GET is pending and starts a new authoritative request', async () => {
    const h = await harness(); h.render(); await h.flush(); expect(h.render().pending).toBe(true)
    h.rotate(); h.render(); await h.flush(); expect(h.requests).toHaveLength(2)
    h.requests[0].resolve({ access_role: 'owner' }); await settle()
    expect(h.roles).toEqual([]); expect(h.render().pending).toBe(true)
    h.requests[1].resolve({ access_role: 'editor' }); await settle()
    expect(h.roles).toEqual(['editor']); expect(h.render().pending).toBe(false)
  })
  it('rejects old A after A → B → A without disturbing newest pending state', async () => {
    const h = await harness(); h.render(); await h.flush()
    h.document('B'); h.render(); await h.flush(); h.document('A'); h.render(); await h.flush()
    h.requests[0].resolve({ access_role: 'owner' }); h.requests[1].resolve({ access_role: 'editor' }); await settle()
    expect(h.roles).toEqual([]); expect(h.render().pending).toBe(true)
    h.requests[2].resolve({ access_role: 'viewer' }); await settle()
    expect(h.roles).toEqual(['viewer']); expect(h.render().pending).toBe(false)
  })
  it('ignores a held older read after newer revocation and leaves source untouched', async () => {
    const h = await harness(); h.render(); await h.flush(); h.focus(); await settle()
    h.requests[1].reject(new Error('404 revoked')); await settle()
    h.requests[0].resolve({ access_role: 'editor' }); await settle()
    expect(h.roles).toEqual(['viewer']); expect(h.render().pending).toBe(false)
  })
  it('rejects a captured old-document refresh callback before effect cleanup', async () => {
    const h = await harness(); const old = h.render(); await h.flush()
    h.document('B'); h.render()
    await old.refresh('A')
    expect(h.requests).toHaveLength(1)
    await h.flush(); expect(h.requests).toHaveLength(2)
    h.requests[1].resolve({ access_role: 'viewer' }); await settle()
    expect(h.roles).toEqual(['viewer'])
  })
  it('does not invalidate an ACL response on unrelated re-render/PDF work', async () => {
    const h = await harness(); h.render(); await h.flush(); h.render(); await h.flush()
    expect(h.requests).toHaveLength(1)
    h.requests[0].resolve({ access_role: 'owner' }); await settle()
    expect(h.roles).toEqual(['owner']); expect(h.render().pending).toBe(false)
  })
  it('fails closed on transient errors and permits a later focus recovery', async () => {
    const h = await harness(); h.render(); await h.flush(); h.requests[0].reject(new Error('network')); await settle()
    expect(h.roles).toEqual(['viewer']); h.focus(); await settle(); expect(h.render().pending).toBe(true)
    h.requests[1].resolve({ access_role: 'editor' }); await settle()
    expect(h.roles).toEqual(['viewer', 'editor']); expect(h.render().pending).toBe(false)
  })
  it('invalidates pending work on signout and unmount', async () => {
    const h = await harness(); h.render(); await h.flush(); h.signedOut(); h.render(); await h.flush(); h.unmount()
    h.requests[0].resolve({ access_role: 'owner' }); await settle()
    expect(h.roles).toEqual([]); expect(h.render().pending).toBe(false)
  })
})
