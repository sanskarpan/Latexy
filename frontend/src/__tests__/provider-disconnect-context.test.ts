import { afterEach, describe, expect, test, vi } from 'vitest'
import type { AccountPreferenceRequestContext } from '../lib/api-client'

const operations = [
  ['getGoogleDriveStatus', 'GET'],
  ['disconnectGitHub', 'DELETE'],
  ['disconnectZotero', 'DELETE'],
  ['disconnectDropbox', 'DELETE'],
  ['disconnectGoogleDrive', 'DELETE'],
  ['disconnectMendeley', 'DELETE'],
] as const

type Operation = (typeof operations)[number][0]
type ProviderApi = {
  [K in Operation]: (context?: AccountPreferenceRequestContext) => Promise<unknown>
}

function mockFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve({ connected: false, scope: null, success: true, message: 'ok' }),
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

function invoke(client: ProviderApi, operation: Operation, context: AccountPreferenceRequestContext) {
  return client[operation](context)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('provider status/disconnect account contexts', () => {
  test.each(operations)('%s allows an unchanged owner context and dispatches its token', async (operation) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    client.setAuthToken('owner-a-token')

    await invoke(client, operation, { authToken: 'owner-a-token', isCurrent: () => true })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer owner-a-token')
    expect(init.method ?? 'GET').toBe(operation === 'getGoogleDriveStatus' ? 'GET' : 'DELETE')
  })

  test.each(operations)('%s rejects a token change while waiting for auth readiness', async (operation) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    const pending = invoke(client, operation, { authToken: 'owner-a-token', isCurrent: () => true })
    await Promise.resolve()
    client.setAuthToken('owner-b-token')

    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test.each(operations)('%s rejects an owner callback that is already stale', async (operation) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    client.setAuthToken('owner-a-token')

    await expect(invoke(client, operation, { authToken: 'owner-a-token', isCurrent: () => false }))
      .rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
