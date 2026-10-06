import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(new URL('../app/admin/tenant/page.tsx', import.meta.url), 'utf8')

describe('tenant admin load recovery', () => {
  it('separates primary list failure from no tenants', () => {
    expect(SOURCE).toContain('tenantListError')
    expect(SOURCE).toContain('!selected && !tenantListError')
    expect(SOURCE).toContain('onClick={() => void loadTenants()}')
  })

  it('retains partial detail results and rejects stale tenant responses', () => {
    expect(SOURCE).toContain('Promise.allSettled')
    expect(SOURCE).toContain('requestId !== detailRequestRef.current')
    expect(SOURCE).toContain('statsError ? (')
    expect(SOURCE).toContain('membersError && (')
    expect(SOURCE).not.toContain("toast.error('Failed to load tenant data')")
  })
})
