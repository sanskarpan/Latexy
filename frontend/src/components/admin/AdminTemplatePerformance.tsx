'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminTemplatePerformanceResponse,
    type AdminTemplatePerformanceRow,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from '@/components/admin/admin-format'

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

function formatShare(value: number): string {
    return `${(Number.isFinite(value) ? value : 0).toFixed(1)}%`
}

function templateLabel(row: AdminTemplatePerformanceRow): string {
    if (row.template_name) return row.template_name
    return `Deleted template ${row.template_id.slice(0, 8)}`
}

function UsageTrend({ data }: { data: AdminTemplatePerformanceResponse }) {
    const max = Math.max(
        ...data.trend.map(point =>
            point.views + point.uses + point.exports + point.compile_success + point.compile_failed
        ),
        1,
    )
    const total = data.trend.reduce(
        (sum, point) =>
            sum + point.views + point.uses + point.exports + point.compile_success + point.compile_failed,
        0,
    )

    if (data.trend.length === 0) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No template activity matches these filters.
            </div>
        )
    }

    return (
        <div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {[
                    ['Views', 'bg-fg-3'],
                    ['Uses', 'bg-accent'],
                    ['Exports', 'bg-ok'],
                    ['Compile success', 'bg-warn'],
                    ['Compile fail', 'bg-err'],
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
                        {data.trend.map(point => {
                            const parts = [
                                ['bg-fg-3', point.views],
                                ['bg-accent', point.uses],
                                ['bg-ok', point.exports],
                                ['bg-warn', point.compile_success],
                                ['bg-err', point.compile_failed],
                            ] as const
                            return (
                                <div
                                    key={point.date}
                                    className="flex h-full min-w-[2px] flex-1 flex-col-reverse justify-start"
                                    title={`${point.date}: ${formatNumber(point.views)} views, ${formatNumber(point.uses)} uses, ${formatNumber(point.exports)} exports`}
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
                        <span>{data.trend[0]?.date}</span>
                        <span>{data.trend[data.trend.length - 1]?.date}</span>
                    </div>
                </div>
            </div>
            <table className="sr-only">
                <caption>
                    Daily template activity over {data.days} days, {formatNumber(total)} recorded actions.
                </caption>
                <thead>
                    <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Views</th>
                        <th scope="col">Uses</th>
                        <th scope="col">Exports</th>
                        <th scope="col">Compile success</th>
                        <th scope="col">Compile fail</th>
                    </tr>
                </thead>
                <tbody>
                    {data.trend.map(point => (
                        <tr key={point.date}>
                            <td>{point.date}</td>
                            <td>{point.views}</td>
                            <td>{point.uses}</td>
                            <td>{point.exports}</td>
                            <td>{point.compile_success}</td>
                            <td>{point.compile_failed}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminTemplatePerformance() {
    const [days, setDays] = useState<number>(30)
    const [plan, setPlan] = useState<string>('')
    const [data, setData] = useState<AdminTemplatePerformanceResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [exporting, setExporting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminTemplatePerformance({
                days,
                plan: plan || undefined,
            })
            if (requestGeneration.current === generation) setData(next)
        } catch (err) {
            if (requestGeneration.current === generation) {
                setError(err instanceof Error ? err.message : 'Failed to load template performance')
            }
        } finally {
            if (requestGeneration.current === generation) setLoading(false)
        }
    }, [days, plan])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const downloadCsv = useCallback(async () => {
        setExporting(true)
        try {
            const blob = await apiClient.downloadAdminTemplatePerformanceCsv({
                days,
                plan: plan || undefined,
            })
            const url = URL.createObjectURL(blob)
            const anchor = document.createElement('a')
            anchor.href = url
            anchor.download = `template-performance-${days}d.csv`
            document.body.appendChild(anchor)
            anchor.click()
            anchor.remove()
            URL.revokeObjectURL(url)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'CSV export failed')
        } finally {
            setExporting(false)
        }
    }, [days, plan])

    const successRate = useMemo(() => {
        if (!data) return 0
        const finished = data.totals.compile_success + data.totals.compile_failed
        return finished > 0 ? (data.totals.compile_success / finished) * 100 : 0
    }, [data])

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Template catalog performance</h3>
                    <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
                        Views, selections, successful uses, exports and compile outcomes for public
                        catalog templates, ranked by successful exports. Only aggregates are shown;
                        templates with fewer than {data?.minimum_users ?? 5} distinct users are
                        suppressed. No résumé content or per-user template history is read.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Template performance period"
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
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </label>
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
                    Loading template performance…
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        {[
                            {
                                label: 'Ranked templates',
                                value: formatNumber(data.totals.templates),
                                detail: `${formatNumber(data.suppressed_templates)} suppressed`,
                            },
                            {
                                label: 'Successful exports',
                                value: formatNumber(data.totals.exports),
                                detail: 'Ranking metric',
                            },
                            {
                                label: 'Compile success',
                                value: formatNumber(data.totals.compile_success),
                                detail: `${formatNumber(data.totals.compile_failed)} failed`,
                            },
                            {
                                label: 'Compile success rate',
                                value: formatShare(successRate),
                                detail: data.reconciliation.reconciled ? 'Reconciled to compilations' : 'Reconciliation pending',
                            },
                        ].map(card => (
                            <div
                                key={card.label}
                                className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5"
                            >
                                <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                                    {card.label}
                                </p>
                                <p className="mt-1 text-lg font-semibold text-fg">{card.value}</p>
                                <p className="text-[10px] text-fg-3">{card.detail}</p>
                            </div>
                        ))}
                    </div>

                    {data.suppressed && (
                        <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 text-xs text-fg-3">
                            Every matching template has fewer than {data.minimum_users} distinct users in
                            this range. Widen the date range or change the plan filter to view aggregates.
                        </div>
                    )}

                    <div className="mt-6">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                            Usage trend
                        </h4>
                        <div className="mt-3">
                            <UsageTrend data={data} />
                        </div>
                    </div>

                    <div className="mt-6 overflow-x-auto">
                        <table className="w-full min-w-[980px] border-collapse text-sm">
                            <caption className="sr-only">
                                Template catalog ranking by successful exports.
                            </caption>
                            <thead>
                                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                                    <th scope="col" className="px-2 py-2">#</th>
                                    <th scope="col" className="px-2 py-2">Template</th>
                                    <th scope="col" className="px-2 py-2 text-right">Users</th>
                                    <th scope="col" className="px-2 py-2 text-right">Views</th>
                                    <th scope="col" className="px-2 py-2 text-right">Uses</th>
                                    <th scope="col" className="px-2 py-2 text-right">Exports</th>
                                    <th scope="col" className="px-2 py-2 text-right">Compile success</th>
                                    <th scope="col" className="px-2 py-2 text-right">Compile fail</th>
                                    <th scope="col" className="px-2 py-2 text-right">Success rate</th>
                                    <th scope="col" className="px-2 py-2">Last activity</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.ranking.map(row => (
                                    <tr key={row.template_id} className="border-b border-line/60 align-top">
                                        <td className="px-2 py-2.5 text-xs text-fg-3">{row.rank}</td>
                                        <td className="px-2 py-2.5">
                                            <div className="flex flex-wrap items-center gap-1.5">
                                                {row.deleted ? (
                                                    <span className="text-sm font-medium text-fg-2">
                                                        {templateLabel(row)}
                                                    </span>
                                                ) : (
                                                    <a
                                                        href={`/templates?preview=${encodeURIComponent(row.template_id)}`}
                                                        className="text-sm font-medium text-fg hover:text-accent-strong"
                                                    >
                                                        {templateLabel(row)}
                                                    </a>
                                                )}
                                                {row.deleted && (
                                                    <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn">
                                                        Deleted
                                                    </span>
                                                )}
                                                {row.category && (
                                                    <span className="text-[10px] uppercase tracking-wider text-fg-3">
                                                        {row.category.replace(/_/g, ' ')}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-2 py-2.5 text-right text-xs text-fg-2">{formatNumber(row.users)}</td>
                                        <td className="px-2 py-2.5 text-right text-xs text-fg-2">{formatNumber(row.views)}</td>
                                        <td className="px-2 py-2.5 text-right text-xs text-fg-2">{formatNumber(row.uses)}</td>
                                        <td className="px-2 py-2.5 text-right text-xs font-semibold text-fg">{formatNumber(row.exports)}</td>
                                        <td className="px-2 py-2.5 text-right text-xs text-ok">{formatNumber(row.compile_success)}</td>
                                        <td className="px-2 py-2.5 text-right text-xs text-err">{formatNumber(row.compile_failed)}</td>
                                        <td className="px-2 py-2.5 text-right text-xs text-fg-2">{formatShare(row.success_rate)}</td>
                                        <td className="px-2 py-2.5 text-xs text-fg-3">{formatDateTime(row.last_used_at)}</td>
                                    </tr>
                                ))}
                                {data.ranking.length === 0 && (
                                    <tr>
                                        <td colSpan={10} className="px-2 py-8 text-center text-xs text-fg-3">
                                            No template aggregates are visible for this range.
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>

                    <div className="mt-4 grid gap-2 rounded-[var(--radius-md)] border border-line bg-surface-2/30 px-3 py-2.5 text-[10px] text-fg-3 sm:grid-cols-2">
                        <p>
                            Compilations: {formatNumber(data.reconciliation.compilation_success)} completed,{' '}
                            {formatNumber(data.reconciliation.compilation_failed)} failed. Attributed to a
                            template: {formatNumber(data.reconciliation.attributed_compile_success)} /{' '}
                            {formatNumber(data.reconciliation.attributed_compile_failed)}.
                        </p>
                        <p>
                            Suppressed rows hold {formatNumber(data.reconciliation.suppressed_compile_success)}{' '}
                            successful and {formatNumber(data.reconciliation.suppressed_compile_failed)}{' '}
                            failed compiles. Unattributed compiles:{' '}
                            {formatNumber(data.reconciliation.unattributed_compile_success + data.reconciliation.unattributed_compile_failed)}.
                        </p>
                    </div>
                </>
            ) : null}
        </section>
    )
}
