import { afterEach, describe, expect, it, vi } from 'vitest'
import { canChangeShare } from '@/lib/share-capability-policy'

type Element = { ref?: unknown; type: unknown; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}

async function recoveryHarness() {
  vi.resetModules()
  let index = 0
  const values: unknown[] = []
  let effects: Array<() => void | (() => void)> = []
  let owner = 'owner-a'
  let allowed = true
  let pathname = '/workspace/builder/resume-a'
  const register = vi.fn()
  const downloadBlob = vi.fn()
  vi.doMock('react', () => ({
    createContext: () => ({ Provider: 'Provider', value: register }),
    useContext: (context: { value: unknown }) => context.value,
    useRef: (initial: unknown) => { const slot = index++; if (!(slot in values)) values[slot] = { current: initial }; return values[slot] },
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
    useState: (initial: unknown) => { const slot = index++; if (!(slot in values)) values[slot] = initial; return [values[slot], (next: unknown) => { values[slot] = next }] },
  }))
  const jsx = (type: unknown, props: unknown) => ({ type, props })
  vi.doMock('react/jsx-runtime', () => ({ jsx, jsxs: jsx, Fragment: 'Fragment' }))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  vi.doMock('next/navigation', () => ({ usePathname: () => pathname }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ data: { user: { id: owner } } }) }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: () => allowed }) }))
  vi.doMock('@/components/CapabilityGate', () => ({ default: 'CapabilityGate' }))
  vi.doMock('@/lib/download', () => ({ downloadBlob }))
  const { default: Boundary } = await import('@/components/CapabilityRouteBoundary')
  const { useCapabilityDraftRecovery: registerDraft } = await import('@/contexts/CapabilityRecoveryContext')
  const children = { type: 'Builder', props: { title: 'unsaved draft' } }
  return {
    register, downloadBlob, children,
    setAllowed: (next: boolean) => { allowed = next },
    setOwner: (next: string) => { owner = next },
    setPath: (next: string) => { pathname = next },
    effects: () => effects,
    render: () => { index = 0; effects = []; return Boundary({ children: children as never }) as unknown as Element },
    draft: (data: unknown) => { index = 0; effects = []; registerDraft(owner, 'draft.json', true, data) },
  }
}

afterEach(() => {
  for (const name of ['react', 'react/jsx-runtime', 'next/link', 'next/navigation', '@/lib/auth-client', '@/contexts/EntitlementsContext', '@/components/CapabilityGate', '@/lib/download']) vi.doUnmock(name)
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('safe capability downgrade', () => {
  it('retains the mounted builder during refresh denial and offers an explicit local draft download', async () => {
    const h = await recoveryHarness()
    const first = h.render()
    const content = elements(first).find((node) => node.props.children === h.children)!
    expect(content.props.hidden).toBe(false)
    const draft = { ownerId: 'owner-a', pathname: '/workspace/builder/resume-a', filename: 'draft.json', dirty: true, read: () => '{"title":"current unsaved title"}' }
    ;(first.props.value as (value: unknown) => void)(draft)
    h.setAllowed(false)
    const denied = h.render()
    expect(elements(denied).filter((node) => node.type === 'h1').map((node) => node.props.children)).toEqual(['Feature unavailable'])
    const retained = elements(denied).find((node) => node.props.children === h.children)!
    expect(retained.type).toBe(content.type)
    expect(retained.props.hidden).toBe(true)
    const domNode = { inert: false }
    ;(retained.ref as (node: unknown) => void)(domNode)
    expect(domNode.inert).toBe(true)
    const download = elements(denied).find((node) => node.type === 'button')!
    ;(download.props.onClick as () => void)()
    expect(h.downloadBlob).toHaveBeenCalledOnce()
    expect(await (h.downloadBlob.mock.calls[0][0] as Blob).text()).toContain('current unsaved title')
    h.setAllowed(true)
    expect(elements(h.render()).find((node) => node.props.children === h.children)?.props.hidden).toBe(false)
  })

  it('warns before leaving dirty recovery and never leaks another owner or document draft', async () => {
    const h = await recoveryHarness()
    const first = h.render()
    ;(first.props.value as (value: unknown) => void)({ ownerId: 'owner-a', pathname: '/workspace/builder/resume-a', filename: 'draft.json', dirty: true, read: () => '{}' })
    h.setAllowed(false)
    const confirm = vi.fn(() => false)
    vi.stubGlobal('window', { confirm })
    const link = elements(h.render()).find((node) => node.type === 'Link')!
    const preventDefault = vi.fn()
    ;(link.props.onClick as (event: unknown) => void)({ preventDefault })
    expect(confirm).toHaveBeenCalledOnce()
    expect(preventDefault).toHaveBeenCalledOnce()
    h.setPath('/workspace/builder/resume-b')
    expect(elements(h.render()).some((node) => node.type === 'button')).toBe(false)
    h.setPath('/workspace/builder/resume-a'); h.setOwner('owner-b')
    const changed = elements(h.render())
    expect(changed.some((node) => node.type === 'button' || node.props.children === h.children)).toBe(false)
  })

  it('serializes the latest explicit draft state without collecting DOM fields', async () => {
    const h = await recoveryHarness()
    h.draft({ title: 'before' }); h.effects()[0]()
    const draft = h.register.mock.calls[0][0]
    h.draft({ title: 'latest', structured_content: { summary: 'unsaved content' } })
    expect(JSON.parse(draft.read())).toEqual({ title: 'latest', structured_content: { summary: 'unsaved content' } })
    expect(draft).toMatchObject({ ownerId: 'owner-a', pathname: '/workspace/builder/resume-a', dirty: true })
  })

  it('requires sharing capabilities for creation, anonymization and review enable, without granting an unsupported update exemption', () => {
    const can = (enabled: string[]) => (key: string) => enabled.includes(key)
    expect(canChangeShare(can([]), false, false)).toBe(false)
    expect(canChangeShare(can(['f01']), false, false)).toBe(true)
    expect(canChangeShare(can(['f01']), true, false)).toBe(false)
    expect(canChangeShare(can(['f01', 'f02']), true, true)).toBe(false)
    expect(canChangeShare(can(['f01', 'f02', 'f03']), true, true)).toBe(true)
    expect(canChangeShare(can([]), true, false)).toBe(false)
    expect(canChangeShare(can(['f01', 'f02']), true, false)).toBe(true)
    expect(canChangeShare(can(['f01']), true, false, true)).toBe(false)
  })
})
