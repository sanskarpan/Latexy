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
  apiClient.setTenantSlug(null)
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

  test('mints a scoped WebSocket ticket over authenticated HTTP', async () => {
    mockFetch({ ticket: 'single-use', expires_in: 60 })
    apiClient.setAuthToken('reusable-session')

    const result = await apiClient.createWebSocketTicket('collab', 'resume-1')

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(url).toContain('/ws/ticket')
    expect(headers.Authorization).toBe('Bearer reusable-session')
    expect(JSON.parse(String(init.body))).toEqual({
      purpose: 'collab',
      resume_id: 'resume-1',
    })
    expect(String(init.body)).not.toContain('reusable-session')
    expect(result).toEqual({ ticket: 'single-use', expires_in: 60 })
  })

  test('propagates only a validated resolved tenant slug', async () => {
    mockFetch({ tenant: { slug: 'example-university' } })
    await apiClient.resolveTenantHost('cv.example.edu')
    await apiClient.getCurrentTenantContext()

    const [, init] = vi.mocked(fetch).mock.calls[1] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['X-Tenant-Slug']).toBe('example-university')

    apiClient.setTenantSlug('../spoofed')
    await apiClient.getCurrentTenantContext()
    const [, invalidInit] = vi.mocked(fetch).mock.calls[2] as [string, RequestInit]
    expect((invalidInit.headers as Record<string, string>)['X-Tenant-Slug']).toBeUndefined()
  })
})
