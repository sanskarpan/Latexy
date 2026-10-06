import { describe, expect, it, vi } from 'vitest'
import {
  appendChatMessage,
  createYWebsocketChatTransport,
  encodeChatFrame,
  MAX_CHAT_FRAME_BYTES,
  MAX_CHAT_HISTORY,
  MAX_CHAT_TEXT_BYTES,
  parseChatFrame,
  parsePermissionDeniedFrame,
  senderLabel,
  utf8ByteLength,
} from '@/lib/collab-chat'

function varUint(value: number): number[] {
  const result: number[] = []
  do {
    const next = value % 128
    value = Math.floor(value / 128)
    result.push(value ? next + 128 : next)
  } while (value)
  return result
}

function serverFrame(payload: unknown, type = 62): Uint8Array {
  const body = new TextEncoder().encode(JSON.stringify(payload))
  return Uint8Array.from([...varUint(type), ...varUint(body.length), ...body])
}

describe('collaborator chat binary protocol', () => {
  it('encodes the backend-compatible chat frame without sender metadata', () => {
    const frame = encodeChatFrame('hello')
    expect(frame[0]).toBe(62)
    expect(parseChatFrame(frame)).toBeNull()
    expect(Array.from(frame.slice(2))).toEqual(Array.from(new TextEncoder().encode('{"type":"chat","text":"hello"}')))
  })

  it('parses only the canonical server shape and maps a valid sender', () => {
    const parsed = parseChatFrame(serverFrame({ type: 'chat', text: 'hello', sender_id: 'server-client', sender_label: 'Alice' }))
    expect(parsed).toEqual({ text: 'hello', senderId: 'server-client', senderLabel: 'Alice' })
  })

  it('rejects trailing bytes, spoofed fields, wrong message type, and malformed JSON', () => {
    const valid = serverFrame({ type: 'chat', text: 'hello', sender_id: 'server-client', sender_label: 'Alice' })
    expect(parseChatFrame(Uint8Array.from([...valid, 0]))).toBeNull()
    expect(parseChatFrame(serverFrame({ type: 'chat', text: 'hello', sender_id: 'x', html: '<b>bad</b>' }))).toBeNull()
    expect(parseChatFrame(serverFrame({ type: 'other', text: 'hello', sender_id: 'x' }))).toBeNull()
    expect(parseChatFrame(Uint8Array.from([62, 2, 0x7b, 0x7b]))).toBeNull()
    expect(parseChatFrame(Uint8Array.from([62, 1, 0xff]))).toBeNull()
    expect(parseChatFrame(serverFrame({ type: 'chat', text: 'hello', sender_id: 'x', sender_label: 'alice@example.com' }))).toBeNull()
    expect(parseChatFrame(serverFrame({ type: 'chat', text: 'hello', sender_id: 'x', sender_label: 'Alice\u202e' }))).toBeNull()
  })

  it('measures text and frames in UTF-8 bytes at multibyte boundaries', () => {
    const exact = '😀'.repeat(512)
    expect(utf8ByteLength(exact)).toBe(MAX_CHAT_TEXT_BYTES)
    expect(() => encodeChatFrame(exact)).not.toThrow()
    expect(() => encodeChatFrame(`${exact}😀`)).toThrow()
    expect(parseChatFrame(serverFrame({ type: 'chat', text: exact, sender_id: 'x', sender_label: 'Alice' }))).toEqual({ text: exact, senderId: 'x', senderLabel: 'Alice' })
    expect(parseChatFrame(serverFrame({ type: 'chat', text: `${exact}😀`, sender_id: 'x', sender_label: 'Alice' }))).toBeNull()
    expect(encodeChatFrame('x').byteLength).toBeLessThanOrEqual(MAX_CHAT_FRAME_BYTES)
  })

  it('rejects NUL, controls, carriage returns, and lone UTF-16 surrogates', () => {
    for (const value of ['bad\u0000text', 'bad\u0001text', 'bad\u007ftext', 'bad\rtext', 'bad\ud800text']) {
      expect(() => encodeChatFrame(value)).toThrow()
      expect(parseChatFrame(serverFrame({ type: 'chat', text: value, sender_id: 'x', sender_label: 'Alice' }))).toBeNull()
    }
    expect(encodeChatFrame('line 1\nline 2\tok')).toBeInstanceOf(Uint8Array)
  })

  it('does not expose raw sender ids and uses stable fallback labels', () => {
    expect(senderLabel('secret-client-id')).toBe('A collaborator')
    expect(senderLabel('secret-client-id', [{ clientId: 'secret-client-id', name: 'Alice' }])).toBe('Alice')
    expect(senderLabel('secret-client-id', [{ userId: 'secret-client-id', displayName: 'Alice' }])).toBe('Alice')
    expect(senderLabel('secret-client-id', [], 'secret-client-id')).toBe('You')
    expect(senderLabel('secret-client-id', [], undefined, 'alice@example.com')).toBe('A collaborator')
    expect(senderLabel('secret-client-id', [{ clientId: 'secret-client-id', name: 'Alice\u200b' }])).toBe('A collaborator')
  })

  it('keeps only bounded in-memory history', () => {
    let messages = [] as ReturnType<typeof appendChatMessage>
    for (let index = 0; index < MAX_CHAT_HISTORY + 5; index += 1) {
      messages = appendChatMessage(messages, { text: String(index), senderId: `server-${index}`, senderLabel: 'A collaborator' }, [], undefined, index)
    }
    expect(messages).toHaveLength(MAX_CHAT_HISTORY)
    expect(messages[0]?.text).toBe('5')
    expect(messages[messages.length - 1]?.text).toBe(String(MAX_CHAT_HISTORY + 4))
  })

  it('recognizes only chat permission/rate-limit notices', () => {
    expect(parsePermissionDeniedFrame(serverFrame({ code: 'chat_rate_limited', message: 'slow down' }, 63))).toEqual({ code: 'chat_rate_limited', message: 'slow down' })
    expect(parsePermissionDeniedFrame(serverFrame({ code: 'chat_forbidden', message: 'gone' }, 63))).toEqual({ code: 'chat_forbidden', message: 'gone' })
    expect(parsePermissionDeniedFrame(serverFrame({ code: 'read_only', message: 'not chat' }, 63))).toBeNull()
    expect(parsePermissionDeniedFrame(serverFrame({ code: 'chat_forbidden', message: 'gone' }, 62))).toBeNull()
  })
})

describe('y-websocket chat transport', () => {
  function fakeProvider() {
    const status = new Set<(payload: { status?: string }) => void>()
    const provider = {
      ws: { readyState: 1, send: vi.fn() },
      wsconnected: true,
      wsconnecting: false,
      messageHandlers: [] as unknown[],
      on: vi.fn((event: 'status', listener: (payload: { status?: string }) => void) => {
        if (event === 'status') status.add(listener)
      }),
      off: vi.fn((event: 'status', listener: (payload: { status?: string }) => void) => {
        if (event === 'status') status.delete(listener)
      }),
      emitStatus: (value: { status?: string }) => status.forEach((listener) => listener(value)),
    }
    return provider
  }

  it('uses the existing authenticated socket and reconstructs incoming frames', () => {
    const provider = fakeProvider()
    const transport = createYWebsocketChatTransport(provider)
    const frames: unknown[] = []
    transport.onFrame((frame) => frames.push(frame))
    const payload = new TextEncoder().encode(JSON.stringify({ type: 'chat', text: 'hello', sender_id: 'socket', sender_label: 'Alice' }))
    const handler = provider.messageHandlers[62] as ((encoder: unknown, decoder: { arr: Uint8Array; pos: number }) => void)
    handler({}, { arr: Uint8Array.from([62, payload.byteLength, ...payload]), pos: 1 })
    expect(parseChatFrame(frames[0])).toEqual({ text: 'hello', senderId: 'socket', senderLabel: 'Alice' })
    const denial = new TextEncoder().encode(JSON.stringify({ code: 'chat_forbidden', message: 'gone' }))
    const denialHandler = provider.messageHandlers[63] as ((encoder: unknown, decoder: { arr: Uint8Array; pos: number }) => void)
    denialHandler({}, { arr: Uint8Array.from([63, denial.byteLength, ...denial]), pos: 1 })
    expect(parsePermissionDeniedFrame(frames[1])).toEqual({ code: 'chat_forbidden', message: 'gone' })
    const outgoing = encodeChatFrame('reply')
    transport.send(outgoing)
    expect(provider.ws.send).toHaveBeenCalledWith(outgoing)
    transport.dispose?.()
    expect(provider.off).toHaveBeenCalled()
    expect(provider.messageHandlers[62]).toBeUndefined()
  })

  it('maps provider status and refuses a closed socket', () => {
    const provider = fakeProvider()
    const transport = createYWebsocketChatTransport(provider)
    const states: string[] = []
    transport.onStatus?.((state) => states.push(state))
    provider.emitStatus({ status: 'connecting' })
    provider.emitStatus({ status: 'disconnected' })
    expect(states).toEqual(['loading', 'disconnected'])
    provider.ws.readyState = 3
    expect(() => transport.send(encodeChatFrame('x'))).toThrow(/disconnected/i)
  })

  it('keeps state live across connection and safely replaces duplicate adapters', () => {
    const provider = fakeProvider()
    provider.wsconnected = false
    provider.wsconnecting = true
    const first = createYWebsocketChatTransport(provider)
    expect(first.state).toBe('loading')
    expect(() => first.send(encodeChatFrame('before'))).toThrow(/disconnected/i)

    provider.wsconnected = true
    provider.wsconnecting = false
    provider.emitStatus({ status: 'connected' })
    expect(first.state).toBe('connected')
    first.send(encodeChatFrame('after'))

    const second = createYWebsocketChatTransport(provider)
    expect(first.state).toBe('connected')
    expect(() => first.send(encodeChatFrame('stale'))).toThrow(/no longer active/i)
    second.send(encodeChatFrame('current'))
    second.dispose?.()
  })
})
