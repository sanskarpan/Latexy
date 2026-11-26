'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminOptimizationAcceptanceMetrics,
    type AdminOptimizationAcceptanceResponse,
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
    { value: 'anonymous', label: 'Anonymous' },
] as const

type Dimension = 'feature' | 'persona' | 'plan' | 'source'

type AcceptanceRow = AdminOptimizationAcceptanceMetrics & {
    feature?: string
    persona?: string
    plan?: string
    source?: string
}

const DIMENSIONS: Array<{ key: Dimension; label: string }> = [
    { key: 'feature', label: 'Feature' },
    { key: 'persona', label: 'Persona' },
    { key: 'plan', label: 'Plan' },
    { key: 'source', label: 'Source' },
]

function formatPct(value: number): string {
    return `${(Number.isFinite(value) ? value : 0).toFixed(2)}%`
}

function dimensionRows(
    data: AdminOptimizationAcceptanceResponse,
    dimension: Dimension,
): AcceptanceRow[] {
    switch (dimension) {
        case 'persona':
            return data.by_persona
        case 'plan':
            return data.by_plan
        case 'source':
            return data.by_source
        default:
            return data.by_feature
    }
}

function AcceptanceTrend({ data }: { data: AdminOptimizationAcceptanceResponse }) {
    const max = Math.max(...data.by_day.map(point => point.candidates_shown), 1)
    if (data.by_day.length === 0) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No visible decision activity in this range. Widen the range or change the filters.
            </div>
        )
    }
    return (
        <div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {[
                    ['Accepted', 'bg-ok'],
                    ['Rejected', 'bg-err'],
                    ['Discarded', 'bg-warn'],
                    ['Undecided', 'bg-fg-3'],
                ].map(([label, color]) => (
                    <span key={label} className="inline-flex items-center gap-1.5 text-[10px] text-fg-3">
                        <span className={`h-2 w-2 rounded-sm ${color}`} aria-hidden="true" />
                        {label}
                    </span>
                ))}
            </div>
            <div className="mt-3 overflow-x-auto">
                <div className="min-w-[560px]">
                    <div className="flex h-40 items-end gap-[2px] border-b border-line" aria-hidden="true">
                        {data.by_day.map(point => {
                            const parts = [
                                ['bg-ok', point.accepted],
                                ['bg-err', point.rejected],
                                ['bg-warn', point.discarded],
                                ['bg-fg-3', point.undecided],
                            ] as const
                            return (
                                <div
                                    key={point.date}
                                    className="flex h-full min-w-[2px] flex-1 flex-col-reverse justify-start"
                                    title={`${point.date}: ${formatNumber(point.candidates_shown)} shown, ${formatNumber(point.decided)} decided, ${formatNumber(point.accepted)} accepted`}
                                >
                                    {parts.map(([color, count]) =>
                                        count > 0 ? (
                                            <div
                                                key={color}
                                                className={`${color} w-full opacity-90`}
                                                style={{ height: `${(count / max) * 100}%` }}
                                            />
                                        ) : null,
                                    )}
                                </div>
                            )
                        })}
                    </div>
                    <div className="mt-1 flex justify-between text-[10px] text-fg-3">
                        <span>{data.by_day[0]?.date}</span>
                        <span>{data.by_day[data.by_day.length - 1]?.date}</span>
                    </div>
                </div>
            </div>
            <table className="sr-only">
                <caption>Daily optimization candidate outcomes over {data.days} days.</caption>
                <thead>
                    <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Candidates shown</th>
                        <th scope="col">Decided</th>
                        <th scope="col">Accepted</th>
                        <th scope="col">Rejected</th>
                        <th scope="col">Discarded</th>
                        <th scope="col">Undecided</th>
                    </tr>
                </thead>
                <tbody>
                    {data.by_day.map(point => (
                        <tr key={point.date}>
                            <td>{point.date}</td>
                            <td>{point.candidates_shown}</td>
                            <td>{point.decided}</td>
                            <td>{point.accepted}</td>
                            <td>{point.rejected}</td>
                            <td>{point.discarded}</td>
                            <td>{point.undecided}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
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

function metricDetail(metrics: AdminOptimizationAcceptanceMetrics, rateKey: 'acceptance_rate_pct' | 'decision_rate_pct') {
    return `${formatPct(metrics[rateKey])} ${rateKey === 'acceptance_rate_pct' ? 'of decided' : 'of shown'}`
}

export default function AdminOptimizationAcceptance() {
    const [days, setDays] = useState<number>(30)
    const [plan, setPlan] = useState<string>('')
    const [feature, setFeature] = useState<string>('')
    const [persona, setPersona] = useState<string>('')
    const [featureInput, setFeatureInput] = useState<string>('')
    const [personaInput, setPersonaInput] = useState<string>('')
    const [dimension, setDimension] = useState<Dimension>('feature')
    const [data, setData] = useState<AdminOptimizationAcceptanceResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [exporting, setExporting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminOptimizationAcceptance({
                days,
                plan: plan || undefined,
                feature: feature || undefined,
                persona: persona || undefined,
            })
            if (requestGeneration.current === generation) setData(next)
        } catch (err) {
            if (requestGeneration.current === generation) {
                setError(err instanceof Error ? err.message : 'Failed to load optimization acceptance')
            }
        } finally {
            if (requestGeneration.current === generation) setLoading(false)
        }
    }, [days, plan, feature, persona])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const downloadCsv = useCallback(async () => {
        setExporting(true)
        try {
            const blob = await apiClient.downloadAdminOptimizationAcceptanceCsv({
                days,
                plan: plan || undefined,
                feature: feature || undefined,
                persona: persona || undefined,
            })
            const url = URL.createObjectURL(blob)
            const anchor = document.createElement('a')
            anchor.href = url
            anchor.download = `optimization-acceptance-${days}d.csv`
            document.body.appendChild(anchor)
            anchor.click()
            anchor.remove()
            URL.revokeObjectURL(url)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'CSV export failed')
        } finally {
            setExporting(false)
        }
    }, [days, plan, feature, persona])

    const rows = useMemo(() => (data ? dimensionRows(data, dimension) : []), [data, dimension])
    const hiddenRows = data?.suppression.by_dimension[dimension] ?? 0

    const applyFilters = useCallback(() => {
        setFeature(featureInput.trim().toLowerCase())
        setPersona(personaInput.trim().toLowerCase())
    }, [featureInput, personaInput])

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Optimization candidate acceptance</h3>
                    <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                        Accepted, rejected and discarded optimization candidates from the resume engine
                        and inline suggestion decisions. Candidates shown and decided are separate denominators.
                        Only aggregate counts are shown; rows with fewer than {data?.minimum_users ?? 5} distinct
                        users are suppressed. No suggestion text, candidate text, résumé content or per-user rows
                        are read.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Optimization acceptance period"
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
                        Feature
                        <input
                            value={featureInput}
                            onChange={event => setFeatureInput(event.target.value)}
                            maxLength={40}
                            placeholder="experience"
                            className="mt-1 block w-32 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        />
                    </label>
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Persona
                        <input
                            value={personaInput}
                            onChange={event => setPersonaInput(event.target.value)}
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
                    <button
                        type="button"
                        onClick={() => void downloadCsv()}
                        disabled={exporting || !data}
                        className="mt-4 rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
                    >
                        {exporting ? 'Preparing CSV…' : 'Export CSV'}
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
                    Loading optimization acceptance…
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                        <MetricCard
                            label="Candidates shown"
                            value={formatNumber(data.totals.candidates_shown)}
                            detail={`${formatNumber(data.totals.users)} distinct users`}
                        />
                        <MetricCard
                            label="Decided"
                            value={formatNumber(data.totals.decided)}
                            detail={metricDetail(data.totals, 'decision_rate_pct')}
                        />
                        <MetricCard
                            label="Accepted"
                            value={formatNumber(data.totals.accepted)}
                            detail={`${formatPct(data.totals.accepted_of_shown_pct)} of shown`}
                        />
                        <MetricCard
                            label="Rejected"
                            value={formatNumber(data.totals.rejected)}
                            detail="Optimization patch or suggestion rejection"
                        />
                        <MetricCard
                            label="Discarded"
                            value={formatNumber(data.totals.discarded)}
                            detail="Conflicted suggestions no longer applicable"
                        />
                        <MetricCard
                            label="Acceptance rate"
                            value={formatPct(data.totals.acceptance_rate_pct)}
                            detail="Accepted / decided"
                        />
                    </div>

                    {data.suppressed && (
                        <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 text-xs text-fg-3">
                            This selection has fewer than {data.minimum_users} distinct users. Counts are
                            hidden; widen the date range or change the plan, feature or persona filter.
                        </div>
                    )}

                    <div className="mt-6">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                            Daily outcome trend
                        </h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            UTC days. Run candidates use the run&apos;s last update day because per-patch
                            decision timestamps are not retained.
                        </p>
                        <div className="mt-3">
                            <AcceptanceTrend data={data} />
                        </div>
                    </div>

                    <div className="mt-6">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Acceptance breakdown
                            </h4>
                            <div
                                className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                                role="group"
                                aria-label="Acceptance breakdown dimension"
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
                            <table className="w-full min-w-[900px] border-collapse text-sm">
                                <caption className="sr-only">
                                    Optimization acceptance by {dimension}.
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                                        <th scope="col" className="px-2 py-2">{dimension}</th>
                                        <th scope="col" className="px-2 py-2 text-right">Shown</th>
                                        <th scope="col" className="px-2 py-2 text-right">Decided</th>
                                        <th scope="col" className="px-2 py-2 text-right">Accepted</th>
                                        <th scope="col" className="px-2 py-2 text-right">Rejected</th>
                                        <th scope="col" className="px-2 py-2 text-right">Discarded</th>
                                        <th scope="col" className="px-2 py-2 text-right">Undecided</th>
                                        <th scope="col" className="px-2 py-2 text-right">Acceptance</th>
                                        <th scope="col" className="px-2 py-2 text-right">Decision rate</th>
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
                                                    {formatNumber(row.candidates_shown)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                    {formatNumber(row.decided)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-ok">
                                                    {formatNumber(row.accepted)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-err">
                                                    {formatNumber(row.rejected)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-warn">
                                                    {formatNumber(row.discarded)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-3">
                                                    {formatNumber(row.undecided)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs font-semibold text-fg">
                                                    {formatPct(row.acceptance_rate_pct)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-3">
                                                    {formatPct(row.decision_rate_pct)}
                                                </td>
                                                <td className="px-2 py-2.5 text-right text-xs text-fg-3">
                                                    {formatNumber(row.users)}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                    {rows.length === 0 && (
                                        <tr>
                                            <td colSpan={10} className="px-2 py-8 text-center text-xs text-fg-3">
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
                            Source reconciliation: {formatNumber(data.reconciliation.run_decision_keys)} run
                            decision keys + {formatNumber(data.reconciliation.suggestion_rows_scanned)} suggestion
                            rows = {formatNumber(data.reconciliation.decided)} decided. Candidates shown:{' '}
                            {formatNumber(data.reconciliation.candidates_shown)}.
                        </p>
                        <p>
                            {data.reconciliation.reconciled ? 'Reconciled to both decision tables.' : 'Reconciliation pending.'}{' '}
                            Run rows past retention excluded:{' '}
                            {formatNumber(data.reconciliation.run_expired_rows_excluded)}.
                            Unmatched run decisions:{' '}
                            {formatNumber(data.reconciliation.run_unmatched_decisions)}. Duplicate patch ids
                            ignored: {formatNumber(data.reconciliation.run_duplicate_patch_ids)}.
                        </p>
                        <p>{data.retention.run_decisions}</p>
                        <p>{data.retention.suggestion_decisions}</p>
                        <p>{data.feature_source}</p>
                        <p>{data.persona_source}</p>
                    </div>
                </>
            ) : null}
        </section>
    )
}
