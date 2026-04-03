/**
 * Unit tests for Feature 41 — yjs-track-changes.ts
 *
 * The module is tested using lightweight mock objects for Y.Text and the
 * WebsocketProvider.  No real Y.js or WebSocket dependency is needed.
 */

import { describe, test, expect, vi, beforeEach } from 'vitest'
import { observeChanges, type TrackedChange } from '@/lib/yjs-track-changes'

// ── Mock helpers ────────────────────────────────────────────────────────────

/** Creates a minimal mock for Y.Text */
function makeYText(initialContent = '') {
  let _content = initialContent
  let _observer: ((event: any, tx: any) => void) | null = null

  const yText = {
    get content() { return _content },
    toString: () => _content,
    observe: vi.fn((cb: (e: any, tx: any) => void) => { _observer = cb }),
    unobserve: vi.fn(() => { _observer = null }),
    delete: vi.fn((offset: number, length: number) => {
      _content = _content.slice(0, offset) + _content.slice(offset + length)
    }),
    insert: vi.fn((offset: number, text: string) => {
      _content = _content.slice(0, offset) + text + _content.slice(offset)
    }),
    get doc() {
      return {
        transact: (fn: () => void) => fn(),
      }
    },
    /** Test helper: fire a remote update event with a delta */
    _fireRemote(delta: any[], providerRef: any) {
      if (!_observer) return
      const event = {
        delta,
        changes: {
          added: new Set<any>(),
          deleted: new Set<any>(),
        },
      }
      _observer(event, { origin: providerRef })
    },
    /** Test helper: fire a remote insertion with item client attribution */
    _fireRemoteInsert(delta: any[], clientId: number, providerRef: any) {
      if (!_observer) return
      const fakeItem = { id: { client: clientId } }
      const event = {
        delta,
        changes: {
          added: new Set([fakeItem]),
          deleted: new Set<any>(),
        },
      }
      _observer(event, { origin: providerRef })
    },
    /** Test helper: fire a local update (should be ignored) */
    _fireLocal(delta: any[]) {
      if (!_observer) return
      const event = { delta, changes: { added: new Set(), deleted: new Set() } }
      _observer(event, { origin: 'local-binding' })
    },
  }

  return yText
}

/** Creates a minimal mock for WebsocketProvider */
function makeProvider(clientId = 1, awarenessStates?: Map<number, any>) {
  const states =
    awarenessStates ??
    new Map([[2, { user: { name: 'Alice', color: '#ff0000' } }]])

  return {
    awareness: {
      clientID: clientId,
      getStates: () => states,
    },
  }
}

// ── Setup ───────────────────────────────────────────────────────────────────

let yText: ReturnType<typeof makeYText>
let provider: ReturnType<typeof makeProvider>
let updates: TrackedChange[][]

beforeEach(() => {
  yText = makeYText('Hello world')
  provider = makeProvider(1, new Map([[2, { user: { name: 'Alice', color: '#4ade80' } }]]))
  updates = []
})

// ── Basic wiring ─────────────────────────────────────────────────────────────

describe('observeChanges — wiring', () => {
  test('attaches observer to yText on creation', () => {
    observeChanges(yText, provider, () => {})
    expect(yText.observe).toHaveBeenCalledTimes(1)
  })

  test('cleanup removes observer and clears map', () => {
    const handle = observeChanges(yText, provider, () => {})
    handle.cleanup()
    expect(yText.unobserve).toHaveBeenCalledTimes(1)
    expect(handle.getChanges()).toHaveLength(0)
  })

  test('getChanges returns empty array initially', () => {
    const handle = observeChanges(yText, provider, () => {})
    expect(handle.getChanges()).toEqual([])
  })
})

// ── Remote vs local changes ───────────────────────────────────────────────

describe('observeChanges — origin filtering', () => {
  test('local changes are ignored', () => {
    const handle = observeChanges(yText, provider, (changes) => updates.push(changes))
    yText._fireLocal([{ insert: ' more text' }])
    expect(updates).toHaveLength(0)
    expect(handle.getChanges()).toHaveLength(0)
  })

  test('remote changes fire onUpdate', () => {
    const handle = observeChanges(yText, provider, (changes) => updates.push(changes))
    yText._content = 'Hello world text'
    yText._fireRemote([{ retain: 11 }, { insert: ' text' }], provider)
    expect(updates).toHaveLength(1)
    expect(handle.getChanges()).toHaveLength(1)
  })
})

// ── Insertions ───────────────────────────────────────────────────────────────

describe('observeChanges — insertion tracking', () => {
  test('records a simple insertion', () => {
    yText = makeYText('Hello world text')
    const handle = observeChanges(yText, provider, (c) => updates.push(c))
    yText._fireRemoteInsert(
      [{ retain: 11 }, { insert: ' text' }],
      2,
      provider,
    )
    const changes = handle.getChanges()
    expect(changes).toHaveLength(1)
    const c = changes[0]
    expect(c.type).toBe('insertion')
    expect(c.text).toBe(' text')
    expect(c.offset).toBe(11)
    expect(c.length).toBe(5)
  })

  test('insertion at start (no retain)', () => {
    yText = makeYText('Prepend Hello')
    const handle = observeChanges(yText, provider, (c) => updates.push(c))
    yText._fireRemoteInsert([{ insert: 'Prepend ' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.type).toBe('insertion')
    expect(c.text).toBe('Prepend ')
    expect(c.offset).toBe(0)
  })

  test('insertion range line/col computed correctly', () => {
    // Content after insert is "Hello\nworld" — insert at offset 6 on line 2
    yText = makeYText('Hello\nXworld')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 6 }, { insert: 'X' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.range.startLineNumber).toBe(2)
    expect(c.range.startColumn).toBe(1)
    expect(c.range.endLineNumber).toBe(2)
    expect(c.range.endColumn).toBe(2)
  })

  test('attributes insertion to correct user from added items', () => {
    yText = makeYText('Hello world!')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 11 }, { insert: '!' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.clientId).toBe(2)
    expect(c.userName).toBe('Alice')
    expect(c.userColor).toBe('#4ade80')
  })

  test('empty insertions are not recorded', () => {
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemote([{ retain: 5 }, { insert: '' }], provider)
    expect(handle.getChanges()).toHaveLength(0)
  })
})

// ── Deletions ─────────────────────────────────────────────────────────────

describe('observeChanges — deletion tracking', () => {
  test('records a deletion with the deleted text from snapshot', () => {
    // prevText = 'Hello world', after delete = 'Helloworld' (removed space at 5)
    yText = makeYText('Hello world')
    const handle = observeChanges(yText, provider, () => {})
    // Simulate: delete char at offset 5
    yText.delete(5, 1)
    yText._fireRemote([{ retain: 5 }, { delete: 1 }], provider)
    const [c] = handle.getChanges()
    expect(c.type).toBe('deletion')
    expect(c.text).toBe(' ')
    expect(c.offset).toBe(5)
    expect(c.length).toBe(1)
  })

  test('deletion of multi-char text', () => {
    yText = makeYText('Hello world')
    const handle = observeChanges(yText, provider, () => {})
    yText.delete(6, 5)  // remove 'world'
    yText._fireRemote([{ retain: 6 }, { delete: 5 }], provider)
    const [c] = handle.getChanges()
    expect(c.type).toBe('deletion')
    expect(c.text).toBe('world')
    expect(c.length).toBe(5)
  })

  test('zero-length deletions are not recorded', () => {
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemote([{ retain: 3 }, { delete: 0 }], provider)
    expect(handle.getChanges()).toHaveLength(0)
  })
})

// ── Mixed delta ────────────────────────────────────────────────────────────

describe('observeChanges — mixed delta', () => {
  test('handles retain + insert + delete in one delta', () => {
    // prevText = 'Hello world'; after replace: 'Hello there'
    // We init with 'Hello world' so prevText is that, then mutate to 'Hello there'
    yText = makeYText('Hello world')
    const handle = observeChanges(yText, provider, () => {})
    yText.delete(6, 5)    // 'Hello '
    yText.insert(6, 'there')  // 'Hello there'
    yText._fireRemoteInsert(
      [{ retain: 6 }, { delete: 5 }, { insert: 'there' }],
      2,
      provider,
    )
    const changes = handle.getChanges()
    const ins = changes.find((c) => c.type === 'insertion')
    const del = changes.find((c) => c.type === 'deletion')
    expect(ins).toBeDefined()
    expect(del).toBeDefined()
    expect(ins!.text).toBe('there')
    expect(del!.text).toBe('world')
  })
})

// ── Timestamp and ID ────────────────────────────────────────────────────────

describe('observeChanges — metadata', () => {
  test('each change has a unique id', () => {
    // Create handle on the same yText we fire on; fire two separate inserts
    const handle = observeChanges(yText, provider, () => {})
    yText.insert(yText.toString().length, 'a')
    yText._fireRemoteInsert([{ retain: yText.toString().length - 1 }, { insert: 'a' }], 2, provider)
    yText.insert(yText.toString().length, 'b')
    yText._fireRemoteInsert([{ retain: yText.toString().length - 1 }, { insert: 'b' }], 2, provider)
    const ids = handle.getChanges().map((c) => c.id)
    const unique = new Set(ids)
    expect(unique.size).toBe(ids.length)
  })

  test('change id starts with "tc-"', () => {
    // Init with final content so prevText == content (fine for insertions)
    const localYText = makeYText('Hello worldX')
    const handle = observeChanges(localYText, provider, () => {})
    localYText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.id).toMatch(/^tc-/)
  })

  test('timestamp is a recent epoch ms value', () => {
    const before = Date.now()
    const localYText = makeYText('Hello worldX')
    const handle = observeChanges(localYText, provider, () => {})
    localYText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const after = Date.now()
    const [c] = handle.getChanges()
    expect(c.timestamp).toBeGreaterThanOrEqual(before)
    expect(c.timestamp).toBeLessThanOrEqual(after)
  })

  test('resolved is false initially', () => {
    const localYText = makeYText('Hello worldX')
    const handle = observeChanges(localYText, provider, () => {})
    localYText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.resolved).toBe(false)
  })
})

// ── Accept ────────────────────────────────────────────────────────────────

describe('acceptChange', () => {
  test('marks change as resolved and removes from getChanges()', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, (c) => updates.push(c))
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const [c] = handle.getChanges()
    handle.acceptChange(c.id)
    expect(handle.getChanges()).toHaveLength(0)
  })

  test('accept fires onUpdate with empty list', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, (c) => updates.push(c))
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    updates.length = 0
    const id = handle.getChanges()[0].id
    handle.acceptChange(id)
    expect(updates).toHaveLength(1)
    expect(updates[0]).toHaveLength(0)
  })

  test('accept does NOT call yText.delete', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    handle.acceptChange(handle.getChanges()[0].id)
    expect(yText.delete).not.toHaveBeenCalled()
  })

  test('accept of nonexistent id is a no-op', () => {
    const handle = observeChanges(yText, provider, () => {})
    expect(() => handle.acceptChange('nonexistent')).not.toThrow()
  })
})

// ── Reject insertion ─────────────────────────────────────────────────────

describe('rejectChange — insertion', () => {
  test('calls yText.delete to remove inserted text', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const [c] = handle.getChanges()
    handle.rejectChange(c.id)
    expect(yText.delete).toHaveBeenCalledWith(11, 1)
  })

  test('rejected insertion is removed from getChanges()', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const id = handle.getChanges()[0].id
    handle.rejectChange(id)
    expect(handle.getChanges()).toHaveLength(0)
  })

  test('reject of nonexistent id is a no-op', () => {
    const handle = observeChanges(yText, provider, () => {})
    expect(() => handle.rejectChange('no-such-id')).not.toThrow()
    expect(yText.delete).not.toHaveBeenCalled()
  })

  test('reject fires onUpdate', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, (c) => updates.push(c))
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    updates.length = 0
    handle.rejectChange(handle.getChanges()[0].id)
    expect(updates).toHaveLength(1)
  })
})

// ── Reject deletion ───────────────────────────────────────────────────────

describe('rejectChange — deletion', () => {
  test('calls yText.insert to restore deleted text', () => {
    yText = makeYText('Hello world')
    const handle = observeChanges(yText, provider, () => {})
    yText.delete(6, 5) // remove 'world'
    yText._fireRemote([{ retain: 6 }, { delete: 5 }], provider)
    const [c] = handle.getChanges()
    handle.rejectChange(c.id)
    expect(yText.insert).toHaveBeenCalledWith(6, 'world')
  })

  test('rejected deletion is removed from getChanges()', () => {
    yText = makeYText('Hello world')
    const handle = observeChanges(yText, provider, () => {})
    yText.delete(6, 5)
    yText._fireRemote([{ retain: 6 }, { delete: 5 }], provider)
    const id = handle.getChanges()[0].id
    handle.rejectChange(id)
    expect(handle.getChanges()).toHaveLength(0)
  })
})

// ── acceptAll / rejectAll ────────────────────────────────────────────────

describe('acceptAll', () => {
  test('resolves all pending changes at once', () => {
    yText = makeYText('AB')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ insert: 'A' }], 2, provider)
    yText._fireRemoteInsert([{ retain: 1 }, { insert: 'B' }], 2, provider)
    expect(handle.getChanges()).toHaveLength(2)
    handle.acceptAll()
    expect(handle.getChanges()).toHaveLength(0)
  })

  test('acceptAll does not touch yText', () => {
    yText = makeYText('AB')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ insert: 'A' }], 2, provider)
    handle.acceptAll()
    expect(yText.delete).not.toHaveBeenCalled()
    expect(yText.insert).not.toHaveBeenCalled()
  })
})

describe('rejectAll', () => {
  test('rejectAll processes multiple insertions and fires onUpdate', () => {
    yText = makeYText('XY')
    const handle = observeChanges(yText, provider, (c) => updates.push(c))
    yText._fireRemoteInsert([{ insert: 'X' }], 2, provider)
    yText._fireRemoteInsert([{ retain: 1 }, { insert: 'Y' }], 2, provider)
    updates.length = 0
    handle.rejectAll()
    expect(handle.getChanges()).toHaveLength(0)
    // onUpdate should have fired exactly once (at the end)
    expect(updates).toHaveLength(1)
    expect(updates[0]).toHaveLength(0)
  })

  test('rejectAll calls yText.delete for each insertion', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    handle.rejectAll()
    expect(yText.delete).toHaveBeenCalled()
  })
})

// ── Awareness fallback for deletions ─────────────────────────────────────

describe('user attribution', () => {
  test('unknown clientId falls back to "Collaborator"', () => {
    // No awareness state for clientId 99
    provider = makeProvider(1, new Map())
    yText = makeYText('Hello world')
    const handle = observeChanges(yText, provider, () => {})
    yText.delete(6, 5)
    yText._fireRemote([{ retain: 6 }, { delete: 5 }], provider)
    const [c] = handle.getChanges()
    expect(c.userName).toBe('Collaborator')
    expect(c.userColor).toBe('#a78bfa')
  })

  test('awareness entry is used when available', () => {
    yText = makeYText('Hello worldX')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ retain: 11 }, { insert: 'X' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.userName).toBe('Alice')
  })
})

// ── offsetToLineCol edge cases ────────────────────────────────────────────

describe('range computation edge cases', () => {
  test('insertion at offset 0 gives line 1, col 1', () => {
    yText = makeYText('ABC')
    const handle = observeChanges(yText, provider, () => {})
    yText._fireRemoteInsert([{ insert: 'A' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.range.startLineNumber).toBe(1)
    expect(c.range.startColumn).toBe(1)
  })

  test('multiline insertion range spans lines correctly', () => {
    yText = makeYText('line1\nline2\nnew\nmore')
    const handle = observeChanges(yText, provider, () => {})
    // Insert "new\nmore" starting at offset 12 (after "line1\nline2\n")
    yText._fireRemoteInsert([{ retain: 12 }, { insert: 'new\nmore' }], 2, provider)
    const [c] = handle.getChanges()
    expect(c.range.startLineNumber).toBe(3)
    expect(c.range.startColumn).toBe(1)
    expect(c.range.endLineNumber).toBe(4)
    expect(c.range.endColumn).toBe(5) // 'more'.length + 1 = 5
  })
})
