import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient, type ChangeHunk } from '../lib/api-client'

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

function lastCall(): { url: string; init: RequestInit; body: Record<string, unknown> } {
  const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
  return { url, init, body: JSON.parse(init.body as string) }
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

const HUNK: ChangeHunk = {
  id: 'abc123',
  kind: 'modified',
  original_text: 'old bullet',
  new_text: 'new bullet',
  before_context: '',
  after_context: '',
  section: 'Experience',
  rationale: 'quantified impact',
  original_start: 10,
  original_end: 20,
}

describe('segmentChanges', () => {
  test('POSTs original + optimized latex and returns hunks + summary', async () => {
    mockFetch({ hunks: [HUNK], summary: { total: 1, added: 0, modified: 1, removed: 0 } })

    const res = await apiClient.segmentChanges({
      original_latex: 'A',
      optimized_latex: 'B',
    })

    const { url, init, body } = lastCall()
    expect(url).toContain('/optimize/segment-changes')
    expect(init.method).toBe('POST')
    expect(body.original_latex).toBe('A')
    expect(body.optimized_latex).toBe('B')
    expect(res.hunks).toHaveLength(1)
    expect(res.summary.modified).toBe(1)
  })

  test('forwards change_reasons when provided', async () => {
    mockFetch({ hunks: [], summary: { total: 0, added: 0, modified: 0, removed: 0 } })

    await apiClient.segmentChanges({
      original_latex: 'A',
      optimized_latex: 'B',
      change_reasons: [{ section: 'Experience', change_type: 'modified', reason: 'clarity' }],
    })

    expect(lastCall().body.change_reasons).toEqual([
      { section: 'Experience', change_type: 'modified', reason: 'clarity' },
    ])
  })
})

describe('applyChanges', () => {
  test('POSTs original latex, hunks, and accepted ids; returns reconstructed latex', async () => {
    mockFetch({ latex: 'RECONSTRUCTED' })

    const res = await apiClient.applyChanges({
      original_latex: 'ORIG',
      hunks: [HUNK],
      accepted_ids: ['abc123'],
    })

    const { url, init, body } = lastCall()
    expect(url).toContain('/optimize/apply-changes')
    expect(init.method).toBe('POST')
    expect(body.original_latex).toBe('ORIG')
    expect(body.accepted_ids).toEqual(['abc123'])
    expect((body.hunks as ChangeHunk[])[0].id).toBe('abc123')
    expect(res.latex).toBe('RECONSTRUCTED')
  })

  test('an empty accepted set is still a valid apply payload', async () => {
    mockFetch({ latex: 'ORIG' })

    const res = await apiClient.applyChanges({
      original_latex: 'ORIG',
      hunks: [HUNK],
      accepted_ids: [],
    })

    expect(lastCall().body.accepted_ids).toEqual([])
    expect(res.latex).toBe('ORIG')
  })
})
