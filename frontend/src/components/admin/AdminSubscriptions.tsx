'use client'

import { useEffect, useMemo, useState } from 'react'
import { apiClient, type AdminSubscriptionAnalyticsResponse } from '@/lib/api-client'
import {
    churnReasonLabel,
    cohortLabel,
    minorToMajor,
    movementDirectionLabel,
    movementLabel,
    planLabel,
    shareLabel,
    suppressedCohortNote,
} from '@/lib/subscription-analytics'
import { formatDateTime, formatMoney, formatNumber } from './admin-format'

const RANGES = [7, 30, 90] as const

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
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
                {label}
            </p>
            <p className={`mt-2 text-2xl font-semibold tracking-tight ${tone ?? 'text-fg'}`}>
                {value}
            </p>
            {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
        </div>
    )
}

function Section({
    id,
    title,
    description,
    children,
}: {
    id: string
    title: string
    description: string
    children: React.ReactNode
}) {
    return (
        <section
            id={id}
            className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface"
        >
            <div className="border-b border-line px-5 py-4">
                <h3 className="text-sm font-semibold text-fg">{title}</h3>
                <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">{description}</p>
            </div>
            {children}
        </section>
    )
}

function EmptyRow({ colSpan, message }: { colSpan: number; message: string }) {
    return (
        <tr>
            <td colSpan={colSpan} className="px-4 py-10 text-center text-sm text-fg-3">
                {message}
            </td>
        </tr>
    )
}

export default function AdminSubscriptions() {
    const [days, setDays] = useState<(typeof RANGES)[number]>(30)
    const [signupMonth, setSignupMonth] = useState('')
    const [signupFrom, setSignupFrom] = useState('')
    const [signupTo, setSignupTo] = useState('')
    const [plan, setPlan] = useState('')
    const [data, setData] = useState<AdminSubscriptionAnalyticsResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        let stale = false
        setLoading(true)
        setError(null)
        apiClient
            .getAdminSubscriptionAnalytics({
                days,
                signup_month: signupMonth || undefined,
                signup_from: signupFrom || undefined,
                signup_to: signupTo || undefined,
                plan: plan.trim() || undefined,
            })
            .then(fresh => {
                if (!stale) setData(fresh)
            })
            .catch((err: unknown) => {
                if (!stale) setError(err instanceof Error ? err.message : String(err))
            })
            .finally(() => {
                if (!stale) setLoading(false)
            })
        return () => {
            stale = true
        }
    }, [days, signupMonth, signupFrom, signupTo, plan])

    const planOptions = useMemo(() => {
        const values = new Set<string>()
        for (const row of data?.plan_mix ?? []) values.add(row.plan_id)
        for (const row of data?.movements ?? []) {
            values.add(row.from_plan)
            values.add(row.to_plan)
        }
        if (plan) values.add(plan)
        return [...values].sort()
    }, [data, plan])

    const summary = data?.summary
    const churnRate = summary?.churn_rate
    const reconciliation = data?.reconciliation

    return (
        <div className="space-y-4">
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div
                        role="group"
                        aria-label="Subscription analytics range"
                        className="flex gap-1 rounded-md border border-line bg-bg p-1"
                    >
                        {RANGES.map(value => (
                            <button
                                key={value}
                                type="button"
                                aria-pressed={days === value}
                                onClick={() => setDays(value)}
                                className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                                    days === value
                                        ? 'bg-accent-soft text-accent-strong'
                                        : 'text-fg-3 hover:text-fg'
                                }`}
                            >
                                {value}d
                            </button>
                        ))}
                    </div>
                    <label className="text-[11px] text-fg-2">
                        Signup cohort
                        <select
                            aria-label="Subscription signup cohort filter"
                            value={signupMonth}
                            onChange={event => {
                                setSignupMonth(event.target.value)
                                if (event.target.value) {
                                    setSignupFrom('')
                                    setSignupTo('')
                                }
                            }}
                            className="mt-1 block min-h-[38px] min-w-44 rounded-md border border-line bg-bg px-3 py-1.5 text-xs text-fg"
                        >
                            <option value="">All cohorts</option>
                            {(data?.available_signup_months ?? []).map(month => (
                                <option key={month.month} value={month.month}>
                                    {cohortLabel(month.month)} ({formatNumber(month.users)})
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Signed after
                        <input
                            type="date"
                            aria-label="Subscription signup start date"
                            value={signupFrom}
                            max={signupTo || undefined}
                            onChange={event => {
                                setSignupFrom(event.target.value)
                                if (event.target.value) setSignupMonth('')
                            }}
                            className="mt-1 block min-h-[38px] rounded-md border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Signed before
                        <input
                            type="date"
                            aria-label="Subscription signup end date"
                            value={signupTo}
                            min={signupFrom || undefined}
                            onChange={event => {
                                setSignupTo(event.target.value)
                                if (event.target.value) setSignupMonth('')
                            }}
                            className="mt-1 block min-h-[38px] rounded-md border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Current plan
                        <select
                            aria-label="Subscription plan filter"
                            value={plan}
                            onChange={event => setPlan(event.target.value)}
                            className="mt-1 block min-h-[38px] min-w-36 rounded-md border border-line bg-bg px-3 py-1.5 text-xs text-fg"
                        >
                            <option value="">All plans</option>
                            {planOptions.map(value => (
                                <option key={value} value={value}>
                                    {planLabel(value)}
                                </option>
                            ))}
                        </select>
                    </label>
                    <p role="status" className="ml-auto text-[11px] text-fg-3">
                        {data
                            ? `${data.filters.start} → ${data.filters.end} · UTC`
                            : 'Loading window…'}
                    </p>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-fg-3">
                    Plan movement and churn come from the append-only subscription ledger written in
                    the billing transaction. Provider webhook logs and PostHog events are never used
                    as financial sources. Amounts are minor units with an explicit currency; cohorts
                    below {data?.minimum_cohort_size ?? 5} subscribers are omitted.
                </p>
            </div>

            {loading && !data ? (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {Array.from({ length: 4 }).map((_, index) => (
                        <div
                            key={index}
                            className="h-28 animate-pulse rounded-[var(--radius-lg)] border border-line bg-surface"
                        />
                    ))}
                </div>
            ) : error ? (
                <div
                    role="alert"
                    className="rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.06] px-5 py-4"
                >
                    <p className="text-sm font-medium text-err">
                        Subscription analytics unavailable
                    </p>
                    <p className="mt-1 text-xs text-err/70">{error}</p>
                </div>
            ) : !data ? null : data.suppressed ? (
                <div
                    role="status"
                    className="rounded-[var(--radius-lg)] border border-line bg-surface px-6 py-12 text-center"
                >
                    <p className="text-sm font-medium text-fg-2">Cohort suppressed</p>
                    <p className="mt-1 text-xs text-fg-3">
                        This signup cohort has fewer than {data.minimum_cohort_size} subscribers.
                        Counts, plan mix and churn are hidden to prevent re-identification.
                    </p>
                </div>
            ) : (
                <>
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <Kpi
                            label="Active at period end"
                            value={formatNumber(summary?.active_at_end)}
                            detail={`${formatNumber(summary?.active_at_start)} at start · ${formatNumber(summary?.new_paid)} new paid`}
                        />
                        <Kpi
                            label="Plan movements"
                            value={formatNumber(summary?.movement_total)}
                            detail={`${formatNumber(summary?.upgrades)} upgrades · ${formatNumber(summary?.downgrades)} downgrades · ${formatNumber(summary?.lateral_moves)} lateral`}
                        />
                        <Kpi
                            label="Churn"
                            value={formatNumber(summary?.churn_count)}
                            detail={
                                churnRate == null
                                    ? `Rate hidden below ${data.minimum_cohort_size} active at start`
                                    : `${churnRate.toFixed(2)}% of active-at-start subscriptions`
                            }
                            tone={summary?.churn_count ? 'text-warn' : undefined}
                        />
                        <Kpi
                            label="Cancellations"
                            value={formatNumber(summary?.cancellations)}
                            detail={`${formatNumber(summary?.cancellation_scheduled)} scheduled · ${formatNumber(summary?.expired)} expired · ${formatNumber(summary?.payment_failed)} failed`}
                        />
                    </div>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <Section
                            id="admin-subscriptions-plan-mix"
                            title="Plan mix at period end"
                            description={`Active subscriptions grouped by plan. MRR is a catalog-based estimate in ${data.currency} minor units (${data.minor_unit}); discounts and taxes are not inferred.`}
                        >
                            <div className="overflow-x-auto">
                                <table className="w-full min-w-[520px] border-collapse text-sm">
                                    <caption className="sr-only">Plan mix at period end</caption>
                                    <thead>
                                        <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-left font-semibold"
                                            >
                                                Plan
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-right font-semibold"
                                            >
                                                Subscriptions
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-right font-semibold"
                                            >
                                                Users
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-right font-semibold"
                                            >
                                                Share
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-right font-semibold"
                                            >
                                                MRR ({data.currency})
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.plan_mix.length === 0 && (
                                            <EmptyRow
                                                colSpan={5}
                                                message="No active subscriptions in this window."
                                            />
                                        )}
                                        {data.plan_mix.map(row => (
                                            <tr key={row.plan_id} className="border-t border-line">
                                                <td className="px-4 py-2.5 text-xs text-fg">
                                                    {planLabel(row.plan_id)}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-xs text-fg">
                                                    {formatNumber(row.subscriptions)}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                    {formatNumber(row.users)}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                    {shareLabel(row.share_pct)}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-xs text-fg">
                                                    {formatMoney(
                                                        minorToMajor(row.mrr_minor),
                                                        row.currency || data.currency
                                                    )}
                                                    <span className="ml-1 text-[10px] text-fg-3">
                                                        ({formatNumber(row.mrr_minor)} minor)
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </Section>

                        <Section
                            id="admin-subscriptions-movements"
                            title="Plan movements"
                            description="Upgrades and downgrades are ordered by configured monthly-equivalent plan price. A same-price move is lateral. Each row counts distinct users with a recorded transition in the window."
                        >
                            <div className="overflow-x-auto">
                                <table className="w-full min-w-[420px] border-collapse text-sm">
                                    <caption className="sr-only">
                                        Plan upgrades, downgrades and lateral movements
                                    </caption>
                                    <thead>
                                        <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-left font-semibold"
                                            >
                                                Direction
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-left font-semibold"
                                            >
                                                Movement
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-right font-semibold"
                                            >
                                                Users
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.movements.length === 0 && (
                                            <EmptyRow
                                                colSpan={3}
                                                message="No plan movements in this window."
                                            />
                                        )}
                                        {data.movements.map(row => (
                                            <tr
                                                key={`${row.direction}:${row.from_plan}:${row.to_plan}`}
                                                className="border-t border-line"
                                            >
                                                <td className="px-4 py-2.5 text-xs">
                                                    <span
                                                        className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                                                            row.direction === 'upgrade'
                                                                ? 'border-ok/30 bg-ok/10 text-ok'
                                                                : row.direction === 'downgrade'
                                                                  ? 'border-warn/30 bg-warn/10 text-warn'
                                                                  : 'border-line bg-surface-2 text-fg-3'
                                                        }`}
                                                    >
                                                        {movementDirectionLabel(row.direction)}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-2.5 text-xs text-fg">
                                                    {movementLabel(
                                                        planLabel(row.from_plan),
                                                        planLabel(row.to_plan)
                                                    )}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-xs text-fg">
                                                    {formatNumber(row.users)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </Section>
                    </div>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <Section
                            id="admin-subscriptions-churn"
                            title="Cancellation and churn signals"
                            description="Terminal cancellations, expiries, payment failures and refunds are counted from the ledger. Churn is a subscription that was active at the start and is terminal at the end."
                        >
                            <div className="overflow-x-auto">
                                <table className="w-full min-w-[360px] border-collapse text-sm">
                                    <caption className="sr-only">
                                        Cancellation, expiry and payment-failure counts
                                    </caption>
                                    <thead>
                                        <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-left font-semibold"
                                            >
                                                Reason
                                            </th>
                                            <th
                                                scope="col"
                                                className="px-4 py-2.5 text-right font-semibold"
                                            >
                                                Subscriptions
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.churn.map(row => (
                                            <tr key={row.reason} className="border-t border-line">
                                                <td className="px-4 py-2.5 text-xs text-fg-2">
                                                    {churnReasonLabel(row.reason)}
                                                </td>
                                                <td className="px-4 py-2.5 text-right text-xs text-fg">
                                                    {formatNumber(row.count)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </Section>

                        <Section
                            id="admin-subscriptions-reconciliation"
                            title="Reconciliation"
                            description="Aggregate checks prove the visible plan mix, movement and churn reconcile to the ledger and current subscription state. No per-user records are returned."
                        >
                            <ul className="divide-y divide-line">
                                {reconciliation?.checks.map(check => (
                                    <li
                                        key={check.key}
                                        className="flex items-start justify-between gap-3 px-5 py-3"
                                    >
                                        <div>
                                            <p className="text-xs font-medium text-fg">
                                                {check.label}
                                            </p>
                                            <p className="mt-0.5 text-[11px] text-fg-3">
                                                {check.detail}
                                            </p>
                                        </div>
                                        <span
                                            className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                                                check.ok
                                                    ? 'border-ok/30 bg-ok/10 text-ok'
                                                    : 'border-err/30 bg-err/10 text-err'
                                            }`}
                                        >
                                            {check.ok ? 'OK' : 'Review'}
                                        </span>
                                    </li>
                                ))}
                                {reconciliation && (
                                    <li className="px-5 py-3 text-[11px] text-fg-3">
                                        {formatNumber(reconciliation.history_rows)} transitions ·{' '}
                                        {formatNumber(reconciliation.backfill_rows)} backfill
                                        snapshots excluded ·{' '}
                                        {formatNumber(reconciliation.current_active_subscriptions)}{' '}
                                        active subscriptions now
                                    </li>
                                )}
                            </ul>
                        </Section>
                    </div>

                    <Section
                        id="admin-subscriptions-cohorts"
                        title="Movement and churn by signup cohort"
                        description={`Monthly signup cohorts. Cohorts below ${data.minimum_cohort_size} subscribers are omitted entirely; the suppression count is shown below.`}
                    >
                        <div className="overflow-x-auto">
                            <table className="w-full min-w-[820px] border-collapse text-sm">
                                <caption className="sr-only">
                                    Plan movement and churn by signup cohort
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-left font-semibold"
                                        >
                                            Cohort
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Users
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Active start
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Active end
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Upgrades
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Downgrades
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Cancellations
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Churn
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-right font-semibold"
                                        >
                                            Churn rate
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-4 py-2.5 text-left font-semibold"
                                        >
                                            Plan mix (end)
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.cohorts.length === 0 && (
                                        <EmptyRow
                                            colSpan={10}
                                            message="No signup cohort has at least five subscribers in this window."
                                        />
                                    )}
                                    {data.cohorts.map(row => (
                                        <tr key={row.cohort} className="border-t border-line">
                                            <td className="px-4 py-2.5 text-xs text-fg">
                                                {cohortLabel(row.cohort)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.users)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.active_at_start)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.active_at_end)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-ok">
                                                {formatNumber(row.upgrades)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-warn">
                                                {formatNumber(row.downgrades)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.cancellations)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-fg">
                                                {formatNumber(row.churn_count)}
                                            </td>
                                            <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                                {row.churn_rate == null
                                                    ? '—'
                                                    : `${row.churn_rate.toFixed(2)}%`}
                                            </td>
                                            <td className="px-4 py-2.5 text-xs text-fg-3">
                                                {row.plan_mix.length === 0
                                                    ? '—'
                                                    : row.plan_mix
                                                          .map(
                                                              plan =>
                                                                  `${planLabel(plan.plan_id)} ${formatNumber(plan.subscriptions)}`
                                                          )
                                                          .join(' · ')}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        {data.suppressed_cohorts > 0 && (
                            <p
                                role="status"
                                className="border-t border-line px-5 py-3 text-[11px] text-fg-3"
                            >
                                {suppressedCohortNote(
                                    data.minimum_cohort_size,
                                    data.suppressed_cohorts
                                )}
                            </p>
                        )}
                        <p className="border-t border-line px-5 py-3 text-[11px] text-fg-3">
                            Generated {formatDateTime(data.generated_at)} · {data.filters.timezone}{' '}
                            · minimum cohort {data.minimum_cohort_size} subscribers.
                        </p>
                    </Section>
                </>
            )}
        </div>
    )
}
