/**
 * Feature 41 — Track Changes via Y.js
 *
 * Observes a Y.js YText for remote edits and maintains a list of TrackedChange
 * objects. Supports accept / reject per-change and in batch.
 *
 * No direct yjs import — receives yText, provider, and the dynamically loaded
 * Y.js positioning helpers to keep collaboration code out of the base bundle.
 */

export interface TrackedChange {
  id: string
  clientId: number
  userId: string
  userName: string
  userColor: string
  type: 'insertion' | 'deletion'
  text: string
  offset: number
  length: number
  range: {
    startLineNumber: number
    startColumn: number
    endLineNumber: number
    endColumn: number
  }
  timestamp: number
  resolved: boolean
}

export interface TrackChangesHandle {
  getChanges: () => TrackedChange[]
  acceptChange: (id: string) => void
  /** False means the tracked range can no longer be proven safe to mutate. */
  rejectChange: (id: string) => boolean
  acceptAll: () => void
  /** False means at least one conflicting change was left pending. */
  rejectAll: () => boolean
  cleanup: () => void
}

interface RelativePositionApi {
  createRelativePositionFromTypeIndex: (type: any, index: number, assoc?: number) => any
  createAbsolutePositionFromRelativePosition: (position: any, doc: any) => {
    type: any
    index: number
  } | null
}

interface ChangeAnchors {
  start: any
  end?: any
}

function computeRange(text: string, offset: number, length: number) {
  const before = text.slice(0, offset)
  const lines = before.split('\n')
  const startLine = lines.length
  const startCol = (lines[lines.length - 1]?.length ?? 0) + 1

  const segment = text.slice(offset, offset + Math.max(length, 1))
  const segLines = segment.split('\n')
  const endLine = startLine + segLines.length - 1
  const endCol =
    segLines.length === 1
      ? startCol + segment.length - 1
      : (segLines[segLines.length - 1]?.length ?? 0) + 1

  return {
    startLineNumber: startLine,
    startColumn: startCol,
    endLineNumber: endLine,
    endColumn: endCol,
  }
}

export function observeChanges(
  yText: any,
  provider: any,
  onUpdate: (changes: TrackedChange[]) => void,
  relativePositions?: RelativePositionApi,
): TrackChangesHandle {
  const changes = new Map<string, TrackedChange>()
  const anchors = new Map<string, ChangeAnchors>()
  let prevText: string = yText.toString()

  const resolveAnchor = (anchor: any): number | null => {
    if (!relativePositions || !yText.doc || !anchor) return null
    const absolute = relativePositions.createAbsolutePositionFromRelativePosition(anchor, yText.doc)
    if (!absolute || absolute.type !== yText) return null
    return absolute.index
  }

  const pendingChanges = (): TrackedChange[] => {
    const current = yText.toString()
    return Array.from(changes.values())
      .filter((change) => !change.resolved)
      .map((change) => {
        const anchor = anchors.get(change.id)
        const start = anchor ? resolveAnchor(anchor.start) : null
        const end = anchor?.end ? resolveAnchor(anchor.end) : null
        if (start != null) {
          change.offset = start
          change.length = change.type === 'insertion' && end != null
            ? Math.max(0, end - start)
            : change.length
          change.range = computeRange(current, start, change.type === 'insertion' ? change.length : 0)
        }
        return change
      })
  }

  const emitUpdate = () => onUpdate(pendingChanges())

  const observer = (event: any, transaction: any) => {
    // Capture snapshot at the very start of each callback so it always reflects
    // the state BEFORE this event regardless of call ordering.
    const snapshot = prevText

    // Only track remote changes.
    // y-websocket passes the WebsocketProvider instance as transactionOrigin when
    // applying remote updates: readSyncMessage(decoder, encoder, doc, provider).
    // Local edits from MonacoBinding use origin=binding or null, so this check
    // correctly distinguishes remote from local.
    if (transaction.origin === provider) {
      const currentText = yText.toString()
      let offset = 0

      for (const op of event.delta) {
        if (op.retain != null) {
          offset += op.retain
        } else if (op.insert != null) {
          const text = typeof op.insert === 'string' ? op.insert : ''
          const length = text.length

          // Try to attribute to a specific client via added items
          let clientId = 0
          if (event.changes?.added) {
            for (const item of event.changes.added) {
              if (item.id?.client != null) {
                clientId = item.id.client
                break
              }
            }
          }

          const awareness = provider.awareness?.getStates?.() as Map<number, any> | undefined
          const state = awareness?.get(clientId)
          const user = state?.user ?? {}

          const id = `ins-${Date.now()}-${Math.random().toString(36).slice(2)}`
          changes.set(id, {
            id,
            clientId,
            userId: user.id ?? String(clientId),
            userName: user.name ?? `User ${clientId}`,
            userColor: user.color ?? '#888',
            type: 'insertion',
            text,
            offset,
            length,
            range: computeRange(currentText, offset, length),
            timestamp: Date.now(),
            resolved: false,
          })
          if (relativePositions && yText.doc) {
            anchors.set(id, {
              // Associate the boundaries with the inserted CRDT items. Unlike
              // numeric offsets, these positions survive unrelated edits.
              start: relativePositions.createRelativePositionFromTypeIndex(yText, offset, 0),
              end: relativePositions.createRelativePositionFromTypeIndex(yText, offset + length, -1),
            })
          }
          offset += length
        } else if (op.delete != null) {
          const length = op.delete
          const text = snapshot.slice(offset, offset + length)

          // Y.js CRDT does not record who deleted text — only who originally
          // created each character. Attribution for deletions is therefore
          // best-effort and shown as "A collaborator" to avoid misleading UI.
          const id = `del-${Date.now()}-${Math.random().toString(36).slice(2)}`
          changes.set(id, {
            id,
            clientId: 0,
            userId: 'unknown',
            userName: 'A collaborator',
            userColor: '#6b7280',
            type: 'deletion',
            text,
            offset,
            length,
            range: computeRange(snapshot, offset, length),
            timestamp: Date.now(),
            resolved: false,
          })
          if (relativePositions && yText.doc) {
            anchors.set(id, {
              start: relativePositions.createRelativePositionFromTypeIndex(yText, offset, 0),
            })
          }
          // offset does NOT advance for deletions (text was removed)
        }
      }
    }

    prevText = yText.toString()
    emitUpdate()
  }

  yText.observe(observer)

  return {
    getChanges: pendingChanges,

    acceptChange(id: string) {
      const c = changes.get(id)
      if (!c) return
      c.resolved = true
      changes.set(id, c)
      anchors.delete(id)
      emitUpdate()
    },

    rejectChange(id: string) {
      const c = changes.get(id)
      if (!c || c.resolved) return false

      const current = yText.toString()
      if (c.type === 'insertion') {
        const anchor = anchors.get(id)
        const anchoredStart = anchor ? resolveAnchor(anchor.start) : null
        const anchoredEnd = anchor?.end ? resolveAnchor(anchor.end) : null
        const start = anchoredStart ?? c.offset
        const end = anchoredEnd ?? start + c.text.length

        // Never search the document by value: duplicate LaTeX fragments are
        // common and deleting the first match can corrupt an unrelated range.
        if (start < 0 || end < start || current.slice(start, end) !== c.text) return false
        yText.delete(start, end - start)
      } else {
        const anchor = anchors.get(id)
        const anchoredStart = anchor ? resolveAnchor(anchor.start) : null
        const insertAt = Math.min(anchoredStart ?? c.offset, current.length)
        if (insertAt < 0) return false
        yText.insert(insertAt, c.text)
      }

      c.resolved = true
      changes.set(id, c)
      anchors.delete(id)
      emitUpdate()
      return true
    },

    acceptAll() {
      for (const [id, c] of changes) {
        if (!c.resolved) {
          c.resolved = true
          changes.set(id, c)
          anchors.delete(id)
        }
      }
      onUpdate([])
    },

    rejectAll() {
      let allRejected = true
      // Descending current offsets keep the non-Y.js test fallback safe; real
      // collaboration uses relative positions and is order independent.
      const ids = pendingChanges()
        .sort((a, b) => b.offset - a.offset)
        .map((change) => change.id)
      for (const id of ids) {
        if (!this.rejectChange(id)) allRejected = false
      }
      return allRejected
    },

    cleanup() {
      yText.unobserve(observer)
    },
  }
}
