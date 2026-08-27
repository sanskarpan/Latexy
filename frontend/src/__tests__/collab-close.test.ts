import { describe, it, expect } from 'vitest'
import {
  classifyCollabClose,
  COLLAB_CLOSE_ROLE_CHANGED,
  MAX_TRANSIENT_COLLAB_RETRIES,
} from '@/lib/collab-close'

describe('classifyCollabClose', () => {
  it('leaves ordinary closes to y-websocket', () => {
    expect(classifyCollabClose(1006, 0)).toBe('ignore')
    expect(classifyCollabClose(1000, 0)).toBe('ignore')
    expect(classifyCollabClose(undefined, 0)).toBe('ignore')
  })

  it('retries 4001 before giving up — a ticket may be expired or already consumed', () => {
    // A fresh HTTP-minted ticket can recover the relay without treating the
    // long-lived login session as invalid.
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

  it('reconnects on a role change instead of locking — a promotion must not cost access', () => {
    // Sharing 4003 here meant promoting a viewer to editor locked their buffer
    // read-only, leaving them with LESS access than before the promotion.
    expect(classifyCollabClose(COLLAB_CLOSE_ROLE_CHANGED, 0)).toBe('retry')
  })

  it('keeps retrying a role change however much the transient budget is spent', () => {
    // The reconnect is the entire point of the close, so it must not degrade to
    // 'stop' the way an ambiguous 4001 does.
    expect(classifyCollabClose(COLLAB_CLOSE_ROLE_CHANGED, 99)).toBe('retry')
  })
})
