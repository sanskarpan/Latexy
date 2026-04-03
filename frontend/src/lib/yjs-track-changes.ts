/**
 * Feature 41 — Track Changes for Y.js collaborative editing.
 *
 * Intercepts remote Y.Text mutations (insertions / deletions), records them
 * as TrackedChange objects and exposes accept / reject operations.
 *
 * This module is framework-agnostic — it receives Y.js objects typed as `any`
 * so that it can be statically imported without bundling yjs separately.
 */

// ── Public types ──────────────────────────────────────────────────────────────

export interface TrackedChange {
  id: string
  clientId: number
  userId: string
  userName: string
  userColor: string
  type: 'insertion' | 'deletion'
  /** Inserted or originally-deleted text */
  text: string
  /** Character offset in the Y.Text at time of recording */
  offset: number
  length: number
  /** Monaco-style range, valid at time of recording */
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

// ── Internal helpers ──────────────────────────────────────────────────────────

function offsetToLineCol(
  docText: string,
  offset: number,
): { line: number; col: number } {
  const clamped = Math.max(0, Math.min(offset, docText.length))
  const before = docText.slice(0, clamped)
  const lines = before.split('\n')
  return { line: lines.length, col: lines[lines.length - 1].length + 1 }
}

function makeRange(
  docText: string,
  startOffset: number,
  endOffset: number,
): TrackedChange['range'] {
  const s = offsetToLineCol(docText, startOffset)
  const e = offsetToLineCol(docText, endOffset)
  return {
    startLineNumber: s.line,
    startColumn: s.col,
    endLineNumber: e.line,
    endColumn: e.col,
  }
}

// ── Factory ───────────────────────────────────────────────────────────────────

/**
 * Attach a Y.Text observer that records remote changes.
 *
 * @param yText    - The Y.Text shared type (pass as `any`)
 * @param provider - The y-websocket WebsocketProvider (pass as `any`)
 * @param onUpdate - Called after every remote change with the current pending list
 */
export function observeChanges(
  yText: any,
  provider: any,
  onUpdate: (changes: TrackedChange[]) => void,
): TrackChangesHandle {
  const map = new Map<string, TrackedChange>()
  let prevText = ''

  try {
    prevText = yText.toString()
  } catch {
    /* yText not ready yet — will be set on first observe */
  }

  // ── User attribution ────────────────────────────────────────────────────

  function getUserInfo(clientId: number) {
    try {
      const states: Map<number, any> =
        provider.awareness?.getStates?.() ?? new Map()
      const s = states.get(clientId)
      return {
        userId: String(clientId),
        userName: (s?.user?.name as string) || 'Collaborator',
        userColor: (s?.user?.color as string) || '#a78bfa',
      }
    } catch {
      return {
        userId: String(clientId),
        userName: 'Collaborator',
        userColor: '#a78bfa',
      }
    }
  }

  /**
   * Try to determine the remote clientId that authored this change.
   *
   * For insertions: Y.js items carry `id.client` == the inserter's clientID.
   * For deletions:  the deleter's clientID is not embedded in the items, so we
   * fall back to the first non-local clientID found in awareness.
   */
  function remoteClientId(event: any): number {
    if ((event.changes?.added as Set<any> | undefined)?.size) {
      const item = (event.changes.added as Set<any>).values().next().value
      if (item?.id?.client !== undefined) return item.id.client as number
    }
    try {
      const local: number = provider.awareness?.clientID ?? -1
      const states: Map<number, any> =
        provider.awareness?.getStates?.() ?? new Map()
      for (const cid of states.keys()) {
        if (cid !== local) return cid
      }
    } catch {
      /* ignore */
    }
    return -1
  }

  function emit() {
    onUpdate([...map.values()].filter((c) => !c.resolved))
  }

  // ── Y.Text observer ─────────────────────────────────────────────────────

  function observer(event: any, transaction: any) {
    // Only track mutations that originated from a remote WebSocket peer
    if (transaction.origin !== provider) {
      prevText = yText.toString()
      return
    }

    const snapshot = prevText
    const currentText: string = yText.toString()
    const cid = remoteClientId(event)
    const user = getUserInfo(cid)

    let offset = 0
    for (const op of event.delta as Array<Record<string, unknown>>) {
      if ('retain' in op) {
        offset += op.retain as number
      } else if ('insert' in op) {
        const text =
          typeof op.insert === 'string' ? (op.insert as string) : ''
        if (text.length > 0) {
          const id = `tc-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
          map.set(id, {
            id,
            clientId: cid,
            ...user,
            type: 'insertion',
            text,
            offset,
            length: text.length,
            range: makeRange(currentText, offset, offset + text.length),
            timestamp: Date.now(),
            resolved: false,
          })
        }
        offset += text.length
      } else if ('delete' in op) {
        const len = op.delete as number
        if (len > 0) {
          const deletedText = snapshot.slice(offset, offset + len)
          const pos = offsetToLineCol(currentText, offset)
          const id = `tc-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
          map.set(id, {
            id,
            clientId: cid,
            ...user,
            type: 'deletion',
            text: deletedText,
            offset,
            length: len,
            range: {
              startLineNumber: pos.line,
              startColumn: pos.col,
              endLineNumber: pos.line,
              endColumn: pos.col,
            },
            timestamp: Date.now(),
            resolved: false,
          })
        }
        // Deletions don't advance the write offset (text is already gone)
      }
    }

    prevText = currentText
    emit()
  }

  yText.observe(observer)

  // ── Accept / reject ─────────────────────────────────────────────────────

  function acceptChange(id: string) {
    const c = map.get(id)
    if (!c || c.resolved) return
    c.resolved = true
    emit()
  }

  function rejectChange(id: string) {
    const c = map.get(id)
    if (!c || c.resolved) return

    try {
      const current: string = yText.toString()
      if (c.type === 'insertion') {
        // Search for the inserted text near its recorded offset and delete it
        const from = Math.max(0, c.offset - c.length)
        const to = Math.min(current.length, c.offset + c.length * 2)
        const window = current.slice(from, to)
        const rel = window.indexOf(c.text)
        if (rel >= 0) {
          yText.delete(from + rel, c.length)
        }
      } else {
        // Re-insert the deleted text at approximately the stored offset
        const insertAt = Math.min(c.offset, current.length)
        yText.insert(insertAt, c.text)
      }
    } catch (err) {
      console.warn('[TrackChanges] rejectChange failed for', c.id, err)
    }

    c.resolved = true
    emit()
  }

  function acceptAll() {
    for (const c of map.values()) {
      if (!c.resolved) c.resolved = true
    }
    emit()
  }

  function rejectAll() {
    const pending = [...map.values()].filter((c) => !c.resolved)

    // Process insertions from highest to lowest offset to avoid position drift
    const insertions = pending
      .filter((c) => c.type === 'insertion')
      .sort((a, b) => b.offset - a.offset)

    // Process re-insertions (rejected deletions) from lowest to highest offset
    const deletions = pending
      .filter((c) => c.type === 'deletion')
      .sort((a, b) => a.offset - b.offset)

    const apply = () => {
      for (const c of insertions) {
        try {
          const current: string = yText.toString()
          const from = Math.max(0, c.offset - c.length)
          const to = Math.min(current.length, c.offset + c.length * 2)
          const window = current.slice(from, to)
          const rel = window.indexOf(c.text)
          if (rel >= 0) yText.delete(from + rel, c.length)
        } catch (err) {
          console.warn('[TrackChanges] rejectAll:insertion failed', err)
        }
      }
      for (const c of deletions) {
        try {
          const current: string = yText.toString()
          yText.insert(Math.min(c.offset, current.length), c.text)
        } catch (err) {
          console.warn('[TrackChanges] rejectAll:deletion failed', err)
        }
      }
    }

    // Wrap in a Y.js transaction if possible to group all ops into one undo step
    try {
      yText.doc?.transact(apply)
    } catch {
      apply()
    }

    for (const c of pending) c.resolved = true
    emit()
  }

  function cleanup() {
    try {
      yText.unobserve(observer)
    } catch {
      /* ignore if already cleaned up */
    }
    map.clear()
  }

  return {
    getChanges: () => [...map.values()].filter((c) => !c.resolved),
    acceptChange,
    rejectChange,
    acceptAll,
    rejectAll,
    cleanup,
  }
}
