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

  constructor() {
    super()
    // EventEmitter throws when an 'error' event is emitted with no listener, so a
    // socket failure used to take the whole TUI down with ERR_UNHANDLED_ERROR.
    // Socket errors are emitted on 'socket_error' now, but this default keeps a
    // stray 'error' from any other source from being fatal.
    this.on('error', () => {})
  }

  connect(url: string, token: string): void {
    this.url = url
    this.token = token
    // destroy() means "tear down the current connection", not "disable this object
    // forever". It is a module-level singleton, so leaving `destroyed` latched made
    // every reconnect after /logout a silent no-op: logging back in produced no job
    // events at all until the process was restarted.
    this.destroyed = false
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

  /** Detach and close any live socket so it cannot keep emitting into this client. */
  private teardownSocket(code = 1000, reason = 'Replaced'): void {
    const old = this.ws
    if (!old) return
    this.ws = null
    old.removeAllListeners()
    // Closing a socket that is still CONNECTING makes ws emit an error, and with
    // every listener just removed that would surface as an unhandled 'error' —
    // the exact crash this class is being fixed for. Keep a sink attached.
    old.on('error', () => {})
    try {
      if (old.readyState === WS.CONNECTING) {
        // close() on a pending handshake is what produces "WebSocket was closed
        // before the connection was established"; terminate() drops it outright.
        old.terminate()
      } else {
        old.close(code, reason)
      }
    } catch {
      /* already gone */
    }
  }

  private openSocket(): void {
    if (this.destroyed) return
    // Replace, never stack. Without this the previous socket kept its 'message'
    // handler and went on publishing into the same client, so every event arrived
    // twice and the old socket stayed open until the server timed it out.
    this.teardownSocket()
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
      // NOT 'error': EventEmitter throws when that channel has no listener, and a
      // backend being down would otherwise crash the whole TUI.
      this.emit('socket_error', { message: err.message })
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
    // A double 'close' would otherwise leave two timers racing to open two sockets.
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectAttempt++
    const delay = Math.min(MIN_BACKOFF * 2 ** (this.reconnectAttempt - 1), MAX_BACKOFF)
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay)
  }

  private startHeartbeat(): void {
    // Same hazard as the reconnect timer: a second 'open' would strand the first
    // interval, leaving it pinging a socket this client no longer owns.
    this.stopHeartbeat()
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
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.stopHeartbeat()
    this.teardownSocket(1000, 'Client destroy')
    this.subscriptions.clear()
    this.buffered = []
  }

  get connected(): boolean {
    return this.ws?.readyState === WS.OPEN
  }
}

export const wsClient = new LatexyWSClient()
