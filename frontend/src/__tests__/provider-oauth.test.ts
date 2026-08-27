import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient } from '../lib/api-client'

const SETTINGS_SOURCE = readFileSync(
  fileURLToPath(new URL('../app/settings/page.tsx', import.meta.url)),
  'utf8'
)

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

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

const PROVIDERS = [
  {
    name: 'Dropbox',
    path: 'dropbox',
    start: () => apiClient.startDropboxOAuth(),
    complete: (ticket: string) => apiClient.completeDropboxOAuth(ticket),
  },
  {
    name: 'Zotero',
    path: 'zotero',
    start: () => apiClient.startZoteroOAuth(),
    complete: (ticket: string) => apiClient.completeZoteroOAuth(ticket),
  },
  {
    name: 'Mendeley',
    path: 'mendeley',
    start: () => apiClient.startMendeleyOAuth(),
    complete: (ticket: string) => apiClient.completeMendeleyOAuth(ticket),
  },
] as const

describe('bound provider OAuth clients', () => {
  test('settings uses the authenticated two-step handshake for every provider', () => {
    for (const provider of PROVIDERS) {
      expect(SETTINGS_SOURCE).toContain(`apiClient.start${provider.name}OAuth()`)
      expect(SETTINGS_SOURCE).toContain(`apiClient.complete${provider.name}OAuth(ticket)`)
      expect(SETTINGS_SOURCE).not.toContain(`\`\${API_BASE}/${provider.path}/connect\``)
    }
    expect(SETTINGS_SOURCE).toContain('if (!sessionData)')
    expect(SETTINGS_SOURCE).toContain('window.location.assign(authorizationUrl)')
  })

  test.each(PROVIDERS)(
    '$name starts OAuth through an authenticated POST',
    async ({ path, start }) => {
      mockFetch({ authorization_url: `https://provider.example/authorize?state=${path}` })
      apiClient.setAuthToken('latexy-session')

      const result = await start()

      const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
      expect(url).toContain(`/${path}/connect`)
      expect(init.method).toBe('POST')
      expect((init.headers as Record<string, string>).Authorization).toBe(
        'Bearer latexy-session'
      )
      expect(result.authorization_url).toContain('provider.example/authorize')
    }
  )

  test.each(PROVIDERS)(
    '$name completes a one-time ticket through an authenticated POST',
    async ({ path, complete }) => {
      mockFetch({ success: true, message: 'Connected' })
      apiClient.setAuthToken('latexy-session')

      await complete('one-time-ticket')

      const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
      expect(url).toContain(`/${path}/complete`)
      expect(init.method).toBe('POST')
      expect(JSON.parse(String(init.body))).toEqual({ ticket: 'one-time-ticket' })
      expect((init.headers as Record<string, string>).Authorization).toBe(
        'Bearer latexy-session'
      )
      expect(String(init.body)).not.toContain('latexy-session')
    }
  )
})
