/**
 * Lifecycle guarantees for the websocket client.
 *
 * Each of these pins a defect that was reachable in normal use: a logout that
 * permanently disabled the client, a socket error that crashed the process, and
 * reconnects that stacked sockets so every event arrived twice.
 */
import { describe, expect, it } from 'vitest'

import { LatexyWSClient } from '../lib/ws-client.js'

const DEAD_URL = 'ws://127.0.0.1:59997/ws/jobs'   // nothing listens here

function client(): any {
  return new LatexyWSClient() as any
}

describe('LatexyWSClient lifecycle', () => {
  it('reconnects after destroy() — /logout must not disable the singleton', () => {
    // wsClient is module-level, and /logout calls destroy(). Latching `destroyed`
    // meant a subsequent login opened no socket at all: every job then looked
    // like it hung, with no events, until the process was restarted.
    const c = client()
    c.connect(DEAD_URL, 'tok')
    expect(c.ws, 'first connect should open a socket').not.toBeNull()

    c.destroy()
    c.connect(DEAD_URL, 'tok2')
    expect(c.ws, 'connect() after destroy() must open a new socket').not.toBeNull()

    c.destroy()
  })

  it('a socket error does not throw — EventEmitter would make it fatal', () => {
    // Emitting on 'error' with no listener throws ERR_UNHANDLED_ERROR, which took
    // down the whole TUI whenever the backend was unreachable.
    const c = client()
    expect(() => c.emit('error', { message: 'ECONNREFUSED' })).not.toThrow()
    c.destroy()
  })

  it('socket errors are delivered on a non-throwing channel', () => {
    const c = client()
    const seen: unknown[] = []
    c.on('socket_error', (e: unknown) => seen.push(e))
    c.emit('socket_error', { message: 'ECONNREFUSED' })
    expect(seen).toHaveLength(1)
    c.destroy()
  })

  it('a second connect() replaces the socket instead of stacking one', () => {
    // An orphaned socket keeps its message handler and goes on publishing into
    // the same client, so every event is delivered twice.
    const c = client()
    c.connect(DEAD_URL, 'tok')
    const first = c.ws
    c.connect(DEAD_URL, 'tok')
    expect(c.ws, 'socket should have been replaced').not.toBe(first)
    expect(first.listenerCount('message'), 'old socket must be detached').toBe(0)
    c.destroy()
  })

  it('destroy() clears subscriptions so a later session does not inherit them', () => {
    const c = client()
    c.connect(DEAD_URL, 'tok')
    c.subscribe('job-1')
    c.subscribe('job-2')
    expect(c.subscriptions.size).toBe(2)
    c.destroy()
    expect(c.subscriptions.size, 'stale subscriptions survived destroy()').toBe(0)
  })

  it('unsubscribe() drops the job so reconnect does not replay it', () => {
    const c = client()
    c.connect(DEAD_URL, 'tok')
    c.subscribe('job-1')
    c.unsubscribe('job-1')
    expect(c.subscriptions.has('job-1')).toBe(false)
    c.destroy()
  })

  it('destroy() leaves no live timers behind', () => {
    const c = client()
    c.connect(DEAD_URL, 'tok')
    c.destroy()
    expect(c.reconnectTimer).toBeNull()
    expect(c.heartbeatTimer).toBeNull()
  })
})
