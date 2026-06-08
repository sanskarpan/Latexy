import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient } from '../lib/api-client'

function mockFetch(responseBody: object = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: {},
      json: () => Promise.resolve(responseBody),
      text: () => Promise.resolve(JSON.stringify(responseBody)),
    })
  )
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

describe('ApiClient header behavior', () => {
  test('omits Content-Type for simple GET requests', async () => {
    mockFetch({ tenant: null })

    await apiClient.getCurrentTenantContext()

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['Content-Type']).toBeUndefined()
  })

  test('keeps JSON Content-Type for JSON POST requests', async () => {
    mockFetch({ success: true, job_id: 'job-1', message: 'ok' })

    await apiClient.submitJob({
      job_type: 'latex_compilation',
      latex_content: '\\documentclass{article}\\begin{document}Hi\\end{document}',
    })

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/json')
  })
})
