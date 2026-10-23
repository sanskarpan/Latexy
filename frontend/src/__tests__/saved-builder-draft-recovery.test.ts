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
  let slots: unknown[] = []
  let index = 0
  let effects: Array<() => void> = []
  let previousKey: string | undefined
  const register = vi.fn()
  const downloadBlob = vi.fn()
  const updateBuilderResume = vi.fn()
  const previewPdf = vi.fn()
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
    useMemo: (read: () => unknown) => { index++; return read() },
    useCallback: (callback: unknown) => { index++; return callback },
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
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session: { user: { id: ownerId }, session: { token: 'must-not-serialize' } }, isPending: false, error: null }) }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: (feature: string) => feature !== 'c01' || editAllowed }) }))
  vi.doMock('@/components/builder/BuilderCapabilityGate', () => ({ default: 'BuilderGate', useBuilderCapability: () => ({ ensureCompatible: async () => {}, isCompatible: () => true, available: true }) }))
  for (const name of ['@/components/builder/BuilderPreview', '@/components/ElementVersionHistoryPanel', '@/components/ExportDropdown', '@/components/SessionLoadError']) {
    vi.doMock(name, () => ({ default: 'Stub' }))
  }
  vi.doMock('@/hooks/useBuilderPdf', () => ({ useBuilderPdf: () => ({ previewPdf, downloadPdf: vi.fn(), clearPreview: vi.fn() }) }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { getBuilderResume, getBuilderTemplates, updateBuilderResume } }))
  vi.doMock('@/lib/download', () => ({ downloadBlob }))
  vi.stubGlobal('window', { setTimeout: vi.fn(() => 1), clearTimeout: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() })
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
  return {
    register, downloadBlob, updateBuilderResume, previewPdf, getBuilderResume, render, load, field, cleanup,
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
