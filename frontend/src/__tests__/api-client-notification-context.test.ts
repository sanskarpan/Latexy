import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AccountPreferenceRequestContext } from '../lib/api-client'

const preferenceSnapshot = {
  job_completed: true,
  job_failed: true,
  share_viewed: false,
  weekly_digest: false,
  tracker_updates: true,
  comment_mentions: true,
}

type NotificationClient = {
  setAuthToken: (token: string | null) => void
  markAuthResolved: () => void
  getNotificationPrefs: (context?: AccountPreferenceRequestContext) => Promise<unknown>
  updateNotificationPrefs: (prefs: typeof preferenceSnapshot, context?: AccountPreferenceRequestContext) => Promise<unknown>
}

function mockFetch() {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(preferenceSnapshot), {
    headers: { 'Content-Type': 'application/json' },
  }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function loadClient(): Promise<NotificationClient> {
  vi.resetModules()
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })
  const { apiClient } = await import('../lib/api-client')
  return apiClient as unknown as NotificationClient
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('notification API account context', () => {
  it.each(['get', 'put'] as const)('allows a current-owner %s with its captured token', async (method) => {
    const fetchMock = mockFetch()
    const client = await loadClient()
    client.setAuthToken('notification-token-a')
    const context = { authToken: 'notification-token-a', isCurrent: () => true }

    const result = method === 'get'
      ? await client.getNotificationPrefs(context)
      : await client.updateNotificationPrefs(preferenceSnapshot, context)

    expect(result).toEqual(preferenceSnapshot)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer notification-token-a')
    expect(init.method ?? 'GET').toBe(method === 'get' ? 'GET' : 'PUT')
  })

  it.each(['get', 'put'] as const)('rejects a stale-owner %s before dispatch', async (method) => {
    const fetchMock = mockFetch()
    const client = await loadClient()
    client.setAuthToken('notification-token-a')
    const context = { authToken: 'notification-token-a', isCurrent: () => false }

    const pending = method === 'get'
      ? client.getNotificationPrefs(context)
      : client.updateNotificationPrefs(preferenceSnapshot, context)

    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each(['get', 'put'] as const)('does not retarget a waiting %s to a later account token', async (method) => {
    const fetchMock = mockFetch()
    const client = await loadClient()
    const context = { authToken: 'notification-token-a', isCurrent: () => true }
    const pending = method === 'get'
      ? client.getNotificationPrefs(context)
      : client.updateNotificationPrefs(preferenceSnapshot, context)
    await Promise.resolve()
    expect(fetchMock).not.toHaveBeenCalled()

    client.setAuthToken('notification-token-b')
    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('accepts an already-dispatched response for the same account across token refresh', async () => {
    let finish!: (response: Response) => void
    const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    const client = await loadClient()
    client.setAuthToken('notification-token-a-old')
    const context = { authToken: 'notification-token-a-old', isCurrent: () => true }

    const pending = client.updateNotificationPrefs(preferenceSnapshot, context)
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    client.setAuthToken('notification-token-a-refreshed')
    finish(new Response(JSON.stringify(preferenceSnapshot), { headers: { 'Content-Type': 'application/json' } }))

    await expect(pending).resolves.toEqual(preferenceSnapshot)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
