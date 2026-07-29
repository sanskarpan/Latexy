import { describe, it, expect } from 'vitest'
import { classifyCollabClose, MAX_TRANSIENT_COLLAB_RETRIES } from '@/lib/collab-close'

describe('classifyCollabClose', () => {
  it('leaves ordinary closes to y-websocket', () => {
    expect(classifyCollabClose(1006, 0)).toBe('ignore')
    expect(classifyCollabClose(1000, 0)).toBe('ignore')
    expect(classifyCollabClose(undefined, 0)).toBe('ignore')
  })

  it('retries 4001 before giving up — it is also what a DB blip looks like', () => {
    // _validate_better_auth_session returns None on ANY exception, so the first 4001 must
    // not be treated as a dead session
    for (let i = 0; i < MAX_TRANSIENT_COLLAB_RETRIES; i++) {
      expect(classifyCollabClose(4001, i)).toBe('retry')
    }
    expect(classifyCollabClose(4001, MAX_TRANSIENT_COLLAB_RETRIES)).toBe('stop')
  })

  it('never locks the buffer for 4001 — the owner keeps editing via REST autosave', () => {
    expect(classifyCollabClose(4001, 99)).not.toBe('lock')
  })

  it('never locks the buffer for 4004 (resume lookup failed)', () => {
    expect(classifyCollabClose(4004, 0)).toBe('stop')
  })

  it('locks only for 4003, where collaboration access was genuinely revoked', () => {
    expect(classifyCollabClose(4003, 0)).toBe('lock')
    expect(classifyCollabClose(4003, 99)).toBe('lock')
  })
})
