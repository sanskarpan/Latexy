import { realpathSync } from 'node:fs'
import { createRequire } from 'node:module'
import React, { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useSuggestionRecovery } from '@/hooks/useSuggestionRecovery'
import { useEditorSourceLoadScope } from '@/hooks/useLatexGeneratorRecovery'
import { useInterviewPrepRecovery } from '@/hooks/useInterviewPrepRecovery'
import { AccountContentScopeProvider } from '@/contexts/AccountContentScope'

const requests = vi.hoisted(() => ({ decide: vi.fn(), get: vi.fn() }))
vi.mock('@/lib/api-client', () => ({ apiClient: { getAuthToken: () => 'token-a', decideSuggestion: requests.decide, getSuggestionDecision: requests.get } }))

function concurrentRenderer() {
  const require = createRequire(import.meta.url)
  const fiber = realpathSync(require.resolve('@react-three/fiber/package.json'))
  const makeReconciler = require(require.resolve('react-reconciler', { paths: [fiber] }))
  const constants = require(require.resolve('react-reconciler/constants', { paths: [fiber] }))
  const renderer = makeReconciler({
    now: Date.now, supportsMutation: true, isPrimaryRenderer: true,
    getRootHostContext: () => ({}), getChildHostContext: () => ({}), prepareForCommit: () => null, resetAfterCommit: () => {},
    shouldSetTextContent: () => false, createInstance: () => ({}), createTextInstance: () => ({}),
    appendInitialChild: () => {}, finalizeInitialChildren: () => false,
    appendChild: () => {}, appendChildToContainer: () => {}, removeChild: () => {}, removeChildFromContainer: () => {},
    clearContainer: () => {}, prepareUpdate: () => null, commitUpdate: () => {}, commitTextUpdate: () => {},
    hideInstance: () => {}, unhideInstance: () => {}, hideTextInstance: () => {}, unhideTextInstance: () => {},
    scheduleTimeout: setTimeout, cancelTimeout: clearTimeout, noTimeout: -1,
    getCurrentEventPriority: () => constants.DefaultEventPriority, detachDeletedInstance: () => {},
  })
  const root = renderer.createContainer({}, constants.ConcurrentRoot, null, false, null, '', (error: unknown) => { throw error }, null)
  return { renderer, root }
}

describe('actual suggestion source readiness at React commit', () => {
  it('keeps retained new-work actions closed while a same-owner reload queues matching source states', async () => {
    const { renderer, root } = concurrentRenderer()
    let hook!: ReturnType<typeof useSuggestionRecovery>, setSource!: React.Dispatch<React.SetStateAction<string>>, force!: () => void
    const sourceVersion = {}, authority = { recoveryIdentity: {}, isAdmissionCurrent: () => true, isCurrent: () => true, canAdmit: () => true }
    const applyAccepted = vi.fn(() => true)
    function ActualSuggestionAndSource() {
      const [source, updateSource] = React.useState('Before Target After'); setSource = updateSource
      const [, update] = React.useState(0); force = () => update(value => value + 1)
      hook = useSuggestionRecovery({ ownerId: 'owner-a', documentId: 'document-a', authToken: 'token-a', authReady: true,
        sourceVersion, role: 'owner', can: () => true, canEdit: true, authorName: 'Owner', readSource: () => source, applyAccepted })
      return null
    }
    const settleCommit = async () => { await new Promise(resolve => setTimeout(resolve, 25)); renderer.flushSync(() => force()) }
    try {
      renderer.flushSync(() => renderer.updateContainer(React.createElement(AccountContentScopeProvider, { value: authority }, React.createElement(ActualSuggestionAndSource)), root, null, null))
      const first = hook.beginDocumentLoad(); expect(hook.finishDocumentLoad(first, true, 'owner')).toBe(true)
      expect(hook.canSuggest).toBe(false)
      await settleCommit(); expect(hook.canSuggest).toBe(true)
      renderer.flushSync(() => hook.create('Target', 'Changed'))
      const old = hook, id = old.suggestions[0].id
      const ticket = old.beginDocumentLoad()
      setSource('New Before Target After')
      expect(old.finishDocumentLoad(ticket, true, 'owner')).toBe(true)
      // A higher-priority render runs before the default-lane source and ready
      // snapshot commit. Neither that render nor an old callback may admit.
      renderer.flushSync(() => force())
      expect(hook.canSuggest).toBe(false); expect(hook.canAccept).toBe(false)
      old.create('Target', 'Too early'); await old.accept(id)
      expect(requests.decide).not.toHaveBeenCalled(); expect(hook.suggestions).toHaveLength(1)
      expect(hook.canReject(hook.suggestions[0])).toBe(true)
      await settleCommit()
      expect(hook.canSuggest).toBe(true); expect(hook.canAccept).toBe(true)
      renderer.flushSync(() => old.create('Target', 'After commit'))
      expect(hook.suggestions).toHaveLength(2)
      expect(hook.suggestions[1].offset).toBe('New Before '.length)
    } finally {
      renderer.flushSync(() => renderer.updateContainer(null, root, null, null)); requests.decide.mockReset()
    }
  })

  it('retires hidden Suspense source admission while preserving same-owner recovery and safe reveal', async () => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    const { renderer, root } = concurrentRenderer()
    const sourceVersion = {}, authority = { recoveryIdentity: {}, isAdmissionCurrent: () => true, isCurrent: () => true, canAdmit: () => true }
    let source!: ReturnType<typeof useEditorSourceLoadScope>
    let suggestion!: ReturnType<typeof useSuggestionRecovery>, interview!: ReturnType<typeof useInterviewPrepRecovery>
    let setHidden!: React.Dispatch<React.SetStateAction<boolean>>
    const applyAccepted = vi.fn(() => true)
    const hideGate = new Promise<void>(() => {})
    function Deferred({ hidden }: { hidden: boolean }) {
      if (hidden) throw hideGate
      return React.createElement('ready')
    }
    function Editor() {
      const [hidden, updateHidden] = React.useState(false); setHidden = updateHidden
      source = useEditorSourceLoadScope('owner-a', 'document-a', sourceVersion, true)
      interview = useInterviewPrepRecovery({ ownerId: 'owner-a', resumeId: 'document-a', authToken: 'token-a',
        authReady: true, sourceReady: source.isSourceReady, can: () => true })
      suggestion = useSuggestionRecovery({ ownerId: 'owner-a', documentId: 'document-a', authToken: 'token-a', authReady: true,
        sourceVersion, role: 'owner', can: () => true, canEdit: source.isSourceReady(), authorName: 'Owner',
        readSource: () => 'Before Target After', applyAccepted })
      return React.createElement('editor', null, React.createElement(Deferred, { hidden }))
    }
    try {
      await act(async () => renderer.updateContainer(React.createElement(AccountContentScopeProvider, { value: authority },
        React.createElement(React.Suspense, { fallback: 'loading' }, React.createElement(Editor))), root, null, null))
      await act(async () => {
        const load = source.beginLoad(), proposalLoad = suggestion.beginDocumentLoad()
        expect(source.finishLoad(load, 'ready', 'server')).toBe(true)
        expect(suggestion.finishDocumentLoad(proposalLoad, true, 'owner')).toBe(true)
      })
      expect(source.isSourceReady()).toBe(true); expect(suggestion.canSuggest).toBe(true); expect(suggestion.canAccept).toBe(true)
      await act(async () => { expect(interview.activate()).toBe(true); suggestion.create('Target', 'Changed') })
      const retained = suggestion, proposal = retained.suggestions[0], recovery = interview.scopeRef.current
      const ready = source.isSourceReady
      await act(async () => renderer.flushSync(() => setHidden(true)))
      expect(ready()).toBe(false)
      await act(async () => { retained.create('Target', 'Hidden'); await retained.accept(proposal.id) })
      expect(requests.decide).not.toHaveBeenCalled(); expect(applyAccepted).not.toHaveBeenCalled()
      expect(suggestion.suggestions).toHaveLength(1); expect(retained.canReject(proposal)).toBe(true)
      requests.decide.mockResolvedValueOnce({ suggestion_id: proposal.id, status: 'rejected', decided_by_role: 'owner', decided_at: '2026-10-14T00:00:00Z' })
      await act(async () => retained.reject(proposal.id))
      expect(requests.decide).toHaveBeenCalledOnce()
      expect(requests.decide.mock.calls[0][1].status).toBe('rejected')
      expect(requests.decide.mock.calls[0][2].isCurrent()).toBe(true)
      await act(async () => renderer.flushSync(() => setHidden(false)))
      expect(source.isSourceReady()).toBe(true); expect(suggestion.canSuggest).toBe(true); expect(suggestion.canAccept).toBe(true)
      expect(suggestion.suggestions).toHaveLength(1); expect(suggestion.suggestions[0].status).toBe('rejected')
      expect(interview.scopeRef.current).toBe(recovery); expect(interview.mounted).toBe(true)
      await act(async () => retained.create('Target', 'After reveal'))
      expect(suggestion.suggestions).toHaveLength(2)

      // Reconnecting an older committed snapshot cannot revive a newer pending load.
      await act(async () => renderer.flushSync(() => setHidden(true)))
      const load = source.beginLoad(), proposalLoad = suggestion.beginDocumentLoad()
      await act(async () => renderer.flushSync(() => setHidden(false)))
      expect(source.isSourceReady()).toBe(false); expect(suggestion.canSuggest).toBe(false); expect(suggestion.canAccept).toBe(false)
      await act(async () => retained.create('Target', 'Still loading'))
      expect(suggestion.suggestions).toHaveLength(2)
      await act(async () => {
        expect(source.finishLoad(load, 'ready', 'server')).toBe(true)
        expect(suggestion.finishDocumentLoad(proposalLoad, true, 'owner')).toBe(true)
      })
      expect(source.isSourceReady()).toBe(true); expect(suggestion.canSuggest).toBe(true); expect(suggestion.canAccept).toBe(true)
      expect(interview.scopeRef.current).toBe(recovery)
    } finally {
      await act(async () => renderer.updateContainer(null, root, null, null))
      requests.decide.mockReset(); vi.unstubAllGlobals()
    }
  })

  it('fails closed without outer account authority', () => {
    const { renderer, root } = concurrentRenderer()
    let hook!: ReturnType<typeof useSuggestionRecovery>
    function Unprotected() {
      hook = useSuggestionRecovery({ ownerId: 'owner-a', documentId: 'document-a', authToken: 'token-a', authReady: true,
        sourceVersion: {}, role: 'owner', can: () => true, canEdit: true, authorName: 'Owner',
        readSource: () => 'Target', applyAccepted: () => true })
      return null
    }
    try {
      renderer.flushSync(() => renderer.updateContainer(React.createElement(Unprotected), root, null, null))
      expect(hook.beginDocumentLoad()).toBeNull(); expect(hook.canSuggest).toBe(false); expect(hook.canAccept).toBe(false)
      hook.create('Target', 'No'); expect(hook.suggestions).toEqual([])
    } finally { renderer.flushSync(() => renderer.updateContainer(null, root, null, null)) }
  })

  it('does not publish a superseded default-lane ready snapshot under StrictMode', async () => {
    const { renderer, root } = concurrentRenderer()
    let hook!: ReturnType<typeof useSuggestionRecovery>, force!: () => void
    const sourceVersion = {}, authority = { recoveryIdentity: {}, isAdmissionCurrent: () => true, isCurrent: () => true, canAdmit: () => true }
    function ActualStrictSource() {
      const [, update] = React.useState(0); force = () => update(value => value + 1)
      hook = useSuggestionRecovery({ ownerId: 'owner-a', documentId: 'document-a', authToken: 'token-a', authReady: true,
        sourceVersion, role: 'owner', can: () => true, canEdit: true, authorName: 'Owner', readSource: () => 'Target', applyAccepted: () => true })
      return null
    }
    const settleCommit = async () => { await new Promise(resolve => setTimeout(resolve, 25)); renderer.flushSync(() => force()) }
    try {
      renderer.flushSync(() => renderer.updateContainer(React.createElement(React.StrictMode, null,
        React.createElement(AccountContentScopeProvider, { value: authority }, React.createElement(ActualStrictSource))), root, null, null))
      await settleCommit()
      const old = hook.beginDocumentLoad(); expect(hook.finishDocumentLoad(old, true, 'owner')).toBe(true)
      let newest!: ReturnType<typeof hook.beginDocumentLoad>
      renderer.flushSync(() => { newest = hook.beginDocumentLoad(); force() })
      await settleCommit()
      expect(hook.canSuggest).toBe(false); expect(hook.canAccept).toBe(false)
      hook.create('Target', 'No'); expect(hook.suggestions).toEqual([])
      expect(hook.finishDocumentLoad(old, true, 'owner')).toBe(false)
      expect(hook.finishDocumentLoad(newest, true, 'owner')).toBe(true)
      expect(hook.canSuggest).toBe(false)
      await settleCommit(); expect(hook.canSuggest).toBe(true)
    } finally { renderer.flushSync(() => renderer.updateContainer(null, root, null, null)) }
  })
})
