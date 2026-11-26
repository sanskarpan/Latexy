'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminCareerAdoptionFeature,
    type AdminCareerAdoptionResponse,
    type AdminCareerAdoptionSegment,
} from '@/lib/api-client'
import { formatNumber } from '@/components/admin/admin-format'

const RANGES = [7, 30, 90, 365] as const
const DIMENSIONS: Array<{ id: 'plan' | 'cohort'; label: string }> = [
    { id: 'plan', label: 'Plan' },
    { id: 'cohort', label: 'Signup cohort' },
]

function formatPercent(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '—'
    return `${value.toFixed(1)}%`
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">{label}</p>
            <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
            <p className="text-[10px] text-fg-3">{detail}</p>
        </div>
    )
}

function FeatureCard({ feature }: { feature: AdminCareerAdoptionFeature }) {
    const adoption = feature.adoption
    return (
        <article className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                    <h3 className="text-sm font-semibold text-fg">{feature.label}</h3>
                    <p className="mt-0.5 font-mono text-[10px] text-fg-3">{feature.event}</p>
                </div>
                <span className="rounded-full border border-line bg-surface px-2 py-0.5 text-[10px] font-medium text-fg-3">
                    {adoption ? `${formatNumber(adoption.users)} adopters` : 'Withheld'}
                </span>
            </div>
            {adoption ? (
                <div className="mt-3 grid grid-cols-2 gap-2">
                    <MetricCard
                        label="Users"
                        value={formatNumber(adoption.users)}
                        detail={`${formatPercent(adoption.penetration ?? 0)} of audience`}
                    />
                    <MetricCard
                        label="Runs"
                        value={formatNumber(adoption.runs)}
                        detail="generation events"
                    />
                    <MetricCard
                        label="Repeat use"
                        value={formatNumber(adoption.repeat_users)}
                        detail={`${formatPercent(adoption.repeat_rate)} repeat rate`}
                    />
                    <MetricCard
                        label="After optimization"
                        value={formatNumber(adoption.after_optimization_users)}
                        detail={`${formatPercent(adoption.after_optimization_rate)} cross-sell`}
                    />
                </div>
            ) : (
                <p className="mt-3 rounded border border-dashed border-line px-3 py-4 text-xs text-fg-3">
                    This filtered audience is below the five-user floor, so adoption and cross-sell
                    counts are withheld.
                </p>
            )}
        </article>
    )
}

function SegmentTable({
    segments,
    dimension,
    featureLabel,
}: {
    segments: AdminCareerAdoptionSegment[]
    dimension: 'plan' | 'cohort'
    featureLabel: string
}) {
    const rows = segments.filter(segment => segment.dimension === dimension)
    if (!rows.length) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No {dimension === 'plan' ? 'plan' : 'signup cohort'} with at least five users is
                visible for {featureLabel} in this selection.
            </div>
        )
    }
    return (
        <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
                <caption className="sr-only">
                    {featureLabel} adoption by {dimension}
                </caption>
                <thead>
                    <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 font-semibold">
                            {dimension === 'plan' ? 'Plan' : 'Cohort'}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Segment users
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Feature users
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Runs
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Repeat users
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Repeat rate
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            After optimization
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Penetration
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => (
                        <tr key={`${row.dimension}:${row.key}`} className="border-t border-line/70">
                            <td className="px-3 py-2 font-medium text-fg">{row.label}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.denominator)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg">
                                {formatNumber(row.users)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.runs)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.repeat_users)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatPercent(row.repeat_rate)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.after_optimization_users)}
                                <span className="block text-[10px] text-fg-3">
                                    {formatPercent(row.after_optimization_rate)}
                                </span>
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatPercent(row.penetration)}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminCareerAdoption() {
    const [days, setDays] = useState(30)
    const [from, setFrom] = useState('')
    const [to, setTo] = useState('')
    const [plan, setPlan] = useState('')
    const [cohort, setCohort] = useState('')
    const [applied, setApplied] = useState({ days: 30, from: '', to: '', plan: '', cohort: '' })
    const [dimension, setDimension] = useState<'plan' | 'cohort'>('plan')
    const [featureKey, setFeatureKey] = useState<AdminCareerAdoptionFeature['key']>('cover_letters')
    const [data, setData] = useState<AdminCareerAdoptionResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminCareerAdoption({
                days: applied.days,
                start_date: applied.from || undefined,
                end_date: applied.to || undefined,
                plan: applied.plan || undefined,
                cohort: applied.cohort || undefined,
            })
            if (generation === requestGeneration.current) setData(next)
        } catch (err) {
            if (generation === requestGeneration.current) {
                setError(err instanceof Error ? err.message : String(err))
            }
        } finally {
            if (generation === requestGeneration.current) setLoading(false)
        }
    }, [applied])

    useEffect(() => {
        void load()
    }, [load])

    const applyPreset = (range: number) => {
        setDays(range)
        setFrom('')
        setTo('')
        setApplied(current => ({ ...current, days: range, from: '', to: '' }))
    }

    const selectedFeature = useMemo(
        () =>
            data?.features.find(feature => feature.key === featureKey) ?? data?.features[0] ?? null,
        [data, featureKey]
    )
    const suppressedTotal = data
        ? (data.suppressed_segments.plan ?? 0) + (data.suppressed_segments.cohort ?? 0)
        : 0
    const adoptionTotals = useMemo(() => {
        const features = data?.features ?? []
        return features.reduce(
            (totals, feature) => {
                if (!feature.adoption) return totals
                totals.runs += feature.adoption.runs
                totals.repeatUsers += feature.adoption.repeat_users
                totals.afterOptimization += feature.adoption.after_optimization_users
                return totals
            },
            { runs: 0, repeatUsers: 0, afterOptimization: 0 }
        )
    }, [data])

    return (
        <section className="mt-6 overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h2 className="text-sm font-semibold text-fg">
                            Career features: adoption and cross-sell
                        </h2>
                        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                            Cover-letter, interview-prep and career-path adoption by plan and signup
                            cohort. Users count distinct adopters; runs count allowlisted generation
                            events; repeat use means two or more runs; cross-sell counts adopters
                            whose first run followed an optimization. Aggregate counts only —
                            generated content, questions, analysis prose, job descriptions and
                            identities are never returned.
                        </p>
                    </div>
                    <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                        {data ? `${data.start_date} → ${data.end_date} · UTC` : 'Loading window…'}
                    </span>
                </div>

                <div className="mt-4 flex flex-wrap items-end gap-3">
                    <div
                        role="group"
                        aria-label="Career adoption date range"
                        className="flex flex-wrap gap-1"
                    >
                        {RANGES.map(range => {
                            const active = !applied.from && !applied.to && applied.days === range
                            return (
                                <button
                                    key={range}
                                    type="button"
                                    aria-pressed={active}
                                    onClick={() => applyPreset(range)}
                                    className={`min-h-[36px] rounded border px-3 py-1.5 text-xs font-medium ${
                                        active
                                            ? 'border-accent text-accent-strong'
                                            : 'border-line text-fg-2 hover:bg-surface-2'
                                    }`}
                                >
                                    {range}d
                                </button>
                            )
                        })}
                    </div>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        From
                        <input
                            type="date"
                            aria-label="Career adoption start date"
                            value={from}
                            onChange={event => setFrom(event.target.value)}
                            className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        To
                        <input
                            type="date"
                            aria-label="Career adoption end date"
                            value={to}
                            onChange={event => setTo(event.target.value)}
                            className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <label className="min-w-[130px] text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Plan
                        <input
                            type="text"
                            aria-label="Filter by plan"
                            placeholder="pro,team"
                            value={plan}
                            onChange={event => setPlan(event.target.value)}
                            className="mt-1 block w-full min-h-[36px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <label className="min-w-[130px] text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Cohort
                        <input
                            type="text"
                            aria-label="Filter by signup cohort"
                            placeholder="2026-11"
                            value={cohort}
                            onChange={event => setCohort(event.target.value)}
                            className="mt-1 block w-full min-h-[36px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <button
                        type="button"
                        onClick={() => setApplied({ days, from, to, plan, cohort })}
                        disabled={loading}
                        className="min-h-[36px] rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                    >
                        {loading ? 'Loading…' : 'Apply filters'}
                    </button>
                </div>

                {error && (
                    <p
                        role="alert"
                        className="mt-3 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
                    >
                        {error}
                    </p>
                )}
            </div>

            {data && (
                <>
                    <div className="grid gap-px border-b border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
                        <MetricCard
                            label="Audience"
                            value={formatNumber(data.audience_users)}
                            detail="users in the selected plan/cohort"
                        />
                        <MetricCard
                            label="Runs"
                            value={formatNumber(adoptionTotals.runs)}
                            detail="across the three features"
                        />
                        <MetricCard
                            label="Repeat uses"
                            value={formatNumber(adoptionTotals.repeatUsers)}
                            detail="feature-level repeat users"
                        />
                        <MetricCard
                            label="Cross-sell"
                            value={formatNumber(adoptionTotals.afterOptimization)}
                            detail="feature-level post-optimization adopters"
                        />
                        <MetricCard
                            label="Hidden segments"
                            value={formatNumber(suppressedTotal)}
                            detail={`below ${data.minimum_segment_size} users`}
                        />
                    </div>

                    {data.suppressed ? (
                        <div className="px-5 py-10 text-center text-sm text-fg-3">
                            The filtered audience has fewer than {data.minimum_segment_size} users,
                            so all adoption and cross-sell metrics are withheld.
                        </div>
                    ) : (
                        <>
                            <div className="grid gap-3 border-b border-line p-4 md:grid-cols-3">
                                {data.features.map(feature => (
                                    <FeatureCard key={feature.key} feature={feature} />
                                ))}
                            </div>

                            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
                                <div
                                    className="flex flex-wrap gap-1"
                                    role="tablist"
                                    aria-label="Adoption breakdown dimension"
                                >
                                    {DIMENSIONS.map(item => (
                                        <button
                                            key={item.id}
                                            type="button"
                                            role="tab"
                                            aria-selected={dimension === item.id}
                                            onClick={() => setDimension(item.id)}
                                            className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                                                dimension === item.id
                                                    ? 'border-accent text-accent-strong'
                                                    : 'border-line text-fg-3 hover:bg-surface-2'
                                            }`}
                                        >
                                            {item.label}
                                        </button>
                                    ))}
                                </div>
                                <div
                                    className="flex flex-wrap gap-1"
                                    role="tablist"
                                    aria-label="Adoption feature"
                                >
                                    {(data.features ?? []).map(feature => (
                                        <button
                                            key={feature.key}
                                            type="button"
                                            role="tab"
                                            aria-selected={selectedFeature?.key === feature.key}
                                            onClick={() => setFeatureKey(feature.key)}
                                            className={`rounded-full border px-3 py-1 text-xs font-medium ${
                                                selectedFeature?.key === feature.key
                                                    ? 'border-accent bg-accent-soft text-accent-strong'
                                                    : 'border-line text-fg-3 hover:bg-surface-2'
                                            }`}
                                        >
                                            {feature.label}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            <div className="px-4 py-4">
                                {selectedFeature ? (
                                    <SegmentTable
                                        segments={selectedFeature.segments}
                                        dimension={dimension}
                                        featureLabel={selectedFeature.label}
                                    />
                                ) : (
                                    <p className="py-8 text-center text-sm text-fg-3">
                                        No feature rows are available.
                                    </p>
                                )}
                            </div>

                            <div className="grid gap-2 border-t border-line px-5 py-3 text-[10px] text-fg-3 sm:grid-cols-2 lg:grid-cols-3">
                                {(data.features ?? []).map(feature => {
                                    const row = data.reconciliation.features?.[feature.key]
                                    if (!row) return null
                                    return (
                                        <p key={feature.key}>
                                            <span className="font-semibold text-fg-2">
                                                {feature.label}:
                                            </span>{' '}
                                            {formatNumber(row.events)} events ·{' '}
                                            {formatNumber(row.table_rows)} persisted rows ·{' '}
                                            {formatNumber(row.matched)} matched
                                            {row.unmatched_events || row.unmatched_rows
                                                ? ` · ${formatNumber(row.unmatched_events)} event-only / ${formatNumber(row.unmatched_rows)} row-only`
                                                : ''}
                                        </p>
                                    )
                                })}
                            </div>
                        </>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-[10px] text-fg-3">
                        <span>
                            Five-user suppression applies to plan and cohort segments; inputs below
                            five users return no metrics. Cross-sell looks back{' '}
                            {data.optimization_lookback_days} days for an optimization.
                        </span>
                        <span>
                            Source: usage_analytics + feature tables · aggregate counts only
                        </span>
                    </div>
                </>
            )}

            {!data && !error && (
                <div role="status" className="px-5 py-10 text-center text-sm text-fg-3">
                    Loading career-feature adoption…
                </div>
            )}
        </section>
    )
}
