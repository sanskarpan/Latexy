import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient } from '../lib/api-client'

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

describe('server-authoritative suggestion decisions', () => {
  test('sends the full CAS and anchor contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve({
        suggestion_id: 'peer-a:s1',
        status: 'accepted',
        decided_by_role: 'owner',
        decided_at: '2026-09-14T00:00:00Z',
        latex_content: 'Before Changed After',
        replayed: false,
      }),
      text: () => Promise.resolve(''),
    }))

    const result = await apiClient.decideSuggestion('resume/1', {
      suggestion_id: 'peer-a:s1',
      status: 'accepted',
      expected_content: 'Before Target After',
      original_text: 'Target',
      replacement_text: 'Changed',
      prefix: 'Before ',
      suffix: ' After',
    })

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/resumes/resume%2F1/suggestion-decisions')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toMatchObject({
      suggestion_id: 'peer-a:s1',
      expected_content: 'Before Target After',
      original_text: 'Target',
      replacement_text: 'Changed',
    })
    expect(result.replayed).toBe(false)
    expect(result.latex_content).toBe('Before Changed After')
  })

  test('keeps server CAS errors visible for pending/retry UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      text: () => Promise.resolve(JSON.stringify({ detail: { code: 'document_changed', message: 'retry' } })),
    }))

    await expect(apiClient.decideSuggestion('resume-1', {
      suggestion_id: 'peer-a:s1',
      status: 'accepted',
      expected_content: 'old',
      original_text: 'old',
      replacement_text: 'new',
    })).rejects.toThrow('HTTP 409')
  })
})
