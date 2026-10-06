import { afterEach, expect, test, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

test('getJobResult rejects a conflicting nested output identity', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    success: true,
    job_id: 'canonical-job',
    result: {
      success: false,
      job_id: 'stale-private-job',
      pdf_job_id: null,
      cover_letter_latex: '\\documentclass{letter}',
    },
  }), { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })

  vi.resetModules()
  const { apiClient } = await import('../lib/api-client')
  apiClient.markAuthResolved()

  await expect(apiClient.getJobResult('canonical-job')).rejects.toThrow('Nested job result identity mismatch')
  expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/jobs/canonical-job/result'), expect.anything())
})

test('getJobResult accepts legacy output without a nested identity', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    success: true,
    job_id: 'canonical-job',
    result: { pdf_job_id: null, cover_letter_latex: '\\documentclass{letter}' },
  }), { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })

  vi.resetModules()
  const { apiClient } = await import('../lib/api-client')
  apiClient.markAuthResolved()
  const result = await apiClient.getJobResult('canonical-job')

  expect(result.job_id).toBe('canonical-job')
  expect(result.pdf_job_id).toBeNull()
})

test('getJobResult rejects an envelope belonging to another job', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    success: true,
    job_id: 'private-other-job',
    result: { pdf_job_id: null },
  }), { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })

  vi.resetModules()
  const { apiClient } = await import('../lib/api-client')
  apiClient.markAuthResolved()

  await expect(apiClient.getJobResult('canonical-job')).rejects.toThrow('Job result identity mismatch')
})

test('getJobResult retains explicit output-unavailable markers on an unsuccessful envelope', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    success: false, job_id: 'canonical-job', error: 'Completed job output unavailable',
    result: {
      success: false, job_id: 'canonical-job', recovery_complete: false,
      error_code: 'output_unavailable', omitted_output_fields: ['cover_letter_latex'],
    },
  }), { headers: { 'Content-Type': 'application/json' } })))
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })
  vi.resetModules()
  const { apiClient } = await import('../lib/api-client')
  apiClient.markAuthResolved()
  await expect(apiClient.getJobResult('canonical-job')).resolves.toMatchObject({
    success: false, job_id: 'canonical-job', recovery_complete: false,
    error_code: 'output_unavailable', omitted_output_fields: ['cover_letter_latex'],
  })
})
