import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient, type ProjectEvidence } from '../lib/api-client'

const PROJECT: ProjectEvidence = {
  source: 'url',
  title: 'Portfolio Project',
  description: 'A thing',
  tech: ['TypeScript'],
  metrics: { stars: 0, forks: 0 },
  dates: { last_active: null },
  url: 'https://example.com/p',
  suggested_bullets: ['Built a thing'],
  raw_excerpt: '',
}

function mockFetch(responseBody: object, ok = true, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok,
      status,
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

describe('importFromUrl', () => {
  test('POSTs the url to /sources/import-url and returns projects', async () => {
    mockFetch({ projects: [PROJECT] })
    const res = await apiClient.importFromUrl('https://example.com')
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/sources/import-url')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string).url).toBe('https://example.com')
    expect(res.projects[0].title).toBe('Portfolio Project')
  })
})

describe('importLinkedIn', () => {
  test('POSTs multipart form-data to /sources/import-linkedin', async () => {
    mockFetch({ projects: [{ ...PROJECT, source: 'linkedin' }] })
    const file = new File([new Uint8Array([1, 2, 3])], 'export.zip', { type: 'application/zip' })

    const res = await apiClient.importLinkedIn(file)

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/sources/import-linkedin')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBeInstanceOf(File)
    expect(res.projects[0].source).toBe('linkedin')
  })

  test('throws on a non-ok response', async () => {
    mockFetch({ detail: 'File too large.' }, false, 413)
    const file = new File([new Uint8Array([1])], 'big.zip', { type: 'application/zip' })
    await expect(apiClient.importLinkedIn(file)).rejects.toThrow(/413/)
  })
})
