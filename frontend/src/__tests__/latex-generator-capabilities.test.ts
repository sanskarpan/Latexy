import { afterEach, describe, expect, it, vi } from 'vitest'

type Element = { type: unknown; props: Record<string, unknown> }
const leaves = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image'] as const
const all = ['ai_writing', 'd14', 'c01', ...leaves]
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  if (typeof node.type === 'function' && ['ModeButton', 'GenerateButton'].includes(node.type.name)) {
    return elements(node.type(node.props))
  }
  return [node, ...elements(node.props.children)]
}
function label(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(label).join('')
  return value && typeof value === 'object' && 'props' in value ? label((value as Element).props.children) : ''
}
function button(tree: unknown, name: string): Element {
  const node = elements(tree).find(item => item.type === 'button' && label(item).trim() === name)
  expect(node, name).toBeDefined()
  return node!
}
function textarea(tree: unknown): Element { return elements(tree).find(item => item.type === 'textarea')! }
const click = (node: Element) => (node.props.onClick as () => unknown)()
const change = (node: Element, value: string) => (node.props.onChange as (event: unknown) => void)({ target: { value } })
const settle = async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }
function deferred<T>() {
  let resolve!: (value: T) => void; let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

async function harness() {
  vi.resetModules()
  let index = 0; let grants = new Set<string>(all); let owner: string | null = 'A'; let pending = false; let refetching = false; let sessionError: Error | null = null
  let token: string | null = 'A-token'; let documentId = 'document-A'; let missingSession = false; let documentContext = 'style context'
  let authorityEpoch = 0; let admissionEpoch = 0; let recoveryIdentity = {}; let authorityProvided = true
  const authority = () => {
    const epoch = authorityEpoch; const admission = admissionEpoch
    const isCurrent = () => authorityProvided && epoch === authorityEpoch
    const isAdmissionCurrent = () => isCurrent() && admission === admissionEpoch
    return { recoveryIdentity, isCurrent, isAdmissionCurrent, canAdmit: () => isAdmissionCurrent() && Boolean(owner && !missingSession && !pending && !refetching && !sessionError) }
  }
  let accountScope = authority()
  const renewAdmission = () => { admissionEpoch += 1; accountScope = authority() }
  const renewAuthority = () => { authorityEpoch += 1; recoveryIdentity = {}; renewAdmission() }
  const slots: Array<{ value?: unknown; deps?: unknown[]; cleanup?: () => void }> = []
  const effects = new Map<number, () => void>()
  const same = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((item, i) => Object.is(item, b[i])))
  vi.doMock('react', async original => ({
    ...await original<typeof import('react')>(),
    useRef: (initial: unknown) => { const at = index++; slots[at] ??= { value: { current: initial } }; return slots[at].value },
    useState: (initial: unknown) => {
      const at = index++; slots[at] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [slots[at].value, (next: unknown) => { slots[at].value = typeof next === 'function' ? (next as (old: unknown) => unknown)(slots[at].value) : next }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => { const at = index++; if (!same(slots[at]?.deps, deps)) slots[at] = { value: callback, deps }; return slots[at].value },
    useEffect: (effect: () => void | (() => void), deps: unknown[]) => {
      const at = index++; const previous = slots[at]
      if (!same(previous?.deps, deps)) {
        slots[at] = { deps, cleanup: previous?.cleanup }
        effects.set(at, () => { slots[at].cleanup?.(); slots[at].cleanup = effect() || undefined })
      }
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
    const snapshot = grants
    return { can: (key: string) => snapshot.has(key) }
  } }))
  // Standalone tests supply an explicit boundary authority; production's
  // missing-provider default is null and must remain fail-closed.
  vi.doMock('@/contexts/AccountContentScope', () => ({ useAccountContentScope: () => authorityProvided ? accountScope : null }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ data: owner && !missingSession ? { user: { id: owner }, session: { token } } : null, isPending: pending, isRefetching: refetching, error: sessionError }) }))
  const result = { latex: '\\section{Admitted}', cached: false, rows: 2, columns: 2 }
  const api = { getAuthToken: () => token,
    generateLatex: vi.fn().mockResolvedValue(result), generateLatexTable: vi.fn().mockResolvedValue(result),
    generateLatexTableFromImage: vi.fn().mockResolvedValue(result), generateLatexMath: vi.fn().mockResolvedValue(result), generateLatexMathFromImage: vi.fn().mockResolvedValue(result) }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/components/LatexGeneratorPanel')).default
  const onInsert = vi.fn(); const onRecoveryChange = vi.fn(); const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  const render = (flush = true) => {
    index = 0
    const tree = Component({ documentId, documentContext, onInsert, onRecoveryChange })
    if (flush) { const queued = [...effects.values()]; effects.clear(); queued.forEach(effect => effect()) }
    return tree
  }
  render()
  return { api, onInsert, onRecoveryChange, writeText, result, render,
    allow: (next: string[]) => { grants = new Set(next) },
    owner: (next: string | null) => { if (owner !== next) renewAuthority(); owner = next; token = next ? `${next}-token` : null },
    session: (nextPending: boolean, error: Error | null = null, missing = false) => {
      const unauthorized = (value: Error | null) => value !== null && 'status' in value && value.status === 401
      if (unauthorized(error) !== unauthorized(sessionError)) renewAuthority()
      else if (pending !== nextPending || sessionError !== error || missingSession !== missing) renewAdmission()
      pending = nextPending; sessionError = error; missingSession = missing
    },
    refetch: (next: boolean) => { if (refetching !== next) renewAdmission(); refetching = next },
    authority: (provided: boolean) => { authorityProvided = provided },
    renewAuthority,
    document: (next: string) => { if (documentId !== next) renewAuthority(); documentId = next },
    context: (next: string) => { documentContext = next },
    token: (next: string | null) => { if (token !== next) renewAdmission(); token = next },
    unmount: () => slots.forEach(slot => slot.cleanup?.()) }
}
type Harness = Awaited<ReturnType<typeof harness>>
function configure(h: Harness, leaf: typeof leaves[number]) {
  const mode = leaf.includes('table') ? 'Table' : leaf.includes('math') ? 'Math' : 'Describe'
  click(button(h.render(), mode))
  const tree = h.render()
  if (leaf.endsWith('image')) {
    const upload = elements(tree).find(item => item.type === 'input' && item.props.type === 'file')!
    ;(upload.props.onChange as (event: unknown) => void)({ target: { value: 'file', files: [{ name: 'local.png', size: 50 }] } })
  } else change(textarea(tree), leaf === 'd14_latex' ? 'Create a heading' : leaf === 'd14_table_text' ? 'A,B\n1,2' : 'x squared')
  return h.render()
}
const action = (leaf: typeof leaves[number]) => leaf === 'd14_latex' ? 'Generate fragment' : leaf.includes('table') ? 'Generate table' : 'Generate math'
const apiMethod = (leaf: typeof leaves[number]) => ({ d14_latex: 'generateLatex', d14_table_text: 'generateLatexTable', d14_table_image: 'generateLatexTableFromImage', d14_math_text: 'generateLatexMath', d14_math_image: 'generateLatexMathFromImage' } as const)[leaf]
afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/contexts/AccountContentScope', '@/lib/auth-client', '@/lib/api-client']) vi.doUnmock(name)
  vi.unstubAllGlobals(); vi.resetModules()
})

describe('D14 exact branch admission and result recovery', () => {
  it('fails closed for a missing protected-content provider, including retained callbacks and recovery', async () => {
    const h = await harness(); const generate = button(configure(h, 'd14_latex'), 'Generate fragment')
    click(generate); await settle(); const tree = h.render()
    const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment')
    h.authority(false); const unavailable = h.render(false)
    expect(label(unavailable)).not.toContain(h.result.latex)
    expect(elements(unavailable).some(node => node.type === 'textarea')).toBe(false)
    click(generate); click(insert); await click(copy)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled()
    h.unmount()
  })
  it('denies old callbacks after outer-boundary ABA without any child rerender or passive cleanup', async () => {
    const h = await harness(); const generate = button(configure(h, 'd14_latex'), 'Generate fragment')
    click(generate); await settle(); const tree = h.render()
    const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment')
    const input = textarea(tree); const mode = button(tree, 'Math')
    h.renewAuthority(); h.renewAuthority()
    click(generate); click(insert); await click(copy); change(input, 'STALE INPUT'); click(mode)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled()
    expect(label(h.render(false))).not.toContain(h.result.latex)
    expect(label(h.render(false))).not.toContain('STALE INPUT'); h.unmount()
  })
  it('rejects late admitted completion after outer invalidation before a child rerender', async () => {
    const h = await harness(); const request = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(request.promise)
    const generate = button(configure(h, 'd14_latex'), 'Generate fragment'); click(generate)
    h.onRecoveryChange.mockClear(); h.renewAuthority(); request.resolve(h.result); await settle()
    expect(label(h.render(false))).not.toContain(h.result.latex)
    expect(h.onRecoveryChange.mock.calls.flat()).not.toContain(true); h.unmount()
  })
  it('retires old admission callbacks across a whole skipped-child refetch cycle while retaining owned recovery', async () => {
    const h = await harness(); const generate = button(configure(h, 'd14_latex'), 'Generate fragment')
    click(generate); await settle(); const tree = h.render()
    const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment')
    h.refetch(true); h.refetch(false) // The panel never rendered the transient state.
    click(generate); click(insert); await click(copy); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(h.writeText).toHaveBeenCalledExactlyOnceWith(h.result.latex)
    const current = h.render(false)
    expect(label(current)).toContain(h.result.latex); expect(textarea(current).props.value).toBe('Create a heading')
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    click(button(current, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledExactlyOnceWith(h.result.latex)
    click(button(current, 'Generate fragment again')); await settle(); expect(h.api.generateLatex).toHaveBeenCalledTimes(2)
    h.unmount()
  })
  it('keeps admitted recovery during authenticated refetch but treats numeric401 as confirmed invalidation', async () => {
    const h = await harness(); const generate = button(configure(h, 'd14_latex'), 'Generate fragment')
    click(generate); await settle(); const tree = h.render(); const insert = button(tree, 'Insert at cursor')
    h.refetch(true); const refreshing = h.render(false)
    expect(label(refreshing)).toContain(h.result.latex); click(generate); click(insert)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    await click(button(refreshing, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledOnce()
    h.refetch(false); h.session(false, Object.assign(new Error('Unauthorized'), { status: 401 }), true)
    expect(label(h.render(false))).not.toContain(h.result.latex)
    h.session(false); h.render(false); click(generate); click(insert)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled(); h.unmount()
  })
  it.each(leaves)('%s toggles only its exact branch, including a retained callback', async leaf => {
    const h = await harness(); const before = configure(h, leaf); const retained = button(before, action(leaf))
    h.allow(all.filter(key => key !== leaf))
    expect(elements(h.render()).some(node => node.type === 'button' && label(node).trim() === action(leaf))).toBe(false)
    click(retained); await settle()
    expect(h.api[apiMethod(leaf)]).not.toHaveBeenCalled()
    h.allow(all); const enabled = button(h.render(), action(leaf))
    expect(enabled.props.disabled).toBe(false)
    click(enabled); await settle()
    expect(h.api[apiMethod(leaf)]).toHaveBeenCalledOnce()
    for (const other of leaves.filter(key => key !== leaf)) expect(h.api[apiMethod(other)]).not.toHaveBeenCalled()
    h.unmount()
  })
  it.each(['d14', 'ai_writing', 'all missing'] as const)('fails closed when %s is unavailable', async denied => {
    const h = await harness(); const old = button(configure(h, 'd14_latex'), 'Generate fragment')
    h.allow(denied === 'all missing' ? [] : all.filter(key => key !== denied)); h.render()
    click(old); await settle(); expect(h.api.generateLatex).not.toHaveBeenCalled(); h.unmount()
  })
  it('uses current text/image input and mode even before the next render', async () => {
    const h = await harness(); let tree = configure(h, 'd14_table_text'); const old = button(tree, 'Generate table')
    const upload = elements(tree).find(item => item.type === 'input' && item.props.type === 'file')!
    ;(upload.props.onChange as (event: unknown) => void)({ target: { value: '', files: [{ name: 'new.png', size: 20 }] } })
    h.allow(all.filter(key => key !== 'd14_table_image')); h.render(); click(old); await settle()
    expect(h.api.generateLatexTable).not.toHaveBeenCalled(); expect(h.api.generateLatexTableFromImage).not.toHaveBeenCalled()
    h.allow(all); tree = h.render(); change(textarea(tree), 'Current,Text\n1,2'); click(old); await settle()
    expect(h.api.generateLatexTable).toHaveBeenCalledWith({ table_text: 'Current,Text\n1,2', first_row_header: true })
    tree = configure(h, 'd14_latex'); const oldStructure = button(tree, 'Generate fragment')
    click(button(tree, 'Math')); click(oldStructure); await settle()
    expect(h.api.generateLatex).not.toHaveBeenCalled(); h.unmount()
  })
  it('keeps same-owner admitted fragments reviewable and copyable after leaf revocation, with separate current C01 checks', async () => {
    const h = await harness(); const request = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(request.promise)
    click(button(configure(h, 'd14_latex'), 'Generate fragment'))
    h.allow(all.filter(key => key !== 'd14_latex')); h.render()
    request.resolve(h.result); await settle()
    let tree = h.render(); expect(label(tree)).toContain(h.result.latex)
    expect(elements(tree).some(node => node.type === 'button' && label(node).trim() === 'Generate fragment again')).toBe(false)
    const retainedInsert = button(tree, 'Insert at cursor')
    h.allow(all.filter(key => key !== 'd14_latex' && key !== 'c01')); tree = h.render()
    expect(elements(tree).some(node => node.type === 'button' && label(node).trim() === 'Insert at cursor')).toBe(false)
    click(retainedInsert); expect(h.onInsert).not.toHaveBeenCalled()
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.allow(all.filter(key => key !== 'd14_latex')); h.render(); click(retainedInsert); click(retainedInsert)
    expect(h.onInsert).toHaveBeenCalledOnce(); h.unmount()
  })
  it('takes a synchronous shared pending lock and rejects replaced-request results', async () => {
    const h = await harness(); const first = deferred<typeof h.result>(); const second = deferred<typeof h.result>()
    h.api.generateLatex.mockReturnValueOnce(first.promise); h.api.generateLatexMath.mockReturnValueOnce(second.promise)
    let tree = configure(h, 'd14_latex'); const old = button(tree, 'Generate fragment'); click(old); click(old)
    expect(h.api.generateLatex).toHaveBeenCalledOnce()
    tree = configure(h, 'd14_math_text'); click(button(tree, 'Generate math')); h.render()
    first.resolve({ ...h.result, latex: 'STALE' }); await settle(); tree = h.render()
    expect(label(tree)).not.toContain('STALE'); expect(button(tree, 'Generating…').props.disabled).toBe(true)
    second.resolve({ ...h.result, latex: 'CURRENT' }); await settle(); expect(label(h.render())).toContain('CURRENT'); h.unmount()
  })
  it.each(['ABA', 'document ABA', 'logout', 'unmount'] as const)('suppresses late owner/session results after %s', async changeScope => {
    const h = await harness(); const request = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(request.promise)
    click(button(configure(h, 'd14_latex'), 'Generate fragment'))
    if (changeScope === 'ABA') { h.owner('B'); h.render(false); h.owner('A'); h.render(false) }
    if (changeScope === 'logout') { h.owner(null); h.render(false) }
    if (changeScope === 'document ABA') { h.document('document-B'); h.render(false); h.document('document-A'); h.render(false) }
    if (changeScope === 'unmount') h.unmount()
    request.resolve({ ...h.result, latex: 'PRIVATE A' }); await settle()
    expect(label(h.render(false))).not.toContain('PRIVATE A'); h.unmount()
  })
  it.each(['pending', 'session error', 'token rotation'] as const)('preserves owned draft and admitted recovery across same-owner %s while blocking unavailable new work', async transient => {
    const h = await harness(); const request = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(request.promise)
    const retained = button(configure(h, 'd14_latex'), 'Generate fragment'); click(retained)
    if (transient === 'pending') h.session(true, null, true)
    if (transient === 'session error') h.session(false, new Error('offline'), true)
    if (transient === 'token rotation') h.token('rotated-A-token')
    const during = h.render(); click(retained); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    expect(label(during)).toContain(transient === 'token rotation' ? 'What should be created?' : 'Create a heading')
    request.resolve(h.result); await settle(); let tree = h.render()
    expect(label(tree)).toContain(h.result.latex)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    if (transient !== 'token rotation') {
      expect(elements(tree).some(node => node.type === 'button' && label(node).trim() === 'Generate fragment again')).toBe(false)
      expect(elements(tree).some(node => node.type === 'button' && label(node).trim() === 'Insert at cursor')).toBe(false)
    }
    h.session(false); tree = h.render(); expect(textarea(tree).props.value).toBe('Create a heading')
    expect(label(tree)).toContain(h.result.latex); click(button(tree, 'Insert at cursor'))
    expect(h.onInsert).toHaveBeenCalledWith(h.result.latex); h.unmount()
  })
  it.each(['d14', 'ai_writing'] as const)('preserves admitted recovery while %s is OFF without exposing new-work controls', async ancestor => {
    const h = await harness(); const request = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(request.promise)
    const retained = button(configure(h, 'd14_latex'), 'Generate fragment'); click(retained)
    h.allow(all.filter(key => key !== ancestor)); h.render(); request.resolve(h.result); await settle()
    const tree = h.render(); expect(label(tree)).toContain(h.result.latex)
    expect(elements(tree).some(node => node.type === 'textarea')).toBe(false)
    expect(elements(tree).some(node => node.type === 'button' && label(node).trim().startsWith('Generate fragment'))).toBe(false)
    click(retained); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    await click(button(tree, 'Copy fragment')); click(button(tree, 'Insert at cursor'))
    expect(h.writeText).toHaveBeenCalledWith(h.result.latex); expect(h.onInsert).toHaveBeenCalledOnce()
    expect(h.onRecoveryChange).toHaveBeenLastCalledWith(true); h.unmount()
  })
  it('hides every OFF new-work input and mode without an owned draft', async () => {
    const h = await harness(); h.allow([]); const tree = h.render()
    expect(elements(tree).filter(node => node.type === 'textarea' || node.type === 'input' || node.props.role === 'tab')).toHaveLength(0)
    expect(label(tree)).not.toContain('Choose PNG'); h.unmount()
  })
  it('fences retained result and generation callbacks on document ABA while ordinary content edits preserve recovery', async () => {
    const h = await harness(); const oldGenerate = button(configure(h, 'd14_latex'), 'Generate fragment'); click(oldGenerate); await settle()
    let tree = h.render(); const oldInsert = button(tree, 'Insert at cursor'); const oldCopy = button(tree, 'Copy fragment')
    h.context('normal editor edit'); tree = h.render(); expect(label(tree)).toContain(h.result.latex)
    h.document('document-B'); expect(label(h.render(false))).not.toContain(h.result.latex)
    h.document('document-A'); expect(label(h.render(false))).not.toContain(h.result.latex)
    click(oldGenerate); click(oldInsert); await click(oldCopy)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled(); h.unmount()
  })
  it('hides a completed old-owner fragment and invalidates its retained insertion/copy callbacks before effects', async () => {
    const h = await harness(); click(button(configure(h, 'd14_latex'), 'Generate fragment')); await settle()
    const tree = h.render(); const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment')
    h.owner('B'); expect(label(h.render(false))).not.toContain(h.result.latex)
    h.owner('A'); expect(label(h.render(false))).not.toContain(h.result.latex)
    click(insert); await click(copy); expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled(); h.unmount()
  })
  it.each(['owner', 'document'] as const)('never renews old callbacks after %s ABA even when the new incarnation has fresh input and results', async kind => {
    const h = await harness(); const oldGenerate = button(configure(h, 'd14_latex'), 'Generate fragment')
    click(oldGenerate); await settle(); const oldTree = h.render()
    const oldInsert = button(oldTree, 'Insert at cursor'); const oldCopy = button(oldTree, 'Copy fragment')
    const oldMode = button(oldTree, 'Math'); const oldInput = textarea(oldTree)
    if (kind === 'owner') { h.owner('B'); h.render(); h.owner('A'); h.render() }
    else { h.document('document-B'); h.render(); h.document('document-A'); h.render() }
    let tree = configure(h, 'd14_latex')
    change(oldInput, 'STALE OLD INPUT')
    expect(textarea(h.render()).props.value).toBe('Create a heading')
    click(oldGenerate); await settle(); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    click(button(tree, 'Generate fragment')); await settle(); tree = h.render()
    click(oldInsert); await click(oldCopy); click(oldMode)
    expect(h.api.generateLatex).toHaveBeenCalledTimes(2)
    expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled()
    tree = h.render(); expect(label(tree)).toContain(h.result.latex)
    click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce(); h.unmount()
  })
  it('retains input bounds and blocks new work after an entitlement outage', async () => {
    const h = await harness(); const tree = configure(h, 'd14_table_text'); const old = button(tree, 'Generate table')
    const upload = elements(tree).find(item => item.type === 'input' && item.props.type === 'file')!
    ;(upload.props.onChange as (event: unknown) => void)({ target: { value: '', files: [{ name: 'large.png', size: 5_000_001 }] } })
    expect(label(h.render())).toContain('5 MB or smaller')
    h.allow([]); h.render(); click(old); await settle()
    expect(h.api.generateLatexTable).not.toHaveBeenCalled(); expect(h.api.generateLatexTableFromImage).not.toHaveBeenCalled(); h.unmount()
  })
})
