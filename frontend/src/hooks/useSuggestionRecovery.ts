'use client'

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useAccountContentScope, type AccountContentScope } from '@/contexts/AccountContentScope'
import { apiClient, type AccountPreferenceRequestContext, type SuggestionDecisionResponse } from '@/lib/api-client'
import { boundSuggestionPresence, canCreateSuggestion, canResolveSuggestion, createSuggestion, mergeSuggestionPresence, type Suggestion, type SuggestionDecision, type SuggestionPresence } from '@/lib/suggestions'

interface Options {
  ownerId: string | null
  documentId: string
  authToken: string | null
  authReady: boolean
  sourceVersion: unknown
  role: string
  can: (feature: string) => boolean
  canEdit: boolean
  authorName: string
  readSource: () => string
  applyAccepted: (expected: string, result: SuggestionDecisionResponse) => boolean
}

function runtime(options: Options, epoch: number, authority: AccountContentScope | null) {
  return {
    ownerId: options.ownerId, documentId: options.documentId, epoch, authority, alive: true, lifetime: 0,
    sourceVersion: options.sourceVersion, authReady: options.authReady, authToken: options.authToken,
    sourceAdmission: {}, sourceReady: false, documentReady: false,
    role: options.role, observedRole: options.role, loadSequence: 0,
    suggestions: [] as Suggestion[], peers: [] as SuggestionPresence[], decisions: [] as SuggestionDecision[],
    mode: false, error: null as string | null,
    draft: null as { findText: string; replacementText: string } | null,
    action: null as { kind: 'accept' | 'reject'; id: string } | null,
  }
}

/** Scope local recovery to a confirmed owner/document incarnation. A transient
 * same-owner refresh retains proposals and rejection/replay recovery. New source
 * admissions wait for the current authenticated document load to finish.
 */
export function useSuggestionRecovery(options: Options) {
  const authority = useAccountContentScope()
  const scope = useRef(runtime(options, 0, authority))
  if (scope.current.ownerId !== options.ownerId || scope.current.documentId !== options.documentId
    || scope.current.authority?.recoveryIdentity !== authority?.recoveryIdentity) {
    scope.current = runtime(options, scope.current.epoch + 1, authority)
  }
  const identity = scope.current
  const current = useRef(options)
  current.current = options
  const [, refresh] = useState(0)
  const [readySource, setReadySource] = useState<{ identity: typeof identity; admission: object; sequence: number } | null>(null)
  const committedSource = useRef<typeof readySource>(null)
  useLayoutEffect(() => {
    committedSource.current = readySource
    if (readySource) refresh(value => value + 1)
  }, [readySource])
  if (identity.sourceVersion !== options.sourceVersion || identity.authReady !== options.authReady || identity.authToken !== options.authToken
    || identity.authority !== authority) {
    identity.sourceVersion = options.sourceVersion
    identity.authReady = options.authReady
    identity.authToken = options.authToken
    identity.authority = authority
    // Retire source tickets during render, before a new passive load begins.
    // Recovery retains its owner/document identity across transient refreshes.
    identity.sourceAdmission = {}
    identity.sourceReady = false
  }
  if (identity.observedRole !== options.role) {
    identity.observedRole = options.role
    identity.role = options.role
  }
  useEffect(() => {
    identity.alive = true
    return () => { identity.alive = false; identity.lifetime += 1 }
  }, [identity])

  const active = useCallback(() => scope.current === identity && identity.alive && Boolean(identity.ownerId) && Boolean(authority?.isCurrent()), [authority, identity])
  const publish = useCallback(() => { if (active()) refresh(value => value + 1) }, [active])
  const mayRecover = useCallback(() => active() && identity.documentReady
    && Boolean(current.current.authToken)
    && apiClient.getAuthToken() === current.current.authToken
    && (identity.role === 'owner' || (['editor', 'commenter', 'viewer'].includes(identity.role) && current.current.can('f04'))), [active, identity])
  const hasCommittedSource = useCallback(() => committedSource.current?.identity === identity
    && committedSource.current.admission === identity.sourceAdmission && committedSource.current.sequence === identity.loadSequence, [identity])
  const mayCreate = useCallback(() => mayRecover() && identity.sourceReady && hasCommittedSource() && Boolean(authority?.canAdmit()) && current.current.authReady
    && current.current.can('f07') && canCreateSuggestion(identity.role), [authority, hasCommittedSource, identity, mayRecover])
  const mayAccept = useCallback(() => mayRecover() && identity.sourceReady && hasCommittedSource() && Boolean(authority?.canAdmit()) && current.current.authReady
    && current.current.canEdit && current.current.can('f07') && current.current.can('c01')
    && canResolveSuggestion(identity.role), [authority, hasCommittedSource, identity, mayRecover])
  const capture = useCallback(() => {
    const token = current.current.authToken
    const lifetime = identity.lifetime
    const isCurrent = () => active() && identity.lifetime === lifetime
      && Boolean(token) && current.current.authToken === token && apiClient.getAuthToken() === token
    return { authToken: token ?? '', isCurrent } satisfies AccountPreferenceRequestContext
  }, [active, identity])

  const beginDocumentLoad = useCallback(() => {
    if (!active() || !authority?.canAdmit()) return null
    identity.sourceReady = false
    identity.loadSequence += 1
    publish()
    return { identity, admission: identity.sourceAdmission, authority, sequence: identity.loadSequence, context: capture() }
  }, [active, authority, capture, identity, publish])
  type LoadTicket = ReturnType<typeof beginDocumentLoad>
  const finishDocumentLoad = useCallback((ticket: LoadTicket, ready: boolean, role?: string) => {
    if (!ticket || ticket.identity !== scope.current || ticket.admission !== ticket.identity.sourceAdmission
      || ticket.sequence !== ticket.identity.loadSequence || !ticket.context.isCurrent()
      || (ready && (!current.current.authReady || !ticket.authority.canAdmit()))) return false
    ticket.identity.sourceReady = ready
    if (ready) {
      ticket.identity.documentReady = true
      // Queue readiness beside the page source updates. Retained callbacks must
      // wait for the matching React commit, including on same-owner reloads.
      setReadySource({ identity: ticket.identity, admission: ticket.admission, sequence: ticket.sequence })
      // The response, rather than the page's default/stale resolver role,
      // establishes authority before React commits the queued role update.
      ticket.identity.role = role ?? current.current.role
      ticket.identity.observedRole = current.current.role
    }
    refresh(value => value + 1)
    return true
  }, [])

  const all = useCallback(() => mergeSuggestionPresence(identity.suggestions, identity.peers, identity.decisions), [identity])
  const record = useCallback((id: string, result: SuggestionDecisionResponse) => {
    identity.suggestions = identity.suggestions.map(item => item.id === id ? { ...item, status: result.status } : item)
    const decision: SuggestionDecision = { id, status: result.status, decidedByRole: result.decided_by_role, decidedAt: Date.parse(result.decided_at) }
    identity.decisions = [...identity.decisions.filter(item => item.id !== id), decision]
  }, [identity])
  const create = useCallback((findText: string, replacementText: string) => {
    if (!active()) return
    if (!mayCreate()) { identity.error = 'Creating suggestions is unavailable for your current permissions.'; publish(); return }
    identity.draft = { findText, replacementText }
    const suggestion = createSuggestion({ source: current.current.readSource(), findText, replacementText,
      authorId: identity.ownerId!, authorName: current.current.authorName })
    if (!suggestion) { identity.error = 'That text is not present in the current document. Edit the text or retry.'; publish(); return }
    identity.suggestions = [...identity.suggestions, suggestion]
    identity.error = null
    publish()
  }, [active, identity, mayCreate, publish])

  const accept = useCallback(async (id: string) => {
    if (!active()) return
    if (!mayAccept()) { identity.error = 'Accepting suggestions is unavailable for your current permissions.'; publish(); return }
    const suggestion = all().find(item => item.id === id && item.status === 'pending')
    if (!suggestion) return
    const source = current.current.readSource()
    const admission = identity.sourceAdmission
    const context = capture()
    identity.action = { kind: 'accept', id }
    try {
      const result = await apiClient.decideSuggestion(identity.documentId, {
        suggestion_id: id, status: 'accepted', expected_content: source, original_text: suggestion.originalText,
        replacement_text: suggestion.replacementText, prefix: suggestion.prefix, suffix: suggestion.suffix,
      }, { ...context, isCurrent: () => context.isCurrent() && identity.sourceAdmission === admission && mayAccept() && current.current.readSource() === source })
      // Admission grants can be revoked after the server commits. Its result
      // is recovery, but only for this exact account/document incarnation.
      if (!context.isCurrent() || !mayRecover()) return
      record(id, result)
      identity.action = null
      if (result.status === 'accepted' && !current.current.applyAccepted(source, result)) {
        identity.error = 'The suggestion was accepted on the server, but this editor changed concurrently. Reload to reconcile it safely.'
      } else identity.error = null
      publish()
    } catch (error) {
      if (!context.isCurrent() || !mayRecover()) return
      identity.error = error instanceof Error ? error.message : 'Could not decide this suggestion. It remains pending.'
      publish()
    }
  }, [active, all, capture, identity, mayAccept, mayRecover, publish, record])

  const reject = useCallback(async (id: string) => {
    if (!active() || !mayRecover()) return
    const suggestion = all().find(item => item.id === id && item.status === 'pending')
    if (!suggestion) return
    const resolver = canResolveSuggestion(identity.role)
    if (!resolver && suggestion.authorId !== identity.ownerId) {
      identity.error = 'Only owners and editors can reject suggestions; authors can withdraw their own.'; publish(); return
    }
    if (!resolver) {
      // Withdrawal is local ephemeral state, never a shared server decision.
      identity.suggestions = identity.suggestions.map(item => item.id === id ? { ...item, status: 'rejected' } : item)
      identity.error = null
      publish()
      return
    }
    const context = capture()
    identity.action = { kind: 'reject', id }
    try {
      const result = await apiClient.decideSuggestion(identity.documentId, {
        suggestion_id: id, status: 'rejected', expected_content: current.current.readSource(),
        original_text: suggestion.originalText, replacement_text: suggestion.replacementText,
        prefix: suggestion.prefix, suffix: suggestion.suffix,
      }, { ...context, isCurrent: () => context.isCurrent() && mayRecover() && canResolveSuggestion(identity.role) })
      if (!context.isCurrent() || !mayRecover()) return
      record(id, result)
      identity.action = null
      identity.error = null
      publish()
    } catch (error) {
      if (!context.isCurrent() || !mayRecover()) return
      identity.error = error instanceof Error ? error.message : 'Could not reject this suggestion. It remains pending.'
      publish()
    }
  }, [active, all, capture, identity, mayRecover, publish, record])

  const confirmRemoteDecisions = useCallback((decisions: SuggestionDecision[]) => {
    if (!mayRecover()) return
    const context = capture()
    for (const candidate of decisions) {
      void apiClient.getSuggestionDecision(identity.documentId, candidate.id, { ...context, isCurrent: () => context.isCurrent() && mayRecover() }).then(confirmed => {
        if (!context.isCurrent() || !mayRecover()) return
        record(confirmed.suggestion_id, confirmed)
        publish()
      }).catch(() => { /* Stale/forged notifications cannot change local status. */ })
    }
  }, [capture, identity, mayRecover, publish, record])
  const remotePresence = useCallback((peers: SuggestionPresence[]) => {
    if (!mayRecover()) return
    identity.peers = peers
    publish()
  }, [identity, mayRecover, publish])
  const retry = useCallback(() => {
    if (!active()) return
    if (identity.action) {
      if (identity.action.kind === 'accept') void accept(identity.action.id)
      else void reject(identity.action.id)
    } else if (identity.draft) create(identity.draft.findText, identity.draft.replacementText)
    else { identity.error = null; publish() }
  }, [accept, active, create, identity, publish, reject])
  const toggleMode = useCallback(() => {
    if (!mayCreate()) return
    identity.mode = !identity.mode
    publish()
  }, [identity, mayCreate, publish])

  const allSuggestions = useMemo(() => mergeSuggestionPresence(identity.suggestions, identity.peers, identity.decisions), [identity.suggestions, identity.peers, identity.decisions])
  const presence = useMemo(() => boundSuggestionPresence({ items: identity.suggestions.filter(item => item.status === 'pending').slice(0, 50), decisions: [] }), [identity.suggestions])
  return {
    key: `suggestions:${identity.epoch}`, suggestions: identity.suggestions, allSuggestions,
    decisions: identity.decisions, mode: identity.mode, error: identity.error,
    presence,
    canSuggest: mayCreate(), canAccept: mayAccept(),
    canReject: (suggestion: Suggestion) => mayRecover() && (canResolveSuggestion(identity.role) || suggestion.authorId === identity.ownerId),
    create, accept, reject, retry, toggleMode, remotePresence, confirmRemoteDecisions, beginDocumentLoad, finishDocumentLoad,
  }
}
