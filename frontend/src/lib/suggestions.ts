/** Bounded local suggestion anchors for collaborative editing (#1390).
 *
 * Suggestions are deliberately separate from Y.Text: creating one never
 * writes the shared document. Acceptance is an explicit owner/editor action
 * and resolves the original text plus nearby context against the latest
 * source before applying. Ambiguous or stale anchors become conflicted.
 */

export interface Suggestion {
  id: string
  authorId: string
  authorName: string
  createdAt: number
  originalText: string
  replacementText: string
  offset: number
  prefix: string
  suffix: string
  status: 'pending' | 'accepted' | 'rejected' | 'conflicted'
  conflictReason?: string
}

export interface SuggestionDecision {
  id: string
  status: 'accepted' | 'rejected' | 'conflicted'
  decidedByRole: 'owner' | 'editor'
  decidedAt: number
}

export interface SuggestionPresence {
  items: Suggestion[]
  decisions: SuggestionDecision[]
}

export const MAX_SUGGESTIONS_PER_PEER = 50
export const MAX_SUGGESTION_TEXT = 2_000
/** Keep each awareness frame well below the collaboration provider's limit. */
export const MAX_SUGGESTION_PAYLOAD_BYTES = 48 * 1024
/** Character limits are useful for UX; byte limits are the actual transport guard. */
export const MAX_SUGGESTION_FIELD_BYTES = 8 * 1024
export const MAX_SHARED_SUGGESTION_DECISIONS = 50
const MAX_SUGGESTION_ID_BYTES = 512

export function utf8ByteLength(value: string): number {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(value).byteLength
  // The fallback is only for unusual non-browser test runtimes.
  return encodeURIComponent(value).replace(/%[0-9A-F]{2}|./g, '_').length
}

function boundedText(value: unknown, maxCharacters: number, maxBytes = MAX_SUGGESTION_FIELD_BYTES): value is string {
  return typeof value === 'string' && value.length <= maxCharacters && utf8ByteLength(value) <= maxBytes
}

export function sanitizeSuggestionDecision(value: unknown): SuggestionDecision | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<SuggestionDecision>
  return boundedText(candidate.id, 320, MAX_SUGGESTION_ID_BYTES) &&
    (candidate.status === 'accepted' || candidate.status === 'rejected' || candidate.status === 'conflicted') &&
    (candidate.decidedByRole === 'owner' || candidate.decidedByRole === 'editor') &&
    typeof candidate.decidedAt === 'number' && Number.isFinite(candidate.decidedAt)
    ? candidate as SuggestionDecision
    : null
}

/** Keep the authoritative decision log bounded even across long-lived rooms. */
export function keepLatestSuggestionDecisions(values: unknown[]): SuggestionDecision[] {
  return values
    .map((value) => sanitizeSuggestionDecision(value))
    .filter((value): value is SuggestionDecision => value !== null)
    .sort((a, b) => a.decidedAt - b.decidedAt)
    .slice(-MAX_SHARED_SUGGESTION_DECISIONS)
}

export function canCreateSuggestion(role: string | null | undefined): boolean {
  return role === 'owner' || role === 'editor' || role === 'commenter'
}

export function canResolveSuggestion(role: string | null | undefined): boolean {
  return role === 'owner' || role === 'editor'
}

const CONTEXT_CHARS = 48

export function createSuggestion(input: {
  source: string
  findText: string
  replacementText: string
  authorId: string
  authorName: string
}): Suggestion | null {
  const originalText = input.findText
  if (!boundedText(originalText, MAX_SUGGESTION_TEXT) || !boundedText(input.replacementText, MAX_SUGGESTION_TEXT) ||
    !boundedText(input.authorId, 120, 512) || !boundedText(input.authorName, 120, 512)) return null
  const offset = input.source.indexOf(originalText)
  if (offset < 0) return null
  return {
    id: `suggestion-${input.authorId}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    authorId: input.authorId,
    authorName: input.authorName,
    createdAt: Date.now(),
    originalText,
    replacementText: input.replacementText,
    offset,
    prefix: input.source.slice(Math.max(0, offset - CONTEXT_CHARS), offset),
    suffix: input.source.slice(offset + originalText.length, offset + originalText.length + CONTEXT_CHARS),
    status: 'pending',
  }
}

/** Validate untrusted awareness payloads before they enter React state. */
export function sanitizeSuggestionPresence(value: unknown): SuggestionPresence {
  if (!value || typeof value !== 'object') return { items: [], decisions: [] }
  const raw = value as { items?: unknown; decisions?: unknown }
  const items: Suggestion[] = []
  if (Array.isArray(raw.items)) for (const item of raw.items.slice(0, MAX_SUGGESTIONS_PER_PEER)) {
    if (!item || typeof item !== 'object') continue
    const candidate = item as Partial<Suggestion>
    if (!boundedText(candidate.id, 320, MAX_SUGGESTION_ID_BYTES) ||
      !boundedText(candidate.authorId, 120, 512) ||
      !boundedText(candidate.authorName, 120, 512) ||
      !boundedText(candidate.originalText, MAX_SUGGESTION_TEXT) ||
      !boundedText(candidate.replacementText, MAX_SUGGESTION_TEXT) ||
      typeof candidate.offset !== 'number' || !Number.isInteger(candidate.offset) || candidate.offset < 0 ||
      !boundedText(candidate.prefix, CONTEXT_CHARS, 512) ||
      !boundedText(candidate.suffix, CONTEXT_CHARS, 512) ||
      typeof candidate.createdAt !== 'number' || !Number.isFinite(candidate.createdAt) ||
      candidate.status !== 'pending') continue
    const next = candidate as Suggestion
    const candidateBytes = utf8ByteLength(JSON.stringify({ items: [...items, next], decisions: [] }))
    if (candidateBytes > MAX_SUGGESTION_PAYLOAD_BYTES) break
    items.push(next)
  }
  // Decisions are authoritative only from the Y.Map transport, never from
  // client-controlled awareness. Keep this field empty for compatibility.
  return { items, decisions: [] }
}

/** Sanitize before publishing as awareness, so local callers obey the same guard. */
export function boundSuggestionPresence(value: SuggestionPresence): SuggestionPresence {
  return sanitizeSuggestionPresence({ items: value.items, decisions: [] })
}

/**
 * Awareness client ids are transport-scoped and therefore are part of the
 * proposal identity when a peer payload enters the app. This prevents one
 * peer from shadowing another peer's proposal by forging the same local id.
 */
export function namespaceSuggestionPresence(value: SuggestionPresence, peerId: number | string): SuggestionPresence {
  const sanitized = sanitizeSuggestionPresence(value)
  const namespace = String(peerId).replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 32) || 'peer'
  // Prefixing consumes a small amount of frame budget; sanitize once more so
  // the internal snapshot remains bounded even at the raw payload ceiling.
  return sanitizeSuggestionPresence({
    items: sanitized.items.map((item) => ({ ...item, id: `${namespace}:${item.id}` })),
    decisions: [],
  })
}

/** Deterministically merge local and peer awareness snapshots for every client. */
export function mergeSuggestionPresence(local: Suggestion[], peers: SuggestionPresence[], localDecisions: SuggestionDecision[]): Suggestion[] {
  const merged = new Map<string, Suggestion>()
  for (const item of [...local, ...peers.flatMap((peer) => peer.items)]) {
    if (!merged.has(item.id)) merged.set(item.id, item)
  }
  for (const decision of [...localDecisions, ...peers.flatMap((peer) => peer.decisions)]) {
    const item = merged.get(decision.id)
    if (item && item.status === 'pending') merged.set(item.id, applySuggestionDecision(item, decision))
  }
  return Array.from(merged.values())
}

/** Apply a server-confirmed decision idempotently to a local proposal snapshot. */
export function applySuggestionDecision(item: Suggestion, decision: SuggestionDecision): Suggestion {
  if (item.id !== decision.id || item.status !== 'pending') return item
  return { ...item, status: decision.status, conflictReason: decision.status === 'conflicted' ? 'A peer could not resolve this anchor.' : item.conflictReason }
}

/** Resolve only a unique exact occurrence with its original nearby context. */
export function resolveSuggestion(source: string, suggestion: Suggestion): { start: number; end: number } | null {
  const candidates: Array<{ start: number; score: number }> = []
  let cursor = 0
  while (cursor <= source.length) {
    const found = source.indexOf(suggestion.originalText, cursor)
    if (found < 0) break
    const prefixStart = Math.max(0, found - suggestion.prefix.length)
    const prefix = source.slice(prefixStart, found)
    const suffix = source.slice(found + suggestion.originalText.length, found + suggestion.originalText.length + suggestion.suffix.length)
    let prefixMatch = 0
    while (prefixMatch < prefix.length && prefixMatch < suggestion.prefix.length &&
      prefix[prefix.length - 1 - prefixMatch] === suggestion.prefix[suggestion.prefix.length - 1 - prefixMatch]) prefixMatch += 1
    let suffixMatch = 0
    while (suffixMatch < suffix.length && suffixMatch < suggestion.suffix.length && suffix[suffixMatch] === suggestion.suffix[suffixMatch]) suffixMatch += 1
    candidates.push({ start: found, score: prefixMatch + suffixMatch })
    cursor = found + Math.max(1, suggestion.originalText.length)
  }
  if (candidates.length === 0) return null
  const highest = Math.max(...candidates.map((candidate) => candidate.score))
  const best = candidates.filter((candidate) => candidate.score === highest)
  // A single exact occurrence is unambiguous even if the selected text spans
  // the whole document and has no prefix/suffix. Context is required only to
  // distinguish multiple occurrences.
  return best.length === 1
    ? { start: best[0].start, end: best[0].start + suggestion.originalText.length }
    : null
}

export function lineColumnAt(source: string, offset: number): { line: number; column: number } {
  const before = source.slice(0, offset)
  const lines = before.split('\n')
  return { line: lines.length, column: (lines[lines.length - 1]?.length ?? 0) + 1 }
}

export function markSuggestionConflict(suggestion: Suggestion, reason: string): Suggestion {
  return { ...suggestion, status: 'conflicted', conflictReason: reason }
}
