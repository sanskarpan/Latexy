/**
 * Retry safety.
 *
 * The client used to retry every method on 5xx and on network errors. A 5xx can
 * be returned after the server has already done the work, so a single
 * `POST /jobs/submit` could enqueue the job three times — and since #998 each one
 * is a separate charge against the caller's plan allowance.
 */
import { createServer, type Server } from 'node:http'

import { afterEach, describe, expect, it } from 'vitest'

import { ApiClient } from '../lib/api-client.js'

let server: Server | null = null

async function serve(handler: (n: number) => { status: number; body: string }) {
  const received: string[] = []
  server = createServer((req, res) => {
    received.push(`${req.method} ${req.url}`)
    const { status, body } = handler(received.length)
    res.writeHead(status, { 'Content-Type': 'application/json' })
    res.end(body)
  })
  await new Promise<void>(r => server!.listen(0, r))
  const port = (server!.address() as { port: number }).port
  return { received, client: new ApiClient({ baseUrl: `http://127.0.0.1:${port}` }) }
}

afterEach(() => {
  server?.close()
  server = null
})

describe('ApiClient retry policy', () => {
  it('does NOT retry a POST after a 5xx', async () => {
    // The job may already have been queued when the 500 came back.
    const { received, client } = await serve(() => ({ status: 500, body: '{}' }))
    await expect(
      client.post('/jobs/submit', { latex_content: 'x' }, { retryDelayMs: 5 }),
    ).rejects.toThrow()
    expect(received.length, 'POST was replayed — duplicate jobs and duplicate charges').toBe(1)
  })

  it('does NOT retry a DELETE after a 5xx', async () => {
    const { received, client } = await serve(() => ({ status: 500, body: '{}' }))
    await expect(client.delete('/resumes/abc', { retryDelayMs: 5 })).rejects.toThrow()
    expect(received.length).toBe(1)
  })

  it('DOES retry a GET after a 5xx — reads are safe to replay', async () => {
    const { received, client } = await serve(n =>
      n < 3 ? { status: 500, body: '{}' } : { status: 200, body: '{"ok":true}' },
    )
    const out = await client.get<{ ok: boolean }>('/resumes/', { retryDelayMs: 5 })
    expect(out.ok).toBe(true)
    expect(received.length, 'GET should have been retried').toBe(3)
  })

  it('retries a POST only when the caller opts in explicitly', async () => {
    const { received, client } = await serve(n =>
      n < 2 ? { status: 500, body: '{}' } : { status: 200, body: '{"ok":true}' },
    )
    await client.post('/idempotent-thing', {}, { retryDelayMs: 5, retry: true })
    expect(received.length).toBe(2)
  })
})
