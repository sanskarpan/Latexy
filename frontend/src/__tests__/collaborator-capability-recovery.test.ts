import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type Element = { type: unknown; props: Record<string, unknown> }
type Slot<T> = { value: T; deps: unknown[] }
type Effect = { deps?: unknown[]; cleanup?: () => void }

function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}

function content(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(content).join(' ')
  return value && typeof value === 'object' && 'props' in value
    ? content((value as Element).props.children)
    : ''
}

function roleSelect(tree: unknown): Element {
  const selects = elements(tree).filter((node) => node.type === 'select')
  expect(selects.length, 'collaborator role selector').toBeGreaterThan(0)
  return selects[selects.length - 1]
}

async function settle() {
  for (let i = 0; i < 8; i += 1) await Promise.resolve()
}

async function harness(
  role: 'editor' | 'commenter' | 'viewer',
  initiallyAllowed: boolean,
  initiallyOwner = true,
  initiallyParentAllowed = true,
) {
  vi.resetModules()
  let f04 = initiallyAllowed
  let parentAllowed = initiallyParentAllowed
  let owner = initiallyOwner
  const createCan = (featureAllowed: boolean, ancestorAllowed: boolean) =>
    (key: string) => key === 'f04' && featureAllowed && ancestorAllowed
  let can = createCan(initiallyAllowed, initiallyParentAllowed)
  let stateIndex = 0
  let refIndex = 0
  let effectIndex = 0
  let callbackIndex = 0
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  const effects: Effect[] = []
  const callbacks: Array<Slot<unknown>> = []
  let pending: Array<() => void> = []
  const collaborator = {
    id: 'collaborator-row', resume_id: 'resume-id', user_id: 'collaborator-id',
    user_name: 'Collaborator', user_email: 'collaborator@example.test', role,
    invited_by: 'owner-id', joined_at: null, created_at: '2026-01-01T00:00:00Z',
  }
  const api = {
    listCollaborators: vi.fn().mockResolvedValue([collaborator]),
    inviteCollaborator: vi.fn().mockResolvedValue({ ...collaborator, role: 'editor' }),
    updateCollaboratorRole: vi.fn().mockImplementation(async (_resumeId: string, _userId: string, nextRole: string) => ({ ...collaborator, role: nextRole })),
    removeCollaborator: vi.fn().mockResolvedValue(undefined),
  }
  const toast = { success: vi.fn(), error: vi.fn() }
  vi.doMock('react', () => ({
    useState: (initial: unknown) => {
      const slot = stateIndex++
      if (!(slot in states)) states[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
      return [states[slot], (next: unknown) => { states[slot] = typeof next === 'function' ? (next as (old: unknown) => unknown)(states[slot]) : next }]
    },
    useRef: (initial: unknown) => { const slot = refIndex++; refs[slot] ??= { current: initial }; return refs[slot] },
    useCallback: (fn: unknown, deps: unknown[]) => {
      const slot = callbackIndex++
      const old = callbacks[slot]
      if (!old || old.deps.length !== deps.length || deps.some((value, i) => !Object.is(value, old.deps[i]))) {
        callbacks[slot] = { value: fn, deps: [...deps] }
      }
      return callbacks[slot].value
    },
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = effectIndex++
      const old = effects[slot]
      if (old && deps && old.deps && deps.length === old.deps.length && deps.every((value, i) => Object.is(value, old.deps![i]))) return
      pending.push(() => { old?.cleanup?.(); effects[slot] = { deps: deps ? [...deps] : undefined, cleanup: effect() || undefined } })
    },
  }))
  const jsx = (type: unknown, props: Record<string, unknown>) => ({ type, props })
  vi.doMock('react/jsx-runtime', () => ({ jsx, jsxs: jsx, Fragment: 'Fragment' }))
  vi.doMock('react/jsx-dev-runtime', () => ({ jsxDEV: jsx, Fragment: 'Fragment' }))
  vi.doMock('lucide-react', () => Object.fromEntries(['X', 'UserPlus', 'Users', 'Crown', 'Eye', 'MessageSquare', 'Trash2', 'Loader2', 'ChevronDown'].map((name) => [name, name])))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can }) }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('sonner', () => ({ toast }))
  const Component = (await import('@/components/CollaboratorPanel')).default
  const onClose = vi.fn()

  return {
    api,
    toast,
    render: () => {
      stateIndex = 0; refIndex = 0; effectIndex = 0; callbackIndex = 0
      return Component({ open: true, resumeId: 'resume-id', isOwner: owner, presenceUsers: [], onClose }) as unknown as Element
    },
    flush: async () => { const scheduled = pending; pending = []; scheduled.forEach((effect) => effect()); await settle() },
    setCapability: (enabled: boolean) => { f04 = enabled; can = createCan(f04, parentAllowed) },
    setParentGate: (enabled: boolean) => { parentAllowed = enabled; can = createCan(f04, parentAllowed) },
    setOwner: (enabled: boolean) => { owner = enabled },
  }
}

beforeEach(() => {
  vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn() })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.doUnmock('react')
  vi.doUnmock('react/jsx-runtime')
  vi.doUnmock('react/jsx-dev-runtime')
  vi.doUnmock('lucide-react')
  vi.doUnmock('@/contexts/EntitlementsContext')
  vi.doUnmock('@/lib/api-client')
  vi.doUnmock('sonner')
  vi.resetModules()
})

describe('collaborator F04 downgrade recovery', () => {
  it('keeps role reductions available while F04 is off and blocks role upgrades', async () => {
    const h = await harness('editor', false)
    h.render(); await h.flush()
    let tree = h.render()
    expect(content(tree)).toContain('1 collaborator')
    expect(content(tree)).not.toContain('Invite by email')
    let selector = roleSelect(tree)
    expect(selector.props.disabled).toBe(false)
    const options = elements(selector).filter((node) => node.type === 'option')
    expect(options.find((node) => node.props.value === 'commenter')?.props.disabled).toBe(false)
    expect(options.find((node) => node.props.value === 'viewer')?.props.disabled).toBe(false)

    await (selector.props.onChange as (event: unknown) => Promise<void>)({ target: { value: 'commenter' } })
    expect(h.api.updateCollaboratorRole).toHaveBeenLastCalledWith('resume-id', 'collaborator-id', 'commenter')
    selector = roleSelect(h.render())
    const editorOption = elements(selector).find((node) => node.type === 'option' && node.props.value === 'editor')
    expect(editorOption?.props.disabled).toBe(true)
    await (selector.props.onChange as (event: unknown) => Promise<void>)({ target: { value: 'editor' } })
    expect(h.api.updateCollaboratorRole).toHaveBeenCalledTimes(1)
    await (selector.props.onChange as (event: unknown) => Promise<void>)({ target: { value: 'viewer' } })
    expect(h.api.updateCollaboratorRole).toHaveBeenLastCalledWith('resume-id', 'collaborator-id', 'viewer')
    expect(h.api.updateCollaboratorRole).toHaveBeenCalledTimes(2)
  })

  it('blocks viewer-to-commenter and captured upgrade handlers after F04 is revoked', async () => {
    const h = await harness('viewer', true)
    h.render(); await h.flush()
    const oldSelect = roleSelect(h.render())
    const staleUpgrade = oldSelect.props.onChange as (event: unknown) => Promise<void>
    h.setCapability(false)
    const currentSelect = roleSelect(h.render())
    expect(currentSelect.props.disabled).toBe(true)
    await staleUpgrade({ target: { value: 'commenter' } })
    await (currentSelect.props.onChange as (event: unknown) => Promise<void>)({ target: { value: 'commenter' } })
    expect(h.api.updateCollaboratorRole).not.toHaveBeenCalled()
  })

  it('keeps lower-role recovery available when the collaboration parent gate is off', async () => {
    const h = await harness('commenter', true)
    h.render(); await h.flush()
    h.setParentGate(false)
    const tree = h.render()
    expect(content(tree)).not.toContain('Invite by email')
    const selector = roleSelect(tree)
    expect(selector.props.disabled).toBe(false)
    const viewerOption = elements(selector).find((node) => node.type === 'option' && node.props.value === 'viewer')
    const editorOption = elements(selector).find((node) => node.type === 'option' && node.props.value === 'editor')
    expect(viewerOption?.props.disabled).toBe(false)
    expect(editorOption?.props.disabled).toBe(true)
    await (selector.props.onChange as (event: unknown) => Promise<void>)({ target: { value: 'viewer' } })
    expect(h.api.updateCollaboratorRole).toHaveBeenCalledExactlyOnceWith('resume-id', 'collaborator-id', 'viewer')
  })

  it('blocks stale invite callbacks after F04 is revoked', async () => {
    const h = await harness('editor', true)
    const enabledTree = h.render()
    await h.flush()
    const form = elements(enabledTree).find((node) => node.type === 'form')
    expect(form).toBeDefined()
    const staleInvite = form!.props.onSubmit as (event: { preventDefault: () => void }) => Promise<void>
    h.setCapability(false)
    h.render()
    await staleInvite({ preventDefault: vi.fn() })
    expect(h.api.inviteCollaborator).not.toHaveBeenCalled()
  })

  it('blocks stale role callbacks when the owner-only parent gate changes', async () => {
    const h = await harness('editor', false)
    h.render(); await h.flush()
    const oldSelect = roleSelect(h.render())
    const staleDowngrade = oldSelect.props.onChange as (event: unknown) => Promise<void>
    h.setOwner(false)
    const nonOwnerTree = h.render()
    expect(content(nonOwnerTree)).not.toContain('1 collaborator')
    await staleDowngrade({ target: { value: 'viewer' } })
    expect(h.api.updateCollaboratorRole).not.toHaveBeenCalled()
  })
})
