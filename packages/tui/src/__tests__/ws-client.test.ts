import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'

vi.mock('ws', () => {
  const MockWSClass = class extends EventEmitter {
    readyState = 1
    send = vi.fn()
    close = vi.fn()
    ping = vi.fn()
    static OPEN = 1
    static CONNECTING = 0
    static CLOSED = 3
  }
  const mockFactory = vi.fn(() => new MockWSClass())
  // ws exposes WebSocket on its default export (same as the factory)
  Object.assign(mockFactory, { WebSocket: MockWSClass, OPEN: 1, CONNECTING: 0, CLOSED: 3 })
  return {
    default: mockFactory,
    WebSocket: MockWSClass,
  }
})

describe('LatexyWSClient', () => {
  let client: import('../lib/ws-client.js').LatexyWSClient
  let mockWSInstance: EventEmitter & { send: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn>; ping: ReturnType<typeof vi.fn>; readyState: number }

  beforeEach(async () => {
    vi.resetModules()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ticket: 'ticket-1', expires_in: 60 }),
    }))
    const wsMod = await import('ws')
    const { LatexyWSClient } = await import('../lib/ws-client.js')
    client = new LatexyWSClient()
    client.connect('ws://localhost:8030/ws/jobs', 'testtoken')
    await vi.waitFor(() => expect(vi.mocked(wsMod.default)).toHaveBeenCalledTimes(1))
    mockWSInstance = vi.mocked(wsMod.default).mock.results[0]!.value as unknown as typeof mockWSInstance
  })

  afterEach(() => {
    client.destroy()
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('buffers events before drain()', () => {
    const received: unknown[] = []
    client.on('event', e => received.push(e))
    const inner = { type: 'log.line', job_id: 'j1', event_id: 'e1', sequence: 1, timestamp: 1, line: 'hello', level: 'info' }
    mockWSInstance.emit('message', Buffer.from(JSON.stringify({ type: 'event', event: inner })))
    expect(received).toHaveLength(0)
    client.drain()
    expect(received).toHaveLength(1)
  })

  it('emits events immediately after drain()', () => {
    client.drain()
    const received: unknown[] = []
    client.on('event', e => received.push(e))
    const inner = { type: 'log.line', job_id: 'j1', event_id: 'e2', sequence: 2, timestamp: 2, line: 'world', level: 'info' }
    mockWSInstance.emit('message', Buffer.from(JSON.stringify({ type: 'event', event: inner })))
    expect(received).toHaveLength(1)
  })

  it('exchanges the session token over HTTP and passes only a one-time ticket to WebSocket', async () => {
    const wsMod = await import('ws')
    expect(fetch).toHaveBeenCalledWith(
      new URL('http://localhost:8030/ws/ticket'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer testtoken' }),
        body: JSON.stringify({ purpose: 'jobs' }),
      })
    )
    expect(vi.mocked(wsMod.default).mock.calls[0]?.[0]).toBe(
      'ws://localhost:8030/ws/jobs?ticket=ticket-1'
    )
    expect(vi.mocked(wsMod.default).mock.calls[0]?.[1]).toBeUndefined()
    expect(String(vi.mocked(wsMod.default).mock.calls[0]?.[0])).not.toContain('testtoken')
  })

  it('mints a fresh ticket for every reconnect', async () => {
    const wsMod = await import('ws')
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ticket: 'ticket-2', expires_in: 60 }),
    } as unknown as Response)
    mockWSInstance.emit('close', 1006)
    await vi.waitFor(() => expect(vi.mocked(wsMod.default)).toHaveBeenCalledTimes(2))
    expect(vi.mocked(wsMod.default).mock.calls.at(-1)?.[0]).toBe(
      'ws://localhost:8030/ws/jobs?ticket=ticket-2'
    )
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('does not open a socket when logout wins a pending ticket request', async () => {
    const wsMod = await import('ws')
    const { LatexyWSClient } = await import('../lib/ws-client.js')
    let finishTicket!: (value: Response) => void
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => {
      finishTicket = resolve
    }))

    const pendingClient = new LatexyWSClient()
    pendingClient.connect('ws://localhost:8030/ws/jobs', 'session-that-is-logging-out')
    pendingClient.destroy()
    finishTicket({
      ok: true,
      status: 200,
      json: async () => ({ ticket: 'stale-ticket', expires_in: 60 }),
    } as Response)
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(vi.mocked(wsMod.default)).toHaveBeenCalledTimes(1)
  })

  it('emits server_error for {type:"error"} frames instead of dropping them', () => {
    const errors: unknown[] = []
    client.on('server_error', e => errors.push(e))
    mockWSInstance.emit('message', Buffer.from(JSON.stringify({
      type: 'error', code: 'forbidden', message: 'Access denied for this job',
    })))
    expect(errors).toEqual([{ code: 'forbidden', message: 'Access denied for this job' }])
  })

  it('forwards job_id on per-job rejections so callers can scope the failure', () => {
    const errors: unknown[] = []
    client.on('server_error', e => errors.push(e))
    mockWSInstance.emit('message', Buffer.from(JSON.stringify({
      type: 'error', code: 'forbidden', message: 'Access denied for this job', job_id: 'job-9',
    })))
    expect(errors).toEqual([
      { code: 'forbidden', message: 'Access denied for this job', job_id: 'job-9' },
    ])
  })

  it('subscribe() sends correct subscribe message', () => {
    client.drain()
    mockWSInstance.emit('open')
    client.subscribe('job123', '0')
    expect(mockWSInstance.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'subscribe', job_id: 'job123', last_event_id: '0' })
    )
  })
})
