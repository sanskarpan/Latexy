import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { AccountPreferenceRequestContext } from '../lib/api-client'

type Provider = 'github' | 'zotero' | 'mendeley' | 'dropbox'
type Client = Awaited<ReturnType<typeof loadBrowserApiClient>>

const providers: Provider[] = ['github', 'zotero', 'mendeley', 'dropbox']

function mockFetch() {
  const response = () => new Response(JSON.stringify({ connected: false }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
  const fetchMock = vi.fn().mockImplementation(response)
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

function readStatus(client: Client, provider: Provider, context: AccountPreferenceRequestContext) {
  if (provider === 'github') return client.getGitHubStatus(context)
  if (provider === 'zotero') return client.getZoteroStatus(context)
  if (provider === 'mendeley') return client.getMendeleyStatus(context)
  return client.getDropboxStatus(context)
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('legacy provider status account context', () => {
  test.each(providers)('%s allows an unchanged owner context through authedFetch', async (provider) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    client.setAuthToken('owner-a-token')
    const context = { authToken: 'owner-a-token', isCurrent: () => true }

    await readStatus(client, provider, context)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toMatch(new RegExp(`/${provider}/status$`))
    expect((fetchMock.mock.calls[0]?.[1].headers as Record<string, string>).Authorization)
      .toBe('Bearer owner-a-token')
  })

  test.each(providers)('%s rejects a stale owner callback before dispatch', async (provider) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    client.setAuthToken('owner-a-token')
    const context = { authToken: 'owner-a-token', isCurrent: () => false }

    await expect(readStatus(client, provider, context))
      .rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test.each(providers)('%s rejects when the auth token changes while waiting for the gate', async (provider) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    const context = { authToken: 'owner-a-token', isCurrent: () => true }
    const pending = readStatus(client, provider, context)
    await Promise.resolve()

    client.setAuthToken('owner-b-token')

    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test.each(providers)('%s rejects when the owner changes after the gate starts', async (provider) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    let current = true
    const context = { authToken: 'owner-a-token', isCurrent: () => current }
    const pending = readStatus(client, provider, context)
    await Promise.resolve()

    current = false
    client.setAuthToken('owner-a-token')

    await expect(pending).rejects.toThrow('Account request context changed before dispatch')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  test.each(providers)('%s allows an unchanged owner after the gate starts', async (provider) => {
    const fetchMock = mockFetch()
    const client = await loadBrowserApiClient()
    const context = { authToken: 'owner-a-token', isCurrent: () => true }
    const pending = readStatus(client, provider, context)
    await Promise.resolve()

    client.setAuthToken('owner-a-token')

    await pending
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect((fetchMock.mock.calls[0]?.[1].headers as Record<string, string>).Authorization)
      .toBe('Bearer owner-a-token')
  })
})
