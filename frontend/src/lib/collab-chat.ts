/**
 * Ephemeral collaborator chat protocol (#1391).
 *
 * Chat is a small extension to the y-websocket binary stream. It is never
 * written to the Y.Doc or any browser/server persistence layer. Keep this
 * module deliberately independent from Yjs so chat cannot accidentally become
 * part of document history.
 */

export const MSG_CHAT = 62
export const MSG_PERMISSION_DENIED = 63
export const MAX_CHAT_TEXT_BYTES = 2 * 1024
export const MAX_CHAT_FRAME_BYTES = 4 * 1024
export const MAX_CHAT_HISTORY = 100

export type ChatConnectionState = 'loading' | 'connected' | 'disconnected'
export type ChatFailureCode = 'send-failed' | 'rate-limited' | 'forbidden' | 'invalid-text'

export interface ChatPresence {
  /** Transport/client identifier, if the integration can correlate it. */
  clientId?: string | number
  /** Awareness user identifier is accepted only for correlation, never rendered. */
  userId?: string
  name?: string
  displayName?: string
}

export interface ChatTransport {
  send: (frame: Uint8Array) => void
  onFrame: (listener: (frame: unknown) => void) => (() => void)
  onStatus?: (listener: (state: ChatConnectionState) => void) => (() => void)
  state?: ChatConnectionState
  dispose?: () => void
}

/** The small public surface of y-websocket used by the chat adapter. Keeping
 * this structural avoids importing the provider in the chat module (and keeps
 * the protocol usable in unit tests). */
export interface YWebsocketChatProvider {
  ws: { readyState: number; send: (data: Uint8Array) => void } | null
  wsconnected: boolean
  wsconnecting: boolean
  messageHandlers: unknown[]
  on: (event: 'status', listener: (payload: { status?: string }) => void) => unknown
  off: (event: 'status', listener: (payload: { status?: string }) => void) => unknown
}

export interface ChatMessage {
  id: string
  text: string
  senderLabel: string
  receivedAt: number
}

export interface ChatFailure {
  code: ChatFailureCode
  message: string
}

export interface ParsedChatMessage {
  text: string
  senderId: string
  /** Server-authenticated User.name, or a generic fallback. */
  senderLabel: string
}

const CONTROL_REPLACEMENT = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u
// Reject Cc/Cf/Cs-like controls that can make a displayed identity deceptive
// (including bidi overrides/isolates and zero-width formatting characters).
const LABEL_UNSAFE_RE = /[\u0000-\u001f\u007f-\u009f\u00ad\u0600-\u0605\u061c\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]/u
const activeChatAdapters = new WeakMap<YWebsocketChatProvider, ChatTransport>()

function safeDisplayLabel(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const label = value.trim()
  if (!label || label.length > 80 || label.includes('@') || hasLoneSurrogate(label) || LABEL_UNSAFE_RE.test(label) || utf8ByteLength(label) > 320) return null
  return label
}

export function utf8ByteLength(value: string): number {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(value).byteLength
  return encodeURIComponent(value).replace(/%[0-9A-F]{2}|./g, '_').length
}

function hasLoneSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1)
      if (next < 0xdc00 || next > 0xdfff) return true
      index += 1
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true
    }
  }
  return false
}

function validateText(text: unknown): asserts text is string {
  if (typeof text !== 'string' || text.trim().length === 0) throw new ChatProtocolError('invalid-text', 'Message cannot be empty')
  if (hasLoneSurrogate(text)) throw new ChatProtocolError('invalid-text', 'Message contains invalid text')
  if (CONTROL_REPLACEMENT.test(text) || text.includes('\r')) {
    throw new ChatProtocolError('invalid-text', 'Message contains unsupported control characters')
  }
  if (utf8ByteLength(text) > MAX_CHAT_TEXT_BYTES) {
    throw new ChatProtocolError('invalid-text', 'Message is too long (2 KiB maximum)')
  }
}

export class ChatProtocolError extends Error {
  readonly code: ChatFailureCode

  constructor(code: ChatFailureCode, message: string) {
    super(message)
    this.name = 'ChatProtocolError'
    this.code = code
  }
}

function encodeVarUint(value: number): Uint8Array {
  if (!Number.isSafeInteger(value) || value < 0) throw new ChatProtocolError('invalid-text', 'Invalid chat frame')
  const bytes: number[] = []
  do {
    const next = value & 0x7f
    value = Math.floor(value / 128)
    bytes.push(value > 0 ? next | 0x80 : next)
  } while (value > 0)
  return Uint8Array.from(bytes)
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.byteLength, 0)
  const result = new Uint8Array(total)
  let offset = 0
  for (const part of parts) {
    result.set(part, offset)
    offset += part.byteLength
  }
  return result
}

/** Encode exactly `varuint(62) + varbuffer(UTF-8 JSON {type,text})`. */
export function encodeChatFrame(text: string): Uint8Array {
  validateText(text)
  const payload = new TextEncoder().encode(JSON.stringify({ type: 'chat', text }))
  const frame = concat(encodeVarUint(MSG_CHAT), encodeVarUint(payload.byteLength), payload)
  if (frame.byteLength > MAX_CHAT_FRAME_BYTES) throw new ChatProtocolError('invalid-text', 'Message frame is too large')
  return frame
}

function toBytes(value: unknown): Uint8Array | null {
  if (value instanceof Uint8Array) return value
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  return null
}

function decodeVarUint(data: Uint8Array, start: number): { value: number; next: number } | null {
  let value = 0
  let multiplier = 1
  let position = start
  for (let count = 0; count < 5; count += 1) {
    if (position >= data.length) return null
    const byte = data[position++]
    value += (byte & 0x7f) * multiplier
    if ((byte & 0x80) === 0) {
      // Reject non-canonical encodings (e.g. 62 encoded as 0xBE 0x00).
      if (encodeVarUint(value).byteLength !== position - start) return null
      return { value, next: position }
    }
    multiplier *= 128
  }
  return null
}

function decodeVarBuffer(data: Uint8Array, start: number): { value: Uint8Array; next: number } | null {
  const length = decodeVarUint(data, start)
  if (!length || length.value > data.length - length.next) return null
  const end = length.next + length.value
  return { value: data.slice(length.next, end), next: end }
}

function strictJson(value: Uint8Array): unknown | null {
  try {
    // fatal prevents malformed UTF-8 from being silently replaced.
    const decoded = new TextDecoder('utf-8', { fatal: true }).decode(value)
    return JSON.parse(decoded) as unknown
  } catch {
    return null
  }
}

/** Strictly parse one canonical server chat frame; trailing bytes are rejected. */
export function parseChatFrame(frame: unknown): ParsedChatMessage | null {
  const data = toBytes(frame)
  if (!data || data.byteLength > MAX_CHAT_FRAME_BYTES) return null
  const type = decodeVarUint(data, 0)
  if (!type || type.value !== MSG_CHAT) return null
  const payload = decodeVarBuffer(data, type.next)
  if (!payload || payload.next !== data.length) return null
  const decoded = strictJson(payload.value)
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) return null
  const candidate = decoded as Record<string, unknown>
  if (Object.keys(candidate).length !== 4 || candidate.type !== 'chat' || typeof candidate.text !== 'string' || typeof candidate.sender_id !== 'string' || typeof candidate.sender_label !== 'string') return null
  try {
    validateText(candidate.text)
  } catch {
    return null
  }
  if (candidate.sender_id.length === 0 || candidate.sender_id.length > 128 || hasLoneSurrogate(candidate.sender_id) || CONTROL_REPLACEMENT.test(candidate.sender_id) || candidate.sender_id.includes('\r')) return null
  if (utf8ByteLength(candidate.sender_id) > 512) return null
  const label = safeDisplayLabel(candidate.sender_label)
  if (!label) return null
  return { text: candidate.text, senderId: candidate.sender_id, senderLabel: label }
}

export interface ParsedPermissionDenied {
  code: string
  message: string
}

export function parsePermissionDeniedFrame(frame: unknown): ParsedPermissionDenied | null {
  const data = toBytes(frame)
  if (!data || data.byteLength > MAX_CHAT_FRAME_BYTES) return null
  const type = decodeVarUint(data, 0)
  if (!type || type.value !== MSG_PERMISSION_DENIED) return null
  const payload = decodeVarBuffer(data, type.next)
  if (!payload || payload.next !== data.length) return null
  const decoded = strictJson(payload.value)
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) return null
  const candidate = decoded as Record<string, unknown>
  if (typeof candidate.code !== 'string' || typeof candidate.message !== 'string') return null
  if (candidate.code !== 'chat_rate_limited' && candidate.code !== 'chat_forbidden') return null
  return { code: candidate.code, message: candidate.message.slice(0, 240) }
}

/** Convert an untrusted server id to a privacy-safe visible label. */
export function senderLabel(senderId: string, presence: readonly ChatPresence[] = [], localSenderId?: string, authenticatedLabel?: string): string {
  if (localSenderId && senderId === localSenderId) return 'You'
  const safeAuthenticatedLabel = safeDisplayLabel(authenticatedLabel)
  if (safeAuthenticatedLabel) return safeAuthenticatedLabel
  const match = presence.find((item) => String(item.clientId ?? '') === senderId || (item.userId && item.userId === senderId))
  const label = safeDisplayLabel(match?.displayName) || safeDisplayLabel(match?.name)
  return label ?? 'A collaborator'
}

export function appendChatMessage(messages: readonly ChatMessage[], parsed: ParsedChatMessage, presence: readonly ChatPresence[] = [], localSenderId?: string, receivedAt = Date.now()): ChatMessage[] {
  const randomId = typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : Math.random().toString(36).slice(2)
  const next: ChatMessage = {
    id: `chat-${receivedAt}-${randomId}`,
    text: parsed.text,
    senderLabel: senderLabel(parsed.senderId, presence, localSenderId, parsed.senderLabel),
    receivedAt,
  }
  return [...messages, next].slice(-MAX_CHAT_HISTORY)
}

/**
 * Adapt the already-authenticated y-websocket connection to the chat hook.
 * y-websocket dispatches unknown message types through `messageHandlers`; the
 * adapter consumes only MSG_CHAT and never replaces the provider's socket or
 * auth parameters. Chat frames bypass Y.Doc/awareness and are therefore never
 * persisted or replayed by the collaboration provider.
 */
export function createYWebsocketChatTransport(provider: YWebsocketChatProvider): ChatTransport {
  const existing = activeChatAdapters.get(provider)
  existing?.dispose?.()
  const listeners = new Set<(frame: unknown) => void>()
  const statusListeners = new Set<(state: ChatConnectionState) => void>()
  const previousHandler = provider.messageHandlers[MSG_CHAT]
  const previousPermissionHandler = provider.messageHandlers[MSG_PERMISSION_DENIED]
  const getState = (): ChatConnectionState => provider.wsconnected ? 'connected' : provider.wsconnecting ? 'loading' : 'disconnected'
  const emitStatus = (state: ChatConnectionState) => {
    for (const listener of statusListeners) listener(state)
  }
  const chatHandler = (_encoder: unknown, decoder: { arr: Uint8Array; pos: number }) => {
    // readMessage has consumed only the message type. Copy the remaining
    // varbuffer bytes so the parser sees the canonical complete frame.
    const frame = new Uint8Array(1 + decoder.arr.length - decoder.pos)
    frame[0] = MSG_CHAT
    frame.set(decoder.arr.subarray(decoder.pos), 1)
    for (const listener of listeners) listener(frame)
  }
  provider.messageHandlers[MSG_CHAT] = chatHandler
  const permissionHandler = (encoder: unknown, decoder: { arr: Uint8Array; pos: number }, ...args: unknown[]) => {
    const frame = new Uint8Array(1 + decoder.arr.length - decoder.pos)
    frame[0] = MSG_PERMISSION_DENIED
    frame.set(decoder.arr.subarray(decoder.pos), 1)
    for (const listener of listeners) listener(frame)
    if (typeof previousPermissionHandler === 'function') previousPermissionHandler(encoder, decoder, ...args)
  }
  provider.messageHandlers[MSG_PERMISSION_DENIED] = permissionHandler
  const onStatus = (payload: { status?: string }) => {
    const state = payload?.status === 'connected' ? 'connected' : payload?.status === 'connecting' ? 'loading' : 'disconnected'
    emitStatus(state)
  }
  provider.on('status', onStatus)

  let disposed = false
  let transport: ChatTransport
  transport = {
    get state() { return getState() },
    send(frame) {
      if (disposed) throw new ChatProtocolError('send-failed', 'Chat transport is no longer active.')
      const socket = provider.ws
      // WebSocket.OPEN is 1; using the numeric constant keeps this adapter
      // testable in Node and avoids touching a different/global socket.
      if (!provider.wsconnected || !socket || socket.readyState !== 1) throw new ChatProtocolError('send-failed', 'Chat is disconnected. Reconnect and try again.')
      if (frame.byteLength === 0 || frame[0] !== MSG_CHAT) throw new ChatProtocolError('invalid-text', 'Invalid chat frame')
      if (frame.byteLength > MAX_CHAT_FRAME_BYTES) throw new ChatProtocolError('invalid-text', 'Message frame is too large')
      socket.send(frame)
    },
    onFrame(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    onStatus(listener) {
      statusListeners.add(listener)
      return () => statusListeners.delete(listener)
    },
    dispose() {
      if (disposed) return
      disposed = true
      if (activeChatAdapters.get(provider) !== transport) return
      if (provider.messageHandlers[MSG_CHAT] === chatHandler) provider.messageHandlers[MSG_CHAT] = previousHandler
      if (provider.messageHandlers[MSG_PERMISSION_DENIED] === permissionHandler) provider.messageHandlers[MSG_PERMISSION_DENIED] = previousPermissionHandler
      provider.off('status', onStatus)
      listeners.clear()
      statusListeners.clear()
      activeChatAdapters.delete(provider)
    },
  }
  activeChatAdapters.set(provider, transport)
  return transport
}
