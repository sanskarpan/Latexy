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
    const wsMod = await import('ws')
    const { LatexyWSClient } = await import('../lib/ws-client.js')
    client = new LatexyWSClient()
    client.connect('ws://localhost:8030/ws/jobs', 'testtoken')
    mockWSInstance = vi.mocked(wsMod.default).mock.results[0]!.value as unknown as typeof mockWSInstance
  })

  afterEach(() => {
    client.destroy()
    vi.clearAllMocks()
  })

  it('buffers events before drain()', () => {
    const received: unknown[] = []
    client.on('event', e => received.push(e))
    const ev = { type: 'log.line', job_id: 'j1', event_id: 'e1', sequence: 1, timestamp: 1, line: 'hello', level: 'info' }
    mockWSInstance.emit('message', Buffer.from(JSON.stringify(ev)))
    expect(received).toHaveLength(0)
    client.drain()
    expect(received).toHaveLength(1)
  })

  it('emits events immediately after drain()', () => {
    client.drain()
    const received: unknown[] = []
    client.on('event', e => received.push(e))
    const ev = { type: 'log.line', job_id: 'j1', event_id: 'e2', sequence: 2, timestamp: 2, line: 'world', level: 'info' }
    mockWSInstance.emit('message', Buffer.from(JSON.stringify(ev)))
    expect(received).toHaveLength(1)
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
