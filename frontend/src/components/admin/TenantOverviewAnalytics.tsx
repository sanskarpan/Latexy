'use client'

import type { TenantStats, TenantTrendPeriod, TenantTrendPoint } from '@/lib/api-client'

const PERIOD_OPTIONS: Array<{ days: TenantTrendPeriod; label: string }> = [
    { days: 7, label: '7 days' },
    { days: 30, label: '30 days' },
    { days: 90, label: '90 days' },
]

const SERIES = [
    { key: 'submissions' as const, label: 'Submissions', className: 'text-accent' },
    { key: 'active_members' as const, label: 'Active members', className: 'text-ok' },
    { key: 'members_joined' as const, label: 'Joined', className: 'text-fg-2' },
]

function Spinner() {
    return (
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-line-2 border-t-accent" />
    )
}

function formatCount(value: number | null | undefined): string {
    return Number.isFinite(value) ? Number(value).toLocaleString() : '0'
}

function formatRate(value: number | null | undefined): string {
    return `${Math.round((Number.isFinite(value) ? Number(value) : 0) * 100)}%`
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-3">
            <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">{label}</p>
            <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
            {hint && <p className="mt-0.5 text-[11px] text-fg-3">{hint}</p>}
        </div>
    )
}

function SeriesPath({
    points,
    field,
    className,
}: {
    points: TenantTrendPoint[]
    field: 'submissions' | 'active_members' | 'members_joined'
    className: string
}) {
    if (points.length === 0) return null
    const width = 600
    const height = 140
    const inset = 8
    const usableWidth = width - inset * 2
    const usableHeight = height - inset * 2
    const max = Math.max(1, ...points.map(point => Number(point[field] ?? 0)))
    const x = (index: number) =>
        inset +
        (points.length === 1 ? usableWidth / 2 : (index / (points.length - 1)) * usableWidth)
    const y = (value: number) => inset + usableHeight - (value / max) * usableHeight
    const path = points
        .map((point, index) => {
            const value = Number(point[field] ?? 0)
            return `${index === 0 ? 'M' : 'L'} ${x(index).toFixed(2)} ${y(value).toFixed(2)}`
        })
        .join(' ')
    return (
        <path
            d={path}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            className={className}
        />
    )
}

export function TenantOverviewTrendChart({
    points,
    period,
}: {
    points: TenantTrendPoint[]
    period: TenantTrendPeriod
}) {
    const hasActivity = points.some(
        point =>
            Number(point.submissions ?? 0) > 0 ||
            Number(point.active_members ?? 0) > 0 ||
            Number(point.members_joined ?? 0) > 0
    )
    return (
        <div className="mt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-fg-2">{`Activity over ${period} days`}</p>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {SERIES.map(series => (
                        <span
                            key={series.key}
                            className="inline-flex items-center gap-1.5 text-[10px] text-fg-3"
                        >
                            <span
                                className={`h-1.5 w-4 rounded-full bg-current ${series.className}`}
                                aria-hidden="true"
                            />
                            {series.label}
                        </span>
                    ))}
                </div>
            </div>
            <svg
                viewBox="0 0 600 156"
                className="mt-2 h-40 w-full"
                role="img"
                aria-label={`Tenant submissions, active members and joins over ${period} days`}
            >
                <line
                    x1="8"
                    y1="148"
                    x2="592"
                    y2="148"
                    stroke="var(--line)"
                    strokeWidth="1"
                    aria-hidden="true"
                />
                <line
                    x1="8"
                    y1="78"
                    x2="592"
                    y2="78"
                    stroke="var(--line)"
                    strokeWidth="1"
                    strokeDasharray="3 4"
                    aria-hidden="true"
                />
                {SERIES.map(series => (
                    <SeriesPath
                        key={series.key}
                        points={points}
                        field={series.key}
                        className={series.className}
                    />
                ))}
            </svg>
            <div className="flex justify-between text-[10px] text-fg-3">
                <span>{points[0]?.date ?? ''}</span>
                <span>{points[points.length - 1]?.date ?? ''}</span>
            </div>
            {!hasActivity && <p className="mt-2 text-xs text-fg-3">No activity in this period.</p>}
        </div>
    )
}

export default function TenantOverviewAnalytics({
    stats,
    loading,
    error,
    onRetry,
    period,
    onPeriodChange,
}: {
    stats: TenantStats | null
    loading: boolean
    error: string | null
    onRetry: () => void
    period: TenantTrendPeriod
    onPeriodChange: (period: TenantTrendPeriod) => void
}) {
    if (loading) {
        return (
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Overview</p>
                <div className="flex justify-center py-8">
                    <Spinner />
                </div>
            </section>
        )
    }

    if (error) {
        return (
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Overview</p>
                <div role="alert" className="space-y-2 py-3 text-center">
                    <p className="text-sm font-semibold text-err">Overview could not be loaded</p>
                    <p className="text-xs text-fg-2">{error}</p>
                    <button
                        type="button"
                        onClick={onRetry}
                        className="rounded border border-line px-3 py-1.5 text-xs text-fg-2 hover:bg-surface-2"
                    >
                        Retry overview
                    </button>
                </div>
            </section>
        )
    }

    if (!stats) {
        return (
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Overview</p>
                <p className="py-6 text-center text-sm text-fg-3">No overview data yet.</p>
            </section>
        )
    }

    const seatsUsed = stats.seats_used ?? stats.member_count ?? 0
    const seatLimit = stats.seat_limit ?? 0
    const seatsAvailable = stats.seats_available ?? Math.max(0, seatLimit - seatsUsed)
    const pendingAvailable = stats.pending_invites_available !== false
    const activation = stats.activation
    const suppression = stats.suppression
    const points = stats.trends?.[String(period) as '7' | '30' | '90'] ?? []
    const hasCohortActivity = (stats.cohort_count ?? 0) > 0 || (stats.submission_count ?? 0) > 0

    return (
        <section
            className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
            aria-label="Tenant overview"
        >
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">Overview</p>
                    <p className="mt-1 text-xs text-fg-3">
                        Aggregate tenant activity only. Personal documents are never included.
                    </p>
                </div>
                <div
                    className="flex items-center gap-1 rounded-full border border-line bg-surface-2 p-1"
                    role="group"
                    aria-label="Trend period"
                >
                    {PERIOD_OPTIONS.map(option => (
                        <button
                            key={option.days}
                            type="button"
                            aria-pressed={period === option.days}
                            onClick={() => onPeriodChange(option.days)}
                            className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition ${
                                period === option.days
                                    ? 'bg-accent-soft text-accent-strong'
                                    : 'text-fg-3 hover:text-fg'
                            }`}
                        >
                            {option.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
                <MetricCard
                    label="Seats"
                    value={`${formatCount(seatsUsed)} / ${formatCount(seatLimit)}`}
                    hint={`${formatCount(seatsAvailable)} available`}
                />
                <MetricCard
                    label="Accepted"
                    value={formatCount(stats.accepted_members)}
                    hint="Current members"
                />
                <MetricCard
                    label="Pending invites"
                    value={pendingAvailable ? formatCount(stats.invited_members) : '—'}
                    hint={pendingAvailable ? 'Awaiting acceptance' : 'Invitation cache unavailable'}
                />
                <MetricCard
                    label="Active"
                    value={formatCount(stats.active_members)}
                    hint={`Last ${stats.active_members_window_days ?? 30} days`}
                />
                <MetricCard
                    label="Cohorts"
                    value={formatCount(stats.cohort_count)}
                    hint={`${formatCount(stats.cohorts_with_submissions)} with submissions`}
                />
                <MetricCard
                    label="Submissions"
                    value={formatCount(stats.submission_count)}
                    hint={`${formatCount(stats.cohort_member_count)} cohort roster entries`}
                />
                <MetricCard
                    label="Activation rate"
                    value={formatRate(activation?.activation_rate)}
                    hint={`${formatCount(activation?.submitting_members)} submitting members`}
                />
                <MetricCard
                    label="Candidate opened"
                    value={formatCount(activation?.opened)}
                    hint="Explicit submissions"
                />
                <MetricCard
                    label="Candidate downloaded"
                    value={formatCount(activation?.downloaded)}
                    hint="Explicit submissions"
                />
            </div>

            {!hasCohortActivity && (
                <p className="mt-4 rounded-[var(--radius-md)] border border-dashed border-line px-4 py-3 text-xs text-fg-3">
                    No cohorts or explicit submissions yet. Seat and member activity will appear
                    here as the tenant grows.
                </p>
            )}

            <TenantOverviewTrendChart points={points} period={period} />

            {suppression && Number(suppression.suppressed_cohorts ?? 0) > 0 && (
                <p className="mt-3 text-[11px] text-fg-3">
                    {`${formatCount(suppression.suppressed_cohorts)} ${Number(suppression.suppressed_cohorts) === 1 ? 'cohort' : 'cohorts'} below ${formatCount(suppression.minimum_cohort_size ?? 5)} members are included in totals only and are never itemised.`}
                </p>
            )}
        </section>
    )
}
