import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ApiClient, ApiError } from '../lib/api-client.js'

describe('ApiClient', () => {
  let client: ApiClient

  beforeEach(() => {
    client = new ApiClient({ baseUrl: 'http://localhost:8030' })
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sets Authorization header when token provided', async () => {
    const mockFetch = vi.mocked(fetch)
    mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    client.setToken('mytoken')
    await client.get('/health')
    const [, init] = mockFetch.mock.calls[0]!
    const headers = new Headers(init?.headers as HeadersInit)
    expect(headers.get('Authorization')).toBe('Bearer mytoken')
  })

  it('throws ApiError on 401', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: 'Unauthorized' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } }
    ))
    client.setToken('bad')
    await expect(client.get('/me')).rejects.toThrow('Unauthorized')
  })

  it('throws ApiError with correct status on 401', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: 'Unauthorized' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } }
    ))
    await expect(client.get('/me')).rejects.toMatchObject({ status: 401 })
  })

  it('retries on 503 up to 3 times then succeeds', async () => {
    const mockFetch = vi.mocked(fetch)
    mockFetch
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    const result = await client.get('/health', { retryDelayMs: 0 })
    expect(result).toEqual({ ok: true })
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })

  it('getWsUrl converts http to ws', () => {
    expect(client.getWsUrl()).toBe('ws://localhost:8030/ws/jobs')
  })
})
