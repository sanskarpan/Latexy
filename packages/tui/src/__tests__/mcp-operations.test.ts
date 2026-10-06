import { describe, expect, it, vi } from 'vitest'

import { createMcpOperations, MCP_RESUME_PAGE_SIZE } from '../mcp/operations.js'
import type { McpApi, McpResume } from '../mcp/operations.js'

const resume = (id: string): McpResume => ({
  id,
  title: `Resume ${id}`,
  latex_content: `\\documentclass{article} ${id}`,
  document_type: 'resume',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  metadata: { compiler: 'xelatex' },
})

function api(overrides: Partial<McpApi> = {}): McpApi {
  return {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    ...overrides,
  } as McpApi
}

describe('MCP API operations', () => {
  it('lists every page with explicit archive and document filters', async () => {
    const get = vi.fn(async (path: string) => {
      const page = new URL(`https://example.test${path}`).searchParams.get('page')
      return page === '1'
        ? { resumes: [resume('one')], total: 201, pages: 2 }
        : { resumes: [resume('two')], total: 201, pages: 2 }
    })
    const operations = createMcpOperations(api({ get: get as McpApi['get'] }))

    const result = await operations.listResumes({ archived: true, documentType: 'academic_cv' })

    expect(result.resumes.map(item => item.id)).toEqual(['one', 'two'])
    expect(result.resumes.every(item => !('latex_content' in item))).toBe(true)
    expect(get).toHaveBeenCalledTimes(2)
    for (const [path] of get.mock.calls) {
      expect(path).toContain(`limit=${MCP_RESUME_PAGE_SIZE}`)
      expect(path).toContain('archived=true')
      expect(path).toContain('document_type=academic_cv')
    }
  })

  it('uses the documented resume write and reversible archive routes', async () => {
    const post = vi.fn(async () => resume('created'))
    const put = vi.fn(async () => resume('updated'))
    const patch = vi.fn(async () => resume('archived'))
    const operations = createMcpOperations(api({
      post: post as McpApi['post'],
      put: put as McpApi['put'],
      patch: patch as McpApi['patch'],
    }))

    await operations.createResume({ title: 'CV', latex_content: '\\documentclass{article}' })
    await operations.updateResume('a/b', { title: 'New title' })
    await operations.archiveResume('a/b')

    expect(post).toHaveBeenCalledWith('/resumes/', expect.objectContaining({
      title: 'CV', document_type: 'resume', is_template: false,
    }))
    expect(put).toHaveBeenCalledWith('/resumes/a%2Fb', { title: 'New title' })
    expect(patch).toHaveBeenCalledWith('/resumes/a%2Fb/archive')
  })

  it('reads stored source and compiler before queueing a compile', async () => {
    const get = vi.fn(async () => resume('source'))
    const post = vi.fn(async () => ({ job_id: 'job-1' }))
    const operations = createMcpOperations(api({
      get: get as McpApi['get'],
      post: post as McpApi['post'],
    }))

    await expect(operations.submitResumeJob('source', 'latex_compilation')).resolves.toEqual({
      job_id: 'job-1', status: 'queued',
    })
    expect(post).toHaveBeenCalledWith('/jobs/submit', expect.objectContaining({
      job_type: 'latex_compilation',
      latex_content: expect.stringContaining('source'),
      compiler: 'xelatex',
      metadata: { resume_id: 'source', submitted_via: 'mcp' },
    }))
  })

  it('does not expose owner or share-link internals in MCP resume responses', async () => {
    const get = vi.fn(async () => ({
      ...resume('private'),
      user_id: 'owner-secret',
      share_token: 'share-secret',
      share_url: 'https://example.test/r/share-secret',
      metadata: { compiler: 'lualatex', share_anonymous_job_id: 'internal-job' },
    }))
    const operations = createMcpOperations(api({ get: get as McpApi['get'] }))

    const result = await operations.readResume('private')
    expect(result).not.toHaveProperty('user_id')
    expect(result).not.toHaveProperty('share_token')
    expect(result).not.toHaveProperty('share_url')
    expect(result.metadata).toEqual({ compiler: 'lualatex' })
  })

  it('only fetches a result after the job is terminal', async () => {
    const runningGet = vi.fn(async () => ({ status: 'processing', percent: 20 }))
    const running = createMcpOperations(api({ get: runningGet as McpApi['get'] }))
    expect(await running.getJobStatus('job')).toEqual({ job_id: 'job', status: 'processing', percent: 20 })
    expect(runningGet).toHaveBeenCalledTimes(1)

    const terminalGet = vi.fn(async (path: string) => path.endsWith('/state')
      ? { status: 'completed' }
      : { success: true, result: { page_count: 1 } })
    const terminal = createMcpOperations(api({ get: terminalGet as McpApi['get'] }))
    expect(await terminal.getJobStatus('job')).toEqual({
      job_id: 'job', status: 'completed', result: { success: true, result: { page_count: 1 } },
    })
    expect(terminalGet).toHaveBeenCalledTimes(2)
  })
})
