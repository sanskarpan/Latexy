import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AccountPreferenceRequestContext } from '@/lib/api-client'

type Client = typeof import('@/lib/api-client')['apiClient']
type Operation = { name: string; run: (client: Client, context?: AccountPreferenceRequestContext) => Promise<unknown> }
const operations: Operation[] = [
  { name: 'useTemplate', run: (c, x) => c.useTemplate('template-a', undefined, undefined, x) },
  { name: 'createTenant', run: (c, x) => c.createTenant({ name: 'Owned tenant', slug: 'owned' }, x) },
  { name: 'listMyTenants', run: (c, x) => c.listMyTenants(x) },
  { name: 'updateTenant', run: (c, x) => c.updateTenant('tenant-a', { custom_domain: 'owned.example.test' }, x) },
  { name: 'listTenantMembers', run: (c, x) => c.listTenantMembers('tenant-a', x) },
  { name: 'inviteTenantMember', run: (c, x) => c.inviteTenantMember('tenant-a', 'member@example.test', 'member', 'cohort-a', x) },
  { name: 'removeTenantMember', run: (c, x) => c.removeTenantMember('tenant-a', 'member-a', x) },
  { name: 'createTenantCohort', run: (c, x) => c.createTenantCohort('tenant-a', 'Owned cohort', x) },
  { name: 'listTenantCohorts', run: (c, x) => c.listTenantCohorts('tenant-a', x) },
  { name: 'listCohortSubmissions', run: (c, x) => c.listCohortSubmissions('tenant-a', 'cohort-a', x) },
  { name: 'getTenantStats', run: (c, x) => c.getTenantStats('tenant-a', x) },
  { name: 'verifyTenantDomain', run: (c, x) => c.verifyTenantDomain('tenant-a', x) },
  { name: 'generateInterviewPrep', run: (c, x) => c.generateInterviewPrep({ resume_id: 'resume-a' }, x) },
  { name: 'listInterviewPrep', run: (c, x) => c.listInterviewPrep('resume-a', x) },
  { name: 'deleteInterviewPrep', run: (c, x) => c.deleteInterviewPrep('prep-a', x) },
  { name: 'evaluateInterviewSimulation', run: (c, x) => c.evaluateInterviewSimulation('prep-a', { mode: 'coach', answers: [] }, x) },
]

async function harness() {
  vi.resetModules()
  vi.stubGlobal('window', { location: { href: 'http://localhost/' } })
  vi.stubGlobal('document', { cookie: '' })
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  const { apiClient } = await import('@/lib/api-client')
  return { client: apiClient, fetch }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.resetModules() })

for (const operation of operations) describe(`${operation.name} launch dispatch context`, () => {
  it.each(['lease', 'grant', 'selection'])('rechecks the captured %s guard after the actual auth-ready wait', async () => {
    const h = await harness()
    let current = true
    const pending = operation.run(h.client, { authToken: 'owner-a-token', isCurrent: () => current })
    const rejected = expect(pending).rejects.toThrow('Account request context changed before dispatch')
    await Promise.resolve()
    expect(h.fetch).not.toHaveBeenCalled()
    current = false
    h.client.setAuthToken('owner-a-token')
    await rejected
    expect(h.fetch).not.toHaveBeenCalled()
  })

  it('does not retarget the queued request to a different owner or same-owner replacement token', async () => {
    const h = await harness()
    const pending = operation.run(h.client, { authToken: 'owner-a-token', isCurrent: () => true })
    const rejected = expect(pending).rejects.toThrow('Account request context changed before dispatch')
    await Promise.resolve()
    h.client.setAuthToken('replacement-token')
    await rejected
    expect(h.fetch).not.toHaveBeenCalled()
  })

  it('preserves unscoped callers and sends the captured current token once', async () => {
    const h = await harness()
    h.client.setAuthToken('owner-a-token')
    await operation.run(h.client)
    await operation.run(h.client, { authToken: 'owner-a-token', isCurrent: () => true })
    expect(h.fetch).toHaveBeenCalledTimes(2)
    for (const [, init] of h.fetch.mock.calls) {
      expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer owner-a-token')
    }
  })

  it('does not cancel an already-dispatched result when the admission lease retires', async () => {
    const h = await harness()
    h.client.setAuthToken('owner-a-token')
    let finish!: (value: Response) => void
    h.fetch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    let current = true
    const pending = operation.run(h.client, { authToken: 'owner-a-token', isCurrent: () => current })
    for (let i = 0; i < 5; i++) await Promise.resolve()
    expect(h.fetch).toHaveBeenCalledOnce()
    current = false
    finish(new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
    await pending
    expect(h.fetch).toHaveBeenCalledOnce()
  })
})
