import { describe, expect, it } from 'vitest'
import { applySuggestionDecision, canCreateSuggestion, canResolveSuggestion, createSuggestion, keepLatestSuggestionDecisions, lineColumnAt, markSuggestionConflict, MAX_SHARED_SUGGESTION_DECISIONS, MAX_SUGGESTION_PAYLOAD_BYTES, mergeSuggestionPresence, namespaceSuggestionPresence, resolveSuggestion, sanitizeSuggestionPresence, utf8ByteLength } from '@/lib/suggestions'

describe('bounded collaboration suggestions', () => {
  it('creates a draft without mutating source and resolves after nearby insertion', () => {
    const source = 'Intro\nTarget phrase\nConclusion'
    const suggestion = createSuggestion({
      source,
      findText: 'Target phrase',
      replacementText: 'Improved phrase',
      authorId: 'editor-1',
      authorName: 'Editor',
    })!
    expect(source).toBe('Intro\nTarget phrase\nConclusion')
    const resolved = resolveSuggestion('Intro\nNew nearby line\nTarget phrase\nConclusion', suggestion)
    expect(resolved).toEqual({ start: 22, end: 35 })
    expect(lineColumnAt('Intro\nNew nearby line\nTarget phrase\nConclusion', resolved!.start)).toEqual({ line: 3, column: 1 })
  })

  it('does not guess when duplicate text has ambiguous anchors', () => {
    const suggestion = createSuggestion({
      source: 'Target',
      findText: 'Target',
      replacementText: 'Changed',
      authorId: 'owner-1',
      authorName: 'Owner',
    })!
    expect(resolveSuggestion('Target Target', suggestion)).toBeNull()
    expect(markSuggestionConflict(suggestion, 'ambiguous').status).toBe('conflicted')
  })

  it('resolves one exact occurrence even when the selection has no surrounding context', () => {
    const suggestion = createSuggestion({
      source: 'Target',
      findText: 'Target',
      replacementText: 'Changed',
      authorId: 'owner-1',
      authorName: 'Owner',
    })!

    expect(resolveSuggestion('Target', suggestion)).toEqual({ start: 0, end: 6 })
  })

  it('marks a direct edit inside the anchor as conflicted instead of applying elsewhere', () => {
    const suggestion = createSuggestion({
      source: 'Keep Target phrase here',
      findText: 'Target phrase',
      replacementText: 'Changed',
      authorId: 'editor-1',
      authorName: 'Editor',
    })!
    expect(resolveSuggestion('Keep Target altered here', suggestion)).toBeNull()
  })

  it('allows commenter proposals but reserves resolution for owner/editor roles', () => {
    expect(canCreateSuggestion('commenter')).toBe(true)
    expect(canCreateSuggestion('viewer')).toBe(false)
    expect(canResolveSuggestion('commenter')).toBe(false)
    expect(canResolveSuggestion('editor')).toBe(true)
  })

  it('bounds and validates awareness payloads', () => {
    const payload = sanitizeSuggestionPresence({
      items: [{ id: 's1', authorId: 'u1', authorName: 'U', originalText: 'x', replacementText: 'y', offset: 0, prefix: '', suffix: '', createdAt: Date.now(), status: 'pending' }, { id: 'bad', status: 'accepted' }],
      decisions: [{ id: 's1', status: 'accepted', decidedByRole: 'commenter', decidedAt: Date.now() }],
    })
    expect(payload.items).toHaveLength(1)
    expect(payload.decisions).toHaveLength(0)
  })

  it('converges peer awareness after one authorized resolution without source writes', () => {
    const proposal = createSuggestion({ source: 'Target', findText: 'Target', replacementText: 'Changed', authorId: 'commenter', authorName: 'Commenter' })!
    const decision = { id: proposal.id, status: 'accepted' as const, decidedByRole: 'editor' as const, decidedAt: Date.now() }
    const peerA = mergeSuggestionPresence([proposal], [{ items: [], decisions: [decision] }], [])
    const peerB = mergeSuggestionPresence([], [{ items: [proposal], decisions: [decision] }], [])
    expect(peerA[0].status).toBe('accepted')
    expect(peerB[0].status).toBe('accepted')
    expect('Target').toBe('Target')
  })

  it('bounds awareness by UTF-8 bytes as well as item count', () => {
    const emoji = '😀'.repeat(1_000)
    const item = {
      id: 'emoji', authorId: 'u1', authorName: '😀', originalText: emoji,
      replacementText: emoji, offset: 0, prefix: '', suffix: '', createdAt: 1, status: 'pending' as const,
    }
    // Multibyte fields are valid individually, but a peer cannot publish an
    // unbounded collection that would exceed the provider frame budget.
    const payload = sanitizeSuggestionPresence({ items: Array.from({ length: 50 }, (_, index) => ({ ...item, id: `emoji-${index}` })) })
    expect(payload.items.length).toBeLessThan(50)
    expect(utf8ByteLength(JSON.stringify(payload))).toBeLessThanOrEqual(MAX_SUGGESTION_PAYLOAD_BYTES)
    expect(sanitizeSuggestionPresence({ items: Array.from({ length: 100 }, (_, index) => ({ ...item, id: `short-${index}`, originalText: 'x', replacementText: 'y' })) }).items).toHaveLength(50)
    expect(createSuggestion({ source: emoji, findText: emoji, replacementText: 'x', authorId: 'u1', authorName: '😀' })).not.toBeNull()
    expect(createSuggestion({ source: emoji, findText: '😀'.repeat(1_001), replacementText: 'x', authorId: 'u1', authorName: 'U' })).toBeNull()
  })

  it('namespaces peer ids so duplicate local ids remain isolated', () => {
    const first = { id: 'suggestion-author-a-1', authorId: 'a', authorName: 'A', originalText: 'x', replacementText: 'one', offset: 0, prefix: '', suffix: '!', createdAt: 1, status: 'pending' as const }
    const forged = { ...first, replacementText: 'two' }
    const merged = mergeSuggestionPresence([], [namespaceSuggestionPresence({ items: [first], decisions: [] }, 11), namespaceSuggestionPresence({ items: [forged], decisions: [] }, 12)], [])
    expect(merged).toHaveLength(2)
    expect(new Set(merged.map((item) => item.id))).toEqual(new Set(['11:suggestion-author-a-1', '12:suggestion-author-a-1']))
  })

  it('lets two independent clients observe one decision and apply it only once', () => {
    const proposal = createSuggestion({ source: 'Target!', findText: 'Target', replacementText: 'Changed', authorId: 'commenter', authorName: 'Commenter' })!
    const peerA = namespaceSuggestionPresence({ items: [proposal], decisions: [] }, 21).items[0]
    const peerB = namespaceSuggestionPresence({ items: [proposal], decisions: [] }, 22).items[0]
    const decision = { id: peerA.id, status: 'accepted' as const, decidedByRole: 'owner' as const, decidedAt: Date.now() }
    const afterFirst = applySuggestionDecision(peerA, decision)
    const afterSecond = applySuggestionDecision(afterFirst, { ...decision, status: 'rejected' })
    expect(afterFirst.status).toBe('accepted')
    expect(afterSecond.status).toBe('accepted')
    expect(mergeSuggestionPresence([], [{ items: [peerA], decisions: [] }, { items: [peerB], decisions: [] }], [decision]).filter((item) => item.status === 'accepted')).toHaveLength(1)
  })

  it('maps a namespaced remote decision back to its author local proposal', () => {
    const proposal = createSuggestion({ source: 'Target!', findText: 'Target', replacementText: 'Changed', authorId: 'commenter', authorName: 'Commenter' })!
    const namespaced = namespaceSuggestionPresence({ items: [proposal], decisions: [] }, 31).items[0]
    const remoteDecision = { id: namespaced.id, status: 'accepted' as const, decidedByRole: 'owner' as const, decidedAt: Date.now() }
    // The provider strips the author's own transport prefix on that client.
    expect(mergeSuggestionPresence([proposal], [], [{ ...remoteDecision, id: proposal.id }])[0].status).toBe('accepted')
  })

  it('keeps the authoritative decision map bounded and drops malformed values', () => {
    const values = Array.from({ length: MAX_SHARED_SUGGESTION_DECISIONS + 5 }, (_, index) => ({
      id: `peer-${index}:suggestion-${index}`, status: 'accepted' as const, decidedByRole: 'owner' as const, decidedAt: index,
    }))
    values.push({ id: 'bad', status: 'accepted', decidedByRole: 'commenter' as never, decidedAt: 999 })
    const retained = keepLatestSuggestionDecisions(values)
    expect(retained).toHaveLength(MAX_SHARED_SUGGESTION_DECISIONS)
    expect(retained[0].id).toContain('peer-5')
    expect(retained.some((item) => item.id === 'bad')).toBe(false)
  })
})
