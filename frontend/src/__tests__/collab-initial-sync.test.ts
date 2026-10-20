import { describe, expect, it, vi } from 'vitest'
import * as Y from 'yjs'
import { bindCollaborationWithoutDiscardingDraft, canSeedCollaborationDocument } from '@/lib/collab-initial-sync'
import { recoveredDraftBaseline, canAcknowledgeCollaborationRecovery, type OfflineDraft } from '@/lib/offline-drafts'

const recovery: OfflineDraft = {
  ownerId: 'actor', resumeId: 'document', title: 'T1', latexContent: 'L',
  expectedLatexContent: 'A', collaborationPaused: true, savedAt: new Date(), syncStatus: 'conflict',
}

describe('initial collaboration admission', () => {
  it('does not seed a recovered L into an empty relay after SQL advances to P', () => {
    const doc = new Y.Doc()
    const text = doc.getText('content')
    const baseline = recoveredDraftBaseline(recovery, 'P')
    expect(baseline).toBe('A')
    expect(canSeedCollaborationDocument({ localValue: recovery.latexContent, remoteValue: text.toString(),
      hasHistory: Y.decodeStateVector(Y.encodeStateVector(doc)).size > 0, readOnly: false,
      paused: Boolean(recovery.collaborationPaused) })).toBe(false)
    const bind = vi.fn()
    expect(bindCollaborationWithoutDiscardingDraft({ hasLocalEdits: false, hasParentDraft: false,
      hasRecoveredDraft: true, localValue: 'L', remoteValue: '', bind })).toBeNull()
    expect(bind).not.toHaveBeenCalled()
    expect(text.toString()).toBe('')
    doc.destroy()
  })

  it('allows a clean peer to adopt live unsaved CRDT content ahead of SQL', () => {
    const doc = new Y.Doc()
    doc.getText('content').insert(0, 'A + peer unsaved')
    let model = 'A'
    const binding = { destroy: vi.fn() }
    const result = bindCollaborationWithoutDiscardingDraft({ hasLocalEdits: false,
      hasParentDraft: false, localValue: model, remoteValue: doc.getText('content').toString(),
      bind: () => { model = doc.getText('content').toString(); return binding } })
    expect(result).toBe(binding)
    expect(model).toBe('A + peer unsaved')
    // The same peer after a successful SQL save/reload remains bindable.
    expect(bindCollaborationWithoutDiscardingDraft({ hasLocalEdits: false,
      localValue: model, remoteValue: model, bind: () => binding })).toBe(binding)
    doc.destroy()
  })

  it.each(['local', 'parent', 'recovered'])('retains a divergent %s draft without mutating peer CRDT', kind => {
    const bind = vi.fn()
    expect(bindCollaborationWithoutDiscardingDraft({ hasLocalEdits: kind === 'local',
      hasParentDraft: kind === 'parent', hasRecoveredDraft: kind === 'recovered',
      localValue: 'local', remoteValue: 'peer', bind })).toBeNull()
    expect(bind).not.toHaveBeenCalled()
  })

  it('allows equality to rejoin without replacing either complete document', () => {
    const binding = {}
    expect(bindCollaborationWithoutDiscardingDraft({ hasLocalEdits: true, hasParentDraft: true,
      hasRecoveredDraft: true, localValue: 'same', remoteValue: 'same', bind: () => binding })).toBe(binding)
  })

  it('does not confuse an intentional peer delete-all with an uninitialized room', () => {
    const doc = new Y.Doc()
    const text = doc.getText('content')
    text.insert(0, 'peer'); text.delete(0, text.length)
    expect(canSeedCollaborationDocument({ localValue: 'old SQL', remoteValue: text.toString(),
      hasHistory: Y.decodeStateVector(Y.encodeStateVector(doc)).size > 0, readOnly: false, paused: false })).toBe(false)
    doc.destroy()
  })

  it('seeds only a fresh writable room without unresolved recovery', () => {
    const input = { localValue: 'new', remoteValue: '', hasHistory: false, readOnly: false, paused: false }
    expect(canSeedCollaborationDocument(input)).toBe(true)
    expect(canSeedCollaborationDocument({ ...input, readOnly: true })).toBe(false)
    expect(canSeedCollaborationDocument({ ...input, paused: true })).toBe(false)
  })

  it('acknowledges its own saved SQL source but never a different writer', () => {
    expect(recoveredDraftBaseline(recovery, 'L')).toBe('L')
    expect(recoveredDraftBaseline(recovery, 'P')).toBe('A')
    expect(recoveredDraftBaseline({ ...recovery, expectedLatexContent: undefined }, 'P')).toBe('')
    expect(recoveredDraftBaseline(null, 'P')).toBe('P')
  })
})


describe('durable title acknowledgment', () => {
  const current = { title: 'T1', savedTitle: 'T0', savedSource: 'L', modelSource: 'L', relaySource: 'L' }
  it('retains recovered T1 after source-only equality/rebind before title save', () => {
    expect(canAcknowledgeCollaborationRecovery(recovery, current)).toBe(false)
  })
  it('acknowledges only after both source and title have saved', () => {
    expect(canAcknowledgeCollaborationRecovery(recovery, { ...current, savedTitle: 'T1' })).toBe(true)
  })
  it('retains a newer title edit while acknowledgment is pending', () => {
    expect(canAcknowledgeCollaborationRecovery(recovery, { ...current, savedTitle: 'T1', title: 'T2' })).toBe(false)
  })
  it('does not acknowledge current source when a peer or server differs', () => {
    expect(canAcknowledgeCollaborationRecovery(recovery, { ...current, savedTitle: 'T1', relaySource: 'P' })).toBe(false)
    expect(canAcknowledgeCollaborationRecovery(recovery, { ...current, savedTitle: 'T1', savedSource: 'P' })).toBe(false)
  })
})
