'use client'

import { useEffect, useMemo, useState } from 'react'
import {
    apiClient,
    type AdminDunningBreakdownRow,
    type AdminDunningRecoveryResponse,
} from '@/lib/api-client'
import { cohortLabel, planLabel, suppressedCohortNote } from '@/lib/subscription-analytics'
import { formatDateTime, formatNumber } from './admin-format'

const RANGES = [7, 30, 90] as const
const MINIMUM_GROUP_SIZE = 5

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

function formatDuration(seconds: number | null | undefined): string {
    if (seconds == null || !Number.isFinite(seconds)) return '—'
    if (seconds < 3600) return `${Math.max(0, Math.round(seconds / 60))}m`
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
    return `${(seconds / 86400).toFixed(1)}d`
}

function rateLabel(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '—'
    return `${value.toFixed(2)}%`
}

function BreakdownTable({
    rows,
    kind,
}: {
    rows: AdminDunningBreakdownRow[]
    kind: 'plan' | 'cohort'
}) {
    const label = kind === 'plan' ? 'Plan' : 'Signup cohort'
    return (
        <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-sm">
                <caption className="sr-only">
                    Dunning recovery by {kind === 'plan' ? 'plan' : 'signup cohort'}
                </caption>
                <thead>
                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                            {label}
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Users
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Open now
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Cases
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Recovered
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Cancelled
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Recovery rate
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Median to active
                        </th>
                        <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                            Median to cancel
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={9} className="px-4 py-10 text-center text-sm text-fg-3">
                                No dunning cases in this window.
                            </td>
                        </tr>
                    )}
                    {rows.map(row => {
                        const key =
                            kind === 'plan'
                                ? row.plan_id ?? 'unknown'
                                : row.cohort ?? 'unknown'
                        return (
                            <tr key={key} className="border-t border-line">
                                <td className="px-4 py-2.5 text-xs text-fg">
                                    {kind === 'plan' ? planLabel(key) : cohortLabel(key)}
                                    {row.suppressed && (
                                        <span className="ml-2 rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] uppercase tracking-wide text-fg-3">
                                            Suppressed
                                        </span>
                                    )}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                    {formatNumber(row.users)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                    {formatNumber(row.open_now)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-fg">
                                    {row.dunning_cases == null
                                        ? '—'
                                        : formatNumber(row.dunning_cases)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-ok">
                                    {row.recovered == null
                                        ? '—'
                                        : formatNumber(row.recovered)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-warn">
                                    {row.cancelled == null
                                        ? '—'
                                        : formatNumber(row.cancelled)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                    {rateLabel(row.recovery_rate)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                    {formatDuration(row.median_time_to_active_seconds)}
                                </td>
                                <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                    {formatDuration(row.median_time_to_cancel_seconds)}
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminDunningRecovery() {
    const [days, setDays] = useState<(typeof RANGES)[number]>(30)
    const [start, setStart] = useState('')
    const [end, setEnd] = useState('')
    const [signupMonth, setSignupMonth] = useState('')
    const [signupFrom, setSignupFrom] = useState('')
    const [signupTo, setSignupTo] = useState('')
    const [plan, setPlan] = useState('')
    const [data, setData] = useState<AdminDunningRecoveryResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        let stale = false
        setLoading(true)
        setError(null)
        apiClient
            .getAdminDunningRecovery({
                days,
                start: start ? `${start}T00:00:00Z` : undefined,
                end: end ? `${end}T23:59:59Z` : undefined,
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
    }, [days, start, end, signupMonth, signupFrom, signupTo, plan])

    const planOptions = useMemo(() => {
        const values = new Set<string>()
        for (const row of data?.by_plan ?? []) {
            if (row.plan_id) values.add(row.plan_id)
        }
        if (plan) values.add(plan)
        return [...values].sort()
    }, [data, plan])

    const summary = data?.summary
    const advisory = data?.advisory
    const reconciliation = data?.reconciliation

    return (
        <div id="admin-dunning-recovery" className="space-y-4">
            <div>
                <h2 className="text-sm font-semibold text-fg">Dunning recovery needs review</h2>
                <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                    Past-due and on-hold recovery from the append-only status ledger. This section
                    is advisory only: it never downgrades, refunds or changes access.
                </p>
            </div>
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
                <div className="flex flex-wrap items-end gap-3">
                    <div
                        role="group"
                        aria-label="Dunning recovery range"
                        className="flex gap-1 rounded-md border border-line bg-bg p-1"
                    >
                        {RANGES.map(value => (
                            <button
                                key={value}
                                type="button"
                                aria-pressed={days === value}
                                onClick={() => {
                                    setDays(value)
                                    setStart('')
                                    setEnd('')
                                }}
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
                        From date
                        <input
                            type="date"
                            aria-label="Dunning event start date"
                            value={start}
                            max={end || undefined}
                            onChange={event => setStart(event.target.value)}
                            className="mt-1 block min-h-[38px] rounded-md border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        To date
                        <input
                            type="date"
                            aria-label="Dunning event end date"
                            value={end}
                            min={start || undefined}
                            onChange={event => setEnd(event.target.value)}
                            className="mt-1 block min-h-[38px] rounded-md border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                        />
                    </label>
                    <label className="text-[11px] text-fg-2">
                        Signup cohort
                        <select
                            aria-label="Dunning signup cohort filter"
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
                            aria-label="Dunning signup start date"
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
                            aria-label="Dunning signup end date"
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
                        Plan
                        <select
                            aria-label="Dunning plan filter"
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
                            ? `${data.filters.start} → ${data.filters.end} · ${data.filters.timezone}`
                            : 'Loading window…'}
                    </p>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-fg-3">
                    Dunning history is append-only and written in the billing transaction. Provider
                    event time controls ordering; duplicate deliveries are ignored and older events
                    are marked as not applied. Plan and cohort slices below{' '}
                    {data?.minimum_cohort_size ?? MINIMUM_GROUP_SIZE} users are suppressed. This
                    view is read-only: it never downgrades, refunds or changes access.
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
                    <p className="text-sm font-medium text-err">Dunning recovery unavailable</p>
                    <p className="mt-1 text-xs text-err/70">{error}</p>
                </div>
            ) : !data ? null : (
                <>
                    <div
                        role={advisory?.active ? 'alert' : 'status'}
                        className={`rounded-[var(--radius-lg)] border px-5 py-4 ${
                            advisory?.active
                                ? advisory.severity === 'high'
                                    ? 'border-err/30 bg-err/[0.06]'
                                    : 'border-warn/30 bg-warn/[0.06]'
                                : 'border-line bg-surface'
                        }`}
                    >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <p
                                    className={`text-sm font-semibold ${
                                        advisory?.active
                                            ? advisory.severity === 'high'
                                                ? 'text-err'
                                                : 'text-warn'
                                            : 'text-fg'
                                    }`}
                                >
                                    {advisory?.title ?? 'Dunning recovery'}
                                </p>
                                <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-2">
                                    {advisory?.message}
                                </p>
                                <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-fg-3">
                                    {advisory?.recommended_action}
                                </p>
                            </div>
                            <span
                                className={`shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
                                    advisory?.active
                                        ? advisory.severity === 'high'
                                            ? 'border-err/30 bg-err/10 text-err'
                                            : 'border-warn/30 bg-warn/10 text-warn'
                                        : 'border-ok/30 bg-ok/10 text-ok'
                                }`}
                            >
                                {advisory?.active ? 'Advisory' : 'Clear'}
                            </span>
                        </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                        <Kpi
                            label="Past due"
                            value={formatNumber(summary?.past_due)}
                            detail={`${formatNumber(summary?.paused)} paused · ${formatNumber(summary?.open_now)} open now`}
                            tone={summary?.past_due ? 'text-warn' : undefined}
                        />
                        <Kpi
                            label="On hold"
                            value={formatNumber(summary?.on_hold)}
                            detail={`${formatNumber(summary?.open_now_users)} distinct users`}
                            tone={summary?.on_hold ? 'text-warn' : undefined}
                        />
                        <Kpi
                            label="Recovery rate"
                            value={rateLabel(summary?.recovery_rate)}
                            detail={`${formatNumber(summary?.recovered)} recovered · ${formatNumber(summary?.dunning_cases)} cases`}
                            tone={
                                summary?.recovery_rate != null && summary.recovery_rate < 50
                                    ? 'text-warn'
                                    : undefined
                            }
                        />
                        <Kpi
                            label="Median time to active"
                            value={formatDuration(summary?.median_time_to_active_seconds)}
                            detail={`${formatNumber(summary?.recovered_to_active)} recovered to active`}
                        />
                        <Kpi
                            label="Median time to cancel"
                            value={formatDuration(summary?.median_time_to_cancel_seconds)}
                            detail={`${formatNumber(summary?.cancelled)} cancelled or expired`}
                        />
                    </div>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <Section
                            id="admin-dunning-by-plan"
                            title="Recovery by plan"
                            description="Past-due, on-hold and recovery outcomes grouped by the plan observed in the status ledger. Cells with fewer than five users are suppressed."
                        >
                            <BreakdownTable rows={data.by_plan} kind="plan" />
                        </Section>
                        <Section
                            id="admin-dunning-by-cohort"
                            title="Recovery by signup cohort"
                            description="Monthly signup cohorts. A cohort with fewer than five users is hidden rather than emitted with masked counts."
                        >
                            <BreakdownTable rows={data.cohorts} kind="cohort" />
                            {data.suppressed_groups > 0 && (
                                <p
                                    role="status"
                                    className="border-t border-line px-5 py-3 text-[11px] text-fg-3"
                                >
                                    {suppressedCohortNote(
                                        data.minimum_cohort_size,
                                        data.suppressed_groups
                                    )}
                                </p>
                            )}
                        </Section>
                    </div>

                    <div className="grid gap-4 xl:grid-cols-2">
                        <Section
                            id="admin-dunning-reconciliation"
                            title="Recovery reconciliation"
                            description="Aggregate checks prove outcomes, plan buckets and cohort buckets reconcile to the same append-only ledger. No per-user records are returned."
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
                                        {formatNumber(reconciliation.history_rows)} status rows ·{' '}
                                        {formatNumber(reconciliation.current_open)} current open ·{' '}
                                        {formatNumber(reconciliation.by_plan_cases)} plan cases ·{' '}
                                        {formatNumber(reconciliation.cohort_cases)} cohort cases
                                    </li>
                                )}
                            </ul>
                        </Section>

                        <Section
                            id="admin-dunning-guardrails"
                            title="Recovery guardrails"
                            description="Dunning reporting is advisory. Any manual action remains in the existing audited admin surfaces and is never performed by this view."
                        >
                            <ul className="divide-y divide-line text-xs">
                                <li className="flex items-center justify-between px-5 py-3">
                                    <span className="text-fg-2">Automatic downgrade</span>
                                    <span className="rounded-full border border-ok/30 bg-ok/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ok">
                                        {data.guardrails.automatic_downgrade ? 'Enabled' : 'Never'}
                                    </span>
                                </li>
                                <li className="flex items-center justify-between px-5 py-3">
                                    <span className="text-fg-2">Automatic refund</span>
                                    <span className="rounded-full border border-ok/30 bg-ok/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ok">
                                        {data.guardrails.automatic_refund ? 'Enabled' : 'Never'}
                                    </span>
                                </li>
                                <li className="flex items-center justify-between px-5 py-3">
                                    <span className="text-fg-2">Provider ordering</span>
                                    <span className="text-fg-3">
                                        {data.guardrails.provider_order}
                                    </span>
                                </li>
                                <li className="flex items-center justify-between px-5 py-3">
                                    <span className="text-fg-2">Manual actions</span>
                                    <span className="text-fg-3">{data.guardrails.manual_actions}</span>
                                </li>
                            </ul>
                            <p className="border-t border-line px-5 py-3 text-[11px] text-fg-3">
                                Generated {formatDateTime(data.generated_at)} · minimum group{' '}
                                {data.minimum_cohort_size} users · no document, email, token or
                                provider payload is read by this report.
                            </p>
                        </Section>
                    </div>
                </>
            )}
        </div>
    )
}
