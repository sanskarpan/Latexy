import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'
import { existsSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const TEX_PATH = join(tmpdir(), `latexy-headless-${process.pid}.tex`)

const fakeWsClient = new EventEmitter() as EventEmitter & Record<string, unknown>
Object.assign(fakeWsClient, {
  connect: vi.fn(),
  drain: vi.fn(),
  subscribe: vi.fn(),
  destroy: vi.fn(),
})

vi.mock('../lib/config.js', () => ({
  readConfig: vi.fn(async () => ({
    token: 'tok', email: null, userId: null,
    backendUrl: 'http://localhost:8030', appUrl: 'http://localhost:5180',
    defaultResumeId: null, activeModel: null, activeProvider: null,
  })),
}))

vi.mock('../lib/api-client.js', () => ({
  initApiClient: vi.fn(() => ({
    get: vi.fn(),
    post: vi.fn(async () => ({ job_id: 'job-1' })),
  })),
}))

vi.mock('../lib/ws-client.js', () => ({ wsClient: fakeWsClient }))

describe('runHeadless compile', () => {
  let stdout: string

  beforeEach(() => {
    stdout = ''
    writeFileSync(TEX_PATH, '\\documentclass{article}\\begin{document}hi\\end{document}')
    vi.spyOn(process.stdout, 'write').mockImplementation((chunk: unknown) => {
      stdout += String(chunk)
      return true
    })
    vi.spyOn(process.stderr, 'write').mockImplementation(() => true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    rmSync(TEX_PATH, { force: true })
    fakeWsClient.removeAllListeners()
  })

  it('fails fast on a forbidden error frame instead of waiting out the timeout', async () => {
    const { runHeadless } = await import('../headless.js')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'server_error') return
      setImmediate(() => fakeWsClient.emit('server_error', {
        code: 'forbidden', message: 'Access denied for this job',
      }))
    })

    const started = Date.now()
    const code = await runHeadless('compile', ['compile', TEX_PATH])

    expect(code).toBe(1)
    expect(Date.now() - started).toBeLessThan(5_000)
    expect(stdout).toContain('forbidden')
    expect(fakeWsClient['destroy']).toHaveBeenCalled()
  })

  it('reports ats_score null for a compile-only job (the worker hardcodes 0.0)', async () => {
    const { runHeadless } = await import('../headless.js')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e1', job_id: 'job-1', timestamp: Date.now(), sequence: 9,
        type: 'job.completed', pdf_job_id: 'job-1', page_count: 3,
        ats_score: 0.0, ats_details: {}, compilation_time: 1.5, compiler: 'xelatex',
      }))
    })

    const code = await runHeadless('compile', ['compile', TEX_PATH])

    expect(code).toBe(0)
    const parsed = JSON.parse(stdout) as Record<string, unknown>
    expect(parsed['success']).toBe(true)
    expect(parsed['pages']).toBe(3)
    expect(parsed['ats_score']).toBeNull()
    expect(parsed['compiler']).toBe('xelatex')
  })

  it('retries the subscribe on the soft rate_limited throttle instead of aborting', async () => {
    const { runHeadless } = await import('../headless.js')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'server_error') return
      setImmediate(() => {
        fakeWsClient.emit('server_error', { code: 'rate_limited', message: 'Too many messages' })
        // The job still completes — a soft throttle must not kill the client
        setTimeout(() => fakeWsClient.emit('event', {
          event_id: 'e1', job_id: 'job-1', timestamp: Date.now(), sequence: 9,
          type: 'job.completed', pdf_job_id: 'job-1', page_count: 1, compilation_time: 1,
        }), 20)
      })
    })

    const code = await runHeadless('compile', ['compile', TEX_PATH])

    expect(code).toBe(0)
    expect((JSON.parse(stdout) as Record<string, unknown>)['success']).toBe(true)
  })

  it('reports failure and writes no file when --output download is not a PDF', async () => {
    const { runHeadless } = await import('../headless.js')
    const outPath = join(tmpdir(), `latexy-headless-${process.pid}.pdf`)
    rmSync(outPath, { force: true })

    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e1', job_id: 'job-1', timestamp: Date.now(), sequence: 9,
        type: 'job.completed', pdf_job_id: 'job-1', page_count: 1, compilation_time: 1,
      }))
    })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Not found' }), { status: 404, statusText: 'Not Found' })
    )

    const code = await runHeadless('compile', ['compile', TEX_PATH, '--output', outPath])

    expect(code).toBe(1)
    expect(stdout).toContain('PDF download failed: HTTP 404')
    expect(existsSync(outPath)).toBe(false)
  })
})
