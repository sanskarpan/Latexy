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

describe('suggestion request account pinning', () => {
  test.each(['decide', 'get'] as const)('refuses %s dispatch after the authenticated token changes', async (operation) => {
    const send = vi.fn(); vi.stubGlobal('fetch', send)
    apiClient.setAuthToken('original-owner-token')
    const context = { authToken: 'original-owner-token', isCurrent: () => true }
    const request = operation === 'decide'
      ? apiClient.decideSuggestion('resume-1', { suggestion_id: 'peer:a', status: 'rejected', expected_content: 'source', original_text: 'source', replacement_text: 'after' }, context)
      : apiClient.getSuggestionDecision('resume-1', 'peer:a', context)
    apiClient.setAuthToken('next-owner-token')
    await expect(request).rejects.toThrow('Account request context changed before dispatch')
    expect(send).not.toHaveBeenCalled()
  })
  test('refuses dispatch when the owner returns to the same token but its document incarnation changed', async () => {
    const send = vi.fn(); vi.stubGlobal('fetch', send); apiClient.setAuthToken('owner-token')
    let current = true
    const request = apiClient.decideSuggestion('resume-1', { suggestion_id: 'peer:a', status: 'rejected', expected_content: 'source', original_text: 'source', replacement_text: 'after' },
      { authToken: 'owner-token', isCurrent: () => current })
    current = false
    await expect(request).rejects.toThrow('Account request context changed before dispatch')
    expect(send).not.toHaveBeenCalled()
  })
})
