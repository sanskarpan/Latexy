import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin coupon and student performance', () => {
  const billing = read('../components/admin/AdminBilling.tsx')
  const component = read('../components/admin/AdminCouponStudentPerformance.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('wires the dedicated revenue section into the billing view', () => {
    expect(billing).toContain(
      "import AdminCouponStudentPerformance from './AdminCouponStudentPerformance'",
    )
    expect(billing).toContain('<AdminCouponStudentPerformance />')
    expect(component).toContain('Coupon &amp; student verification performance')
    expect(component).toContain('Student request → verify → paid funnel')
  })

  it('shows redemption, conversion, expiry and student funnel metrics', () => {
    expect(component).toContain('redemption_rate_pct')
    expect(component).toContain('conversion_pct')
    expect(component).toContain('expired_redemptions')
    expect(component).toContain('repeated_reservation_events')
    expect(component).toContain('requested_to_verified')
    expect(component).toContain('verified_to_paid')
    expect(component).toContain('repeated_failure_users')
  })

  it('renders advisory human-review flags without automatic punishment', () => {
    expect(apiClient).toContain('requires_human_review')
    expect(apiClient).toContain("automated_action: 'none'")
    expect(component).toContain('Human review required · No automatic action')
    expect(component).toContain('No account is blocked, refunded, downgraded or otherwise')
  })

  it('uses date and plan filters with five-user suppression', () => {
    expect(component).toContain('RANGES')
    expect(component).toContain('Plan filter')
    expect(component).toContain('minimum_segment_size')
    expect(component).toContain('suppressed_coupons')
    expect(component).toContain('suppressed_segments')
    expect(apiClient).toContain('getAdminCouponStudentPerformance')
    expect(apiClient).toContain('/admin/revenue/coupon-student-performance')
    expect(apiClient).toContain("qs.set('plan', params.plan)")
  })

  it('never renders student emails, account ids, tokens or event metadata', () => {
    expect(component).not.toContain('student_email')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('event_metadata')
    expect(component).not.toContain('verification_token')
    expect(component).not.toContain('ip_address')
    expect(component).not.toContain('user_agent')
  })
})
