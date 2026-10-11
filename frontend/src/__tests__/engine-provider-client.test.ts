import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../lib/api-client'

const body = { expected_content_revision: 3, expected_source_sha256: 'source-hash', job_description: 'A role', effort: 'standard' as const }
afterEach(() => { apiClient.setAuthToken(null); vi.unstubAllGlobals() })

describe('engine provider admission contract', () => {
  it('omits provider overrides for Automatic and sends exact explicit choices', async () => {
    apiClient.setAuthToken('owner-token')
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ success: true, job_id: 'review' }) })
    vi.stubGlobal('fetch', fetcher)
    const context = { authToken: 'owner-token', isCurrent: () => true }
    await apiClient.optimizeEngineDocument('resume/one', body, context)
    await apiClient.optimizeEngineDocument('resume/one', { ...body, provider: 'anthropic', provider_model: 'priced-exact-model' }, context)
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(body)
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ ...body, provider: 'anthropic', provider_model: 'priced-exact-model' })
    expect(fetcher.mock.calls[1][0]).toContain('/resumes/resume%2Fone/engine/optimize')
    expect(fetcher.mock.calls[1][1].headers.Authorization).toBe('Bearer owner-token')
  })
  it('loads options from the authenticated engine endpoint', async () => {
    apiClient.setAuthToken('owner-token')
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ providers: [] }) })
    vi.stubGlobal('fetch', fetcher)
    await apiClient.getEngineProviders({ authToken: 'owner-token', isCurrent: () => true })
    expect(fetcher.mock.calls[0][0]).toMatch(/\/resumes\/engine\/providers$/)
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer owner-token')
  })
  it('blocks a queued review and options request after the account changes', async () => {
    apiClient.setAuthToken('previous-owner-token')
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
    const context = { authToken: 'previous-owner-token', isCurrent: () => true }
    const pending = apiClient.optimizeEngineDocument('resume', { ...body, provider: 'openrouter', provider_model: 'priced-model' }, context)
    apiClient.setAuthToken('new-owner-token')
    await expect(pending).rejects.toThrow('Account request context changed')
    await expect(apiClient.getEngineProviders(context)).rejects.toThrow('Account request context changed')
    expect(fetcher).not.toHaveBeenCalled()
  })
})
