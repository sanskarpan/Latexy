import { afterEach, describe, expect, it, vi } from 'vitest'

type Element = { type: unknown; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}
function text(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(text).join(' ')
  return value && typeof value === 'object' && 'props' in value ? text((value as Element).props.children) : ''
}
function button(tree: unknown, label: string) {
  const result = elements(tree).find((node) => node.type === 'button' && text(node).includes(label))
  expect(result, label).toBeDefined()
  return result!
}
async function harness(kind: 'share' | 'byok' | 'developer', existingShare = false) {
  vi.resetModules()
  let index = 0
  const state: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  let refIndex = 0
  const api = { createShareLink: vi.fn(), revokeShareLink: vi.fn().mockResolvedValue(undefined), createDeveloperKey: vi.fn() }
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  vi.doMock('react', async (importOriginal) => {
    const actual = await importOriginal<typeof import('react')>()
    return {
      ...actual,
      useEffect: () => {}, useCallback: (callback: unknown) => callback, useMemo: (factory: () => unknown) => factory(),
      useRef: (initial: unknown) => { const slot = refIndex++; refs[slot] ??= { current: initial }; return refs[slot] },
      useState: (initial: unknown) => {
        const slot = index++
        if (!(slot in state)) {
          state[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
          if (kind === 'byok' && [2, 3].includes(slot)) state[slot] = false
          if (kind === 'byok' && slot === 1) state[slot] = { mock: ['mock-model'] }
          if (kind === 'byok' && slot === 6) state[slot] = true // Open before revocation.
          if (kind === 'byok' && slot === 7) state[slot] = { provider: 'mock', api_key: 'placeholder', key_name: 'test' }
          if (kind === 'developer' && slot === 0) state[slot] = false
          if (kind === 'developer' && slot === 4) state[slot] = 'test key'
        }
        return [state[slot], (next: unknown) => { state[slot] = typeof next === 'function' ? (next as (previous: unknown) => unknown)(state[slot]) : next }]
      },
    }
  })
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: () => false }) }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session: { user: { id: 'owner' }, session: { token: 'mock-session' } }, isPending: false, error: null }) }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
  const Component = kind === 'share' ? (await import('@/components/ShareResumeModal')).default
    : kind === 'byok' ? (await import('@/components/byok/APIKeyManager')).default
      : (await import('@/app/developer/page')).default
  return {
    api, fetch,
    render: () => {
      index = 0; refIndex = 0
      return (Component as (props: unknown) => unknown)({ ownerId: 'owner', resumeId: 'resume', resumeTitle: 'test', onClose: () => {}, ...(existingShare ? { initialShareToken: 'token', initialShareUrl: 'https://example.test/r/token' } : {}) })
    },
  }
}
afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/hooks/useRequireAuth', '@/lib/api-client', 'sonner']) vi.doUnmock(name)
  vi.unstubAllGlobals(); vi.resetModules()
})

describe('denied new-action buttons keep management available', () => {
  it('blocks share generation in both button and handler, while existing links can still be revoked', async () => {
    const fresh = await harness('share')
    const generate = button(fresh.render(), 'Generate shareable link')
    expect(generate.props.disabled).toBe(true)
    expect(generate.props['aria-description']).toContain('Unavailable')
    await (generate.props.onClick as () => Promise<void>)()
    expect(fresh.api.createShareLink).not.toHaveBeenCalled()
    const existing = await harness('share', true)
    const revoke = button(existing.render(), 'Revoke link')
    expect(revoke.props.disabled).not.toBe(true)
    ;(revoke.props.onClick as () => void)()
    const confirm = button(existing.render(), 'Revoke permanently')
    expect(confirm.props.disabled).toBe(false)
    await (confirm.props.onClick as () => Promise<void>)()
    expect(existing.api.revokeShareLink).toHaveBeenCalledWith('resume')
  })
  it('blocks a BYOK save even if a form was already open before revocation', async () => {
    const h = await harness('byok')
    const save = elements(h.render()).find((node) => node.type === 'button' && (node.props.onClick as { name?: string })?.name === 'addAPIKey')!
    expect(save.props.disabled).toBe(true)
    expect(save.props['aria-description']).toContain('Unavailable')
    await (save.props.onClick as () => Promise<void>)()
    expect(h.fetch).not.toHaveBeenCalled()
  })
  it('blocks developer key creation in the button and handler', async () => {
    const h = await harness('developer')
    const create = elements(h.render()).find((node) => node.type === 'button' && (node.props.onClick as { name?: string })?.name === 'handleCreateKey')!
    expect(create.props.disabled).toBe(true)
    expect(create.props['aria-description']).toContain('Unavailable')
    await (create.props.onClick as () => Promise<void>)()
    expect(h.api.createDeveloperKey).not.toHaveBeenCalled()
  })
})
