/**
 * WSClient — singleton WebSocket manager for Latexy.
 *
 * Features:
 * - Single persistent WebSocket to /ws/jobs — a socket that is replaced
 *   (auth change/disconnect) is detached first so its late close event cannot
 *   tear down or duplicate the live one
 * - Exponential backoff reconnect (100ms → 200ms → 400ms → … max 30s)
 * - Auto-resubscribes all pending jobs on reconnect, sending last_event_id
 *   so the server replays missed events ("0" = replay the whole stream)
 * - Drops replayed events the client has already seen (stream IDs are
 *   monotonic), so the non-idempotent UI reducer never sees a duplicate
 * - Typed event emitter: on/off for "connected" | "disconnected" |
 *   "event" | "subscribed" | "error"
 * - Heartbeat ping every 25s when connected
 */

import { apiClient, getWebSocketUrl } from './api-client'
import type { AnyEvent } from './event-types'
import { createTraceHeaders } from './telemetry'

// ------------------------------------------------------------------ //
//  Event emitter types                                                //
// ------------------------------------------------------------------ //

type WSEventType = 'connected' | 'disconnected' | 'event' | 'subscribed' | 'error'

type WSEventHandler<T = unknown> = (payload: T) => void

interface WSEventMap {
  connected: void
  disconnected: { wasClean: boolean }
  event: AnyEvent
  subscribed: { job_id: string; replayed_count: number }
  /** `job_id` is present only when the rejection concerns one specific job
   *  (subscribe/cancel/rate-limit). Connection-wide errors (invalid_json,
   *  unknown_message_type) carry no job_id. */
  error: { code: string; message: string; job_id?: string }
}

// ------------------------------------------------------------------ //
//  Stream ID ordering                                                 //
// ------------------------------------------------------------------ //

/** Compare two Redis Stream entry IDs ("<milliseconds>-<sequence>").
 *  Returns true when `candidate` is strictly newer than `lastSeen`. */
export function isNewerStreamId(candidate: string, lastSeen: string): boolean {
  const [candMs, candSeq] = candidate.split('-').map(Number)
  const [lastMs, lastSeq] = lastSeen.split('-').map(Number)
  if (Number.isNaN(candMs) || Number.isNaN(lastMs)) return true
  if (candMs !== lastMs) return candMs > lastMs
  return (candSeq || 0) > (lastSeq || 0)
}

// ------------------------------------------------------------------ //
//  WSClient                                                           //
// ------------------------------------------------------------------ //

export class WSClient {
  private _ws: WebSocket | null = null
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _reconnectAttempt = 0
  private _maxReconnectDelay = 30_000 // ms
  private _heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private _manuallyDisconnected = false
  private _connectRequested = false
  private _socketGeneration = 0

  /** Whether the HTTP client can mint an authenticated one-time WS ticket. The
   * reusable Better Auth credential stays inside apiClient and never enters a
   * WebSocket URL. */
  private _authenticated = false

  constructor(
    private readonly _ticketProvider: () => Promise<string> = async () =>
      (await apiClient.createWebSocketTicket('jobs')).ticket,
  ) {}

  /**
   * job_id → last received stream entry ID (for replay on reconnect).
   * "0" (the initial value) means "replay the entire stream", so events
   * published before the subscribe frame lands are never lost.
   */
  private _subscriptions = new Map<string, string>()

  /** Multi-listener event emitter */
  private _listeners = new Map<WSEventType, Set<WSEventHandler<any>>>()

  // ---------------------------------------------------------------- //
  //  Connection management                                            //
  // ---------------------------------------------------------------- //

  connect(): void {
    this._manuallyDisconnected = false
    this._connectRequested = true

    if (this._ws && this._ws.readyState === WebSocket.OPEN) return
    if (this._ws && this._ws.readyState === WebSocket.CONNECTING) return

    this._openSocket()
  }

  /** Reconnect when the resolved session changes between anonymous/authenticated.
   * Authenticated handshakes mint a fresh purpose-bound, single-use ticket. */
  setAuthenticated(authenticated: boolean): void {
    if (this._authenticated === authenticated) return
    this._authenticated = authenticated
    this._socketGeneration++ // invalidate an in-flight ticket request
    if (this._ws) {
      this._closeSocket(1000, 'Reconnect with updated auth')
    }
    if (this._connectRequested && !this._manuallyDisconnected) this._openSocket()
  }

  disconnect(): void {
    this._manuallyDisconnected = true
    this._connectRequested = false
    this._socketGeneration++ // invalidate an in-flight ticket request
    this._cancelReconnect()
    if (this._ws) {
      this._closeSocket(1000, 'Client disconnect')
      // The detached socket's close event is ignored, so announce it here.
      this._emit('disconnected', { wasClean: true })
    }
  }

  get connected(): boolean {
    return this._ws?.readyState === WebSocket.OPEN
  }

  // ---------------------------------------------------------------- //
  //  Subscription management                                          //
  // ---------------------------------------------------------------- //

  subscribe(jobId: string, lastEventId?: string): void {
    // Default "0" = replay from the start of the stream. Without it every event
    // published before this frame reaches the server (job.queued, and for fast
    // jobs job.completed itself) would be lost.
    //
    // An explicit "0" must never clobber an existing watermark: a second
    // subscriber (or a Fast Refresh / StrictMode remount) would then force a
    // full server replay that the shared 'event' emitter fans out to the
    // already-running listeners, whose reducers append log lines blindly.
    const known = this._subscriptions.get(jobId)
    const requested = lastEventId ?? known ?? '0'
    const from = known && requested === '0' ? known : requested
    this._subscriptions.set(jobId, from)
    this._sendSubscribe(jobId, from)
  }

  /** Number of jobs currently subscribed on this connection. Used to decide
   *  whether an error frame without a job_id can be attributed unambiguously. */
  get subscriptionCount(): number {
    return this._subscriptions.size
  }

  unsubscribe(jobId: string): void {
    this._subscriptions.delete(jobId)
    this._send({ type: 'unsubscribe', job_id: jobId })
  }

  cancelJob(jobId: string): void {
    this._send({ type: 'cancel', job_id: jobId })
  }

  ping(): void {
    this._send({ type: 'ping' })
  }

  // ---------------------------------------------------------------- //
  //  Event emitter                                                    //
  // ---------------------------------------------------------------- //

  on<K extends WSEventType>(event: K, handler: WSEventHandler<WSEventMap[K]>): void {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set())
    this._listeners.get(event)!.add(handler)
  }

  off<K extends WSEventType>(event: K, handler: WSEventHandler<WSEventMap[K]>): void {
    this._listeners.get(event)?.delete(handler)
  }

  // ---------------------------------------------------------------- //
  //  Private helpers                                                  //
  // ---------------------------------------------------------------- //

  private _openSocket(): void {
    this._cancelReconnect()
    // Never leave a previous socket attached — exactly one live socket per client.
    if (this._ws) this._closeSocket(1000, 'Replaced by new connection')

    const generation = ++this._socketGeneration
    if (!this._authenticated) {
      this._createSocket(null, generation)
      return
    }

    // Fetch over normal authenticated HTTP so the reusable session credential
    // never appears in the WebSocket request URL. Every reconnect gets a new
    // ticket because the backend atomically consumes it on first use.
    void this._ticketProvider()
      .then((ticket) => this._createSocket(ticket, generation))
      .catch(() => {
        if (generation === this._socketGeneration && !this._manuallyDisconnected) {
          this._scheduleReconnect()
        }
      })
  }

  private _createSocket(ticket: string | null, generation: number): void {
    if (generation !== this._socketGeneration || this._manuallyDisconnected) return
    try {
      const url = new URL(getWebSocketUrl())
      const traceHeaders = createTraceHeaders()
      if (traceHeaders.traceparent) {
        url.searchParams.set('traceparent', traceHeaders.traceparent)
      }
      if (traceHeaders['X-Request-ID']) {
        url.searchParams.set('request_id', traceHeaders['X-Request-ID'])
      }
      if (ticket) {
        url.searchParams.set('ticket', ticket)
      }
      const ws = new WebSocket(url.toString())
      this._ws = ws

      ws.onopen = () => {
        if (this._ws !== ws) return // superseded socket — ignore
        this._reconnectAttempt = 0
        this._startHeartbeat()
        this._emit('connected', undefined)

        // Re-subscribe to all jobs, sending last_event_id for replay
        for (const [jobId, lastEventId] of this._subscriptions) {
          this._sendSubscribe(jobId, lastEventId)
        }
      }

      ws.onmessage = (event: MessageEvent) => {
        if (this._ws !== ws) return // superseded socket — ignore
        this._handleMessage(event.data)
      }

      ws.onclose = (event: CloseEvent) => {
        // A socket replaced by an auth change/disconnect closes asynchronously.
        // Without this identity check it would null out (and schedule a
        // reconnect for) the socket that already took its place.
        if (this._ws !== ws) return

        this._stopHeartbeat()
        this._ws = null
        this._emit('disconnected', { wasClean: event.wasClean })

        if (!this._manuallyDisconnected) {
          this._scheduleReconnect()
        }
      }

      ws.onerror = () => {
        // onclose will fire after onerror — no extra handling needed
      }
    } catch (err) {
      this._scheduleReconnect()
    }
  }

  /** Detach every handler from the current socket and close it. The detached
   *  socket can still emit close/message events; they are dropped by the
   *  `this._ws !== ws` identity checks (and by having no handlers at all). */
  private _closeSocket(code: number, reason: string): void {
    const ws = this._ws
    if (!ws) return

    this._ws = null
    this._stopHeartbeat()
    ws.onopen = null
    ws.onmessage = null
    ws.onclose = null
    ws.onerror = null
    ws.close(code, reason)
  }

  private _handleMessage(raw: string): void {
    let msg: Record<string, unknown>
    try {
      msg = JSON.parse(raw)
    } catch {
      return
    }

    const type = msg.type as string

    if (type === 'event') {
      const evt = msg.event as AnyEvent
      if (evt) {
        // Track the Redis Stream entry ID (format: milliseconds-sequence, e.g. "1234567890123-0")
        // so we can resume replay from the correct position on reconnect.
        // The server includes this as msg.stream_id in every event envelope.
        const jobId = evt.job_id
        const streamId = msg.stream_id as string | undefined
        if (jobId && this._subscriptions.has(jobId) && streamId) {
          const lastSeen = this._subscriptions.get(jobId)!
          // Stream IDs are monotonic, so anything not strictly newer than the
          // last delivered entry is a replay of something the reducer already
          // consumed — drop it rather than double-applying it.
          if (!isNewerStreamId(streamId, lastSeen)) return
          this._subscriptions.set(jobId, streamId)
        }
        this._emit('event', evt)
      }
    } else if (type === 'subscribed') {
      this._emit('subscribed', {
        job_id: msg.job_id as string,
        replayed_count: msg.replayed_count as number,
      })
    } else if (type === 'pong') {
      // no-op
    } else if (type === 'error') {
      const code = msg.code as string
      const message = msg.message as string
      // Server rejections (forbidden / rate_limited / invalid_request) used to
      // vanish silently, leaving the UI waiting for events that never come.
      const errJobId = msg.job_id as string | undefined
      console.error(`[WSClient] server error ${code}: ${message}`)
      this._emit('error', { code, message, job_id: errJobId })
    }
  }

  private _sendSubscribe(jobId: string, lastEventId?: string): void {
    const msg: Record<string, unknown> = { type: 'subscribe', job_id: jobId }
    if (lastEventId) msg.last_event_id = lastEventId
    this._send(msg)
  }

  private _send(msg: Record<string, unknown>): void {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(msg))
    }
  }

  private _emit<K extends WSEventType>(event: K, payload: WSEventMap[K]): void {
    for (const handler of this._listeners.get(event) ?? []) {
      try {
        handler(payload)
      } catch (err) {
        console.error(`[WSClient] handler error for ${event}:`, err)
      }
    }
  }

  private _scheduleReconnect(): void {
    this._cancelReconnect()
    const delay = Math.min(100 * 2 ** this._reconnectAttempt, this._maxReconnectDelay)
    this._reconnectAttempt++
    this._reconnectTimer = setTimeout(() => this._openSocket(), delay)
  }

  private _cancelReconnect(): void {
    if (this._reconnectTimer !== null) {
      clearTimeout(this._reconnectTimer)
      this._reconnectTimer = null
    }
  }

  private _startHeartbeat(): void {
    this._stopHeartbeat()
    this._heartbeatTimer = setInterval(() => this.ping(), 25_000)
  }

  private _stopHeartbeat(): void {
    if (this._heartbeatTimer !== null) {
      clearInterval(this._heartbeatTimer)
      this._heartbeatTimer = null
    }
  }
}

// Singleton — one WebSocket for the entire app
export const wsClient = new WSClient()
