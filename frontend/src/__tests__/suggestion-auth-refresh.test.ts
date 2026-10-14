import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import { useSuggestionRecovery } from '@/hooks/useSuggestionRecovery'
import { AuthSync } from '@/components/AuthSync'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import type { SuggestionDecisionResponse } from '@/lib/api-client'

const SESSION = { user: { id: 'owner-a', name: 'Owner' }, session: { token: 'token-a' } }
type SessionError = { status: number; message: string }
interface SessionSnapshot {
  data: typeof SESSION | null
  isPending: boolean
  isRefetching: boolean
  error: SessionError | null
  refetch: () => Promise<void>
}
interface SessionAtom { value: SessionSnapshot; set: (value: SessionSnapshot) => void }
const authority = vi.hoisted(() => ({ recoveryIdentity: {}, isAdmissionCurrent: () => true, isCurrent: (): boolean => true, canAdmit: (): boolean => true }))
const state = vi.hoisted(() => ({ refs: [] as Array<{ current: unknown }>, slot: 0,
  effects: [] as Array<() => void | (() => void)>, atom: null as SessionAtom | null,
  token: 'token-a' as string | null, decide: vi.fn(), get: vi.fn(), push: vi.fn(), ws: vi.fn(), resolved: vi.fn() }))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(),
  useRef: (value: unknown) => {
    const slot = state.slot++
    if (!state.refs[slot]) state.refs[slot] = { current: value }
    return state.refs[slot]
  }, useState: (value: unknown) => { const slot = state.slot++; state.refs[slot] ??= { current: value }; return [state.refs[slot].current, (next: unknown) => { state.refs[slot].current = typeof next === 'function' ? (next as (value: unknown) => unknown)(state.refs[slot].current) : next }] }, useCallback: (callback: unknown) => callback,
  useMemo: (callback: () => unknown) => callback(), useLayoutEffect: (effect: () => void) => { effect() },
  useEffect: (effect: () => void | (() => void)) => { state.effects.push(effect) },
}))
vi.mock('@/lib/auth-client', () => ({ useSession: () => state.atom!.value }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: state.push }) }))
vi.mock('@/contexts/AccountContentScope', () => ({ useAccountContentScope: () => authority }))
vi.mock('@/lib/api-client', () => ({ apiClient: { decideSuggestion: state.decide, getSuggestionDecision: state.get,
  getAuthToken: () => state.token, setAuthToken: (token: string | null) => { state.token = token }, markAuthResolved: state.resolved } }))
vi.mock('@/lib/ws-client', () => ({ wsClient: { setAuthenticated: state.ws } }))

afterEach(() => {
  state.refs = []; state.slot = 0; state.effects = []; state.atom = null; state.token = 'token-a'
  vi.clearAllMocks(); vi.unstubAllGlobals()
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(yes => { resolve = yes })
  return { promise, resolve }
}
function outcome(id: string, status: 'accepted' | 'rejected' = 'rejected'): SuggestionDecisionResponse {
  return { suggestion_id: id, status, decided_by_role: 'owner', decided_at: '2026-10-13T12:00:00Z',
    latex_content: status === 'accepted' ? 'Before Changed After' : '', replayed: false, replay_available: true }
}

// Run the installed Better Auth lifecycle, not a fixture that incorrectly makes
// authenticated refresh isPending=true or changes an equal session reference.
const sessionModule = path.join(path.dirname(createRequire(import.meta.url).resolve('better-auth/client')), 'session-atom.mjs')
let getSessionAtom: (fetch: (...args: unknown[]) => Promise<unknown>, options: Record<string, unknown>) => { session: SessionAtom }
beforeAll(async () => { ({ getSessionAtom } = await import(pathToFileURL(sessionModule).href)) })
const editor = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')
const readyExpression = editor.match(/authReady:\s*(Boolean\([^\n]+?\)),\s*sourceVersion/)?.[1]
if (!readyExpression) throw new Error('Saved editor suggestion readiness expression was not found')
const editorAuthReady = new Function('sessionUserId', 'sessionLoading', 'sessionRefetching', 'sessionError', `return ${readyExpression}`) as (
  userId: string | null, pending: boolean, refetching: boolean, error: unknown,
) => boolean

const headerSource = ts.createSourceFile('GlobalHeader.tsx', readFileSync(new URL('../components/GlobalHeader.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const header = headerSource.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'GlobalHeader') as ts.FunctionDeclaration
const headerStatements = [...header.body!.statements]
const headerStart = headerStatements.findIndex(node => ts.isVariableStatement(node) && node.getText(headerSource).includes('= useSession()'))
const headerEnd = headerStatements.findIndex(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(item => item.name.getText(headerSource) === 'effectiveUserId'))
const headerIdentityCode = ts.transpileModule(`(() => { ${headerStatements.slice(headerStart, headerEnd + 1).map(node => node.getText(headerSource)).join('\n')} return { headerOwner: effectiveUserId, confirmedNoSession } })()`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const headerPurge = headerStatements.find(node => ts.isExpressionStatement(node) && node.getText(headerSource).includes('const previousOwner = lastOfflinePdfOwnerRef.current')) as ts.ExpressionStatement
const headerPurgeCode = ts.transpileModule(`(${(headerPurge.expression as ts.CallExpression).arguments[0].getText(headerSource)})()`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText

function harness() {
  const pending = deferred<{ data: typeof SESSION | null; error: SessionError | null }>()
  const fetch = vi.fn(() => pending.promise)
  const { session: atom } = getSessionAtom(fetch, {}) as { session: SessionAtom }
  atom.set({ ...atom.value, data: SESSION, isPending: false, isRefetching: false, error: null })
  state.atom = atom
  const applyAccepted = vi.fn(() => true)
  const headerRef = { current: null as typeof SESSION | null }
  const lastOfflinePdfOwnerRef = { current: null as string | null }
  const rememberOfflinePdfOwner = vi.fn(), forgetOfflinePdfOwner = vi.fn()
  const clearAllOfflineCompiledPdfs = vi.fn().mockResolvedValue(undefined), clearAllDrafts = vi.fn().mockResolvedValue(undefined), clearCompileQueue = vi.fn().mockResolvedValue(undefined)
  const clearAllDraftsExcept = vi.fn().mockResolvedValue(undefined), clearOfflineCompiledPdfsExcept = vi.fn().mockResolvedValue(undefined)
  let previousHeaderOwner: string | undefined
  function TestActualAuthAndSuggestionHooks() {
    AuthSync()
    const auth = useRequireAuth()
    const userId = auth.session?.user.id ?? null
    const suggestion = useSuggestionRecovery({ ownerId: userId, documentId: 'resume-a',
      authToken: auth.session?.session.token ?? null, authReady: editorAuthReady(userId, auth.isPending, auth.isRefetching, auth.error),
      sourceVersion: auth.session, role: 'owner', can: () => true, canEdit: true, authorName: 'Owner',
      readSource: () => 'Before Target After', applyAccepted })
    const { headerOwner, confirmedNoSession } = runInNewContext(headerIdentityCode, { useSession: () => atom.value,
      useRef: () => headerRef, isConfirmedSessionUnauthorized }) as { headerOwner: string | undefined; confirmedNoSession: boolean }
    if (headerOwner !== previousHeaderOwner) {
      runInNewContext(headerPurgeCode, { effectiveUserId: headerOwner, lastOfflinePdfOwnerRef, rememberOfflinePdfOwner,
        forgetOfflinePdfOwner, clearAllOfflineCompiledPdfs, clearAllDrafts, clearCompileQueue, clearAllDraftsExcept, clearOfflineCompiledPdfsExcept, confirmedNoSession })
      previousHeaderOwner = headerOwner
    }
    return { auth, suggestion, headerOwner }
  }
  const render = () => {
    state.slot = 0; state.effects = []
    const result = TestActualAuthAndSuggestionHooks()
    vi.stubGlobal('document', { cookie: '' }); state.effects[0]() // Actual AuthSync commit effect.
    return result
  }
  const load = () => {
    const hook = render().suggestion
    expect(hook.finishDocumentLoad(hook.beginDocumentLoad(), true, 'owner')).toBe(true)
    return render().suggestion
  }
  const proposal = () => { load().create('Target', 'Changed'); return render().suggestion }
  const refresh = async () => {
    const completion = atom.value.refetch()
    await Promise.resolve()
    expect(atom.value.isPending).toBe(false); expect(atom.value.isRefetching).toBe(true)
    expect(atom.value.data).toBe(SESSION)
    return { completion, ...render() }
  }
  return { pending, atom, render, load, proposal, refresh, applyAccepted, forgetOfflinePdfOwner, clearAllOfflineCompiledPdfs }
}

describe('real authenticated-refetch suggestion lifecycle', () => {
  it('closes source admissions with stable session data, retires old loads and preserves rejection recovery', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id; old.toggleMode()
    const ticket = old.beginDocumentLoad()
    const refreshing = await h.refresh()
    expect(refreshing.auth.isPending).toBe(false); expect(refreshing.auth.isRefetching).toBe(true)
    expect(refreshing.suggestion.canSuggest).toBe(false); expect(refreshing.suggestion.canAccept).toBe(false)
    expect(refreshing.suggestion.canReject(old.suggestions[0])).toBe(true); expect(refreshing.suggestion.mode).toBe(true)
    expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
    refreshing.suggestion.create('Target', 'Blocked'); await refreshing.suggestion.accept(id)
    expect(state.decide).not.toHaveBeenCalled(); expect(h.render().suggestion.suggestions).toHaveLength(1)
    state.decide.mockResolvedValueOnce(outcome(id)); await refreshing.suggestion.reject(id)
    expect(h.render().suggestion.decisions[0].status).toBe('rejected')
    h.pending.resolve({ data: structuredClone(SESSION), error: null }); await refreshing.completion
    expect(h.atom.value.data).toBe(SESSION) // Better Auth deliberately retains the equal reference.
    expect(h.render().suggestion.canSuggest).toBe(false); expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
    expect(h.load().canSuggest).toBe(true)
  })

  it('does not revive pre-refetch queued acceptance after successful equal-data refresh and source reload', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); state.decide.mockReturnValueOnce(pending.promise)
    const request = old.accept(id); const context = state.decide.mock.calls[0][2]
    expect(context.isCurrent()).toBe(true)
    const refreshing = await h.refresh(); expect(context.isCurrent()).toBe(false)
    h.pending.resolve({ data: structuredClone(SESSION), error: null }); await refreshing.completion
    expect(h.load().canAccept).toBe(true); expect(context.isCurrent()).toBe(false)
    pending.resolve(outcome(id, 'accepted')); await request
    expect(h.applyAccepted).toHaveBeenCalledOnce() // An already dispatched write remains owned recovery.
  })

  it.each(['accept', 'reject', 'get'] as const)('consumes already admitted owner %s outcomes during authenticated refetch', async action => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); let request: Promise<void> | undefined
    if (action === 'get') { state.get.mockReturnValueOnce(pending.promise); old.confirmRemoteDecisions([{ id, status: 'rejected', decidedByRole: 'owner', decidedAt: 1 }]) }
    else { state.decide.mockReturnValueOnce(pending.promise); request = old[action](id) }
    const refreshing = await h.refresh()
    pending.resolve(outcome(id, action === 'accept' ? 'accepted' : 'rejected')); await request; await Promise.resolve()
    expect(h.render().suggestion.decisions[0].status).toBe(action === 'accept' ? 'accepted' : 'rejected')
    h.pending.resolve({ data: SESSION, error: null }); await refreshing.completion
  })

  it('retains current-owner recovery through a real failed refresh without reopening source admissions', async () => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id; const ticket = old.beginDocumentLoad()
    const refreshing = await h.refresh(); h.pending.resolve({ data: null, error: { status: 503, message: 'temporary failure' } }); await refreshing.completion
    const failed = h.render()
    expect(failed.auth.session).toBe(SESSION); expect(failed.auth.isPending).toBe(false); expect(failed.auth.isRefetching).toBe(false)
    expect(failed.auth.error).toBeTruthy(); expect(failed.suggestion.canSuggest).toBe(false); expect(failed.suggestion.canReject(old.suggestions[0])).toBe(true)
    expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(false)
    state.decide.mockResolvedValueOnce(outcome(id)); await failed.suggestion.reject(id)
    expect(h.render().suggestion.decisions[0].status).toBe('rejected'); state.effects[1]()
    expect(state.push).not.toHaveBeenCalled()
    expect(state.token).toBe('token-a'); expect(failed.headerOwner).toBe('owner-a'); expect(h.clearAllOfflineCompiledPdfs).not.toHaveBeenCalled()
  })

  it.each(['accept', 'reject', 'get'] as const)('invalidates owned state and ignores late %s results after a real401 and return to A', async action => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const pending = deferred<SuggestionDecisionResponse>(); let request: Promise<void> | undefined
    if (action === 'get') { state.get.mockReturnValueOnce(pending.promise); old.confirmRemoteDecisions([{ id, status: 'accepted', decidedByRole: 'owner', decidedAt: 1 }]) }
    else { state.decide.mockReturnValueOnce(pending.promise); request = old[action](id) }
    const refreshing = await h.refresh(); h.pending.resolve({ data: null, error: { status: 401, message: 'session expired' } }); await refreshing.completion
    expect(h.atom.value.data).toBeNull(); expect(h.atom.value.error?.status).toBe(401)
    const invalid = h.render()
    expect(invalid.auth.session).toBeNull(); expect(invalid.headerOwner).toBeUndefined(); expect(state.token).toBeNull()
    expect(state.ws).toHaveBeenLastCalledWith(false); expect(h.forgetOfflinePdfOwner).toHaveBeenCalledOnce(); expect(h.clearAllOfflineCompiledPdfs).toHaveBeenCalledOnce()
    expect(invalid.suggestion.suggestions).toEqual([]); expect(invalid.suggestion.decisions).toEqual([]); expect(invalid.suggestion.canReject(old.suggestions[0])).toBe(false)
    vi.stubGlobal('window', { location: { pathname: '/workspace/resume-a/edit' } }); vi.stubGlobal('navigator', { onLine: false })
    state.effects[1](); expect(state.push).toHaveBeenCalledWith('/login?redirect=%2Fworkspace%2Fresume-a%2Fedit')
    h.atom.set({ ...h.atom.value, data: SESSION, error: null }); h.render(); h.load()
    expect(h.render().suggestion.suggestions).toEqual([])
    state.decide.mockClear(); state.get.mockClear()
    old.create('Target', 'Old'); await old.accept(id); await old.reject(id); old.retry(); old.confirmRemoteDecisions([{ id, status: 'accepted', decidedByRole: 'owner', decidedAt: 1 }])
    expect(state.decide).not.toHaveBeenCalled(); expect(state.get).not.toHaveBeenCalled()
    pending.resolve(outcome(id, 'accepted')); await request; await Promise.resolve()
    expect(h.applyAccepted).not.toHaveBeenCalled(); expect(h.render().suggestion.decisions).toEqual([])
  })

  it.each(['logout', 'owner-switch'] as const)('fences captured actions when refetch confirms %s', async change => {
    const h = harness(); const old = h.proposal(); const id = old.suggestions[0].id
    const refreshing = await h.refresh()
    const next = change === 'logout' ? null : { user: { id: 'owner-b', name: 'Other' }, session: { token: 'token-b' } }
    h.pending.resolve({ data: next, error: null }); await refreshing.completion
    state.token = next?.session.token ?? ''
    const current = h.render().suggestion
    expect(current.suggestions).toEqual([]); expect(current.decisions).toEqual([]); expect(current.canAccept).toBe(false)
    old.create('Target', 'Old'); await old.accept(id); await old.reject(id); old.retry()
    expect(state.decide).not.toHaveBeenCalled(); expect(h.applyAccepted).not.toHaveBeenCalled()
  })
})
