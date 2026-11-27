import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin refund and goodwill requests', () => {
  const billing = read('../components/admin/AdminBilling.tsx')
  const userDetail = read('../components/admin/AdminUserDetail.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('supports refund and goodwill requests from a local or Dodo payment ID', () => {
    expect(billing).toContain('Create refund or goodwill request')
    expect(billing).toContain('Payment UUID or Dodo payment ID')
    expect(billing).toContain('PAYMENT_UUID_RE')
    expect(billing).toContain('provider_payment_id')
    expect(billing).toContain("request_kind: refundKind")
    expect(billing).toContain('Goodwill')
    expect(apiClient).toContain("request_kind?: 'refund' | 'goodwill'")
    expect(apiClient).toContain('provider_payment_id?: string')
  })

  it('keeps evidence admin-only and execution behind approval', () => {
    expect(billing).toContain('Evidence (optional, admin-only)')
    expect(billing).toContain('Never paste card data')
    expect(billing).toContain('Refund and goodwill approval queue')
    expect(billing).toContain('require a different admin to approve')
    expect(billing).toContain('Execution never happens')
    expect(userDetail).toContain("row.request_kind === 'goodwill' ? 'goodwill' : 'refund'")
  })

  it('never renders card data or provider payloads', () => {
    expect(billing).not.toContain('card_number')
    expect(billing).not.toContain('last4')
    expect(billing).not.toContain('DODO_API_KEY')
    expect(billing).not.toContain('payload_sha256')
    expect(userDetail).not.toContain('provider_payload')
  })
})
