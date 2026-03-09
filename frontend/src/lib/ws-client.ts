/**
 * WSClient — singleton WebSocket manager for Latexy.
 *
 * Features:
 * - Single persistent WebSocket to /ws/jobs
 * - Exponential backoff reconnect (100ms → 200ms → 400ms → … max 30s)
 * - Auto-resubscribes all pending jobs on reconnect, sending last_event_id
 *   so the server replays missed events
 * - Typed event emitter: on/off for "connected" | "disconnected" |
 *   "event" | "subscribed" | "error"
 * - Heartbeat ping every 25s when connected
 */

import { getWebSocketUrl } from './api-client'
import type { AnyEvent } from './event-types'

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
  error: { code: string; message: string }
}

// ------------------------------------------------------------------ //
//  WSClient                                                           //
// ------------------------------------------------------------------ //

class WSClient {
  private _ws: WebSocket | null = null
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private _reconnectAttempt = 0
  private _maxReconnectDelay = 30_000 // ms
  private _heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private _manuallyDisconnected = false

  /**
   * job_id → last received stream entry ID (for replay on reconnect).
   * undefined means "subscribe from now" (no replay).
   */
  private _subscriptions = new Map<string, string | undefined>()

  /** Multi-listener event emitter */
  private _listeners = new Map<WSEventType, Set<WSEventHandler<any>>>()

  // ---------------------------------------------------------------- //
  //  Connection management                                            //
  // ---------------------------------------------------------------- //

  connect(): void {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) return
    if (this._ws && this._ws.readyState === WebSocket.CONNECTING) return

    this._manuallyDisconnected = false
    this._openSocket()
  }

  disconnect(): void {
    this._manuallyDisconnected = true
    this._cancelReconnect()
    this._stopHeartbeat()
    if (this._ws) {
      this._ws.close(1000, 'Client disconnect')
      this._ws = null
    }
  }

  get connected(): boolean {
    return this._ws?.readyState === WebSocket.OPEN
  }

  // ---------------------------------------------------------------- //
  //  Subscription management                                          //
  // ---------------------------------------------------------------- //

  subscribe(jobId: string, lastEventId?: string): void {
    this._subscriptions.set(jobId, lastEventId)
    this._sendSubscribe(jobId, lastEventId)
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
    try {
      const url = getWebSocketUrl()
      const ws = new WebSocket(url)
      this._ws = ws

      ws.onopen = () => {
        this._reconnectAttempt = 0
        this._startHeartbeat()
        this._emit('connected', undefined)

        // Re-subscribe to all jobs, sending last_event_id for replay
        for (const [jobId, lastEventId] of this._subscriptions) {
          this._sendSubscribe(jobId, lastEventId)
        }
      }

      ws.onmessage = (event: MessageEvent) => {
        this._handleMessage(event.data)
      }

      ws.onclose = (event: CloseEvent) => {
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
        if (jobId && this._subscriptions.has(jobId)) {
          const streamId = msg.stream_id as string | undefined
          if (streamId) {
            this._subscriptions.set(jobId, streamId)
          }
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
      this._emit('error', {
        code: msg.code as string,
        message: msg.message as string,
      })
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
