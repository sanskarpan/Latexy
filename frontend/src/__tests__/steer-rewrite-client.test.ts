import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient } from '../lib/api-client'

function mockFetch(responseBody: object) {
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

function lastBody(): Record<string, unknown> {
  const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
  return JSON.parse(init.body as string)
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

describe('rewriteText steer action', () => {
  test('forwards the steer action + free-text instruction', async () => {
    mockFetch({ rewritten: 'Led a team...', action: 'steer', cached: false })

    const res = await apiClient.rewriteText({
      selected_text: 'Managed a team of engineers to deliver features.',
      action: 'steer',
      instruction: 'Emphasize leadership and quantify impact',
    })

    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/ai/rewrite')
    const body = lastBody()
    expect(body.action).toBe('steer')
    expect(body.instruction).toBe('Emphasize leadership and quantify impact')
    expect(res.rewritten).toBe('Led a team...')
  })

  test('omits instruction for non-steer actions', async () => {
    mockFetch({ rewritten: 'x', action: 'improve', cached: false })

    await apiClient.rewriteText({
      selected_text: 'Managed a team of engineers to deliver features.',
      action: 'improve',
    })

    expect('instruction' in lastBody()).toBe(false)
  })
})
