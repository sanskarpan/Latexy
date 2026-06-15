import { EventEmitter } from 'node:events'
import WS from 'ws'
import type { AnyEvent } from './event-types.js'

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

  private openSocket(): void {
    if (this.destroyed) return
    this.ws = new WS(this.url, {
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
        const ev = JSON.parse(data.toString()) as AnyEvent
        this.publish(ev)
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
