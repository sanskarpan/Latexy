'use client'

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { MessageSquare, Send } from 'lucide-react'
import {
  appendChatMessage,
  encodeChatFrame,
  parseChatFrame,
  parsePermissionDeniedFrame,
  type ChatConnectionState,
  type ChatFailure,
  type ChatMessage,
  type ChatPresence,
  type ChatTransport,
} from '@/lib/collab-chat'

export interface CollaboratorChatState {
  messages: ChatMessage[]
  connectionState: ChatConnectionState
  canChat: boolean
  canSend: boolean
  failure: ChatFailure | null
  send: (text: string) => boolean
  clear: () => void
}

export interface UseCollaboratorChatOptions {
  /** Change this whenever the resume/room changes. It clears ephemeral history. */
  roomKey: string
  /** Change this whenever the authenticated account changes. */
  authKey: string
  transport: ChatTransport | null
  presence?: readonly ChatPresence[]
  localSenderId?: string
  canChat?: boolean
}

function failureForPermission(code: string, message: string): ChatFailure | null {
  if (code === 'chat_rate_limited') return { code: 'rate-limited', message: 'You are sending messages too quickly. Please wait a moment.' }
  if (code === 'chat_forbidden') return { code: 'forbidden', message: 'Chat is no longer available for this resume.' }
  return message ? { code: 'send-failed', message } : null
}

async function frameBytes(value: unknown): Promise<Uint8Array | null> {
  if (value instanceof Blob) {
    try { return new Uint8Array(await value.arrayBuffer()) } catch { return null }
  }
  if (value instanceof Uint8Array) return value
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  return null
}

/**
 * Connect chat to the editor's already-authenticated collaboration transport.
 * The transport adapter owns the socket; this hook only handles chat frames and
 * a bounded in-memory transcript.
 */
export function useCollaboratorChat({
  roomKey,
  authKey,
  transport,
  presence = [],
  localSenderId,
  canChat = true,
}: UseCollaboratorChatOptions): CollaboratorChatState {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // No transport means the collaboration socket has not mounted or failed to
  // initialise; it is not evidence that a chat connection is still loading.
  // This avoids an infinite “Connecting…” state after ticket/init failures.
  const [connectionState, setConnectionState] = useState<ChatConnectionState>(transport?.state ?? 'disconnected')
  const [failure, setFailure] = useState<ChatFailure | null>(null)
  const presenceRef = useRef(presence)
  const localSenderIdRef = useRef(localSenderId)
  presenceRef.current = presence
  localSenderIdRef.current = localSenderId

  useEffect(() => {
    setMessages([])
    setFailure(null)
    let active = true
    const currentTransport = transport
    setConnectionState(currentTransport?.state ?? 'disconnected')
    if (!currentTransport) return () => { active = false }

    const offStatus = currentTransport.onStatus?.((state) => {
      if (active) setConnectionState(state)
    })
    const offFrame = currentTransport.onFrame((raw) => {
      void frameBytes(raw).then((bytes) => {
        if (!active || !bytes) return
        const parsed = parseChatFrame(bytes)
        if (parsed) {
          setMessages((previous) => appendChatMessage(previous, parsed, presenceRef.current, localSenderIdRef.current, Date.now()))
          return
        }
        const denied = parsePermissionDeniedFrame(bytes)
        if (denied) setFailure(failureForPermission(denied.code, denied.message))
      })
    })
    return () => {
      active = false
      offStatus?.()
      offFrame()
      currentTransport.dispose?.()
      setMessages([])
    }
  }, [roomKey, authKey, transport])

  const send = useCallback((text: string): boolean => {
    if (!canChat) {
      setFailure({ code: 'forbidden', message: 'You do not have permission to use chat.' })
      return false
    }
    if (!transport || (transport.state && transport.state !== 'connected')) {
      setFailure({ code: 'send-failed', message: 'Chat is disconnected. Reconnect and try again.' })
      return false
    }
    try {
      transport.send(encodeChatFrame(text))
      setFailure(null)
      // The backend intentionally excludes the sender from fan-out. Add one
      // local in-memory copy after send succeeds, so each authored message is
      // visible exactly once without putting chat in Y.Doc/history.
      const localId = localSenderIdRef.current ?? '__local__'
      setMessages((previous) => appendChatMessage(previous, { text, senderId: localId, senderLabel: 'You' }, presenceRef.current, localId, Date.now()))
      return true
    } catch (error) {
      setFailure({
        code: error instanceof Error && 'code' in error && (error as { code?: string }).code === 'invalid-text' ? 'invalid-text' : 'send-failed',
        message: error instanceof Error ? error.message : 'Message could not be sent.',
      })
      return false
    }
  }, [canChat, transport])

  const clear = useCallback(() => {
    setMessages([])
    setFailure(null)
  }, [])

  return { messages, connectionState, canChat, canSend: canChat && connectionState === 'connected', failure, send, clear }
}

export interface CollaboratorChatProps {
  chat: CollaboratorChatState
  onClose?: () => void
  title?: string
}

/** Accessible, plain-text-only chat transcript. History is explicitly ephemeral. */
export default function CollaboratorChat({ chat, onClose, title = 'Collaborator chat' }: CollaboratorChatProps) {
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const headingId = `collab-chat-heading-${useId().replace(/:/g, '')}`
  const statusText = chat.connectionState === 'loading'
    ? 'Connecting…'
    : chat.connectionState === 'connected'
      ? 'Connected'
      : 'Disconnected'

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!draft.trim() || chat.connectionState !== 'connected') return
    if (chat.send(draft)) setDraft('')
  }

  return (
    <section className="flex h-full w-full min-w-0 flex-col bg-surface" aria-labelledby={headingId}>
      <header className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <MessageSquare className="h-4 w-4 shrink-0 text-accent-strong" aria-hidden="true" />
          <h2 id={headingId} className="truncate text-sm font-semibold text-fg">{title}</h2>
          <span className="text-[11px] text-fg-3" role="status" aria-live="polite">{statusText}</span>
        </div>
        {onClose && <button type="button" onClick={onClose} aria-label="Close collaborator chat" className="rounded px-1 text-fg-3 hover:text-fg">×</button>}
      </header>

      <p className="border-b border-line px-4 py-2 text-[11px] leading-4 text-fg-3">Messages are live only and are not saved.</p>

      {!chat.canChat && (
        <p className="border-b border-line px-4 py-2 text-xs text-fg-2">You do not have permission to use chat.</p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2" role="log" aria-live="polite" aria-label="Chat messages">
        {chat.messages.length === 0 ? (
          <p className="py-8 text-center text-xs text-fg-3">No messages yet.</p>
        ) : (
          <ul className="space-y-2">
            {chat.messages.map((message) => (
              <li key={message.id} className="rounded border border-line bg-surface-2 px-3 py-2 text-xs">
                <p className="mb-0.5 text-[10px] font-semibold text-fg-2">{message.senderLabel}</p>
                <p className="whitespace-pre-wrap break-words text-fg">{message.text}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {chat.failure && <p role="alert" className="mx-3 mb-2 rounded border border-err/30 bg-err/10 px-2 py-1.5 text-xs text-err">{chat.failure.message}</p>}

      <form onSubmit={submit} className="flex shrink-0 gap-2 border-t border-line p-3">
        <label htmlFor={`${headingId}-input`} className="sr-only">Chat message</label>
        <input
          ref={inputRef}
          id={`${headingId}-input`}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={chat.connectionState === 'connected' && chat.failure?.code !== 'forbidden' ? 'Write a message…' : 'Chat unavailable'}
          disabled={!chat.canSend}
          maxLength={2048}
          className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2.5 py-2 text-xs text-fg outline-none focus:border-accent"
        />
        <button type="submit" disabled={!chat.canSend || !draft.trim()} aria-label="Send chat message" className="rounded bg-accent px-3 text-accent-fg disabled:cursor-not-allowed disabled:opacity-50">
          <Send className="h-4 w-4" aria-hidden="true" />
        </button>
      </form>
    </section>
  )
}
