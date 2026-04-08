/**
 * Feature 41 — Track Changes via Y.js
 *
 * Observes a Y.js YText for remote edits and maintains a list of TrackedChange
 * objects. Supports accept / reject per-change and in batch.
 *
 * No direct yjs import — receives yText and provider as `any` to avoid
 * bundling yjs into the module (it's loaded dynamically in the editor).
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
  rejectChange: (id: string) => void
  acceptAll: () => void
  rejectAll: () => void
  cleanup: () => void
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
): TrackChangesHandle {
  const changes = new Map<string, TrackedChange>()
  let prevText: string = yText.toString()

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
          // offset does NOT advance for deletions (text was removed)
        }
      }
    }

    prevText = yText.toString()
    onUpdate(Array.from(changes.values()).filter((c) => !c.resolved))
  }

  yText.observe(observer)

  return {
    getChanges: () => Array.from(changes.values()).filter((c) => !c.resolved),

    acceptChange(id: string) {
      const c = changes.get(id)
      if (!c) return
      c.resolved = true
      changes.set(id, c)
      onUpdate(Array.from(changes.values()).filter((x) => !x.resolved))
    },

    rejectChange(id: string) {
      const c = changes.get(id)
      if (!c || c.resolved) return
      c.resolved = true

      const current = yText.toString()
      if (c.type === 'insertion') {
        // 1. Try narrow window near the tracked offset first.
        const from = Math.max(0, c.offset)
        const narrow = current.slice(from, from + c.length + c.text.length + 20)
        const narrowFound = narrow.indexOf(c.text)
        if (narrowFound !== -1) {
          yText.delete(from + narrowFound, c.text.length)
        } else {
          // 2. Full-document fallback (handles heavy concurrent edits).
          const globalIdx = current.indexOf(c.text)
          if (globalIdx !== -1) {
            yText.delete(globalIdx, c.text.length)
          }
          // If still not found the text was already removed; silently succeed.
        }
      } else {
        // Re-insert the deleted text
        const insertAt = Math.min(c.offset, current.length)
        yText.insert(insertAt, c.text)
      }

      changes.set(id, c)
      onUpdate(Array.from(changes.values()).filter((x) => !x.resolved))
    },

    acceptAll() {
      for (const [id, c] of changes) {
        if (!c.resolved) {
          c.resolved = true
          changes.set(id, c)
        }
      }
      onUpdate([])
    },

    rejectAll() {
      const unresolved = Array.from(changes.values()).filter((c) => !c.resolved)
      // Sort insertions descending by offset (delete from end to start)
      const insertions = unresolved
        .filter((c) => c.type === 'insertion')
        .sort((a, b) => b.offset - a.offset)
      // Sort deletions ascending by offset (re-insert from start to end)
      const deletions = unresolved
        .filter((c) => c.type === 'deletion')
        .sort((a, b) => a.offset - b.offset)

      const apply = () => {
        for (const c of insertions) {
          const current = yText.toString()
          const from = Math.max(0, c.offset)
          const narrow = current.slice(from, from + c.text.length + 20)
          const narrowIdx = narrow.indexOf(c.text)
          if (narrowIdx !== -1) {
            yText.delete(from + narrowIdx, c.text.length)
          } else {
            const globalIdx = current.indexOf(c.text)
            if (globalIdx !== -1) yText.delete(globalIdx, c.text.length)
          }
        }
        for (const c of deletions) {
          const current = yText.toString()
          const insertAt = Math.min(c.offset, current.length)
          yText.insert(insertAt, c.text)
        }
      }

      if (yText.doc?.transact) {
        yText.doc.transact(apply)
      } else {
        apply()
      }

      for (const [id, c] of changes) {
        c.resolved = true
        changes.set(id, c)
      }
      onUpdate([])
    },

    cleanup() {
      yText.unobserve(observer)
    },
  }
}
