import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import Panel from '@/components/SemanticOptimizationPanel'
import ImportedPanel from '@/components/ImportedOptimizationPanel'
import type { ResumeEngineDocument, SemanticOptimizationRun } from '@/lib/resume-engine-types'

const state = vi.hoisted(() => ({ current: true, request: {} as Record<string, string>,
  denied: new Set<string>(), run: null as SemanticOptimizationRun | null, token: 'owner-token', stateIndex: 0, expanded: false,
  refIndex: 0, refs: [] as Array<{ current: unknown }>,
  effects: [] as Array<() => void | (() => void)>,
  optimize: vi.fn<(...args: unknown[]) => Promise<{ success: boolean; job_id: string }>>(),
  decide: vi.fn(), getRun: vi.fn(),
}))
vi.mock('react', async (original) => ({ ...await original<typeof import('react')>(),
  useState: (initial: unknown) => {
    const slot = state.stateIndex++
    return [slot === 1 && initial === null ? state.run : slot === 0 && initial === false ? state.expanded : initial, vi.fn()]
  }, useRef: (value: unknown) => {
    const slot = state.refIndex++
    if (!state.refs[slot]) state.refs[slot] = { current: value }
    return state.refs[slot]
  }, useEffect: (effect: () => void | (() => void)) => { state.effects.push(effect) },
}))
vi.mock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: (key: string) => !state.denied.has(key) }) }))
vi.mock('@/lib/api-client', () => ({ apiClient: { optimizeEngineDocument: state.optimize, decideEngineRun: state.decide, getEngineRun: state.getRun, getAuthToken: () => state.token } }))
vi.mock('@/hooks/useEngineProviderChoice', () => ({ useEngineProviderChoice: () => ({
  request: state.request, choice: { provider: state.request.provider ?? 'automatic', model: state.request.provider_model ?? '' },
  options: { default: { ready: true }, providers: [] }, error: null, choose: vi.fn(), retry: vi.fn(),
  accountContext: { authToken: 'owner-token', isCurrent: () => state.current },
}) }))
afterEach(() => {
  vi.clearAllMocks(); state.current = true; state.denied.clear(); state.run = null
  state.token = 'owner-token'; state.effects = []; state.expanded = false; state.refs = []
})

const document: ResumeEngineDocument = {
  document_id: 'resume', source_mode: 'managed', source_sha256: 'source', content_revision: 4, structured_version: 1,
  template_id: 'standard', nodes: [], opaque_blocks: [],
}
function completedRun(): SemanticOptimizationRun {
  return { run_id: 'review', document_id: 'resume', base_revision: 4, source_sha256: 'source', status: 'completed',
    job_status: 'completed', effort: 'standard', acceptance_ready: true, document, decisions: {}, budget: {},
    result: { patches: [{ patch_id: 'patch-one', node_id: 'field-one', expected_node_revision: 'node-revision',
      original_text: 'Built tools', text: 'Developed tools', reason: 'Clarity' }], warnings: [], missing_evidence: [], candidate_source_sha256: 'candidate' },
  }
}
function findButton(node: unknown, label: string): ReactElement<{ onClick: () => void; disabled?: boolean }> | undefined {
  if (Array.isArray(node)) return node.map((child) => findButton(child, label)).find(Boolean)
  if (!node || typeof node !== 'object' || !('props' in node)) return
  const element = node as ReactElement<{ children?: unknown; onClick: () => void; disabled?: boolean }>
  const text = Array.isArray(element.props.children) ? element.props.children.join('') : element.props.children
  if (element.type === 'button' && text === label) return element
  return findButton(element.props.children, label)
}
function elements(node: unknown): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!node || typeof node !== 'object' || !('props' in node)) return []
  const element = node as ReactElement<Record<string, unknown>>
  return [element, ...elements(element.props.children)]
}

function panel(request: Record<string, string>, admitted: Promise<{ success: boolean; job_id: string }>, currentSourceHash = 'source', startDisabled = false,
  options: { preserveRefs?: boolean; identity?: string; disabled?: boolean } = {}) {
  state.stateIndex = 0; state.refIndex = 0; state.effects = []
  if (!options.preserveRefs) state.refs = []
  state.request = request; state.optimize.mockImplementation(() => admitted)
  const onStarted = vi.fn()
  const onApplied = vi.fn()
  const tree = Panel({ resumeId: 'resume', identity: options.identity ?? 'owner:resume', currentSourceHash, disabled: options.disabled ?? false, startDisabled,
    document, jobDescription: 'A target role', setJobDescription: vi.fn(),
    runId: state.run?.run_id ?? null, onStarted, onApplied })
  return { click: (label = 'Find suggestions') => findButton(tree, label)!.props.onClick(), button: (label: string) => findButton(tree, label)!,
    optimize: state.optimize, onStarted, onApplied, tree }
}

describe('provider choice in the actual semantic review panel', () => {
  it('preserves Automatic omission in the panel admission body', async () => {
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    review.click(); await Promise.resolve()
    expect(review.optimize.mock.calls[0][0]).toBe('resume')
    expect(review.optimize.mock.calls[0][1]).toEqual({
      expected_content_revision: 4, expected_source_sha256: 'source', job_description: 'A target role', effort: 'standard',
    })
    expect(review.optimize.mock.calls[0][2]).toMatchObject({ authToken: 'owner-token', isCurrent: expect.any(Function) })
    expect(review.optimize.mock.calls[0][1]).not.toHaveProperty('provider')
    expect(review.optimize.mock.calls[0][1]).not.toHaveProperty('provider_model')
    expect(review.onStarted).toHaveBeenCalledWith('review')
  })
  it('uses the selected provider/model rather than replacing it with defaults', async () => {
    const review = panel({ provider: 'openrouter', provider_model: 'priced/exact-model' }, Promise.resolve({ success: true, job_id: 'review' }))
    review.click(); await Promise.resolve()
    expect(review.optimize.mock.calls[0][1]).toMatchObject({ provider: 'openrouter', provider_model: 'priced/exact-model' })
  })
  it('does not adopt an admission response after account changes', async () => {
    let resolve!: (value: { success: boolean; job_id: string }) => void
    const review = panel({}, new Promise((done) => { resolve = done }))
    review.click(); state.current = false; resolve({ success: true, job_id: 'previous-account-review' }); await Promise.resolve()
    expect(review.onStarted).not.toHaveBeenCalled()
  })
  it.each(['d01', 'd18', 'c05', 'c01'])('blocks a new review when %s is denied', async (key) => {
    state.denied.add(key)
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    expect(review.button('Find suggestions')).toBeUndefined()
    expect(elements(review.tree).some((element) => ['textarea', 'select'].includes(String(element.type)) || element.props['aria-label'] === 'Review effort')).toBe(false)
    expect(review.optimize).not.toHaveBeenCalled()
  })
  it('checks live grants when an already-rendered start action is invoked', async () => {
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    state.denied.add('d18'); review.click(); await Promise.resolve()
    expect(review.optimize).not.toHaveBeenCalled()
  })
  it('checks live caller restrictions and source identity before starting a captured action', async () => {
    const ready = Promise.resolve({ success: true, job_id: 'review' })
    const review = panel({}, ready)
    panel({}, ready, 'source', false, { preserveRefs: true, disabled: true })
    review.click(); await Promise.resolve()
    expect(review.optimize).not.toHaveBeenCalled()
    panel({}, ready, 'new-local-source', false, { preserveRefs: true })
    review.click(); await Promise.resolve()
    expect(review.optimize).not.toHaveBeenCalled()
  })
  it('fences an admitted response across owner A to B to A', async () => {
    let resolve!: (value: { success: boolean; job_id: string }) => void
    const admission = new Promise<{ success: boolean; job_id: string }>((done) => { resolve = done })
    const review = panel({}, admission)
    review.click()
    panel({}, admission, 'source', false, { preserveRefs: true, identity: 'owner-b:resume' })
    panel({}, admission, 'source', false, { preserveRefs: true, identity: 'owner:resume' })
    resolve({ success: true, job_id: 'previous-owner-review' }); await Promise.resolve()
    expect(review.onStarted).not.toHaveBeenCalled()
  })
  it('admits only one review for repeated clicks before rerender', async () => {
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    review.click(); review.click(); await Promise.resolve()
    expect(review.optimize).toHaveBeenCalledOnce()
  })
  it('retains an admitted review response after optimization grants are revoked', async () => {
    let resolve!: (value: { success: boolean; job_id: string }) => void
    const review = panel({}, new Promise((done) => { resolve = done }))
    review.click(); state.denied.add('d01'); resolve({ success: true, job_id: 'admitted-review' }); await Promise.resolve()
    expect(review.onStarted).toHaveBeenCalledWith('admitted-review')
  })
  it('continues stored-run polling on downgrade', async () => {
    state.run = completedRun(); state.denied.add('d01'); state.denied.add('d18')
    state.getRun.mockResolvedValue(completedRun())
    panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    const cleanup = state.effects[2]()
    await Promise.resolve()
    expect(state.getRun).toHaveBeenCalledWith('resume', 'review')
    if (typeof cleanup === 'function') cleanup()
  })
  it.each(['d03', 'c01'])('blocks acceptance when %s is revoked but keeps reject-only recovery', async (key) => {
    state.run = completedRun()
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    state.denied.add(key)
    state.decide.mockResolvedValue({ document, latex_content: 'saved source', decisions: { patches: { 'patch-one': 'rejected' } } })
    review.click('Accept'); await Promise.resolve()
    expect(state.decide).not.toHaveBeenCalled()
    review.click('Reject'); await Promise.resolve()
    expect(state.decide).toHaveBeenCalledWith('resume', 'review', expect.objectContaining({ accept_patch_ids: [], reject_patch_ids: ['patch-one'] }), expect.objectContaining({ authToken: 'owner-token' }))
    expect(review.onApplied).not.toHaveBeenCalled()
    const off = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    expect(off.button('Accept')).toBeUndefined()
    expect(off.button('Accept all 1 suggestions')).toBeUndefined()
    expect(off.button('Reject').props.disabled).toBe(false)
  })
  it('does not require start-only grants to accept an existing suggestion', async () => {
    state.run = completedRun(); state.denied.add('d01'); state.denied.add('d18'); state.denied.add('c05')
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }), 'source', true)
    state.decide.mockResolvedValue({ document, latex_content: 'accepted source', decisions: { patches: { 'patch-one': 'accepted' } } })
    expect(review.button('Accept').props.disabled).toBe(false)
    review.click('Accept'); await Promise.resolve()
    expect(review.onApplied).toHaveBeenCalledWith(document, 'accepted source', expect.any(Number))
  })
  it('rejects a stored suggestion without replacing a newer local draft', async () => {
    state.run = completedRun(); state.denied.add('d01'); state.denied.add('d03'); state.denied.add('c01')
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }), 'new-local-source')
    state.decide.mockResolvedValue({ document, latex_content: 'saved source', decisions: { patches: { 'patch-one': 'rejected' } } })
    expect(review.button('Reject').props.disabled).toBe(false)
    review.click('Reject'); await Promise.resolve()
    expect(state.decide).toHaveBeenCalledOnce()
    expect(review.onApplied).not.toHaveBeenCalled()
  })
  it('does not apply a decision response after the authenticated token changes', async () => {
    state.run = completedRun()
    let resolve!: (value: unknown) => void
    state.decide.mockImplementation(() => new Promise((done) => { resolve = done }))
    const review = panel({}, Promise.resolve({ success: true, job_id: 'review' }))
    review.click('Accept'); state.token = 'another-owner-token'; resolve({ document, latex_content: 'other source', decisions: {} }); await Promise.resolve()
    expect(review.onApplied).not.toHaveBeenCalled()
    expect(state.decide.mock.calls[0][3].isCurrent()).toBe(false)
  })
  it('does not dispatch captured acceptance after caller restrictions or local source change', async () => {
    state.run = completedRun()
    const ready = Promise.resolve({ success: true, job_id: 'review' })
    const review = panel({}, ready)
    panel({}, ready, 'source', false, { preserveRefs: true, disabled: true })
    review.click('Accept'); await Promise.resolve()
    expect(state.decide).not.toHaveBeenCalled()
    panel({}, ready, 'new-local-source', false, { preserveRefs: true })
    review.click('Accept'); await Promise.resolve()
    expect(state.decide).not.toHaveBeenCalled()
  })
})

describe('imported candidate capability controls', () => {
  function imported() {
    state.stateIndex = 0; state.refIndex = 0; state.refs = []; state.expanded = true
    const onRun = vi.fn(), onApply = vi.fn(), onDiscard = vi.fn(), onPreview = vi.fn()
    const tree = ImportedPanel({ jobDescription: 'Target job', setJobDescription: vi.fn(), disabled: false, startDisabled: true,
      running: false, candidate: true, changes: [], onRun, onApply, onDiscard, onPreview })
    return { onRun, onApply, onDiscard, onPreview, tree, click: (label: string) => findButton(tree, label)!.props.onClick(), button: (label: string) => findButton(tree, label)! }
  }
  it('separates existing candidate acceptance from start-only grants', () => {
    state.denied.add('d01'); state.denied.add('d18'); state.denied.add('c05')
    const review = imported()
    expect(review.button('Start advanced review')).toBeUndefined()
    expect(review.button('Hide advanced review')).toBeUndefined()
    expect(elements(review.tree).some((element) => element.type === 'textarea')).toBe(false)
    expect(review.button('Accept complete candidate').props.disabled).toBe(false)
    expect(review.onRun).not.toHaveBeenCalled()
    review.click('Accept complete candidate'); expect(review.onApply).toHaveBeenCalledOnce()
  })
  it('blocks a captured acceptance action on live denial while retaining preview and discard', () => {
    const review = imported(); state.denied.add('d03'); state.denied.add('c01')
    review.click('Accept complete candidate'); expect(review.onApply).not.toHaveBeenCalled()
    review.click('Review candidate PDF'); expect(review.onPreview).toHaveBeenCalledOnce()
    review.click('Discard'); expect(review.onDiscard).toHaveBeenCalledOnce()
    const off = imported()
    expect(off.button('Accept complete candidate')).toBeUndefined()
    expect(off.button('Discard').props.disabled).toBe(false)
  })
})
