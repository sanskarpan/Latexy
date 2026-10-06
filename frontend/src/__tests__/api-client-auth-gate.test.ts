import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

/**
 * The auth-ready gate makes requests wait for AuthSync to publish the Better Auth
 * session state, but the wait must be *bounded* — a slow/hanging session endpoint
 * must not deadlock the app (including anonymous flows like /try).
 *
 * The gate only exists in the browser, so these tests stub `window` before
 * importing a fresh module instance.
 */

function mockFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: {},
    json: () => Promise.resolve({}),
    text: () => Promise.resolve('{}'),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function loadBrowserApiClient() {
  vi.resetModules()
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })
  const mod = await import('../lib/api-client')
  return mod.apiClient
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('ApiClient auth-ready gate', () => {
  test.each(['account', 'tenant'] as const)('isolates in-flight job lists across %s changes', async (change) => {
    const fetchMock = mockFetch()
    let finishOld!: (response: Response) => void
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve }))
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ jobs: [{ job_id: 'new-context' }] }), {
      headers: { 'Content-Type': 'application/json' },
    }))
    const client = await loadBrowserApiClient()
    client.setAuthToken('synthetic-owner-a')
    client.setTenantSlug('tenant-a')
    const oldRead = client.listJobs()
    const oldRejected = expect(oldRead).rejects.toThrow('context changed')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    if (change === 'account') client.setAuthToken('synthetic-owner-b')
    else client.setTenantSlug('tenant-b')
    const newRead = client.listJobs()
    finishOld(new Response(JSON.stringify({ jobs: [{ job_id: 'private-old-context' }] }), {
      headers: { 'Content-Type': 'application/json' },
    }))
    await oldRejected
    expect((await newRead).jobs).toEqual([{ job_id: 'new-context' }])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const headers = fetchMock.mock.calls[1][1].headers as Record<string, string>
    expect(headers.Authorization).toBe(`Bearer synthetic-owner-${change === 'account' ? 'b' : 'a'}`)
    expect(headers['X-Tenant-Slug']).toBe(change === 'tenant' ? 'tenant-b' : 'tenant-a')
  })

  test('does not start the fallback timer until an API request needs it', async () => {
    mockFetch()
    await loadBrowserApiClient()

    expect(vi.getTimerCount()).toBe(0)
  })

  test('holds a request until AuthSync reports the session state', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.getCurrentTenantContext()
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-123')
    client.markAuthResolved()
    await pending

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-123')
  })

  test('allows an account preference request with its unchanged auth context', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    client.setAuthToken('account-token-a')
    const response = await client.getMe({
      authToken: 'account-token-a',
      isCurrent: () => true,
    })

    expect(response).toEqual({})
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>).Authorization)
      .toBe('Bearer account-token-a')
  })

  test('rejects an account preference request when its token changes during the auth gate', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    const pending = client.getMe({
      authToken: 'account-token-a',
      isCurrent: () => true,
    })
    await Promise.resolve()
    client.setAuthToken('account-token-b')

    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test('rejects an account preference request when its owner epoch is stale', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    client.setAuthToken('account-token-a')
    const pending = client.updateMePreferences(
      { spell_dictionary: ['private-word'] },
      { authToken: 'account-token-a', isCurrent: () => false },
    )

    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test('falls through unauthenticated if the session never resolves', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.getCurrentTenantContext()
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    // No setAuthToken / markAuthResolved at all — the deadline must open the gate.
    await vi.advanceTimersByTimeAsync(9000)
    await pending

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBeUndefined()
  })

  test('a null token from a page does not open the gate early', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.getCurrentTenantContext()
    // A page mirroring its own (not yet hydrated) session token must not release
    // the gate — otherwise the request goes out without the token AuthSync is
    // about to publish.
    client.setAuthToken(null)
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-456')
    await pending

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-456')
  })

  test('raw-fetch helpers are gated too (deleteResume)', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.deleteResume('resume-1')
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-789')
    client.markAuthResolved()
    await pending

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-789')
  })

  test('SyncTeX downloads use the authenticated request path', async () => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()

    const pending = client.downloadSynctex('job-1')
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('tok-synctex')
    await pending

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch(/\/download\/job-1\/synctex$/)
    expect((init.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-synctex')
  })

  test('deduplicates concurrent job-list reads from dashboard consumers', async () => {
    const fetchMock = mockFetch()
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: {},
      json: () => Promise.resolve({ jobs: [] }),
      text: () => Promise.resolve('{"jobs":[]}'),
    })
    const client = await loadBrowserApiClient()
    client.setAuthToken('tok-jobs')

    await Promise.all([client.listJobs(), client.listJobs()])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toMatch(/\/jobs\/$/)
  })
})
