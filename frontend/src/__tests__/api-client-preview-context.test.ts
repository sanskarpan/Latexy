import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AccountPreferenceRequestContext, JobSubmitRequest, JobSubmitResponse } from '@/lib/api-client'

type PreviewClient = {
  setAuthToken: (token: string | null) => void
  getAuthToken: () => string | null
  getResume: (id: string) => Promise<unknown>
  compileLatex: (body: { latex_content: string; resume_id: string }, context?: AccountPreferenceRequestContext) => Promise<JobSubmitResponse>
  submitJob: (body: JobSubmitRequest, context?: AccountPreferenceRequestContext) => Promise<JobSubmitResponse>
}

async function harness() {
  vi.resetModules()
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })
  vi.stubGlobal('navigator', { sendBeacon: () => true })
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ success: true, job_id: 'owned-preview' }), {
    headers: { 'Content-Type': 'application/json' },
  })))
  vi.stubGlobal('fetch', fetch)
  const { apiClient } = await import('@/lib/api-client')
  return { client: apiClient as unknown as PreviewClient, fetch }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.resetModules() })

for (const method of ['compileLatex', 'submitJob'] as const) {
  describe(`${method} owned preview dispatch`, () => {
    const start = (client: PreviewClient, context?: AccountPreferenceRequestContext) => method === 'compileLatex'
      ? client.compileLatex({ latex_content: 'owner A source', resume_id: 'resume-A' }, context)
      : client.submitJob({ job_type: 'latex_compilation', latex_content: 'owner A source', metadata: { resume_id: 'resume-A' } }, context)

    it.each(['owner', 'source', 'grant'])('rejects a %s change during the actual auth-ready wait before HTTP dispatch', async () => {
      const h = await harness()
      let current = true
      const pending = start(h.client, { authToken: 'owner-A-token', isCurrent: () => current })
      const rejected = expect(pending).rejects.toThrow('Account request context changed before dispatch')
      await Promise.resolve()
      expect(h.fetch).not.toHaveBeenCalled()
      current = false
      h.client.setAuthToken('owner-A-token')
      await rejected
      expect(h.fetch).not.toHaveBeenCalled()
    })

    it('never retargets a pending owner A body to owner B credentials', async () => {
      const h = await harness()
      const pending = start(h.client, { authToken: 'owner-A-token', isCurrent: () => true })
      const rejected = expect(pending).rejects.toThrow('Account request context changed before dispatch')
      await Promise.resolve()
      h.client.setAuthToken('owner-B-token')
      await rejected
      expect(h.fetch).not.toHaveBeenCalled()
    })

    it('preserves existing unscoped callers and dispatches a current captured context once', async () => {
      const h = await harness()
      h.client.setAuthToken('owner-A-token')
      await start(h.client)
      await start(h.client, { authToken: 'owner-A-token', isCurrent: () => true })
      expect(h.fetch).toHaveBeenCalledTimes(2)
      for (const [, init] of h.fetch.mock.calls as [string, RequestInit][]) {
        expect((init.headers as Record<string, string>).Authorization).toBe('Bearer owner-A-token')
        expect(JSON.parse(String(init.body))).toMatchObject({ job_type: 'latex_compilation', latex_content: 'owner A source' })
      }
    })
  })
}

it('cannot complete the authenticated source read before AuthSync publishes its token', async () => {
  const h = await harness()
  const sourceRead = h.client.getResume('resume-A')
  await Promise.resolve()
  expect(h.fetch).not.toHaveBeenCalled()
  expect(h.client.getAuthToken()).toBeNull()
  h.client.setAuthToken('owner-A-token')
  await sourceRead
  expect(h.fetch).toHaveBeenCalledOnce()
  expect(h.client.getAuthToken()).toBe('owner-A-token')
  const [, init] = h.fetch.mock.calls[0] as [string, RequestInit]
  expect((init.headers as Record<string, string>).Authorization).toBe('Bearer owner-A-token')
})
