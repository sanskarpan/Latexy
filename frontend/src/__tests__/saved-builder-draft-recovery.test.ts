import { afterEach, describe, expect, it, vi } from 'vitest'

type Element = { type: unknown; key?: string; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}

const mockedModules = [
  'react', 'react/jsx-runtime', 'next/link', 'next/dynamic', 'next/navigation', 'sonner',
  '@/components/builder/BuilderCapabilityGate', '@/components/builder/BuilderPreview',
  '@/components/ElementVersionHistoryPanel', '@/components/ExportDropdown', '@/components/SessionLoadError',
  '@/hooks/useRequireAuth', '@/hooks/useBuilderPdf', '@/contexts/EntitlementsContext', '@/lib/api-client', '@/lib/download',
]

async function harness() {
  vi.resetModules()
  let ownerId = 'owner-a'
  let resumeId = 'resume-a'
  let editAllowed = true
  let builderAllowed = true
  let authUnverified = false
  let compatible = true
  let slots: unknown[] = []
  let index = 0
  let effects: Array<() => void> = []
  let previousKey: string | undefined
  const register = vi.fn()
  const downloadBlob = vi.fn()
  const updateBuilderResume = vi.fn(async (id: string, patch: { title: string; template_id: string; structured_content: unknown; expected_structured_version: number }) => ({
    resume: { id, user_id: ownerId, title: patch.title, selected_template_id: patch.template_id,
      structured_content: patch.structured_content, structured_version: patch.expected_structured_version + 1,
      latex_content: 'updated source', builder_status: 'active' },
    template_family: 'ats',
  }))
  const previewPdf = vi.fn()
  let prepareResume!: () => Promise<unknown>
  const structured = {
    basics: { name: 'Saved name', label: '', email: '', phone: '', location: '', website: '', linkedin: '', github: '', summary: 'Saved summary' },
    experience: [], education: [], projects: [], skills: [], certifications: [], awards: [], languages: [], interests: [],
    section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'], hidden_sections: [],
  }
  let responseOwner: string | null = null
  const getBuilderResume = vi.fn(async (id: string) => ({
    resume: { id, user_id: responseOwner ?? ownerId, title: `${ownerId}:${id}`, selected_template_id: 'template-a',
      structured_content: structured, structured_version: 1, latex_content: 'saved source', builder_status: 'active' },
    template_family: 'ats',
  }))
  const getBuilderTemplates = vi.fn(async () => [{ id: 'template-a', name: 'Template A' }, { id: 'template-b', name: 'Template B' }])
  const ensureCompatible = vi.fn(async () => { if (!compatible) throw new Error('Builder is incompatible') })
  const isCompatible = () => compatible
  const can = (feature: string) => feature === 'b08' ? builderAllowed : feature !== 'c01' || editAllowed
  let timerId = 0
  let now = 0
  const timers = new Map<number, { due: number; callback: () => void }>()
  const memo = (read: () => unknown, deps: unknown[]) => {
    const slot = index++
    const previous = slots[slot] as { deps: unknown[]; value: unknown } | undefined
    if (previous && deps.every((value, position) => value === previous.deps[position])) return previous.value
    const value = read()
    slots[slot] = { deps, value }
    return value
  }
  const cleanup = () => {
    for (const slot of slots) (slot as { cleanup?: () => void } | undefined)?.cleanup?.()
    slots = []
  }
  vi.doMock('react', () => ({
    createContext: () => ({ Provider: 'Provider', value: register }),
    useContext: (context: { value: unknown }) => context.value,
    useState: (initial: unknown) => {
      const slot = index++
      if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
      return [slots[slot], (next: unknown) => { slots[slot] = typeof next === 'function' ? (next as (old: unknown) => unknown)(slots[slot]) : next }]
    },
    useRef: (initial: unknown) => { const slot = index++; if (!(slot in slots)) slots[slot] = { current: initial }; return slots[slot] },
    useMemo: memo,
    useCallback: (callback: unknown, deps: unknown[]) => memo(() => callback, deps),
    useEffect: (effect: () => void | (() => void), deps: unknown[]) => {
      const slot = index++
      const previous = slots[slot] as { deps: unknown[]; cleanup?: () => void } | undefined
      if (previous && deps.every((value, position) => value === previous.deps[position])) return
      effects.push(() => {
        previous?.cleanup?.()
        slots[slot] = { deps, cleanup: effect() }
      })
    },
  }))
  const jsx = (type: unknown, props: Record<string, unknown>, key?: string) => ({ type, props, key })
  vi.doMock('react/jsx-runtime', () => ({ jsx, jsxs: jsx, Fragment: 'Fragment' }))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  vi.doMock('next/dynamic', () => ({ default: () => 'PDFPreview' }))
  vi.doMock('next/navigation', () => ({ useParams: () => ({ resumeId }), usePathname: () => `/workspace/builder/${resumeId}` }))
  vi.doMock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session: { user: { id: ownerId }, session: { token: 'must-not-serialize' } }, isPending: authUnverified, error: null }) }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can }) }))
  vi.doMock('@/components/builder/BuilderCapabilityGate', () => ({ default: 'BuilderGate', useBuilderCapability: () => ({ ensureCompatible, isCompatible, available: compatible }) }))
  for (const name of ['@/components/builder/BuilderPreview', '@/components/ElementVersionHistoryPanel', '@/components/ExportDropdown', '@/components/SessionLoadError']) {
    vi.doMock(name, () => ({ default: 'Stub' }))
  }
  vi.doMock('@/hooks/useBuilderPdf', () => ({ useBuilderPdf: (options: { prepareResume: () => Promise<unknown> }) => {
    prepareResume = options.prepareResume
    return { previewPdf, downloadPdf: vi.fn(), clearPreview: vi.fn() }
  } }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { getBuilderResume, getBuilderTemplates, updateBuilderResume } }))
  vi.doMock('@/lib/download', () => ({ downloadBlob }))
  vi.stubGlobal('window', {
    setTimeout: vi.fn((callback: () => void, delay: number) => { const id = ++timerId; timers.set(id, { due: now + delay, callback }); return id }),
    clearTimeout: vi.fn((id: number) => timers.delete(id)), addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })
  const { default: Page } = await import('@/app/workspace/builder/[resumeId]/page')
  const render = () => {
    const page = Page() as unknown as Element
    if (previousKey !== page.key) { cleanup(); previousKey = page.key }
    const form = page.props.children as Element
    index = 0
    effects = []
    const tree = (form.type as (props: unknown) => Element)(form.props)
    for (const effect of effects) effect()
    return tree
  }
  const load = async () => { render(); await new Promise(resolve => setImmediate(resolve)); return render() }
  const field = (tree: Element, id: string) => elements(tree).find(node => node.props.id === id)!
  const advanceAutosave = async (milliseconds = 600) => {
    now += milliseconds
    for (const [id, timer] of [...timers]) {
      if (timer.due > now) continue
      timers.delete(id)
      timer.callback()
    }
    await new Promise(resolve => setImmediate(resolve))
    return render()
  }
  const setPause = (kind: string, paused: boolean) => {
    if (kind === 'b08') builderAllowed = !paused
    else if (kind === 'c01') editAllowed = !paused
    else if (kind === 'auth') authUnverified = paused
    else if (kind === 'compatibility') compatible = !paused
    else throw new Error('Unknown pause scope')
  }
  return {
    register, downloadBlob, updateBuilderResume, previewPdf, getBuilderResume, render, load, field, cleanup,
    ensureCompatible, advanceAutosave, setPause,
    pendingTimers: () => timers.size,
    flushSave: () => prepareResume(),
    denyEditing: () => { editAllowed = false },
    setIdentity: (owner: string, document: string) => { ownerId = owner; resumeId = document },
    mismatchOwner: () => { responseOwner = 'other-owner' },
  }
}

afterEach(() => {
  for (const name of mockedModules) vi.doUnmock(name)
  vi.unstubAllGlobals()
  vi.resetModules()
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

type Harness = Awaited<ReturnType<typeof harness>>
function editTitle(h: Harness, tree: Element, title: string) {
  ;(h.field(tree, 'builder-resume-title').props.onChange as (event: unknown) => void)({ target: { value: title } })
  return h.render()
}

async function expectRecoverableDraft(h: Harness, tree: Element, title: string) {
  const draft = h.register.mock.lastCall?.[0]
  expect(draft).toMatchObject({ ownerId: 'owner-a', dirty: true })
  expect(elements(tree).some(node => node.type === 'h1' && node.props.children === title)).toBe(true)
  // The outer capability boundary uses this registered reader when B08 hides
  // the retained form. Exercise that real local recovery action for every pause.
  const { downloadCapabilityDraft } = await import('@/contexts/CapabilityRecoveryContext')
  downloadCapabilityDraft(draft)
  const [blob] = h.downloadBlob.mock.lastCall!
  const text = await (blob as Blob).text()
  expect(JSON.parse(text)).toMatchObject({ format: 'latexy-builder-draft', resume_id: 'resume-a', title })
  expect(text).not.toContain('must-not-serialize')
}

describe('actual saved builder autosave admission and recovery', () => {
  it.each(['b08', 'c01', 'auth', 'compatibility'])('cancels a pending autosave during settled %s denial and rearms the retained revision', async kind => {
    const h = await harness()
    let tree = editTitle(h, await h.load(), 'Retained pending edit')
    expect(h.pendingTimers()).toBe(1)
    h.setPause(kind, true)
    tree = h.render()
    expect(h.pendingTimers()).toBe(0)
    await h.advanceAutosave(2_000)
    expect(h.updateBuilderResume).not.toHaveBeenCalled()
    await expectRecoverableDraft(h, tree, 'Retained pending edit')
    h.setPause(kind, false)
    h.render()
    expect(h.pendingTimers()).toBe(1)
    await h.advanceAutosave()
    expect(h.updateBuilderResume).toHaveBeenCalledExactlyOnceWith('resume-a', expect.objectContaining({
      title: 'Retained pending edit', expected_structured_version: 1,
    }))
    await h.advanceAutosave(2_000)
    expect(h.updateBuilderResume).toHaveBeenCalledOnce()
    expect(h.register.mock.lastCall?.[0]).toMatchObject({ dirty: false })
    h.cleanup()
  })

  it.each(['b08', 'c01', 'auth', 'compatibility'])('rechecks %s after an awaited compatibility check before admitting a PATCH', async kind => {
    const h = await harness()
    const check = deferred<void>()
    h.ensureCompatible.mockImplementationOnce(() => check.promise)
    editTitle(h, await h.load(), 'Retained awaited edit')
    await h.advanceAutosave()
    expect(h.ensureCompatible).toHaveBeenCalledOnce()
    expect(h.updateBuilderResume).not.toHaveBeenCalled()
    h.setPause(kind, true)
    let tree = h.render()
    check.resolve()
    await new Promise(resolve => setImmediate(resolve))
    tree = h.render()
    expect(h.updateBuilderResume).not.toHaveBeenCalled()
    await expectRecoverableDraft(h, tree, 'Retained awaited edit')
    h.setPause(kind, false)
    h.render()
    await h.advanceAutosave()
    expect(h.updateBuilderResume).toHaveBeenCalledExactlyOnceWith('resume-a', expect.objectContaining({
      title: 'Retained awaited edit', expected_structured_version: 1,
    }))
    h.cleanup()
  })

  it('settles an admitted write but pauses the queued newer revision until B08 is regranted', async () => {
    const h = await harness()
    const acceptedWrite = h.updateBuilderResume.getMockImplementation()!
    const flight = deferred<Awaited<ReturnType<typeof acceptedWrite>>>()
    h.updateBuilderResume.mockImplementationOnce(() => flight.promise)
    let tree = editTitle(h, await h.load(), 'Admitted revision')
    tree = await h.advanceAutosave()
    expect(h.updateBuilderResume).toHaveBeenCalledOnce()
    tree = editTitle(h, tree, 'Queued retained revision')
    h.setPause('b08', true)
    h.render()
    const [id, patch] = h.updateBuilderResume.mock.calls[0]
    flight.resolve(await acceptedWrite(id, patch))
    await new Promise(resolve => setImmediate(resolve))
    tree = h.render()
    await h.advanceAutosave(2_000)
    expect(h.updateBuilderResume).toHaveBeenCalledOnce()
    await expectRecoverableDraft(h, tree, 'Queued retained revision')
    h.setPause('b08', false)
    h.render()
    await h.advanceAutosave()
    expect(h.updateBuilderResume).toHaveBeenCalledTimes(2)
    expect(h.updateBuilderResume.mock.calls[1]).toEqual(['resume-a', expect.objectContaining({
      title: 'Queued retained revision', expected_structured_version: 2,
    })])
    await h.advanceAutosave(2_000)
    expect(h.updateBuilderResume).toHaveBeenCalledTimes(2)
    h.cleanup()
  })

  it('keeps clean read-only preparation available without a new PATCH', async () => {
    const h = await harness()
    await h.load()
    h.setPause('b08', true)
    h.setPause('c01', true)
    h.render()
    await expect(h.flushSave()).resolves.toMatchObject({ resume: { id: 'resume-a', title: 'owner-a:resume-a' } })
    expect(h.ensureCompatible).toHaveBeenCalledOnce()
    expect(h.updateBuilderResume).not.toHaveBeenCalled()
    h.cleanup()
  })

  it('preserves a conflicted recovery draft without automatically retrying on regrant', async () => {
    const h = await harness()
    h.updateBuilderResume.mockRejectedValueOnce(new Error('409 newer saved copy'))
    editTitle(h, await h.load(), 'Conflicted retained edit')
    let tree = await h.advanceAutosave()
    h.setPause('b08', true)
    tree = h.render()
    await expectRecoverableDraft(h, tree, 'Conflicted retained edit')
    h.setPause('b08', false)
    h.render()
    await h.advanceAutosave(2_000)
    expect(h.updateBuilderResume).toHaveBeenCalledOnce()
    expect(h.register.mock.lastCall?.[0]).toMatchObject({ dirty: true })
    h.cleanup()
  })

  it('does not admit an old compatibility continuation after an owner ABA transition', async () => {
    const h = await harness()
    const check = deferred<void>()
    h.ensureCompatible.mockImplementationOnce(() => check.promise)
    editTitle(h, await h.load(), 'Old owner edit')
    await h.advanceAutosave()
    for (const owner of ['owner-b', 'owner-a']) {
      h.setIdentity(owner, 'resume-a')
      await h.load()
    }
    check.resolve()
    await new Promise(resolve => setImmediate(resolve))
    h.render()
    await h.advanceAutosave(2_000)
    expect(h.updateBuilderResume).not.toHaveBeenCalled()
    expect(h.register.mock.lastCall?.[0]).toMatchObject({ ownerId: 'owner-a', dirty: false })
    h.cleanup()
  })
})

describe('actual saved builder draft recovery wiring', () => {
  it('registers only a loaded owned document and downloads latest unsaved fields without writes or compilation', async () => {
    const h = await harness()
    h.render()
    expect(h.register.mock.calls.every(([draft]) => draft === null)).toBe(true)
    await new Promise(resolve => setImmediate(resolve))
    let tree = h.render()
    for (const [id, value] of [['builder-resume-title', ' Unsaved title '], ['builder-template-select', 'template-b'], ['builder-basics-summary', 'Unsaved summary']]) {
      ;(h.field(tree, id).props.onChange as (event: unknown) => void)({ target: { value } })
      tree = h.render()
    }
    h.denyEditing()
    tree = h.render()
    const draft = h.register.mock.calls[h.register.mock.calls.length - 1][0]
    expect(draft).toMatchObject({ ownerId: 'owner-a', pathname: '/workspace/builder/resume-a', dirty: true })
    const button = elements(tree).find(node => node.type === 'button' && node.props.children === 'Download current builder draft (.json)')!
    ;(button.props.onClick as () => void)()
    expect(h.downloadBlob).toHaveBeenCalledOnce()
    const [blob, filename] = h.downloadBlob.mock.calls[0]
    const text = await (blob as Blob).text()
    expect(JSON.parse(text)).toMatchObject({ format: 'latexy-builder-draft', version: 1, resume_id: 'resume-a', title: ' Unsaved title ', template_id: 'template-b', structured_content: { basics: { summary: 'Unsaved summary' } } })
    expect(Object.keys(JSON.parse(text)).sort()).toEqual(['format', 'resume_id', 'structured_content', 'template_id', 'title', 'version'])
    expect(filename).toBe('latexy-builder-resume-a-draft.json')
    expect(text).not.toContain('must-not-serialize')
    expect(h.updateBuilderResume).not.toHaveBeenCalled()
    expect(h.previewPdf).not.toHaveBeenCalled()
    h.cleanup()
  })

  it('invalidates retained readers and click callbacks on owner/document transitions including ABA', async () => {
    const h = await harness()
    await h.load()
    h.denyEditing()
    const tree = h.render()
    const oldDraft = h.register.mock.calls[h.register.mock.calls.length - 1][0]
    const oldClick = elements(tree).find(node => node.type === 'button' && node.props.children === 'Download current builder draft (.json)')!.props.onClick as () => void
    for (const [owner, document] of [['owner-a', 'resume-b'], ['owner-b', 'resume-a'], ['owner-a', 'resume-a']]) {
      h.setIdentity(owner, document)
      await h.load()
      expect(oldDraft.read()).toBeNull()
      oldClick()
      expect(h.downloadBlob).not.toHaveBeenCalled()
      const current = h.register.mock.calls[h.register.mock.calls.length - 1][0]
      expect(current.ownerId).toBe(owner)
      expect(JSON.parse(current.read()).resume_id).toBe(document)
    }
    h.cleanup()
  })

  it('never registers a response for a different owner as local recovery', async () => {
    const h = await harness()
    h.mismatchOwner()
    await h.load()
    expect(h.register.mock.calls.every(([draft]) => draft === null)).toBe(true)
    h.cleanup()
  })
})
