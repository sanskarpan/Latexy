import { EventEmitter } from 'node:events'
import WS from 'ws'
import type { AnyEvent } from './event-types.js'

export interface WSServerError {
  code: string
  message: string
  /** Present only when the rejection concerns one specific job (see ws_routes._send_error). */
  job_id?: string
}

const MAX_BUFFER = 2000
const MIN_BACKOFF = 100
const MAX_BACKOFF = 30_000

export class LatexyWSClient extends EventEmitter {
  private ws: InstanceType<typeof WS> | null = null
  private url = ''
  private token = ''
  private buffered: AnyEvent[] = []
  private drained = false
  private reconnectTimer: NodeJS.Timeout | null = null
  private heartbeatTimer: NodeJS.Timeout | null = null
  private reconnectAttempt = 0
  private destroyed = false
  private subscriptions = new Map<string, string>()

  connect(url: string, token: string): void {
    this.url = url
    this.token = token
    this.openSocket()
  }

  /** Backend auth reads the session token from ?token= only (see ws_routes._resolve_ws_user). */
  private socketUrl(): string {
    if (!this.token) return this.url
    const url = new URL(this.url)
    // set() (not append()) so reconnects via openSocket() cannot stack duplicate params
    url.searchParams.set('token', this.token)
    return url.toString()
  }

  private openSocket(): void {
    if (this.destroyed) return
    this.ws = new WS(this.socketUrl(), {
      headers: { Authorization: `Bearer ${this.token}` },
    })

    this.ws.on('open', () => {
      this.reconnectAttempt = 0
      this.startHeartbeat()
      this.resubscribeAll()
      this.emit('connected')
    })

    this.ws.on('message', (data: Buffer) => {
      try {
        const outer = JSON.parse(data.toString()) as Record<string, unknown>
        if (outer['type'] === 'event' && outer['event']) {
          // Unwrap the server's envelope: {type:"event", event:{...}} → emit inner event
          this.publish(outer['event'] as AnyEvent)
        } else if (outer['type'] === 'subscribed') {
          this.emit('subscribed', outer)
        } else if (outer['type'] === 'error') {
          // {type:"error", code, message, job_id?} — surfaced as 'server_error' (not 'error',
          // which EventEmitter throws on when unhandled) so callers can abort instead of
          // waiting. job_id is forwarded when present so per-job rejections stay scoped.
          const err: WSServerError = {
            code: String(outer['code'] ?? 'unknown'),
            message: String(outer['message'] ?? ''),
          }
          if (typeof outer['job_id'] === 'string' && outer['job_id']) {
            err.job_id = outer['job_id']
          }
          this.emit('server_error', err)
        }
        // Other outer types (heartbeat) are intentionally ignored
      } catch {}
    })

    this.ws.on('close', (code) => {
      this.stopHeartbeat()
      const wasClean = code === 1000
      this.emit('disconnected', { wasClean })
      if (!this.destroyed && !wasClean) this.scheduleReconnect()
    })

    this.ws.on('error', (err) => {
      this.emit('error', { message: err.message })
    })
  }

  private publish(ev: AnyEvent): void {
    if (this.drained) {
      this.emit('event', ev)
      return
    }
    if (this.buffered.length < MAX_BUFFER) this.buffered.push(ev)
  }

  drain(): void {
    this.drained = true
    for (const ev of this.buffered) this.emit('event', ev)
    this.buffered = []
  }

  subscribe(jobId: string, lastEventId = '0'): void {
    this.subscriptions.set(jobId, lastEventId)
    this.send({ type: 'subscribe', job_id: jobId, last_event_id: lastEventId })
  }

  unsubscribe(jobId: string): void {
    this.subscriptions.delete(jobId)
    this.send({ type: 'unsubscribe', job_id: jobId })
  }

  private resubscribeAll(): void {
    for (const [jobId, lastEventId] of this.subscriptions) {
      this.send({ type: 'subscribe', job_id: jobId, last_event_id: lastEventId })
    }
  }

  private send(msg: unknown): void {
    if (this.ws?.readyState === WS.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  private scheduleReconnect(): void {
    this.reconnectAttempt++
    const delay = Math.min(MIN_BACKOFF * 2 ** (this.reconnectAttempt - 1), MAX_BACKOFF)
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay)
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WS.OPEN) this.ws.ping()
    }, 25_000)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  destroy(): void {
    this.destroyed = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.stopHeartbeat()
    this.ws?.close(1000, 'Client destroy')
    this.ws = null
  }

  get connected(): boolean {
    return this.ws?.readyState === WS.OPEN
  }
}

export const wsClient = new LatexyWSClient()
