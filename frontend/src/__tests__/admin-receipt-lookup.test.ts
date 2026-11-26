import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin receipt lookup and audited resend', () => {
  const lookup = read('../components/admin/AdminReceiptLookup.tsx')
  const page = read('../app/admin/page.tsx')
  const apiClient = read('../lib/api-client.ts')
  const supportActions = read('../components/admin/AdminSupportActions.tsx')

  it('is wired into an admin-only receipts tab', () => {
    expect(page).toContain(
      "import AdminReceiptLookup from '@/components/admin/AdminReceiptLookup'",
    )
    expect(page).toContain("{ id: 'receipts', label: 'Receipts' }")
    expect(page).toContain("{tab === 'receipts' && <AdminReceiptLookup />}")
    expect(page).toContain("new URLSearchParams(window.location.search).get('user')")
    expect(lookup).toContain('Receipt and invoice lookup')
  })

  it('searches by payment, subscription, user and email hash and links the timeline', () => {
    expect(apiClient).toContain('/admin/receipts/search')
    expect(apiClient).toContain("qs.set('payment_id'")
    expect(apiClient).toContain("qs.set('subscription_id'")
    expect(apiClient).toContain("qs.set('user_id'")
    expect(apiClient).toContain("qs.set('email_hash'")
    expect(lookup).toContain('Payment ID')
    expect(lookup).toContain('Subscription ID')
    expect(lookup).toContain('Email hash')
    expect(lookup).toContain('/admin?tab=customers&user=')
  })

  it('requires a reason, confirmation and idempotency key before resending', () => {
    expect(lookup).toContain('window.confirm')
    expect(lookup).toContain('Reason for this audited resend')
    expect(lookup).toContain('crypto.randomUUID')
    expect(apiClient).toContain('idempotency_key')
    expect(supportActions).toContain('newReceiptKey')
    expect(supportActions).toContain('result.duplicate')
    expect(lookup).not.toContain('card_number')
    expect(lookup).not.toContain('raw_payload')
    expect(lookup).not.toContain('verification_url')
    expect(lookup).not.toContain('reset_url')
  })

  it('shows invoice availability, duplicate and failure states', () => {
    expect(lookup).toContain('invoice_state')
    expect(lookup).toContain('invoice_attached')
    expect(lookup).toContain('not_exposed')
    expect(lookup).toContain('duplicate')
    expect(lookup).toContain('role="alert"')
  })
})
