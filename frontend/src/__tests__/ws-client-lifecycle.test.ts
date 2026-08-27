import { describe, test, expect, beforeEach, afterEach, vi } from 'vitest'
import { WSClient, isNewerStreamId } from '../lib/ws-client'
import type { AnyEvent } from '../lib/event-types'

// ─── fake WebSocket ───────────────────────────────────────────────────────────
//
// jsdom is not available (vitest runs in the node environment), so the client is
// driven against a minimal socket double that records what it was told to do.

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  static instances: FakeWebSocket[] = []

  readyState = FakeWebSocket.CONNECTING
  sent: Array<Record<string, unknown>> = []
  closeArgs: { code: number; reason: string } | null = null

  onopen: ((ev: unknown) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: { wasClean: boolean }) => void) | null = null
  onerror: ((ev: unknown) => void) | null = null

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data))
  }

  close(code: number, reason: string): void {
    this.readyState = FakeWebSocket.CLOSED
    this.closeArgs = { code, reason }
  }

  // -- test drivers ------------------------------------------------------- //

  /** Simulate the server accepting the handshake. */
  open(): void {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.({})
  }

  /** Simulate the browser delivering the (always asynchronous) close event. */
  fireClose(wasClean = true): void {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({ wasClean })
  }

  receive(msg: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(msg) })
  }

  get subscribeFrames(): Array<Record<string, unknown>> {
    return this.sent.filter((m) => m.type === 'subscribe')
  }
}

const event = (jobId: string, sequence: number): AnyEvent =>
  ({
    event_id: `evt-${sequence}`,
    job_id: jobId,
    timestamp: 1000 + sequence,
    sequence,
    type: 'job.progress',
    percent: sequence,
    stage: 'latex_compilation',
    message: 'working',
  }) as AnyEvent

let client: WSClient

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  ;(globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket
  client = new WSClient()
})

afterEach(() => {
  vi.useRealTimers()
  delete (globalThis as unknown as { WebSocket?: unknown }).WebSocket
})

// ─── J1: socket identity ──────────────────────────────────────────────────────

describe('WSClient — socket identity', () => {
  test('auth change replaces the socket with a one-time ticket and no session token', async () => {
    client = new WSClient(async () => 'one-time-ticket')
    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()

    client.setAuthenticated(true)
    await Promise.resolve()

    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(first.closeArgs).toEqual({ code: 1000, reason: 'Reconnect with updated auth' })
    expect(FakeWebSocket.instances[1].url).toContain('ticket=one-time-ticket')
    expect(FakeWebSocket.instances[1].url).not.toContain('token=')
  })

  test('a late close from the replaced socket does not disconnect the live one', async () => {
    client = new WSClient(async () => 'one-time-ticket')
    const disconnected = vi.fn()
    client.on('disconnected', disconnected)

    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()
    client.setAuthenticated(true)
    await Promise.resolve()
    const second = FakeWebSocket.instances[1]
    second.open()

    // The browser fires the old socket's close event after the new one is live.
    first.fireClose()
    vi.advanceTimersByTime(60_000)

    expect(disconnected).not.toHaveBeenCalled()
    expect(FakeWebSocket.instances).toHaveLength(2) // no reconnect storm
    expect(client.connected).toBe(true)
  })

  test('authenticated reconnects mint a fresh ticket', async () => {
    const tickets = vi.fn()
      .mockResolvedValueOnce('ticket-1')
      .mockResolvedValueOnce('ticket-2')
    client = new WSClient(tickets)
    client.setAuthenticated(true)
    client.connect()
    await Promise.resolve()
    const first = FakeWebSocket.instances[0]
    first.open()

    first.fireClose(false)
    vi.advanceTimersByTime(100)
    await Promise.resolve()

    expect(tickets).toHaveBeenCalledTimes(2)
    expect(FakeWebSocket.instances[0].url).toContain('ticket=ticket-1')
    expect(FakeWebSocket.instances[1].url).toContain('ticket=ticket-2')
  })

  test('logout invalidates an in-flight authenticated ticket request', async () => {
    let releaseTicket!: (ticket: string) => void
    client = new WSClient(() => new Promise((resolve) => { releaseTicket = resolve }))
    client.setAuthenticated(true)
    client.connect()
    expect(FakeWebSocket.instances).toHaveLength(0)

    client.setAuthenticated(false)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0].url).not.toContain('ticket=')

    releaseTicket('stale-auth-ticket')
    await Promise.resolve()
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  test('a real close of the live socket still reconnects with backoff', () => {
    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()

    first.fireClose(false)
    expect(client.connected).toBe(false)
    expect(FakeWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(100)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  test('disconnect stops reconnects and reports disconnection once', () => {
    const disconnected = vi.fn()
    client.on('disconnected', disconnected)

    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()

    client.disconnect()
    first.fireClose()
    vi.advanceTimersByTime(60_000)

    expect(disconnected).toHaveBeenCalledTimes(1)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})

// ─── J2: server error frames ──────────────────────────────────────────────────

describe('WSClient — server error frames', () => {
  test('emits an error frame to listeners', () => {
    const onError = vi.fn()
    client.on('error', onError)

    client.connect()
    const ws = FakeWebSocket.instances[0]
    ws.open()
    ws.receive({ type: 'error', code: 'forbidden', message: 'Access denied for this job' })

    expect(onError).toHaveBeenCalledWith({
      code: 'forbidden',
      message: 'Access denied for this job',
      job_id: undefined,
    })
  })

  test('forwards the job_id the server tags per-job rejections with', () => {
    const onError = vi.fn()
    client.on('error', onError)

    client.connect()
    const ws = FakeWebSocket.instances[0]
    ws.open()
    ws.receive({
      type: 'error',
      code: 'forbidden',
      message: 'Access denied for this job',
      job_id: 'job-2',
    })

    expect(onError).toHaveBeenCalledWith({
      code: 'forbidden',
      message: 'Access denied for this job',
      job_id: 'job-2',
    })
  })
})

// ─── J3 / J4: replay ──────────────────────────────────────────────────────────

describe('WSClient — replay', () => {
  test('the first subscribe replays from the start of the stream', () => {
    client.connect()
    const ws = FakeWebSocket.instances[0]
    ws.open()

    client.subscribe('job-1')

    expect(ws.subscribeFrames).toEqual([
      { type: 'subscribe', job_id: 'job-1', last_event_id: '0' },
    ])
  })

  test('resubscribe on reconnect carries the last seen stream id', () => {
    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()
    client.subscribe('job-1')
    first.receive({ type: 'event', event: event('job-1', 1), stream_id: '1700000000000-0' })

    first.fireClose(false)
    vi.advanceTimersByTime(100)
    const second = FakeWebSocket.instances[1]
    second.open()

    expect(second.subscribeFrames).toEqual([
      { type: 'subscribe', job_id: 'job-1', last_event_id: '1700000000000-0' },
    ])
  })

  test('resubscribe still replays from 0 when no event arrived before the outage', () => {
    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()
    client.subscribe('job-1')

    first.fireClose(false)
    vi.advanceTimersByTime(100)
    const second = FakeWebSocket.instances[1]
    second.open()

    expect(second.subscribeFrames).toEqual([
      { type: 'subscribe', job_id: 'job-1', last_event_id: '0' },
    ])
  })

  test('replayed events already delivered are dropped', () => {
    const onEvent = vi.fn()
    client.on('event', onEvent)

    client.connect()
    const first = FakeWebSocket.instances[0]
    first.open()
    client.subscribe('job-1')
    first.receive({ type: 'event', event: event('job-1', 1), stream_id: '1700000000000-0' })
    first.receive({ type: 'event', event: event('job-1', 2), stream_id: '1700000000000-1' })

    first.fireClose(false)
    vi.advanceTimersByTime(100)
    const second = FakeWebSocket.instances[1]
    second.open()
    // Server replays the last entry again plus one new one
    second.receive({ type: 'event', event: event('job-1', 2), stream_id: '1700000000000-1' })
    second.receive({ type: 'event', event: event('job-1', 3), stream_id: '1700000001000-0' })

    expect(onEvent.mock.calls.map(([e]) => (e as AnyEvent).sequence)).toEqual([1, 2, 3])
  })

  test('a second subscribe does not reset the watermark to 0', () => {
    client.connect()
    const ws = FakeWebSocket.instances[0]
    ws.open()

    client.subscribe('job-1')
    ws.receive({ type: 'event', event: event('job-1', 1), stream_id: '1700000000000-0' })

    // Another listener mounts for the same job (or React remounts the hook).
    client.subscribe('job-1')
    client.subscribe('job-1', '0')

    expect(ws.subscribeFrames).toEqual([
      { type: 'subscribe', job_id: 'job-1', last_event_id: '0' },
      { type: 'subscribe', job_id: 'job-1', last_event_id: '1700000000000-0' },
      { type: 'subscribe', job_id: 'job-1', last_event_id: '1700000000000-0' },
    ])
  })

  test('a re-subscribe after unsubscribe replays the whole stream again', () => {
    client.connect()
    const ws = FakeWebSocket.instances[0]
    ws.open()

    client.subscribe('job-1')
    ws.receive({ type: 'event', event: event('job-1', 1), stream_id: '1700000000000-0' })
    client.unsubscribe('job-1')
    client.subscribe('job-1')

    expect(ws.subscribeFrames[ws.subscribeFrames.length - 1]).toEqual({
      type: 'subscribe',
      job_id: 'job-1',
      last_event_id: '0',
    })
  })

  test('subscriptionCount tracks live subscriptions', () => {
    client.connect()
    FakeWebSocket.instances[0].open()

    expect(client.subscriptionCount).toBe(0)
    client.subscribe('job-1')
    client.subscribe('job-2')
    expect(client.subscriptionCount).toBe(2)
    client.unsubscribe('job-1')
    expect(client.subscriptionCount).toBe(1)
  })
})

// ─── stream id ordering ───────────────────────────────────────────────────────

describe('isNewerStreamId', () => {
  test('orders by milliseconds then sequence', () => {
    expect(isNewerStreamId('100-0', '0')).toBe(true)
    expect(isNewerStreamId('100-1', '100-0')).toBe(true)
    expect(isNewerStreamId('100-0', '100-0')).toBe(false)
    expect(isNewerStreamId('99-9', '100-0')).toBe(false)
  })
})
