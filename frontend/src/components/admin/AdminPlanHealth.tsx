'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminPlanHealthMetric,
    type AdminPlanHealthResponse,
    type AdminPlanHealthRiskFlag,
} from '@/lib/api-client'
import { formatDateTime, formatMoney, formatNumber } from './admin-format'

const WINDOWS = [7, 30, 90] as const
const PLAN_ORDER = ['weekly', 'lifetime'] as const

function rate(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)}%`
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">
                {label}
            </p>
            <p className="mt-1 text-xl font-semibold text-fg">{value}</p>
            {detail && <p className="mt-0.5 text-[10px] text-fg-3">{detail}</p>}
        </div>
    )
}

const SEVERITY_TONE: Record<AdminPlanHealthRiskFlag['severity'], string> = {
    critical: 'border-err/30 bg-err/10 text-err',
    high: 'border-err/20 bg-err/[0.06] text-err',
    medium: 'border-warn/30 bg-warn/10 text-warn',
    low: 'border-line bg-surface-2/40 text-fg-2',
}

function PlanSummary({
    plan,
    data,
}: {
    plan: AdminPlanHealthMetric
    data: AdminPlanHealthResponse
}) {
    const label = plan.plan_id === 'weekly' ? 'Weekly' : 'Lifetime'
    const currency = plan.revenue.currency || data.currency

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
                <div>
                    <h4 className="text-xs font-semibold text-fg">{label} plan</h4>
                    <p className="mt-0.5 text-[10px] text-fg-3">
                        {plan.plan_id === 'weekly'
                            ? 'Recurring weekly subscriptions, renewals and churn.'
                            : 'One-time lifetime purchases, refunded access and retention.'}
                    </p>
                </div>
                <span className="text-[10px] text-fg-3">
                    {formatNumber(plan.revenue.payments_count)} settled payment
                    {plan.revenue.payments_count === 1 ? '' : 's'} in window
                </span>
            </div>
            <div className="grid gap-3 px-4 py-3 sm:grid-cols-2 xl:grid-cols-4">
                <Metric
                    label="Active"
                    value={formatNumber(plan.active_subscriptions)}
                    detail={`${formatNumber(plan.past_due_subscriptions)} past due / on hold`}
                />
                <Metric
                    label="New"
                    value={formatNumber(plan.new_subscriptions)}
                    detail={`${formatNumber(plan.cancelled_subscriptions)} cancelled in window`}
                />
                <Metric
                    label="Gross revenue"
                    value={formatMoney(plan.revenue.gross, currency)}
                    detail={`${formatMoney(plan.revenue.net, currency)} net of refunds`}
                />
                <Metric
                    label="Refunds"
                    value={formatNumber(plan.refunds.count)}
                    detail={`${formatMoney(plan.refunds.amount, currency)} · ${rate(
                        plan.refunds.amount_rate_pct
                    )} of gross`}
                />
                <Metric
                    label="Chargebacks"
                    value={formatNumber(plan.chargebacks.count)}
                    detail={`${formatNumber(plan.chargebacks.open_count)} open · ${formatMoney(
                        plan.chargebacks.amount,
                        currency
                    )}`}
                />
                {plan.plan_id === 'weekly' ? (
                    <>
                        <Metric
                            label="Renewals"
                            value={formatNumber(plan.renewal.renewals)}
                            detail={`${formatNumber(plan.renewal.cancellations)} cancellations`}
                        />
                        <Metric
                            label="Renewal rate"
                            value={rate(plan.renewal.renewal_rate_pct)}
                            detail="Renewals ÷ renewal decisions"
                        />
                        <Metric
                            label="Churn"
                            value={rate(plan.renewal.churn_rate_pct)}
                            detail="Cancellations ÷ (active + cancellations)"
                        />
                    </>
                ) : (
                    <>
                        <Metric
                            label="Lifetime sales"
                            value={formatNumber(plan.lifetime_sales)}
                            detail="Settled lifetime purchases"
                        />
                        <Metric
                            label="Refunded lifetime"
                            value={formatNumber(plan.lifetime_refunds)}
                            detail="Full refunds revoke access"
                        />
                        <Metric
                            label="Lifetime refund rate"
                            value={rate(plan.lifetime_refund_rate_pct)}
                            detail="Refunded ÷ settled lifetime sales"
                        />
                    </>
                )}
                <Metric
                    label="Cohort retention"
                    value={rate(plan.retention.retention_pct)}
                    detail={`${formatNumber(
                        plan.retention.retained_subscriptions
                    )} of ${formatNumber(plan.retention.tracked_subscriptions)} tracked`}
                />
            </div>
            <div className="border-t border-line px-4 py-3">
                <h5 className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    Monthly cohort retention
                </h5>
                <p className="mt-1 text-[10px] text-fg-3">
                    Cohorts with fewer than {plan.retention.minimum_cohort_size} distinct users are
                    suppressed. {formatNumber(plan.retention.suppressed_cohorts)} cohort
                    {plan.retention.suppressed_cohorts === 1 ? '' : 's'} withheld in the last{' '}
                    {plan.retention.months} months.
                </p>
                <div className="mt-2 overflow-x-auto rounded-md border border-line">
                    <table className="w-full min-w-[560px] border-collapse text-xs">
                        <caption className="sr-only">
                            {label} monthly signup cohort retention
                        </caption>
                        <thead>
                            <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                <th scope="col" className="px-3 py-2 text-left font-semibold">
                                    Cohort
                                </th>
                                <th scope="col" className="px-3 py-2 text-right font-semibold">
                                    Users
                                </th>
                                <th scope="col" className="px-3 py-2 text-right font-semibold">
                                    Subscriptions
                                </th>
                                <th scope="col" className="px-3 py-2 text-right font-semibold">
                                    Active now
                                </th>
                                <th scope="col" className="px-3 py-2 text-right font-semibold">
                                    Retained
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {plan.retention.cohorts.map(cohort => (
                                <tr key={cohort.cohort} className="border-t border-line">
                                    <th
                                        scope="row"
                                        className="px-3 py-1.5 text-left font-medium text-fg-2"
                                    >
                                        {cohort.cohort}
                                    </th>
                                    <td className="px-3 py-1.5 text-right text-fg">
                                        {formatNumber(cohort.users)}
                                    </td>
                                    <td className="px-3 py-1.5 text-right text-fg">
                                        {formatNumber(cohort.subscriptions)}
                                    </td>
                                    <td className="px-3 py-1.5 text-right text-fg">
                                        {formatNumber(cohort.active_subscriptions)}
                                    </td>
                                    <td className="px-3 py-1.5 text-right text-fg">
                                        {rate(cohort.retained_pct)}
                                    </td>
                                </tr>
                            ))}
                            {plan.retention.cohorts.length === 0 && (
                                <tr>
                                    <td colSpan={5} className="px-3 py-5 text-center text-fg-3">
                                        No publishable cohort in the last{' '}
                                        {plan.retention.months} months.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    )
}

function RiskFlags({ flags }: { flags: AdminPlanHealthRiskFlag[] }) {
    return (
        <div>
            <h4 className="text-xs font-semibold text-fg">Advisory risk flags</h4>
            <p className="mt-1 text-[10px] text-fg-3">
                Every flag requires human review. Opening a flag does not refund, downgrade,
                cancel or grant anything automatically.
            </p>
            {flags.length === 0 ? (
                <p className="mt-2 rounded-md border border-line bg-surface-2/30 px-3 py-2 text-[11px] text-fg-3">
                    No advisory threshold is currently crossed.
                </p>
            ) : (
                <ul className="mt-2 space-y-2">
                    {flags.map(flag => (
                        <li
                            key={`${flag.plan_id}.${flag.code}`}
                            className={`rounded-md border px-3 py-2 ${SEVERITY_TONE[flag.severity]}`}
                        >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <span className="text-[11px] font-semibold">
                                    {flag.plan_id} · {flag.title}
                                </span>
                                <span className="text-[10px] uppercase tracking-wide">
                                    {flag.severity} · review required
                                </span>
                            </div>
                            <p className="mt-1 text-[10px] leading-relaxed opacity-90">
                                {flag.detail}
                            </p>
                            <p className="mt-1 text-[10px] opacity-80">
                                {flag.metric}: {formatNumber(flag.value)} (threshold{' '}
                                {formatNumber(flag.threshold)}) · sample{' '}
                                {formatNumber(flag.sample_size)} · auto action: none
                            </p>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

export default function AdminPlanHealth() {
    const [days, setDays] = useState<number>(30)
    const [data, setData] = useState<AdminPlanHealthResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const requestId = useRef(0)

    const load = useCallback(async () => {
        const id = ++requestId.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminPlanHealth(days)
            if (requestId.current === id) setData(next)
        } catch (err) {
            if (requestId.current === id) {
                setError(err instanceof Error ? err.message : 'Failed to load plan health.')
            }
        } finally {
            if (requestId.current === id) setLoading(false)
        }
    }, [days])

    useEffect(() => {
        void load()
    }, [load])

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Weekly and lifetime plan health</h3>
                    <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-fg-3">
                        Active, new, cancelled, refunded and chargeback counts for weekly and
                        lifetime plans, with revenue, refund rate, renewal/churn and monthly
                        cohort retention. Counts reconcile to subscriptions and payments. Flags
                        are advisory only; they never trigger an automatic refund, downgrade,
                        cancellation or grant. No customer identifiers are returned.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Plan health period"
                    >
                        {WINDOWS.map(value => (
                            <button
                                key={value}
                                type="button"
                                aria-pressed={days === value}
                                onClick={() => setDays(value)}
                                className={`rounded px-2.5 py-1 text-[10px] font-medium ${
                                    days === value
                                        ? 'bg-accent-soft text-accent-strong'
                                        : 'text-fg-3 hover:text-fg'
                                }`}
                            >
                                {value} days
                            </button>
                        ))}
                    </div>
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                    >
                        Refresh
                    </button>
                </div>
            </div>

            {error && (
                <p
                    role="alert"
                    className="mx-5 mt-4 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
                >
                    {error}
                </p>
            )}

            {data ? (
                <div className="space-y-5 px-5 py-4">
                    <div className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-[10px] leading-relaxed text-warn">
                        <span className="font-semibold">Advisory only. </span>
                        Human review is required before acting on any flag. This view does not
                        refund, downgrade, cancel or grant access automatically.
                    </div>

                    <div className="grid gap-4 xl:grid-cols-2">
                        {PLAN_ORDER.map(planId => (
                            <PlanSummary key={planId} plan={data.plans[planId]} data={data} />
                        ))}
                    </div>

                    <RiskFlags flags={data.risk_flags} />

                    <div className="rounded-md border border-line bg-surface-2/30 px-3 py-2 text-[10px] leading-relaxed text-fg-3">
                        <span className="font-semibold text-fg-2">Reconciliation: </span>
                        {data.reconciliation.balanced ? 'balanced' : 'review differences'} ·{' '}
                        {formatNumber(data.reconciliation.scanned_subscriptions)} subscriptions,{' '}
                        {formatNumber(data.reconciliation.scanned_payments)} payments and{' '}
                        {formatNumber(data.reconciliation.scanned_refunds)} refunds scanned
                        {data.reconciliation.rows_truncated
                            ? ' (row cap reached; detail is partial)'
                            : ''}
                        . {formatNumber(data.reconciliation.unlinked_chargebacks)} dispute event
                        {data.reconciliation.unlinked_chargebacks === 1 ? '' : 's'} could not be
                        linked to a weekly or lifetime plan. Minimum cohort:{' '}
                        {formatNumber(data.minimum_cohort_size)} users.
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[10px] text-fg-3">
                        <span>
                            {formatDateTime(data.window_start)} → {formatDateTime(data.window_end)}
                        </span>
                        <span>Generated {formatDateTime(data.generated_at)}</span>
                    </div>

                    <ul className="space-y-1 text-[10px] text-fg-3">
                        {data.notes.map(note => (
                            <li key={note}>• {note}</li>
                        ))}
                    </ul>
                </div>
            ) : (
                !error && (
                    <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
                        Loading weekly and lifetime plan health…
                    </div>
                )
            )}
        </section>
    )
}
