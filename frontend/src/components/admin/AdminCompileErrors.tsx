'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminCompileErrorClassKey,
    type AdminCompileErrorsResponse,
} from '@/lib/api-client'
import { formatNumber } from '@/components/admin/admin-format'

const CLASS_ORDER: AdminCompileErrorClassKey[] = [
    'syntax',
    'missing_package',
    'timeout',
    'engine',
    'storage',
    'pdf_limit',
    'unknown',
]

const CLASS_COLORS: Record<AdminCompileErrorClassKey, string> = {
    syntax: 'bg-err',
    missing_package: 'bg-warn',
    timeout: 'bg-accent',
    engine: 'bg-ok',
    storage: 'bg-fg-2',
    pdf_limit: 'bg-fg-3',
    unknown: 'bg-line-2',
}

const CLASS_LABELS: Record<AdminCompileErrorClassKey, string> = {
    syntax: 'Syntax',
    missing_package: 'Missing package',
    timeout: 'Timeout',
    engine: 'Engine',
    storage: 'Storage',
    pdf_limit: 'PDF limit',
    unknown: 'Unknown',
}

function formatShare(value: number): string {
    return `${(Number.isFinite(value) ? value * 100 : 0).toFixed(1)}%`
}

function shortId(value: string): string {
    return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}

function ClassBadge({ errorClass }: { errorClass: AdminCompileErrorClassKey }) {
    return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-fg">
            <span
                className={`h-2 w-2 shrink-0 rounded-full ${CLASS_COLORS[errorClass]}`}
                aria-hidden="true"
            />
            {CLASS_LABELS[errorClass]}
        </span>
    )
}

function ErrorTrendChart({ data }: { data: AdminCompileErrorsResponse }) {
    const max = Math.max(...data.trend.map(point => point.failed_compilations), 1)
    const totals = data.trend.reduce((sum, point) => sum + point.failed_compilations, 0)

    if (data.trend.length === 0) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No failed compilations match these filters.
            </div>
        )
    }

    return (
        <div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                {CLASS_ORDER.map(key => (
                    <span
                        key={key}
                        className="inline-flex items-center gap-1.5 text-[10px] text-fg-3"
                    >
                        <span
                            className={`h-2 w-2 rounded-sm ${CLASS_COLORS[key]}`}
                            aria-hidden="true"
                        />
                        {CLASS_LABELS[key]}
                    </span>
                ))}
            </div>
            <div className="mt-3 overflow-x-auto">
                <div className="min-w-[560px]">
                    <div
                        className="flex h-40 items-end gap-[2px] border-b border-line"
                        aria-hidden="true"
                    >
                        {data.trend.map(point => (
                            <div
                                key={point.date}
                                className="group relative flex h-full min-w-[2px] flex-1 flex-col-reverse justify-start"
                                title={`${point.date}: ${formatNumber(point.failed_compilations)} failed`}
                            >
                                {CLASS_ORDER.map(key => {
                                    const count = point.by_class[key] ?? 0
                                    if (count <= 0) return null
                                    return (
                                        <div
                                            key={key}
                                            className={`${CLASS_COLORS[key]} w-full opacity-90`}
                                            style={{ height: `${(count / max) * 100}%` }}
                                        />
                                    )
                                })}
                            </div>
                        ))}
                    </div>
                    <div className="mt-1 flex justify-between text-[10px] text-fg-3">
                        <span>{data.trend[0]?.date}</span>
                        <span>{data.trend[data.trend.length - 1]?.date}</span>
                    </div>
                </div>
            </div>
            <table className="sr-only">
                <caption>
                    Daily failed compilations by class over {data.days} days, {formatNumber(totals)}{' '}
                    total.
                </caption>
                <thead>
                    <tr>
                        <th scope="col">Date</th>
                        {CLASS_ORDER.map(key => (
                            <th key={key} scope="col">
                                {CLASS_LABELS[key]}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {data.trend.map(point => (
                        <tr key={point.date}>
                            <td>{point.date}</td>
                            {CLASS_ORDER.map(key => (
                                <td key={key}>{point.by_class[key] ?? 0}</td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminCompileErrors({ days }: { days: number }) {
    const [errorClass, setErrorClass] = useState<AdminCompileErrorClassKey | ''>('')
    const [data, setData] = useState<AdminCompileErrorsResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminCompileErrors({
                days,
                error_class: errorClass || undefined,
            })
            if (requestGeneration.current === generation) setData(next)
        } catch (err) {
            if (requestGeneration.current === generation) {
                setError(err instanceof Error ? err.message : 'Failed to load compile errors')
            }
        } finally {
            if (requestGeneration.current === generation) setLoading(false)
        }
    }, [days, errorClass])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const availableClasses = useMemo(
        () => data?.classes.map(item => item.error_class) ?? [],
        [data]
    )

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Compile error taxonomy</h3>
                    <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
                        Failed compilations grouped by an allowlisted error class captured at write
                        time. Only aggregate counts and public template metadata are shown; raw logs
                        and document text never enter analytics.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Error class
                        <select
                            value={errorClass}
                            onChange={event =>
                                setErrorClass(event.target.value as AdminCompileErrorClassKey | '')
                            }
                            className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                        >
                            <option value="">All classes</option>
                            {availableClasses.map(key => (
                                <option key={key} value={key}>
                                    {CLASS_LABELS[key]}
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
                </div>
            </div>

            {error && (
                <div
                    role="alert"
                    className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
                >
                    {data ? 'Showing the last successful data. ' : ''}
                    Refresh failed: {error}
                </div>
            )}

            {!data && loading ? (
                <div role="status" className="mt-6 text-center text-xs text-fg-3">
                    Loading compile errors…
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        {[
                            {
                                label: 'Failed compiles',
                                value: formatNumber(data.totals.failed_compilations),
                                detail: `${formatNumber(data.totals.classes_with_errors)} classes`,
                            },
                            {
                                label: 'Classified',
                                value: formatNumber(data.totals.classified_compilations),
                                detail: 'Known taxonomy class',
                            },
                            {
                                label: 'Unknown',
                                value: formatNumber(data.totals.unknown_compilations),
                                detail: 'Legacy or unmatched signal',
                            },
                            {
                                label: 'Reconciliation',
                                value: data.totals.reconciled ? 'Aligned' : 'Mismatch',
                                detail: `${formatNumber(data.totals.class_total)} class total`,
                            },
                        ].map(metric => (
                            <div
                                key={metric.label}
                                className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2"
                            >
                                <p className="text-[10px] uppercase tracking-wider text-fg-3">
                                    {metric.label}
                                </p>
                                <p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">
                                    {metric.value}
                                </p>
                                <p className="text-[10px] text-fg-3">{metric.detail}</p>
                            </div>
                        ))}
                    </div>

                    {!data.totals.reconciled && (
                        <p className="mt-3 rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
                            Class totals do not reconcile to failed compilations. Refresh before
                            acting on these buckets.
                        </p>
                    )}

                    <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
                        <div className="overflow-x-auto">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Top errors
                            </h4>
                            <table className="mt-3 w-full min-w-[420px] border-collapse text-left text-xs">
                                <caption className="sr-only">
                                    Failed compilations by error class with affected templates
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                        <th scope="col" className="py-2 pr-3 font-semibold">
                                            Class
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Failures
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Share
                                        </th>
                                        <th scope="col" className="pl-2 py-2 font-semibold">
                                            Affected templates
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.top_errors.length === 0 && (
                                        <tr>
                                            <td colSpan={4} className="py-6 text-center text-fg-3">
                                                No failed compilations in this period.
                                            </td>
                                        </tr>
                                    )}
                                    {data.top_errors.map(bucket => (
                                        <tr
                                            key={bucket.error_class}
                                            className="border-t border-line align-top"
                                        >
                                            <td className="py-2.5 pr-3">
                                                <ClassBadge errorClass={bucket.error_class} />
                                                {bucket.sparse && (
                                                    <span className="ml-2 rounded-full border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-warn">
                                                        Sparse
                                                    </span>
                                                )}
                                            </td>
                                            <td className="px-2 py-2.5 text-right tabular-nums text-fg-2">
                                                {formatNumber(bucket.count)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right tabular-nums text-fg-2">
                                                {formatShare(bucket.share)}
                                            </td>
                                            <td className="pl-2 py-2.5">
                                                {bucket.affected_templates.length === 0 ? (
                                                    <span className="text-fg-3">
                                                        No template attribution
                                                    </span>
                                                ) : (
                                                    <ul className="space-y-1">
                                                        {bucket.affected_templates.map(template => (
                                                            <li key={template.template_id}>
                                                                <a
                                                                    href={template.href}
                                                                    className="font-medium text-accent-strong underline-offset-2 hover:underline"
                                                                    title={`Open ${template.template_name ?? template.template_id} preview`}
                                                                >
                                                                    {template.template_name ??
                                                                        shortId(
                                                                            template.template_id
                                                                        )}
                                                                </a>
                                                                <span className="ml-1.5 tabular-nums text-fg-3">
                                                                    {formatNumber(template.count)}
                                                                </span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                )}
                                                {bucket.unattributed_templates > 0 && (
                                                    <p className="mt-1 text-[10px] text-fg-3">
                                                        {formatNumber(
                                                            bucket.unattributed_templates
                                                        )}{' '}
                                                        without a template id
                                                    </p>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        <div>
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Daily trend
                            </h4>
                            <p className="mt-1 text-[11px] text-fg-3">
                                Failed compilations per day, stacked by class.
                            </p>
                            <div className="mt-3">
                                <ErrorTrendChart data={data} />
                            </div>
                        </div>
                    </div>
                </>
            ) : null}
        </section>
    )
}
