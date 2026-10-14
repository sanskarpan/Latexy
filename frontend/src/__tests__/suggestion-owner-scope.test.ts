import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import { useSuggestionRecovery } from '@/hooks/useSuggestionRecovery'
import type { SuggestionDecisionResponse } from '@/lib/api-client'
import type { Suggestion } from '@/lib/suggestions'

const authority = vi.hoisted(() => ({ recoveryIdentity: {}, isAdmissionCurrent: () => true, isCurrent: (): boolean => true, canAdmit: (): boolean => true }))
const state = vi.hoisted(() => ({ refs: [] as Array<{ current: unknown }>, slot: 0, effects: [] as Array<() => void | (() => void)>,
  authorityValue: null as import('@/contexts/AccountContentScope').AccountContentScope | null, token: 'token-a', decide: vi.fn(), get: vi.fn(), refresh: vi.fn() }))
vi.mock('react', async (original) => ({ ...await original<typeof import('react')>(),
  useRef: (value: unknown) => {
    const slot = state.slot++
    if (!state.refs[slot]) state.refs[slot] = { current: value }
    return state.refs[slot]
  }, useState: (value: unknown) => { const slot = state.slot++; state.refs[slot] ??= { current: value }; return [state.refs[slot].current, (next: unknown) => { state.refs[slot].current = typeof next === 'function' ? (next as (value: unknown) => unknown)(state.refs[slot].current) : next; state.refresh() }] }, useCallback: (callback: unknown) => callback, useMemo: (callback: () => unknown) => callback(),
  useLayoutEffect: (effect: () => void) => { effect() },
  useEffect: (effect: () => void | (() => void)) => { state.effects.push(effect) },
}))
vi.mock('@/contexts/AccountContentScope', () => ({ useAccountContentScope: () => state.authorityValue ?? authority }))
vi.mock('@/lib/api-client', () => ({ apiClient: { decideSuggestion: state.decide, getSuggestionDecision: state.get, getAuthToken: () => state.token } }))

afterEach(() => { state.refs = []; state.slot = 0; state.effects = []; state.token = 'token-a'; state.authorityValue = null; vi.clearAllMocks() })
const SOURCE = 'Before Target After'
function outcome(id: string, status: 'accepted' | 'rejected' = 'rejected'): SuggestionDecisionResponse {
  return { suggestion_id: id, status, decided_by_role: 'owner', decided_at: '2026-10-13T12:00:00Z',
    latex_content: status === 'accepted' ? 'Before Changed After' : '', replayed: false, replay_available: true }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function harness() {
  const grants = new Set<string>()
  const input = {
    ownerId: 'owner-a' as string | null, documentId: 'resume-a', authToken: 'token-a' as string | null, authReady: true,
    sourceVersion: {}, role: 'owner', can: (key: string) => !grants.has(key), canEdit: true,
    authorName: 'Owner', readSource: vi.fn(() => SOURCE), applyAccepted: vi.fn(() => true),
  }
  function TestSuggestionHook() { return useSuggestionRecovery(input) }
  const render = () => { state.slot = 0; state.effects = []; return TestSuggestionHook() }
  const load = (role = input.role) => { const hook = render(); expect(hook.finishDocumentLoad(hook.beginDocumentLoad(), true, role)).toBe(true); return render() }
  const proposal = () => { const hook = load(); hook.create('Target', 'Changed'); return render() }
  const switchScope = (ownerId = 'owner-b', documentId = 'resume-b') => {
    input.ownerId = ownerId; input.documentId = documentId; input.authToken = `token-${ownerId.slice(-1)}`; input.sourceVersion = {}; state.token = input.authToken
    return render()
  }
  return { input, grants, render, load, proposal, switchScope }
}

describe('actual suggestion action owner/document fences', () => {
  it.each(['refetch', 'pending', 'error', 'snapshot'] as const)('cannot revive a queued acceptance across actual outer %s ABA skipped by the child', async change => {
    const source = ts.createSourceFile('AccountContentBoundary.tsx', readFileSync(new URL('../components/AccountContentBoundary.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const component = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'AccountContentBoundary') as ts.FunctionDeclaration
    const code = ts.transpileModule(`const Boundary = ${component.getText(source).replace('export default ', '')}; Boundary({ children: null })`, { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText
    const refs: Array<{ current: unknown }> = []; let index = 0
    const session = { user: { id: 'owner-a' }, session: { token: 'token-a' } }
    let parent = { data: session, isPending: false, isRefetching: false, error: null as unknown }
    const boundaryRender = () => { index = 0; return runInNewContext(code, {
      useSession: () => parent, usePathname: () => '/workspace/resume-a/edit',
      useRef: (value: unknown) => { const slot = index++; refs[slot] ??= { current: value }; return refs[slot] }, useEffect: () => {}, isConfirmedSessionUnauthorized,
      React: { createElement: (_type: unknown, props: unknown) => ({ props }) }, Fragment: 'Fragment', AccountContentScopeProvider: 'Provider',
    }).props.value as import('@/contexts/AccountContentScope').AccountContentScope }
    const initial = boundaryRender(); state.authorityValue = initial
    const h = harness(); h.proposal()
    const sourceTicket = h.render().beginDocumentLoad(); expect(h.render().finishDocumentLoad(sourceTicket, true, 'owner')).toBe(true)
    const old = h.render(), id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(pending.promise)
    const request = old.accept(id), context = state.decide.mock.calls[0][2]
    parent = { data: change === 'snapshot' ? structuredClone(session) : session,
      isPending: change === 'pending', isRefetching: change === 'refetch', error: change === 'error' ? { status: 503 } : null }
    boundaryRender(); expect(context.isCurrent()).toBe(false)
    parent = { data: session, isPending: false, isRefetching: false, error: null }
    const settled = boundaryRender()
    // No child render or new source load occurred between the outer renders.
    expect(context.isCurrent()).toBe(false); expect(initial.isCurrent()).toBe(true)
    expect(old.canReject(old.suggestions[0])).toBe(true)
    expect(old.finishDocumentLoad(sourceTicket, true, 'owner')).toBe(false)
    old.create('Target', 'Before fresh source'); expect(old.suggestions).toHaveLength(1)
    state.authorityValue = settled
    const fresh = h.load() // Fresh admission, identical text/token, same recovery.
    expect(fresh.suggestions).toHaveLength(1); expect(fresh.canAccept).toBe(true)
    expect(context.isCurrent()).toBe(false)
    old.create('Target', 'Old callback'); await old.accept(id); expect(state.decide).toHaveBeenCalledOnce()
    pending.resolve(outcome(id, 'accepted')); await request
    // A result that actually committed before refresh is still owned recovery.
    expect(h.input.applyAccepted).toHaveBeenCalledOnce(); expect(h.render().decisions[0].status).toBe('accepted')
  })

  it.each(['accept', 'reject', 'remote-get'] as const)('fences retained callbacks and late %s before the old child rerenders or cleans up', async action => {
    const h = harness(), old = h.proposal(), id = old.suggestions[0].id
    const ticket = old.beginDocumentLoad(); expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(true); h.render()
    const pending = deferred<SuggestionDecisionResponse>()
    let request: Promise<void> | undefined
    if (action === 'remote-get') {
      state.get.mockReturnValueOnce(pending.promise)
      old.confirmRemoteDecisions([{ id, status: 'rejected', decidedByRole: 'owner', decidedAt: 1 }])
    } else { state.decide.mockReturnValueOnce(pending.promise); request = old[action](id) }
    const count = state.decide.mock.calls.length
    const isCurrent = vi.spyOn(authority, 'isCurrent').mockReturnValue(false)
    try {
      // The outer boundary has retired this authority while the old hook refs
      // and passive lifetime are still intact. No child render is performed.
      old.create('Target', 'Injected'); await old.accept(id); await old.reject(id); old.retry()
      expect(old.beginDocumentLoad()).toBeNull(); expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
      expect(state.decide).toHaveBeenCalledTimes(count)
      const context = action === 'remote-get' ? state.get.mock.calls[0][2] : state.decide.mock.calls[0][2]
      expect(context.isCurrent()).toBe(false)
      pending.resolve(outcome(id, action === 'accept' ? 'accepted' : 'rejected')); await request; await Promise.resolve()
      expect(h.input.applyAccepted).not.toHaveBeenCalled()
    } finally { isCurrent.mockRestore() }
    expect(h.render().decisions).toEqual([])
  })

  it('closes new work from live outer refetch readiness before the child rerenders while preserving owned rejection', async () => {
    const h = harness(), old = h.proposal(), id = old.suggestions[0].id
    const canAdmit = vi.spyOn(authority, 'canAdmit').mockReturnValue(false)
    try {
      old.create('Target', 'Injected'); await old.accept(id); expect(state.decide).not.toHaveBeenCalled()
      state.decide.mockResolvedValueOnce(outcome(id)); await old.reject(id)
      expect(state.decide).toHaveBeenCalledOnce(); expect(state.decide.mock.calls[0][2].isCurrent()).toBe(true)
    } finally { canAdmit.mockRestore() }
    expect(h.render().suggestions).toHaveLength(1); expect(h.render().decisions[0].status).toBe('rejected')
  })

  it.each(['owner', 'document', 'aba'])('blocks captured create/accept/reject/retry callbacks across %s switches', async (change) => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    // A failed action leaves a retry target which must not cross identity.
    state.decide.mockRejectedValueOnce(new Error('retry this')); await old.reject(id)
    expect(h.render().error).toBe('retry this'); state.decide.mockClear()
    if (change === 'document') h.switchScope('owner-a', 'resume-b')
    else { h.switchScope(); if (change === 'aba') h.switchScope('owner-a', 'resume-a') }
    old.create('Target', 'Injected'); await old.accept(id); await old.reject(id); old.retry(); h.render().retry()
    const next = h.render()
    expect(next.suggestions).toEqual([]); expect(next.decisions).toEqual([]); expect(next.error).toBeNull(); expect(next.mode).toBe(false)
    expect(state.decide).not.toHaveBeenCalled(); expect(h.input.applyAccepted).not.toHaveBeenCalled()
  })

  it.each(['reject', 'accept'] as const)('ignores late %s responses and errors after account A→B→A', async (action) => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(pending.promise)
    const request = old[action](id)
    const context = state.decide.mock.calls[0][2]
    h.switchScope(); h.switchScope('owner-a', 'resume-a'); h.load()
    expect(context.isCurrent()).toBe(false)
    pending.resolve(outcome(id, action === 'accept' ? 'accepted' : 'rejected')); await request
    expect(h.render().decisions).toEqual([]); expect(h.render().error).toBeNull(); expect(h.input.applyAccepted).not.toHaveBeenCalled()
    // A late rejection cannot add another owner's error either.
    const current = h.proposal(); const nextId = current.suggestions[0].id
    const failure = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(failure.promise)
    const failed = current[action](nextId); h.switchScope(); failure.reject(new Error('old account failure')); await failed
    expect(h.render().error).toBeNull()
  })

  it('ignores late document responses, remote GET confirmations and stale presence', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(pending.promise)
    const request = old.reject(id)
    const confirmed = deferred<SuggestionDecisionResponse>(); state.get.mockReturnValueOnce(confirmed.promise)
    old.confirmRemoteDecisions([{ id, status: 'rejected', decidedByRole: 'owner', decidedAt: 1 }])
    const getContext = state.get.mock.calls[0][2]
    h.switchScope('owner-a', 'resume-b'); h.load()
    old.remotePresence([{ items: old.suggestions, decisions: [] }]); old.confirmRemoteDecisions([])
    expect(getContext.isCurrent()).toBe(false)
    pending.resolve(outcome(id)); confirmed.resolve(outcome(id)); await request; await Promise.resolve()
    expect(h.render().allSuggestions).toEqual([]); expect(h.render().decisions).toEqual([])
  })

  it('does not inherit a default owner role or ready source in the next scope', async () => {
    const h = harness(); h.proposal(); const next = h.switchScope()
    expect(next.canSuggest).toBe(false); expect(next.canAccept).toBe(false)
    next.create('Target', 'No'); expect(h.render().suggestions).toEqual([])
    const viewer = h.load('viewer')
    const foreign: Suggestion = { id: 'foreign', authorId: 'another-user', authorName: 'Peer', originalText: 'Target', replacementText: 'No',
      offset: 7, prefix: 'Before ', suffix: ' After', status: 'pending', createdAt: 1 }
    viewer.remotePresence([{ items: [foreign], decisions: [] }]); const ready = h.render()
    expect(ready.canAccept).toBe(false); expect(ready.canReject(foreign)).toBe(false)
    await ready.reject('foreign'); expect(state.decide).not.toHaveBeenCalled()
  })

  it('requires the newest successful source load for creation and acceptance', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const first = old.beginDocumentLoad(); const second = old.beginDocumentLoad()
    expect(old.finishDocumentLoad(first, true)).toBe(false)
    const loading = h.render(); expect(loading.canAccept).toBe(false); expect(loading.canSuggest).toBe(false)
    await loading.accept(id); expect(state.decide).not.toHaveBeenCalled()
    expect(loading.finishDocumentLoad(second, true, 'owner')).toBe(true)
    expect(h.render().canAccept).toBe(true)
    h.input.sourceVersion = {}; const reloading = h.render()
    expect(reloading.canAccept).toBe(false); expect(reloading.canReject(reloading.suggestions[0])).toBe(true)
  })

  it('retains proposal, mode and retry recovery through a same-owner transient refresh', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    old.toggleMode(); state.decide.mockRejectedValueOnce(new Error('retry this')); await old.reject(id)
    h.input.authReady = false; h.grants.add('f07'); h.grants.add('c01'); const pending = h.render()
    expect(pending.suggestions.map(item => item.id)).toEqual([id]); expect(pending.mode).toBe(true)
    expect(pending.canSuggest).toBe(false); expect(pending.canAccept).toBe(false); expect(pending.canReject(pending.suggestions[0])).toBe(true)
    state.decide.mockResolvedValueOnce(outcome(id)); pending.retry(); await Promise.resolve(); await Promise.resolve()
    expect(state.decide).toHaveBeenLastCalledWith('resume-a', expect.objectContaining({ status: 'rejected' }), expect.objectContaining({ authToken: 'token-a' }))
    expect(h.render().decisions[0].status).toBe('rejected')
    h.input.authReady = true; h.grants.clear()
    expect(h.render().canAccept).toBe(false) // fresh source readiness is still required
    expect(h.load().canAccept).toBe(true)
  })

  it.each(['version', 'version-aba', 'auth-ready', 'token-aba'] as const)('retires source-load tickets synchronously on %s transitions before the next effect', (change) => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const ticket = old.beginDocumentLoad(); const initialVersion = h.input.sourceVersion
    if (change.startsWith('version')) {
      h.input.sourceVersion = {}; h.render()
      if (change === 'version-aba') { h.input.sourceVersion = initialVersion; h.render() }
    } else if (change === 'auth-ready') {
      h.input.authReady = false; h.render(); h.input.authReady = true; h.render()
    } else {
      h.input.authToken = 'token-b'; state.token = 'token-b'; h.render()
      h.input.authToken = 'token-a'; state.token = 'token-a'; h.render()
    }
    expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
    const recovering = h.render()
    expect(recovering.canSuggest).toBe(false); expect(recovering.canAccept).toBe(false)
    expect(recovering.suggestions[0].id).toBe(id); expect(recovering.canReject(recovering.suggestions[0])).toBe(true)
    expect(h.load().canAccept).toBe(true)
    expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
  })

  it('does not let a load started during unresolved authentication establish source readiness', () => {
    const h = harness(); h.proposal(); h.input.authReady = false
    const pending = h.render(); const ticket = pending.beginDocumentLoad()
    expect(pending.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
    expect(h.render().canSuggest).toBe(false)
    h.input.authReady = true; h.render()
    expect(pending.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
    expect(h.load().canAccept).toBe(true)
  })

  it('does not revive a queued acceptance after a new source admission becomes ready', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const result = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(result.promise)
    const request = old.accept(id); const context = state.decide.mock.calls[0][2]
    expect(context.isCurrent()).toBe(true)
    h.input.sourceVersion = {}; h.render(); h.load()
    expect(h.render().canAccept).toBe(true); expect(context.isCurrent()).toBe(false)
    // An already dispatched server result remains same-document recovery.
    result.resolve(outcome(id, 'accepted')); await request
    expect(h.input.applyAccepted).toHaveBeenCalledOnce(); expect(h.render().decisions[0].status).toBe('accepted')
  })

  it('accepts an already committed same-scope result after admission grants are revoked', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(pending.promise)
    const request = old.accept(id)
    h.grants.add('f07'); h.grants.add('c01'); h.input.canEdit = false; h.render()
    pending.resolve(outcome(id, 'accepted')); await request
    expect(h.input.applyAccepted).toHaveBeenCalledOnce(); expect(h.render().decisions[0].status).toBe('accepted')
  })

  it('pins tokens and refuses local commits after auth changes before a session rerender', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(pending.promise)
    const request = old.reject(id); state.token = 'other-auth-token'
    pending.resolve(outcome(id)); await request
    expect(h.render().decisions).toEqual([]); expect(h.render().canReject(old.suggestions[0])).toBe(false)
  })

  it('checks current F04 for editor recovery and keeps author withdrawal local', async () => {
    const h = harness(); h.input.role = 'editor'; const editor = h.proposal(); h.grants.add('f07'); h.grants.add('c01'); h.grants.add('f04')
    expect(h.render().canReject(editor.suggestions[0])).toBe(false); await editor.reject(editor.suggestions[0].id)
    expect(state.decide).not.toHaveBeenCalled()
    h.grants.clear(); h.input.role = 'commenter'; const own = h.load('commenter'); own.create('Target', 'Changed')
    const pending = h.render(); const id = pending.suggestions[0].id
    h.grants.add('f07'); h.grants.add('c01'); await pending.reject(id)
    expect(state.decide).not.toHaveBeenCalled(); expect(h.render().suggestions[0].status).toBe('rejected'); expect(h.render().decisions).toEqual([])
  })

  it('fences unmounts and clears draft/error retry targets on confirmed logout', () => {
    const h = harness(); const old = h.load(); old.create('missing', 'Draft'); expect(h.render().error).toBeTruthy()
    const cleanup = state.effects[0](); if (typeof cleanup === 'function') cleanup()
    old.retry(); expect(state.decide).not.toHaveBeenCalled()
    h.input.ownerId = null; h.input.authToken = null; state.token = ''; const loggedOut = h.render()
    expect(loggedOut.error).toBeNull(); expect(loggedOut.suggestions).toEqual([]); old.create('Target', 'No'); old.retry()
    expect(h.render().suggestions).toEqual([])
  })
})

describe('independent document-access revocation', () => {
  it.each(['accept', 'reject', 'get'] as const)('drops late editor %s outcomes when F04 is revoked in flight', async (action) => {
    const h = harness(); h.input.role = 'editor'; const hook = h.proposal(); const id = hook.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>()
    let request: Promise<void> | undefined
    if (action === 'get') {
      state.get.mockReturnValueOnce(pending.promise)
      hook.confirmRemoteDecisions([{ id, status: 'accepted', decidedByRole: 'owner', decidedAt: 1 }])
    } else {
      state.decide.mockReturnValueOnce(pending.promise); request = hook[action](id)
    }
    h.grants.add('f04'); h.render(); pending.resolve(outcome(id, 'accepted')); await request; await Promise.resolve()
    expect(h.input.applyAccepted).not.toHaveBeenCalled(); expect(h.render().decisions).toEqual([]); expect(h.render().suggestions[0].status).toBe('pending')
  })
  it('blocks an already queued editor GET at its live account-context dispatch fence', () => {
    const h = harness(); h.input.role = 'editor'; const hook = h.proposal(); const id = hook.suggestions[0].id
    state.get.mockReturnValueOnce(new Promise(() => {}))
    hook.confirmRemoteDecisions([{ id, status: 'accepted', decidedByRole: 'owner', decidedAt: 1 }])
    const context = state.get.mock.calls[0][2]
    expect(context.isCurrent()).toBe(true); h.grants.add('f04'); h.render(); expect(context.isCurrent()).toBe(false)
  })
  it('ignores late editor rejection errors after independent access revocation', async () => {
    const h = harness(); h.input.role = 'editor'; const hook = h.proposal(); const pending = deferred<SuggestionDecisionResponse>()
    state.decide.mockReturnValueOnce(pending.promise); const request = hook.reject(hook.suggestions[0].id)
    h.grants.add('f04'); h.render(); pending.reject(new Error('late denied-context failure')); await request
    expect(h.render().error).toBeNull()
  })
  it.each(['reject', 'get'] as const)('retains owner %s recovery when F07, C01 and collaborator F04 are disabled in flight', async (action) => {
    const h = harness(); const hook = h.proposal(); const id = hook.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); let request: Promise<void> | undefined
    if (action === 'get') { state.get.mockReturnValueOnce(pending.promise); hook.confirmRemoteDecisions([{ id, status: 'rejected', decidedByRole: 'owner', decidedAt: 1 }]) }
    else { state.decide.mockReturnValueOnce(pending.promise); request = hook.reject(id) }
    h.grants.add('f07'); h.grants.add('c01'); h.grants.add('f04'); h.render()
    pending.resolve(outcome(id)); await request; await Promise.resolve()
    expect(h.render().decisions[0].status).toBe('rejected'); expect(h.input.applyAccepted).not.toHaveBeenCalled()
  })
})
