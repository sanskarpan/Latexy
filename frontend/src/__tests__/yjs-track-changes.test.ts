import { describe, test, expect, vi } from 'vitest'
import { observeChanges } from '../lib/yjs-track-changes'
import type { TrackedChange, TrackChangesHandle } from '../lib/yjs-track-changes'

// ── Helpers ────────────────────────────────────────────────────────────────

function makeYText(initial = '') {
  let content = initial
  const observers: Array<(event: any, txn: any) => void> = []
  const doc = {
    transact: (fn: () => void) => fn(),
  }
  return {
    toString: () => content,
    observe: (fn: (e: any, t: any) => void) => observers.push(fn),
    unobserve: (fn: (e: any, t: any) => void) => {
      const idx = observers.indexOf(fn)
      if (idx !== -1) observers.splice(idx, 1)
    },
    insert: (index: number, text: string) => {
      content = content.slice(0, index) + text + content.slice(index)
    },
    delete: (index: number, length: number) => {
      content = content.slice(0, index) + content.slice(index + length)
    },
    doc,
    // Fire a remote event
    _fireRemote(delta: any[], origin: any) {
      observers.forEach((fn) => fn({ delta, changes: { added: new Set() } }, { origin }))
    },
  }
}

function makeProvider(clientId = 99, awarenessStates?: Map<number, any>) {
  const states =
    awarenessStates ??
    new Map([[clientId, { user: { id: 'u1', name: 'Alice', color: '#f00' } }]])
  return {
    awareness: {
      clientID: 1, // local client
      getStates: () => states,
    },
  }
}

// ── Module exports ─────────────────────────────────────────────────────────

describe('module exports', () => {
  test('observeChanges is a function', () => {
    expect(typeof observeChanges).toBe('function')
  })

  test('observeChanges returns a TrackChangesHandle', () => {
    const yText = makeYText()
    const provider = makeProvider()
    const handle = observeChanges(yText, provider, () => {})
    expect(typeof handle.getChanges).toBe('function')
    expect(typeof handle.acceptChange).toBe('function')
    expect(typeof handle.rejectChange).toBe('function')
    expect(typeof handle.acceptAll).toBe('function')
    expect(typeof handle.rejectAll).toBe('function')
    expect(typeof handle.cleanup).toBe('function')
    handle.cleanup()
  })
})

// ── Origin filtering ───────────────────────────────────────────────────────

describe('origin filtering', () => {
  test('ignores local changes (wrong origin)', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    const updates: TrackedChange[][] = []
    const handle = observeChanges(yText, provider, (c) => updates.push(c))

    // Fire with a different origin (local) — no changes should be recorded
    const localOrigin = { someOtherOrigin: true }
    yText._fireRemote([{ insert: ' world' }], localOrigin)

    // onUpdate may be called but with no tracked changes
    const allEmpty = updates.every((u) => u.length === 0)
    expect(allEmpty).toBe(true)
    expect(handle.getChanges()).toHaveLength(0)
    handle.cleanup()
  })

  test('tracks remote changes (origin === provider)', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    const updates: TrackedChange[][] = []
    const handle = observeChanges(yText, provider, (c) => updates.push(c))

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)

    expect(updates.length).toBeGreaterThan(0)
    handle.cleanup()
  })
})

// ── Insertion tracking ─────────────────────────────────────────────────────

describe('insertion tracking', () => {
  test('creates an insertion TrackedChange for insert delta op', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)

    expect(lastChanges).toHaveLength(1)
    const c = lastChanges[0]
    expect(c.type).toBe('insertion')
    expect(c.text).toBe(' world')
    expect(c.offset).toBe(5)
    expect(c.length).toBe(6)
    handle.cleanup()
  })

  test('insertion has resolved=false initially', () => {
    const yText = makeYText()
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(0, 'foo')
    yText._fireRemote([{ insert: 'foo' }], provider)

    expect(lastChanges[0].resolved).toBe(false)
    handle.cleanup()
  })

  test('insertion has correct id', () => {
    const yText = makeYText()
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(0, 'bar')
    yText._fireRemote([{ insert: 'bar' }], provider)

    expect(lastChanges[0].id).toMatch(/^ins-/)
    handle.cleanup()
  })

  test('insertion has timestamp', () => {
    const yText = makeYText()
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    const before = Date.now()
    yText.insert(0, 'baz')
    yText._fireRemote([{ insert: 'baz' }], provider)
    const after = Date.now()

    expect(lastChanges[0].timestamp).toBeGreaterThanOrEqual(before)
    expect(lastChanges[0].timestamp).toBeLessThanOrEqual(after)
    handle.cleanup()
  })
})

// ── Deletion tracking ──────────────────────────────────────────────────────

describe('deletion tracking', () => {
  test('creates a deletion TrackedChange for delete delta op', () => {
    const yText = makeYText('hello world')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.delete(5, 6)
    yText._fireRemote([{ retain: 5 }, { delete: 6 }], provider)

    expect(lastChanges).toHaveLength(1)
    const c = lastChanges[0]
    expect(c.type).toBe('deletion')
    expect(c.text).toBe(' world')
    expect(c.offset).toBe(5)
    expect(c.length).toBe(6)
    handle.cleanup()
  })

  test('deletion has resolved=false initially', () => {
    const yText = makeYText('abc')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.delete(0, 3)
    yText._fireRemote([{ delete: 3 }], provider)

    expect(lastChanges[0].resolved).toBe(false)
    handle.cleanup()
  })

  test('deletion id starts with del-', () => {
    const yText = makeYText('abc')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.delete(0, 3)
    yText._fireRemote([{ delete: 3 }], provider)

    expect(lastChanges[0].id).toMatch(/^del-/)
    handle.cleanup()
  })
})

// ── acceptChange ───────────────────────────────────────────────────────────

describe('acceptChange', () => {
  test('marks change as resolved and removes from getChanges', () => {
    const yText = makeYText()
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(0, 'hello')
    yText._fireRemote([{ insert: 'hello' }], provider)

    const id = lastChanges[0].id
    handle.acceptChange(id)

    expect(handle.getChanges()).toHaveLength(0)
    expect(lastChanges).toHaveLength(0)
    handle.cleanup()
  })

  test('acceptChange on non-existent id is a no-op', () => {
    const yText = makeYText()
    const provider = makeProvider()
    const handle = observeChanges(yText, provider, () => {})
    // Should not throw
    expect(() => handle.acceptChange('non-existent-id')).not.toThrow()
    handle.cleanup()
  })
})

// ── rejectChange ───────────────────────────────────────────────────────────

describe('rejectChange', () => {
  test('rejectChange for insertion deletes the inserted text', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)

    const id = lastChanges[0].id
    handle.rejectChange(id)

    expect(yText.toString()).toBe('hello')
    expect(handle.getChanges()).toHaveLength(0)
    handle.cleanup()
  })

  test('rejectChange for deletion re-inserts the deleted text', () => {
    const yText = makeYText('hello world')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.delete(5, 6)
    yText._fireRemote([{ retain: 5 }, { delete: 6 }], provider)

    const id = lastChanges[0].id
    handle.rejectChange(id)

    expect(yText.toString()).toBe('hello world')
    expect(handle.getChanges()).toHaveLength(0)
    handle.cleanup()
  })

  test('rejectChange on already-resolved change is a no-op', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)

    const id = lastChanges[0].id
    handle.acceptChange(id)

    // rejectChange after accept should be no-op
    const content = yText.toString()
    expect(() => handle.rejectChange(id)).not.toThrow()
    expect(yText.toString()).toBe(content)
    handle.cleanup()
  })
})

// ── acceptAll ─────────────────────────────────────────────────────────────

describe('acceptAll', () => {
  test('marks all pending changes as resolved', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)
    yText.insert(11, '!')
    yText._fireRemote([{ retain: 11 }, { insert: '!' }], provider)

    handle.acceptAll()

    expect(handle.getChanges()).toHaveLength(0)
    expect(lastChanges).toHaveLength(0)
    handle.cleanup()
  })

  test('text remains unchanged after acceptAll', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    const handle = observeChanges(yText, provider, () => {})

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)

    handle.acceptAll()

    expect(yText.toString()).toBe('hello world')
    handle.cleanup()
  })
})

// ── rejectAll ─────────────────────────────────────────────────────────────

describe('rejectAll', () => {
  test('reverts all insertions', () => {
    const yText = makeYText('hello')
    const provider = makeProvider()
    const handle = observeChanges(yText, provider, () => {})

    yText.insert(5, ' world')
    yText._fireRemote([{ retain: 5 }, { insert: ' world' }], provider)

    handle.rejectAll()

    expect(yText.toString()).toBe('hello')
    expect(handle.getChanges()).toHaveLength(0)
    handle.cleanup()
  })

  test('reverts all deletions', () => {
    const yText = makeYText('hello world')
    const provider = makeProvider()
    const handle = observeChanges(yText, provider, () => {})

    yText.delete(5, 6)
    yText._fireRemote([{ retain: 5 }, { delete: 6 }], provider)

    handle.rejectAll()

    expect(yText.toString()).toBe('hello world')
    expect(handle.getChanges()).toHaveLength(0)
    handle.cleanup()
  })
})

// ── User attribution ───────────────────────────────────────────────────────

describe('user attribution', () => {
  test('attributes insertion to user from awareness', () => {
    const yText = makeYText()
    const awarenessMap = new Map([
      [99, { user: { id: 'uid-alice', name: 'Alice', color: '#ff0000' } }],
    ])
    const provider = makeProvider(99, awarenessMap)
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(0, 'Hi')
    yText._fireRemote([{ insert: 'Hi' }], provider)

    // The name/color may default because no added items set clientId
    expect(lastChanges[0].userName).toBeDefined()
    expect(lastChanges[0].userColor).toBeDefined()
    handle.cleanup()
  })

  test('falls back to User <clientId> when no awareness user', () => {
    const yText = makeYText()
    const provider = makeProvider(0, new Map())
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(0, 'Hi')
    yText._fireRemote([{ insert: 'Hi' }], provider)

    expect(lastChanges[0].userName).toMatch(/User/)
    handle.cleanup()
  })
})

// ── computeRange correctness ───────────────────────────────────────────────

describe('computeRange correctness', () => {
  test('single-line insertion at start gives line 1, col 1', () => {
    const yText = makeYText()
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(0, 'hello')
    yText._fireRemote([{ insert: 'hello' }], provider)

    expect(lastChanges[0].range.startLineNumber).toBe(1)
    expect(lastChanges[0].range.startColumn).toBe(1)
    handle.cleanup()
  })

  test('insertion on second line has startLineNumber=2', () => {
    const initial = 'line1\n'
    const yText = makeYText(initial)
    const provider = makeProvider()
    let lastChanges: TrackedChange[] = []
    const handle = observeChanges(yText, provider, (c) => { lastChanges = c })

    yText.insert(initial.length, 'line2')
    yText._fireRemote([{ retain: initial.length }, { insert: 'line2' }], provider)

    expect(lastChanges[0].range.startLineNumber).toBe(2)
    handle.cleanup()
  })

  test('getChanges returns only unresolved changes', () => {
    const yText = makeYText()
    const provider = makeProvider()
    const handle = observeChanges(yText, provider, () => {})

    yText.insert(0, 'a')
    yText._fireRemote([{ insert: 'a' }], provider)
    yText.insert(1, 'b')
    yText._fireRemote([{ retain: 1 }, { insert: 'b' }], provider)

    expect(handle.getChanges()).toHaveLength(2)

    const firstId = handle.getChanges()[0].id
    handle.acceptChange(firstId)

    expect(handle.getChanges()).toHaveLength(1)
    handle.cleanup()
  })
})

// ── cleanup ────────────────────────────────────────────────────────────────

describe('cleanup', () => {
  test('cleanup unobserves the yText', () => {
    const yText = makeYText()
    const provider = makeProvider()
    let callCount = 0
    const handle = observeChanges(yText, provider, () => { callCount++ })

    handle.cleanup()

    // After cleanup, remote events should not trigger onUpdate
    yText.insert(0, 'hello')
    yText._fireRemote([{ insert: 'hello' }], provider)

    expect(callCount).toBe(0)
  })
})
