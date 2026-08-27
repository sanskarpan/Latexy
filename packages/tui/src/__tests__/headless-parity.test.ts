import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'

let sessionToken: string | null = 'tok'
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
    token: sessionToken,
    email: null,
    userId: null,
    backendUrl: 'http://localhost:8030',
    appUrl: 'http://localhost:5180',
    defaultResumeId: null,
    activeModel: null,
    activeProvider: null,
  })),
}))

vi.mock('../lib/api-client.js', () => ({
  initApiClient: vi.fn(() => ({
    get: getMock,
    post: postMock,
    getWsUrl: () => 'ws://localhost:8030/ws/jobs',
  })),
}))

vi.mock('../lib/ws-client.js', () => ({ wsClient: fakeWsClient }))

function completeJob(jobId = 'job-1'): void {
  fakeWsClient.on('newListener', (name: string) => {
    if (name !== 'event') return
    setImmediate(() => fakeWsClient.emit('event', {
      event_id: 'e1',
      job_id: jobId,
      timestamp: Date.now(),
      sequence: 1,
      type: 'job.completed',
    }))
  })
}

describe('headless command parity', () => {
  let stdout: string

  beforeEach(() => {
    stdout = ''
    sessionToken = 'tok'
    getMock.mockReset()
    postMock.mockReset()
    vi.mocked(fakeWsClient['connect'] as ReturnType<typeof vi.fn>).mockClear()
    vi.mocked(fakeWsClient['subscribe'] as ReturnType<typeof vi.fn>).mockClear()
    vi.mocked(fakeWsClient['destroy'] as ReturnType<typeof vi.fn>).mockClear()
    vi.spyOn(process.stdout, 'write').mockImplementation((chunk: unknown) => {
      stdout += String(chunk)
      return true
    })
    vi.spyOn(process.stderr, 'write').mockImplementation(() => true)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    fakeWsClient.removeAllListeners()
  })

  it('optimizes a resume and returns the authoritative job result', async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === '/resumes/resume-1') return { latex_content: '\\documentclass{article}' }
      if (path === '/jobs/job-1/result') {
        return {
          success: true,
          job_id: 'job-1',
          result: { optimized_latex: '\\documentclass{article} optimized', changes_made: [{ section: 'summary' }] },
        }
      }
      throw new Error(`Unexpected GET ${path}`)
    })
    postMock.mockResolvedValue({ job_id: 'job-1' })
    completeJob()

    const { runHeadless } = await import('../headless.js')
    const code = await runHeadless('optimize', [
      'optimize', 'resume-1', '--jd', 'Senior TypeScript engineer', '--level', 'conservative', '--model', 'gpt-test',
    ])

    expect(code).toBe(0)
    expect(postMock).toHaveBeenCalledWith('/jobs/submit', expect.objectContaining({
      job_type: 'llm_optimization',
      job_description: 'Senior TypeScript engineer',
      optimization_level: 'conservative',
      model: 'gpt-test',
      metadata: { resume_id: 'resume-1' },
    }))
    expect(JSON.parse(stdout)).toMatchObject({
      success: true,
      job_id: 'job-1',
      optimized_latex: '\\documentclass{article} optimized',
    })
  })

  it('runs ATS scoring with a scraped JD and returns detailed scoring output', async () => {
    getMock.mockImplementation(async (path: string) => {
      if (path === '/resumes/resume-2') return { latex_content: '\\documentclass{article}' }
      if (path === '/jobs/job-ats/result') {
        return {
          success: true,
          job_id: 'job-ats',
          result: { ats_score: 87.5, category_scores: { keywords: 90 } },
        }
      }
      throw new Error(`Unexpected GET ${path}`)
    })
    postMock.mockImplementation(async (path: string) => {
      if (path === '/scrape-job-description') return { description: 'Scraped job description' }
      if (path === '/jobs/submit') return { job_id: 'job-ats' }
      throw new Error(`Unexpected POST ${path}`)
    })
    completeJob('job-ats')

    const { runHeadless } = await import('../headless.js')
    const code = await runHeadless('ats', [
      'ats', 'score', 'resume-2', '--jd', 'https://example.com/job', '--industry', 'software_engineering',
    ])

    expect(code).toBe(0)
    expect(postMock).toHaveBeenCalledWith('/jobs/submit', expect.objectContaining({
      job_type: 'ats_scoring',
      job_description: 'Scraped job description',
      industry: 'software_engineering',
    }))
    expect(JSON.parse(stdout)).toMatchObject({ success: true, job_id: 'job-ats', ats_score: 87.5 })
  })

  it('returns status immediately without opening a WebSocket', async () => {
    getMock.mockResolvedValue({ status: 'running', stage: 'latex', percent: 45 })

    const { runHeadless } = await import('../headless.js')
    const code = await runHeadless('status', ['status', 'job-status'])

    expect(code).toBe(0)
    expect(getMock).toHaveBeenCalledWith('/jobs/job-status/state')
    expect(fakeWsClient['connect']).not.toHaveBeenCalled()
    expect(JSON.parse(stdout)).toMatchObject({ success: true, job_id: 'job-status', percent: 45 })
  })

  it('returns a deterministic failure when a waited job is cancelled', async () => {
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e1', job_id: 'job-cancelled', timestamp: Date.now(), sequence: 1, type: 'job.cancelled',
      }))
    })

    const { runHeadless } = await import('../headless.js')
    const code = await runHeadless('status', ['status', 'job-cancelled', '--wait'])

    expect(code).toBe(1)
    expect(JSON.parse(stdout)).toMatchObject({ success: false, error_code: 'cancelled', retryable: false })
  })

  it('lists paginated resumes as JSON', async () => {
    getMock.mockResolvedValue({ resumes: [{ id: 'resume-1', title: 'CV' }], total: 1, page: 2, pages: 2 })

    const { runHeadless } = await import('../headless.js')
    const code = await runHeadless('list', ['list', '--page', '2', '--limit', '25'])

    expect(code).toBe(0)
    expect(getMock).toHaveBeenCalledWith('/resumes/?page=2&limit=25')
    expect(JSON.parse(stdout)).toMatchObject({ success: true, total: 1, page: 2 })
  })

  it('uses distinct exit codes for auth, invalid input, backend outage, and job failure', async () => {
    const { runHeadless } = await import('../headless.js')

    sessionToken = null
    expect(await runHeadless('list', ['list'])).toBe(2)

    sessionToken = 'tok'
    stdout = ''
    getMock.mockRejectedValueOnce(Object.assign(new Error('Session expired'), { status: 401 }))
    expect(await runHeadless('list', ['list'])).toBe(2)

    stdout = ''
    expect(await runHeadless('optimize', ['optimize', 'resume-1', '--jd', 'JD', '--level', 'reckless'])).toBe(3)

    stdout = ''
    getMock.mockRejectedValueOnce(new TypeError('fetch failed'))
    expect(await runHeadless('list', ['list'])).toBe(4)

    stdout = ''
    getMock.mockResolvedValueOnce({ latex_content: '\\documentclass{article}' })
    postMock.mockResolvedValueOnce({ job_id: 'job-failed' })
    fakeWsClient.on('newListener', (name: string) => {
      if (name !== 'event') return
      setImmediate(() => fakeWsClient.emit('event', {
        event_id: 'e2', job_id: 'job-failed', timestamp: Date.now(), sequence: 2,
        type: 'job.failed', error_message: 'Provider unavailable', error_code: 'llm_error', retryable: true,
      }))
    })
    expect(await runHeadless('optimize', ['optimize', 'resume-1', '--jd', 'JD'])).toBe(1)
    expect(JSON.parse(stdout)).toMatchObject({ success: false, error_code: 'llm_error', retryable: true })
  })
})
