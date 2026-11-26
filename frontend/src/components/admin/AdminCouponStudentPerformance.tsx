'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminCouponStudentPerformance as CouponStudentPerformanceData,
  type AdminRevenueReviewFlag,
} from '@/lib/api-client'
import { formatNumber } from './admin-format'

const RANGES = [7, 30, 90] as const
const PLAN_OPTIONS = ['', 'student', 'basic', 'pro', 'byok', 'team', 'weekly', 'lifetime'] as const

function pct(value: number | null | undefined): string {
  const numeric = Number.isFinite(value ?? NaN) ? Number(value) : 0
  return `${numeric.toFixed(1)}%`
}

function Kpi({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail?: string
  tone?: string
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-bg/40 p-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">{label}</p>
      <p className={`mt-1.5 text-lg font-semibold tracking-tight ${tone ?? 'text-fg'}`}>{value}</p>
      {detail && <p className="mt-1 text-[10px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function ReviewFlags({ flags }: { flags: AdminRevenueReviewFlag[] }) {
  if (flags.length === 0) {
    return (
      <p className="px-5 py-6 text-sm text-fg-3">
        No review flags in this range. Flags are advisory and never trigger an automatic account action.
      </p>
    )
  }
  return (
    <ul className="divide-y divide-line">
      {flags.map((flag) => (
        <li key={flag.flag_id} className="px-5 py-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-xs font-semibold text-fg">{flag.title}</p>
              <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-fg-3">{flag.detail}</p>
            </div>
            <span
              className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                flag.severity === 'high'
                  ? 'border-err/30 bg-err/10 text-err'
                  : 'border-warn/30 bg-warn/10 text-warn'
              }`}
            >
              {flag.severity} · review
            </span>
          </div>
          <p className="mt-2 text-[10px] text-fg-3">
            {flag.coupon_code ? `Coupon ${flag.coupon_code} · ` : ''}
            {formatNumber(flag.affected_count)} affected · Human review required · No automatic action
          </p>
        </li>
      ))}
    </ul>
  )
}

export default function AdminCouponStudentPerformance() {
  const [days, setDays] = useState<number>(30)
  const [plan, setPlan] = useState<string>('')
  const [data, setData] = useState<CouponStudentPerformanceData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)

  const load = useCallback(async (range: number, planFilter: string) => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminCouponStudentPerformance({
        days: range,
        plan: planFilter || undefined,
      })
      if (requestGeneration.current === generation) setData(next)
    } catch (err) {
      if (requestGeneration.current === generation) {
        setError(
          err instanceof Error
            ? err.message
            : 'Failed to load coupon and student verification performance',
        )
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(days, plan)
    return () => {
      requestGeneration.current += 1
    }
  }, [days, plan, load])

  const coupon = data?.coupon
  const student = data?.student
  const maxStep = Math.max(...(student?.steps.map((step) => step.count) ?? [0]), 1)

  return (
    <section className="mt-4 overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">
              Coupon &amp; student verification performance
            </h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              First-party coupon reservations and student verification milestones from existing billing
              tables and aggregate lifecycle events. Student email addresses, verification tokens and
              account identifiers are never returned. Every review flag is advisory only.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div
              className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
              role="group"
              aria-label="Coupon and student performance date range"
            >
              {RANGES.map((range) => (
                <button
                  key={range}
                  type="button"
                  aria-pressed={days === range}
                  onClick={() => setDays(range)}
                  className={`rounded px-2.5 py-1 text-[11px] font-medium ${
                    days === range ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'
                  }`}
                >
                  {range}d
                </button>
              ))}
            </div>
            <select
              aria-label="Plan filter"
              value={plan}
              onChange={(event) => setPlan(event.target.value)}
              className="min-h-[34px] rounded-[var(--radius-md)] border border-line bg-bg px-2.5 py-1 text-[11px] text-fg"
            >
              {PLAN_OPTIONS.map((option) => (
                <option key={option || 'all'} value={option}>
                  {option ? option : 'All plans'}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void load(days, plan)}
              disabled={loading}
              className="min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>
        </div>
        {data && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-fg-3">
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-semibold">
              {data.period.days} day window
            </span>
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-semibold">
              Minimum segment: {data.minimum_segment_size} users
            </span>
            {data.filters.plan && (
              <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-semibold">
                Plan: {data.filters.plan}
              </span>
            )}
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-semibold">
              Aggregate only
            </span>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="border-b border-line px-5 py-3 text-xs text-err">
          {error}
        </p>
      )}

      {coupon && (
        <>
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              label="Redemption rate"
              value={pct(coupon.totals.redemption_rate_pct)}
              detail={`${formatNumber(coupon.totals.redemptions)} redeemed · ${formatNumber(coupon.totals.reservations)} reserved · ${formatNumber(coupon.totals.released)} released`}
            />
            <Kpi
              label="Paid conversion"
              value={pct(coupon.totals.conversion_pct)}
              detail={`${formatNumber(coupon.totals.paid_redemptions)} of ${formatNumber(coupon.totals.redemptions)} redemptions linked to a paid subscription`}
            />
            <Kpi
              label="Expired / reused"
              value={`${formatNumber(coupon.totals.expired_redemptions)} / ${formatNumber(coupon.totals.repeated_reservation_events)}`}
              detail="Redemptions after expiry · repeated reservations"
              tone={coupon.totals.expired_redemptions > 0 ? 'text-warn' : 'text-fg'}
            />
            <Kpi
              label="Capacity used"
              value={pct(coupon.totals.capacity_used_pct)}
              detail={`${formatNumber(coupon.totals.active_coupons)} active · ${formatNumber(coupon.totals.expired_coupons)} expired · ${formatNumber(coupon.totals.exhausted_coupons)} exhausted`}
            />
          </div>

          <div className="grid gap-4 border-t border-line p-4 xl:grid-cols-[1.35fr_1fr]">
            <div className="overflow-hidden rounded-[var(--radius-md)] border border-line">
              <div className="border-b border-line px-4 py-3">
                <h4 className="text-xs font-semibold text-fg">Coupon performance</h4>
                <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                  Segments with fewer than {data?.minimum_segment_size ?? 5} distinct users are suppressed.
                  Checkout codes are promotional identifiers, not account data.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse text-sm">
                  <caption className="sr-only">Coupon redemption and conversion by code</caption>
                  <thead>
                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                      <th scope="col" className="px-4 py-2.5 text-left font-semibold">Code</th>
                      <th scope="col" className="px-4 py-2.5 text-right font-semibold">Users</th>
                      <th scope="col" className="px-4 py-2.5 text-right font-semibold">Reserved</th>
                      <th scope="col" className="px-4 py-2.5 text-right font-semibold">Redeemed</th>
                      <th scope="col" className="px-4 py-2.5 text-right font-semibold">Paid</th>
                      <th scope="col" className="px-4 py-2.5 text-right font-semibold">Conversion</th>
                      <th scope="col" className="px-4 py-2.5 text-right font-semibold">Expired</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coupon.by_coupon.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="px-4 py-8 text-center text-sm text-fg-3">
                          No visible coupon activity. {formatNumber(coupon.suppressed_coupons)} small
                          segment(s) were suppressed.
                        </td>
                      </tr>
                    ) : (
                      coupon.by_coupon.map((row) => (
                        <tr key={row.coupon_id} className="border-t border-line">
                          <td className="px-4 py-2 text-xs font-semibold text-fg">
                            {row.code ?? 'Unattributed'}
                            {row.discount_percent != null && (
                              <span className="ml-2 text-[10px] font-normal text-fg-3">
                                {row.discount_percent}% off
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-right text-xs text-fg-2">
                            {formatNumber(row.distinct_users)}
                          </td>
                          <td className="px-4 py-2 text-right text-xs text-fg-2">
                            {formatNumber(row.reservations)}
                          </td>
                          <td className="px-4 py-2 text-right text-xs text-fg">
                            {formatNumber(row.redemptions)}
                          </td>
                          <td className="px-4 py-2 text-right text-xs text-fg">
                            {formatNumber(row.paid_redemptions)}
                          </td>
                          <td className="px-4 py-2 text-right text-xs text-fg-2">
                            {pct(row.conversion_pct)}
                          </td>
                          <td className="px-4 py-2 text-right text-xs text-fg-2">
                            {formatNumber(row.expired_redemptions)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="overflow-hidden rounded-[var(--radius-md)] border border-line">
              <div className="border-b border-line px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-xs font-semibold text-fg">Human-review queue</h4>
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                      coupon.reconciliation.balanced
                        ? 'border-ok/30 bg-ok/10 text-ok'
                        : 'border-err/30 bg-err/10 text-err'
                    }`}
                  >
                    {coupon.reconciliation.balanced ? 'Ledger balanced' : 'Ledger needs review'}
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                  Review flags are advisory. No account is blocked, refunded, downgraded or otherwise
                  punished automatically.
                </p>
              </div>
              <ReviewFlags flags={data?.review_flags ?? []} />
              {coupon.suppressed_review_flags > 0 && (
                <p className="border-t border-line px-5 py-3 text-[10px] text-fg-3">
                  {formatNumber(coupon.suppressed_review_flags)} small review group(s) were suppressed.
                </p>
              )}
              <ul className="divide-y divide-line border-t border-line">
                {coupon.reconciliation.checks.map((check) => (
                  <li key={check.key} className="flex items-start justify-between gap-3 px-5 py-2.5">
                    <div className="flex items-start gap-2">
                      <span
                        className={`mt-1 inline-block h-1.5 w-1.5 rounded-full ${check.ok ? 'bg-ok' : 'bg-err'}`}
                      />
                      <span className="text-[11px] text-fg-2">{check.label}</span>
                    </div>
                    <span className={`font-mono text-[10px] ${check.ok ? 'text-ok' : 'text-err'}`}>
                      Δ {formatNumber(check.difference)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}

      {student && student.applicable && (
        <div className="border-t border-line p-4">
          <div className="rounded-[var(--radius-md)] border border-line">
            <div className="border-b border-line px-4 py-3">
              <h4 className="text-xs font-semibold text-fg">Student request → verify → paid funnel</h4>
              <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                Distinct users with ordered first-party lifecycle events. Expired or reused verification
                links are review signals only; no automatic punishment is applied.
              </p>
            </div>
            <div className="grid gap-3 p-4 sm:grid-cols-3">
              {student.steps.map((step) => (
                <div key={step.key} className="rounded-[var(--radius-md)] border border-line bg-bg/40 p-3">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">
                      {step.label}
                    </p>
                    <p className="text-lg font-semibold text-fg">{formatNumber(step.count)}</p>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full bg-accent-strong"
                      style={{ width: `${Math.max(0, Math.min(100, (step.count / maxStep) * 100))}%` }}
                    />
                  </div>
                  <p className="mt-2 text-[10px] text-fg-3">
                    {pct(step.from_start)} of requests · {pct(step.from_previous)} from previous
                  </p>
                </div>
              ))}
            </div>
            <div className="grid gap-3 border-t border-line p-4 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi
                label="Request → verify"
                value={pct(student.conversion.requested_to_verified)}
                detail={`${formatNumber(student.verified_users)} of ${formatNumber(student.requested_users)} requested`}
              />
              <Kpi
                label="Verify → paid"
                value={pct(student.conversion.verified_to_paid)}
                detail={`${formatNumber(student.paid_users)} of ${formatNumber(student.verified_users)} verified`}
              />
              <Kpi
                label="Request → paid"
                value={pct(student.conversion.requested_to_paid)}
                detail="End-to-end conversion"
              />
              <Kpi
                label="Verification failures"
                value={formatNumber(student.failures.total_events)}
                detail={`${formatNumber(student.failures.distinct_users)} users · ${
                  student.failures.repeated_failure_users_suppressed
                    ? 'repeated users suppressed'
                    : `${formatNumber(student.failures.repeated_failure_users ?? 0)} repeated`
                }`}
                tone={student.failures.total_events > 0 ? 'text-warn' : 'text-fg'}
              />
            </div>
            <div className="flex flex-wrap gap-2 border-t border-line px-4 py-3">
              {student.failures.by_reason.length === 0 ? (
                <span className="text-[11px] text-fg-3">No verification failures in this range.</span>
              ) : (
                student.failures.by_reason.map((reason) => (
                  <span
                    key={reason.reason}
                    className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] text-fg-2"
                  >
                    {reason.label}: {formatNumber(reason.count)}
                  </span>
                ))
              )}
              {student.suppressed_segments > 0 && (
                <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] text-fg-3">
                  {formatNumber(student.suppressed_segments)} small plan segment(s) suppressed
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {data && (
        <p className="border-t border-line px-5 py-3 text-[10px] leading-relaxed text-fg-3">
          {data.notes[0]} {data.notes[2]}
        </p>
      )}
    </section>
  )
}
