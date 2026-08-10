/**
 * A reconnect must resume the event stream where it left off.
 *
 * The subscription map was seeded with '0' and never advanced, so every
 * reconnect resubscribed from the start and the server replayed the entire job.
 * Nothing downstream deduplicates — JobController appends — so a compile that
 * dropped its socket once rendered every build-log line twice, and an /optimize
 * rendered the generated LaTeX concatenated with itself.
 *
 * Verified against the real backend during the round-4 audit: subscribing to a
 * finished job with last_event_id='0' replayed all 20 of its events.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { WebSocketServer, type WebSocket as WSSocket } from 'ws'

import { LatexyWSClient } from '../lib/ws-client.js'

describe('websocket resume position', () => {
  let server: WebSocketServer
  let port: number
  let sockets: WSSocket[] = []
  const subscribeFrames: Array<Record<string, unknown>> = []

  beforeEach(async () => {
    subscribeFrames.length = 0
    sockets = []
    server = new WebSocketServer({ port: 0 })
    await new Promise<void>(r => server.on('listening', () => r()))
    port = (server.address() as { port: number }).port
    server.on('connection', sock => {
      sockets.push(sock)
      sock.on('message', raw => {
        const msg = JSON.parse(String(raw)) as Record<string, unknown>
        if (msg['type'] === 'subscribe') subscribeFrames.push(msg)
      })
    })
  })

  afterEach(async () => {
    for (const s of sockets) { try { s.terminate() } catch { /* gone */ } }
    await new Promise<void>(r => server.close(() => r()))
  })

  async function connected(client: LatexyWSClient): Promise<void> {
    await new Promise<void>(r => client.once('connected', () => r()))
  }

  function emit(sock: WSSocket, jobId: string, seq: number): void {
    sock.send(JSON.stringify({
      type: 'event',
      event: {
        event_id: `1700000000000-${seq}`, job_id: jobId, sequence: seq,
        type: 'log.line', line: `line ${seq}`,
      },
    }))
  }

  it('resubscribes from the last event it received, not from the start', async () => {
    const client = new LatexyWSClient()
    client.drain()
    client.connect(`ws://127.0.0.1:${port}`, 'tok')
    await connected(client)

    client.subscribe('job-1', '0')
    for (let seq = 1; seq <= 5; seq++) emit(sockets[0]!, 'job-1', seq)
    await new Promise(r => setTimeout(r, 150))

    expect(client.resumePosition('job-1')).toBe('1700000000000-5')

    subscribeFrames.length = 0
    sockets[0]!.terminate()
    await connected(client)
    await new Promise(r => setTimeout(r, 100))

    expect(subscribeFrames.length).toBe(1)
    expect(
      subscribeFrames[0]!['last_event_id'],
      'a reconnect that asks for 0 makes the server replay the whole job',
    ).toBe('1700000000000-5')

    client.destroy()
  })

  it('does not resurrect a subscription that was already released', async () => {
    const client = new LatexyWSClient()
    client.drain()
    client.connect(`ws://127.0.0.1:${port}`, 'tok')
    await connected(client)

    client.subscribe('job-2', '0')
    emit(sockets[0]!, 'job-2', 1)
    await new Promise(r => setTimeout(r, 80))
    client.unsubscribe('job-2')

    // A late event for a finished job must not put it back in the resubscribe set.
    emit(sockets[0]!, 'job-2', 2)
    await new Promise(r => setTimeout(r, 80))
    expect(client.resumePosition('job-2')).toBeUndefined()

    subscribeFrames.length = 0
    sockets[0]!.terminate()
    await connected(client)
    await new Promise(r => setTimeout(r, 100))
    expect(subscribeFrames, 'released job was resubscribed on reconnect').toHaveLength(0)

    client.destroy()
  })
})
