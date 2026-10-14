import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'

type Session = { user: { id: string } }
type State = { data: Session | null; isPending: boolean; isRefetching?: boolean; error: unknown }
type Atom = { value: State & { isRefetching: boolean; refetch: () => Promise<void> }; set: (next: Atom['value']) => void }

async function harness() {
  vi.resetModules()
  let session: State = { data: { user: { id: 'a' } }, isPending: false, error: null }
  let atom: Atom | null = null
  let index = 0; let pathname = '/workspace/doc-A/edit'
  const refs: Array<{ current: unknown }> = []; const effects: Array<() => (() => void) | void> = []
  let cleanup: (() => void) | undefined
  vi.doMock('react', async original => ({ ...await original<typeof import('react')>(), Fragment: 'Fragment',
    useRef: (initial: unknown) => { const at = index++; refs[at] ??= { current: initial }; return refs[at] },
    useEffect: (effect: () => (() => void) | void) => { const at = index++; if (!refs[at]) { refs[at] = { current: true }; effects.push(effect) } },
  }))
  vi.doMock('next/navigation', () => ({ usePathname: () => pathname }))
  vi.doMock('react/jsx-runtime', () => ({ jsx: (type: unknown, props: unknown, key: unknown) => ({ type, props, key }) }))
  vi.doMock('react/jsx-dev-runtime', () => ({ jsxDEV: (type: unknown, props: unknown, key: unknown) => ({ type, props, key }) }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => atom?.value ?? session }))
  const Boundary = (await import('@/components/AccountContentBoundary')).default
  return { render: () => { index = 0; const tree = Boundary({ children: null }); return { key: tree.props.children.key, authority: tree.props.value as import('@/contexts/AccountContentScope').AccountContentScope } },
    path: (next: string) => { pathname = next }, mount: () => { cleanup = effects[0]?.() || undefined },
    unmount: () => { cleanup?.() }, remount: () => { cleanup = effects[0]?.() || undefined }, session: (next: typeof session) => { session = next }, useActualAtom: async () => {
    const sessionModule = path.join(path.dirname(createRequire(import.meta.url).resolve('better-auth/client')), 'session-atom.mjs')
    const { getSessionAtom } = await import(pathToFileURL(sessionModule).href)
    let release!: (next: { data: Session | null; error: { status: number; message: string } | null }) => void
    const response = new Promise<{ data: Session | null; error: { status: number; message: string } | null }>(resolve => { release = resolve })
    const fetch = vi.fn(() => response); const created = getSessionAtom(fetch, {}) as { session: Atom }
    atom = created.session; const known = session.data!
    atom.set({ ...atom.value, data: known, isPending: false, isRefetching: false, error: null })
    return { atom, known, fetch, release }
  } }
}
afterEach(() => { for (const name of ['react', 'react/jsx-runtime', 'react/jsx-dev-runtime', '@/lib/auth-client', 'next/navigation']) vi.doUnmock(name); vi.resetModules() })
describe('private page state ownership', () => {
  it('returns no authority when a private callback has no provider', async () => {
    vi.resetModules()
    vi.doMock('react', async original => ({ ...await original<typeof import('react')>(),
      useContext: (context: { _currentValue: unknown }) => context._currentValue,
    }))
    const { useAccountContentScope } = await import('@/contexts/AccountContentScope')
    expect(useAccountContentScope()).toBeNull()
  })
  it('changes the subtree key for switch, signout and A-B-A so old drafts and key data cannot return', async () => {
    const h = await harness(); const a = h.render().key
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null }); const b = h.render().key
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); const again = h.render().key
    h.session({ data: null, isPending: false, error: null }); const anonymous = h.render().key
    expect(new Set([a, b, again, anonymous]).size).toBe(4)
  })
  it.each([401, 503])('uses installed Better Auth%s authority to reset or preserve the private subtree synchronously', async status => {
    const h = await harness(); const actual = await h.useActualAtom(); const key = h.render().key
    const completion = actual.atom.value.refetch(); await Promise.resolve()
    expect(actual.atom.value.data).toBe(actual.known); expect(actual.atom.value.isPending).toBe(false)
    expect(actual.atom.value.isRefetching).toBe(true); expect(h.render().key).toBe(key)
    actual.release({ data: null, error: { status, message: `Synthetic ${status}` } }); await completion
    const after = h.render().key
    if (status === 503) expect(after).toBe(key)
    else {
      expect(after).not.toBe(key); actual.fetch.mockResolvedValueOnce({ data: structuredClone(actual.known), error: null })
      await actual.atom.value.refetch(); const renewed = h.render().key
      expect(renewed).not.toBe(key); expect(renewed).not.toBe(after)
    }
  })
  it('rejects a stale session paired with authoritative numeric 401', async () => {
    const h = await harness(); const key = h.render().key
    h.session({ data: { user: { id: 'a' } }, isPending: false, isRefetching: false, error: { status: 401 } })
    expect(h.render().key).not.toBe(key)
  })
  it('fences retained callbacks before effect cleanup across owner401 and route ABA while keeping route Fragment identity stable', async () => {
    const h = await harness(); const first = h.render(); h.mount()
    expect(first.authority.isCurrent()).toBe(true); expect(first.authority.canAdmit()).toBe(true)
    expect(h.render().authority).toBe(first.authority)
    h.path('/workspace/doc-B/edit'); const other = h.render()
    expect(other.key).toBe(first.key); expect(first.authority.isCurrent()).toBe(false)
    h.path('/workspace/doc-A/edit'); const again = h.render()
    expect(again.key).toBe(first.key); expect(first.authority.isCurrent()).toBe(false); expect(other.authority.isCurrent()).toBe(false)
    h.session({ data: null, isPending: false, isRefetching: false, error: { status: 401 } }); h.render()
    expect(again.authority.isCurrent()).toBe(false); expect(again.authority.canAdmit()).toBe(false)
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); const fresh = h.render()
    expect(fresh.authority.canAdmit()).toBe(true); expect(again.authority.isCurrent()).toBe(false)
    h.unmount(); expect(fresh.authority.isCurrent()).toBe(false)
    h.remount(); expect(h.render().authority).toBe(fresh.authority); expect(fresh.authority.canAdmit()).toBe(true)
  })
  it('preserves recovery identity through refetch/503 while retiring old admission leases permanently', async () => {
    const h = await harness(); const first = h.render(); const session = { user: { id: 'a' } }
    h.session({ data: session, isPending: false, isRefetching: true, error: null }); const refresh = h.render()
    expect(refresh.authority).not.toBe(first.authority); expect(refresh.authority.recoveryIdentity).toBe(first.authority.recoveryIdentity); expect(first.authority.isCurrent()).toBe(true); expect(first.authority.canAdmit()).toBe(false)
    h.session({ data: session, isPending: false, isRefetching: false, error: { status: 503 } }); h.render()
    expect(first.authority.isCurrent()).toBe(true); expect(first.authority.canAdmit()).toBe(false)
    h.session({ data: session, isPending: false, isRefetching: false, error: null }); const settled = h.render()
    expect(settled.authority.recoveryIdentity).toBe(first.authority.recoveryIdentity)
    expect(first.authority.canAdmit()).toBe(false); expect(refresh.authority.canAdmit()).toBe(false)
    expect(settled.authority.canAdmit()).toBe(true)
  })
  it('retires the installed stable-session refetch lease even when the child skips its uncertain render', async () => {
    const h = await harness(), actual = await h.useActualAtom(), first = h.render()
    const completion = actual.atom.value.refetch(); await Promise.resolve()
    expect(actual.atom.value.data).toBe(actual.known); expect(actual.atom.value.isPending).toBe(false)
    const refresh = h.render(); expect(first.authority.canAdmit()).toBe(false)
    actual.release({ data: structuredClone(actual.known), error: null }); await completion
    expect(actual.atom.value.data).toBe(actual.known)
    const settled = h.render()
    expect(settled.key).toBe(first.key); expect(settled.authority.recoveryIdentity).toBe(first.authority.recoveryIdentity)
    expect(first.authority.isCurrent()).toBe(true); expect(refresh.authority.isCurrent()).toBe(true)
    expect(first.authority.canAdmit()).toBe(false); expect(refresh.authority.canAdmit()).toBe(false)
    expect(settled.authority.canAdmit()).toBe(true); expect(h.render().authority).toBe(settled.authority)
  })
  it.each(['pending', 'refetch', 'error', 'snapshot'] as const)('never revives old %s admission after A→B→A while keeping recovery', async change => {
    const h = await harness(), original = { user: { id: 'a' } }
    h.session({ data: original, isPending: false, isRefetching: false, error: null }); const first = h.render()
    h.session({ data: change === 'snapshot' ? { user: { id: 'a' } } : original,
      isPending: change === 'pending', isRefetching: change === 'refetch', error: change === 'error' ? { status: 503 } : null })
    const uncertain = h.render()
    h.session({ data: original, isPending: false, isRefetching: false, error: null }); const settled = h.render()
    expect(first.authority.canAdmit()).toBe(false); expect(uncertain.authority.canAdmit()).toBe(false)
    expect(first.authority.isAdmissionCurrent()).toBe(false); expect(uncertain.authority.isAdmissionCurrent()).toBe(false)
    expect(settled.authority.isAdmissionCurrent()).toBe(true)
    expect(settled.authority.canAdmit()).toBe(true)
    expect(settled.authority.recoveryIdentity).toBe(first.authority.recoveryIdentity); expect(first.authority.isCurrent()).toBe(true)
  })
  it('distinguishes a current unready cold offline lease from an older retired uncertain lease', async () => {
    const h = await harness()
    h.session({ data: null, isPending: false, isRefetching: false, error: { status: 503 } })
    const first = h.render()
    expect(first.authority.isCurrent()).toBe(true); expect(first.authority.isAdmissionCurrent()).toBe(true)
    expect(first.authority.canAdmit()).toBe(false)
    h.session({ data: null, isPending: false, isRefetching: false, error: new Error('offline') })
    const next = h.render()
    expect(next.authority.recoveryIdentity).toBe(first.authority.recoveryIdentity)
    expect(first.authority.isCurrent()).toBe(true); expect(first.authority.isAdmissionCurrent()).toBe(false)
    expect(next.authority.isAdmissionCurrent()).toBe(true); expect(next.authority.canAdmit()).toBe(false)
  })
  it('preserves mounted offline draft state during unresolved or failed same-account session reads', async () => {
    const h = await harness(); const key = h.render().key
    h.session({ data: null, isPending: true, error: null }); expect(h.render().key).toBe(key)
    h.session({ data: null, isPending: false, error: new Error('offline') }); expect(h.render().key).toBe(key)
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); expect(h.render().key).toBe(key)
  })
})
