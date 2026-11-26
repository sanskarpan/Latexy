import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin support email delivery surface', () => {
  const userDetail = read('../components/admin/AdminUserDetail.tsx')
  const supportActions = read('../components/admin/AdminSupportActions.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired into User 360 behind the admin-only branch', () => {
    expect(userDetail).toContain("import AdminSupportActions from './AdminSupportActions'")
    expect(userDetail).toContain('<AdminSupportActions')
    expect(userDetail).toContain('emailVerified={data.user.email_verified}')
    expect(supportActions).toContain('Support email delivery')
    expect(supportActions).toContain('Resend verification')
    expect(supportActions).toContain('Send password reset')
    expect(supportActions).toContain('Email receipt')
  })

  it('uses reason-and-confirmation admin endpoints and never renders action links', () => {
    expect(apiClient).toContain('/support/resend-verification')
    expect(apiClient).toContain('/support/password-reset')
    expect(apiClient).toContain('/support/resend-receipt')
    expect(apiClient).toContain('/payments/${encodeURIComponent(paymentId)}/receipt')
    expect(apiClient).toContain('confirm: true')
    expect(supportActions).toContain('window.confirm')
    expect(supportActions).toContain('reason')
    expect(supportActions).not.toContain('reset_url')
    expect(supportActions).not.toContain('verification_url')
    expect(supportActions).not.toContain('one-time link:')
  })
})
