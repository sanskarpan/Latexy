import { afterEach, describe, expect, it, vi } from 'vitest'

async function harness() {
  vi.resetModules()
  let session: { data: { user: { id: string } } | null; isPending: boolean; error: unknown } = { data: { user: { id: 'a' } }, isPending: false, error: null }
  let ref: { current: unknown } | undefined
  vi.doMock('react', () => ({ Fragment: 'Fragment', useRef: (initial: unknown) => { ref ??= { current: initial }; return ref } }))
  vi.doMock('react/jsx-runtime', () => ({ jsx: (type: unknown, props: unknown, key: unknown) => ({ type, props, key }) }))
  vi.doMock('react/jsx-dev-runtime', () => ({ jsxDEV: (type: unknown, props: unknown, key: unknown) => ({ type, props, key }) }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => session }))
  const Boundary = (await import('@/components/AccountContentBoundary')).default
  return { render: () => Boundary({ children: null }), session: (next: typeof session) => { session = next } }
}
afterEach(() => { for (const name of ['react', 'react/jsx-runtime', 'react/jsx-dev-runtime', '@/lib/auth-client']) vi.doUnmock(name); vi.resetModules() })
describe('private page state ownership', () => {
  it('changes the subtree key for switch, signout and A-B-A so old drafts and key data cannot return', async () => {
    const h = await harness(); const a = h.render().key
    h.session({ data: { user: { id: 'b' } }, isPending: false, error: null }); const b = h.render().key
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); const again = h.render().key
    h.session({ data: null, isPending: false, error: null }); const anonymous = h.render().key
    expect(new Set([a, b, again, anonymous]).size).toBe(4)
  })
  it('preserves mounted offline draft state during unresolved or failed same-account session reads', async () => {
    const h = await harness(); const key = h.render().key
    h.session({ data: null, isPending: true, error: null }); expect(h.render().key).toBe(key)
    h.session({ data: null, isPending: false, error: new Error('offline') }); expect(h.render().key).toBe(key)
    h.session({ data: { user: { id: 'a' } }, isPending: false, error: null }); expect(h.render().key).toBe(key)
  })
})
