import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'
import { existsSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

let testDirectory = ''
let texPath = ''
let defaultResumeId: string | null = null
const getMock = vi.fn()
const postMock = vi.fn()

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
    defaultResumeId, activeModel: null, activeProvider: null,
  })),
}))

vi.mock('../lib/api-client.js', () => ({
  initApiClient: vi.fn(() => ({
    get: getMock,
    post: postMock,
  })),
}))

vi.mock('../lib/ws-client.js', () => ({ wsClient: fakeWsClient }))

describe('runHeadless compile', () => {
  let stdout: string

  beforeEach(() => {
    stdout = ''
    defaultResumeId = null
    testDirectory = mkdtempSync(join(tmpdir(), 'latexy-headless-test-'))
    texPath = join(testDirectory, 'resume.tex')
    writeFileSync(texPath, '\\documentclass{article}\\begin{document}hi\\end{document}', { mode: 0o600 })
    getMock.mockReset()
    postMock.mockReset()
    postMock.mockResolvedValue({ job_id: 'job-1' })
    vi.spyOn(process.stdout, 'write').mockImplementation((chunk: unknown) => {
      stdout += String(chunk)
      return true
    })
    vi.spyOn(process.stderr, 'write').mockImplementation(() => true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    rmSync(testDirectory, { recursive: true, force: true })
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
    const code = await runHeadless('compile', ['compile', texPath])

    expect(code).toBe(1)
    expect(Date.now() - started).toBeLessThan(5_000)
    expect(stdout).toContain('forbidden')
    expect(fakeWsClient['destroy']).toHaveBeenCalled()
  })

  it('fails fast with backend-unreachable exit code when the event stream cannot connect', async () => {
    const { runHeadless } = await import('../headless.js')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'socket_error') return
      setImmediate(() => fakeWsClient.emit('socket_error', {
        message: 'connect ECONNREFUSED 127.0.0.1:8030', code: 'ECONNREFUSED',
      }))
    })

    const started = Date.now()
    const code = await runHeadless('compile', ['compile', texPath])

    expect(code).toBe(4)
    expect(Date.now() - started).toBeLessThan(5_000)
    expect(stdout).toContain('Cannot reach the Latexy event stream')
    expect(fakeWsClient['destroy']).toHaveBeenCalled()
  })

  it('classifies an expired event-stream ticket as an authentication failure', async () => {
    const { runHeadless } = await import('../headless.js')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'socket_error') return
      setImmediate(() => fakeWsClient.emit('socket_error', {
        message: 'WebSocket ticket request failed (401)', status: 401,
      }))
    })

    const code = await runHeadless('compile', ['compile', texPath])

    expect(code).toBe(2)
    expect(stdout).toContain('WebSocket ticket request failed (401)')
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

    const code = await runHeadless('compile', ['compile', texPath])

    expect(code).toBe(0)
    const parsed = JSON.parse(stdout) as Record<string, unknown>
    expect(parsed['success']).toBe(true)
    expect(parsed['pages']).toBe(3)
    expect(parsed['ats_score']).toBeNull()
    expect(parsed['compiler']).toBe('xelatex')
  })

  it('uses a saved resume compiler unless the CLI flag overrides it', async () => {
    const { runHeadless } = await import('../headless.js')
    getMock.mockResolvedValue({
      latex_content: '\\documentclass{article}\\begin{document}hi\\end{document}',
      metadata: { compiler: 'lualatex' },
    })
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e1', job_id: 'job-1', timestamp: Date.now(), sequence: 9,
        type: 'job.completed', pdf_job_id: 'job-1', page_count: 1,
        compilation_time: 1, compiler: 'lualatex',
      }))
    })

    const code = await runHeadless('compile', ['compile', '--resume-id', 'resume-1'])

    expect(code).toBe(0)
    expect(postMock).toHaveBeenCalledWith('/jobs/submit', expect.objectContaining({
      compiler: 'lualatex',
    }))
  })

  it('compiles the saved default resume when no file or id is provided', async () => {
    defaultResumeId = 'resume-default'
    getMock.mockImplementation(async (path: string) => {
      if (path === '/resumes/resume-default') {
        return {
          latex_content: '\\documentclass{article}\\begin{document}hi\\end{document}',
          metadata: { compiler: 'xelatex' },
        }
      }
      throw new Error(`Unexpected GET ${path}`)
    })
    const { runHeadless } = await import('../headless.js')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e-default', job_id: 'job-1', timestamp: Date.now(), sequence: 1,
        type: 'job.completed', page_count: 1, compilation_time: 1, compiler: 'xelatex',
      }))
    })

    const code = await runHeadless('compile', ['compile'])

    expect(code).toBe(0)
    expect(getMock).toHaveBeenCalledWith('/resumes/resume-default')
    expect(postMock).toHaveBeenCalledWith('/jobs/submit', expect.objectContaining({
      compiler: 'xelatex',
    }))
  })

  it('does not use the saved default when --resume-id has no value', async () => {
    defaultResumeId = 'resume-default'
    const { runHeadless } = await import('../headless.js')

    const code = await runHeadless('compile', ['compile', '--resume-id', '--json'])

    expect(code).toBe(3)
    expect(JSON.parse(stdout)).toMatchObject({ success: false })
    expect(stdout).toContain('Missing value for --resume-id')
    expect(getMock).not.toHaveBeenCalled()
    expect(postMock).not.toHaveBeenCalled()
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

    const code = await runHeadless('compile', ['compile', texPath])

    expect(code).toBe(0)
    expect((JSON.parse(stdout) as Record<string, unknown>)['success']).toBe(true)
  })

  it('reports failure and writes no file when --output download is not a PDF', async () => {
    const { runHeadless } = await import('../headless.js')
    const outPath = join(testDirectory, 'result.pdf')

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

    const code = await runHeadless('compile', ['compile', texPath, '--output', outPath])

    expect(code).toBe(1)
    expect(stdout).toContain('PDF download failed: HTTP 404')
    expect(existsSync(outPath)).toBe(false)
  })

  it('maps an AbortSignal timeout during PDF download to backend-unreachable', async () => {
    const { runHeadless } = await import('../headless.js')
    const outPath = join(testDirectory, 'timeout.pdf')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e-timeout', job_id: 'job-1', timestamp: Date.now(), sequence: 1,
        type: 'job.completed', page_count: 1, compilation_time: 1,
      }))
    })
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new DOMException('The operation timed out', 'TimeoutError'),
    )

    const code = await runHeadless('compile', ['compile', texPath, '--output', outPath])

    expect(code).toBe(4)
    expect(stdout).toContain('Cannot reach the Latexy backend')
    expect(existsSync(outPath)).toBe(false)
  })

  it('keeps unexpected PDF download errors on the generic failure exit code', async () => {
    const { runHeadless } = await import('../headless.js')
    const outPath = join(testDirectory, 'unexpected.pdf')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e-unexpected', job_id: 'job-1', timestamp: Date.now(), sequence: 1,
        type: 'job.completed', page_count: 1, compilation_time: 1,
      }))
    })
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('download parser exploded'))

    const code = await runHeadless('compile', ['compile', texPath, '--output', outPath])

    expect(code).toBe(1)
    expect(stdout).toContain('download parser exploded')
    expect(existsSync(outPath)).toBe(false)
  })

  it('does not misclassify an unrelated TypeError as backend-unreachable', async () => {
    const { runHeadless } = await import('../headless.js')
    const outPath = join(testDirectory, 'type-error.pdf')
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e-type-error', job_id: 'job-1', timestamp: Date.now(), sequence: 1,
        type: 'job.completed', page_count: 1, compilation_time: 1,
      }))
    })
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('response parser bug'))

    const code = await runHeadless('compile', ['compile', texPath, '--output', outPath])

    expect(code).toBe(1)
    expect(stdout).toContain('response parser bug')
    expect(stdout).not.toContain('Cannot reach the Latexy backend')
  })
})
