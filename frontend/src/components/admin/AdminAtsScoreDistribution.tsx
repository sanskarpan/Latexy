'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminAtsScoreDistributionMetrics,
    type AdminAtsScoreDistributionResponse,
} from '@/lib/api-client'
import { formatNumber } from '@/components/admin/admin-format'

const RANGES = [
    { days: 7, label: '7d' },
    { days: 30, label: '30d' },
    { days: 90, label: '90d' },
    { days: 365, label: '365d' },
] as const

const PLAN_OPTIONS = [
    { value: '', label: 'All plans' },
    { value: 'free', label: 'Free' },
    { value: 'basic', label: 'Basic' },
    { value: 'pro', label: 'Pro' },
    { value: 'byok', label: 'BYOK' },
    { value: 'team', label: 'Team' },
] as const

type Dimension = 'industry' | 'profile' | 'plan'

type BreakdownRow = AdminAtsScoreDistributionMetrics & {
    industry?: string
    profile?: string
    plan?: string
}

const DIMENSIONS: Array<{ key: Dimension; label: string }> = [
    { key: 'industry', label: 'Industry' },
    { key: 'profile', label: 'Profile' },
    { key: 'plan', label: 'Plan' },
]

function formatPct(value: number | null | undefined): string {
    return `${(Number.isFinite(value) ? Number(value) : 0).toFixed(2)}%`
}

function formatScore(value: number | null | undefined): string {
    return value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(1)
}

function formatDelta(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(Number(value))) return '—'
    const number = Number(value)
    return `${number > 0 ? '+' : ''}${number.toFixed(1)}`
}

function dimensionRows(
    data: AdminAtsScoreDistributionResponse,
    dimension: Dimension,
): BreakdownRow[] {
    switch (dimension) {
        case 'profile':
            return data.by_profile
        case 'plan':
            return data.by_plan
        default:
            return data.by_industry
    }
}

function MetricCard({
    label,
    value,
    detail,
}: {
    label: string
    value: string
    detail: string
}) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">{label}</p>
            <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
            <p className="text-[10px] text-fg-3">{detail}</p>
        </div>
    )
}

function ScoreDistribution({
    data,
}: {
    data: AdminAtsScoreDistributionResponse
}) {
    const max = Math.max(
        ...data.distribution.flatMap(bucket => [bucket.before_count, bucket.after_count]),
        1,
    )
    if (data.distribution.length === 0) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No baseline runs are visible for this selection. Widen the range or change the filters.
            </div>
        )
    }
    return (
        <div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {[
                    ['Before optimization', 'bg-fg-3'],
                    ['After optimization', 'bg-accent'],
                ].map(([label, color]) => (
                    <span key={label} className="inline-flex items-center gap-1.5 text-[10px] text-fg-3">
                        <span className={`h-2 w-2 rounded-sm ${color}`} aria-hidden="true" />
                        {label}
                    </span>
                ))}
            </div>
            <div className="mt-3 space-y-2">
                {data.distribution.map(bucket => (
                    <div key={bucket.bucket} className="grid grid-cols-[52px_1fr] items-center gap-3">
                        <span className="text-[10px] font-medium text-fg-3">{bucket.bucket}</span>
                        <div className="space-y-1">
                            <div
                                className="flex items-center gap-2"
                                title={`Before: ${formatNumber(bucket.before_count)} runs (${formatPct(bucket.before_pct)})`}
                            >
                                <div className="h-2.5 flex-1 overflow-hidden rounded-sm bg-surface-2">
                                    <div
                                        className="h-full bg-fg-3/70"
                                        style={{ width: `${(bucket.before_count / max) * 100}%` }}
                                    />
                                </div>
                                <span className="w-10 text-right text-[10px] tabular-nums text-fg-3">
                                    {formatNumber(bucket.before_count)}
                                </span>
                            </div>
                            <div
                                className="flex items-center gap-2"
                                title={`After: ${formatNumber(bucket.after_count)} runs (${formatPct(bucket.after_pct)})`}
                            >
                                <div className="h-2.5 flex-1 overflow-hidden rounded-sm bg-surface-2">
                                    <div
                                        className="h-full bg-accent"
                                        style={{ width: `${(bucket.after_count / max) * 100}%` }}
                                    />
                                </div>
                                <span className="w-10 text-right text-[10px] tabular-nums text-fg-3">
                                    {formatNumber(bucket.after_count)}
                                </span>
                            </div>
                        </div>
                    </div>
                ))}
            </div>
            <table className="mt-4 w-full border-collapse text-xs">
                <caption className="sr-only">ATS score distribution before and after optimization.</caption>
                <thead>
                    <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-2 py-1.5">Bucket</th>
                        <th scope="col" className="px-2 py-1.5 text-right">Before</th>
                        <th scope="col" className="px-2 py-1.5 text-right">Before %</th>
                        <th scope="col" className="px-2 py-1.5 text-right">After</th>
                        <th scope="col" className="px-2 py-1.5 text-right">After %</th>
                    </tr>
                </thead>
                <tbody>
                    {data.distribution.map(bucket => (
                        <tr key={bucket.bucket} className="border-b border-line/60">
                            <td className="px-2 py-1.5 font-medium text-fg">{bucket.bucket}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-fg-2">
                                {formatNumber(bucket.before_count)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-fg-3">
                                {formatPct(bucket.before_pct)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-fg-2">
                                {formatNumber(bucket.after_count)}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums text-fg-3">
                                {formatPct(bucket.after_pct)}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminAtsScoreDistribution() {
    const [days, setDays] = useState<number>(30)
    const [industry, setIndustry] = useState<string>('')
    const [profile, setProfile] = useState<string>('')
    const [plan, setPlan] = useState<string>('')
    const [industryInput, setIndustryInput] = useState<string>('')
    const [profileInput, setProfileInput] = useState<string>('')
    const [dimension, setDimension] = useState<Dimension>('industry')
    const [data, setData] = useState<AdminAtsScoreDistributionResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminAtsScoreDistribution({
                days,
                industry: industry || undefined,
                profile: profile || undefined,
                plan: plan || undefined,
            })
            if (requestGeneration.current === generation) setData(next)
        } catch (err) {
            if (requestGeneration.current === generation) {
                setError(err instanceof Error ? err.message : 'Failed to load ATS score distribution')
            }
        } finally {
            if (requestGeneration.current === generation) setLoading(false)
        }
    }, [days, industry, profile, plan])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const rows = useMemo(() => (data ? dimensionRows(data, dimension) : []), [data, dimension])
    const hiddenRows = data?.suppression.by_dimension[dimension] ?? 0

    const applyFilters = useCallback(() => {
        setIndustry(industryInput.trim().toLowerCase())
        setProfile(profileInput.trim().toLowerCase())
    }, [industryInput, profileInput])

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">ATS score distribution and improvement</h3>
                    <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                        Before/after ATS score buckets, median delta and improvement rate across completed
                        optimization records. Only aggregate scores and bounded industry, profile and plan
                        keys are read; résumé content, job descriptions and identities are never returned.
                        Rows without a baseline are excluded and counted. Breakdown rows with fewer than{' '}
                        {data?.minimum_users ?? 5} distinct users are hidden.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="ATS score distribution period"
                    >
                        {RANGES.map(range => (
                            <button
                                key={range.days}
                                type="button"
                                aria-pressed={days === range.days}
                                onClick={() => setDays(range.days)}
                                className={`rounded px-2.5 py-1.5 text-xs font-medium transition ${
                                    days === range.days
                                        ? 'bg-accent-soft text-accent-strong'
                                        : 'text-fg-3 hover:text-fg'
                                }`}
                            >
                                {range.label}
                            </button>
                        ))}
                    </div>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Plan
                        <select
                            value={plan}
                            onChange={event => setPlan(event.target.value)}
                            className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        >
                            {PLAN_OPTIONS.map(option => (
                                <option key={option.value || 'all'} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Industry
                        <input
                            value={industryInput}
                            onChange={event => setIndustryInput(event.target.value)}
                            maxLength={100}
                            placeholder="tech_saas"
                            className="mt-1 block w-36 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Profile
                        <input
                            value={profileInput}
                            onChange={event => setProfileInput(event.target.value)}
                            maxLength={64}
                            placeholder="startup"
                            className="mt-1 block w-28 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <button
                        type="button"
                        onClick={applyFilters}
                        disabled={loading}
                        className="mt-4 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        Apply
                    </button>
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="mt-4 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        {loading ? 'Refreshing…' : 'Refresh'}
                    </button>
                </div>
            </div>

            {error && (
                <div
                    role="alert"
                    className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
                >
                    {data ? 'Showing the last successful data. ' : ''}
                    {error}
                </div>
            )}

            {!data && loading ? (
                <div role="status" className="mt-6 text-center text-xs text-fg-3">
                    Loading ATS score distribution…
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                        <MetricCard
                            label="Baseline runs"
                            value={formatNumber(data.totals.runs)}
                            detail={`${formatNumber(data.totals.users)} distinct users`}
                        />
                        <MetricCard
                            label="Median delta"
                            value={formatDelta(data.totals.median_delta)}
                            detail={`median_improvement ${formatDelta(data.totals.median_improvement)} · p25 ${formatDelta(data.totals.p25_delta)} · p75 ${formatDelta(data.totals.p75_delta)}`}
                        />
                        <MetricCard
                            label="Improvement rate"
                            value={formatPct(data.totals.improvement_rate_pct)}
                            detail={`${formatNumber(data.totals.improved)} improved · ${formatNumber(data.totals.declined)} declined`}
                        />
                        <MetricCard
                            label="Mean before"
                            value={formatScore(data.totals.mean_before)}
                            detail={`Median ${formatScore(data.totals.median_before)}`}
                        />
                        <MetricCard
                            label="Mean after"
                            value={formatScore(data.totals.mean_after)}
                            detail={`Median ${formatScore(data.totals.median_after)}`}
                        />
                        <MetricCard
                            label="Missing baseline"
                            value={formatNumber(data.excluded.missing_baseline)}
                            detail="Excluded from score and delta math"
                        />
                    </div>

                    {data.suppressed && (
                        <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 text-xs text-fg-3">
                            This selection has fewer than {data.minimum_users} distinct users. Score metrics and
                            breakdowns are hidden; widen the date range or change the filters.
                        </div>
                    )}

                    <div className="mt-6">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                    Score distribution
                                </h4>
                                <p className="mt-1 text-[10px] text-fg-3">
                                    UTC days. {formatNumber(data.reconciliation.rows_scanned)} scored rows scanned;{' '}
                                    {formatNumber(data.excluded.missing_baseline)} missing a baseline;{' '}
                                    {formatNumber(data.excluded.invalid_scores)} invalid.
                                </p>
                            </div>
                        </div>
                        <div className="mt-3">
                            <ScoreDistribution data={data} />
                        </div>
                    </div>

                    <div className="mt-6">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Improvement breakdown
                            </h4>
                            <div
                                className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                                role="group"
                                aria-label="ATS improvement breakdown dimension"
                            >
                                {DIMENSIONS.map(item => (
                                    <button
                                        key={item.key}
                                        type="button"
                                        aria-pressed={dimension === item.key}
                                        onClick={() => setDimension(item.key)}
                                        className={`rounded px-2.5 py-1 text-[10px] font-semibold transition ${
                                            dimension === item.key
                                                ? 'bg-accent-soft text-accent-strong'
                                                : 'text-fg-3 hover:text-fg'
                                        }`}
                                    >
                                        {item.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                        {hiddenRows > 0 && (
                            <p className="mt-2 text-[10px] text-fg-3">
                                {formatNumber(hiddenRows)} {dimension} row
                                {hiddenRows === 1 ? '' : 's'} hidden for fewer than {data.minimum_users}{' '}
                                distinct users.
                            </p>
                        )}
                        <div className="mt-3 overflow-x-auto">
                            <table className="w-full min-w-[820px] border-collapse text-sm">
                                <caption className="sr-only">
                                    ATS score improvement by {dimension}.
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                                        <th scope="col" className="px-2 py-2">{dimension}</th>
                                        <th scope="col" className="px-2 py-2 text-right">Runs</th>
                                        <th scope="col" className="px-2 py-2 text-right">Before</th>
                                        <th scope="col" className="px-2 py-2 text-right">After</th>
                                        <th scope="col" className="px-2 py-2 text-right">Median delta</th>
                                        <th scope="col" className="px-2 py-2 text-right">Improvement</th>
                                        <th scope="col" className="px-2 py-2 text-right">Declined</th>
                                        <th scope="col" className="px-2 py-2 text-right">Users</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map(row => {
                                        const key = row[dimension] ?? ''
                                        return (
                                            <tr key={key} className="border-b border-line/60 align-top">
                                                <td className="px-2 py-2.5 text-xs font-medium text-fg">{key}</td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                    {formatNumber(row.runs)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-3">
                                                    {formatScore(row.mean_before)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-3">
                                                    {formatScore(row.mean_after)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs font-semibold text-fg">
                                                    {formatDelta(row.median_delta)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-ok">
                                                    {formatPct(row.improvement_rate_pct)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-err">
                                                    {formatNumber(row.declined)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-3">
                                                    {formatNumber(row.users)}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                    {rows.length === 0 && (
                                        <tr>
                                            <td colSpan={8} className="px-2 py-8 text-center text-xs text-fg-3">
                                                No visible aggregate rows for this selection.
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="mt-4 grid gap-2 rounded-[var(--radius-md)] border border-line bg-surface-2/30 px-3 py-2.5 text-[10px] text-fg-3 sm:grid-cols-2">
                        <p>
                            {data.reconciliation.reconciled
                                ? 'Scanned rows reconcile to baseline, missing-baseline and invalid counts.'
                                : 'Reconciliation pending.'}{' '}
                            Median improvement is the median before/after delta across baseline runs; negative
                            deltas are retained.
                        </p>
                        <p>
                            {data.privacy.aggregate_only
                                ? 'Aggregate-only response: no per-user rows, résumé content, job descriptions or identities.'
                                : 'Privacy metadata unavailable.'}
                        </p>
                        {data.notes.map(note => (
                            <p key={note}>{note}</p>
                        ))}
                    </div>
                </>
            ) : null}
        </section>
    )
}
