'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminCompileLatencyBucket,
    type AdminCompileLatencyResponse,
} from '@/lib/api-client'
import { formatNumber } from '@/components/admin/admin-format'

const DIMENSIONS = [
    { key: 'plan', label: 'Plan family', bucketKey: 'by_plan' },
    { key: 'compiler', label: 'Compiler', bucketKey: 'by_compiler' },
    { key: 'template', label: 'Template', bucketKey: 'by_template' },
] as const

const PLAN_OPTIONS = ['free', 'basic', 'pro', 'byok', 'team']
const COMPILER_OPTIONS = ['pdflatex', 'xelatex', 'lualatex']

type DimensionKey = (typeof DIMENSIONS)[number]['key']
type DimensionBucketKey = (typeof DIMENSIONS)[number]['bucketKey']

function formatSeconds(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '—'
    return `${value.toFixed(2)}s`
}

function formatId(value: string): string {
    return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}

function SparseBadge() {
    return (
        <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn">
            Sparse
        </span>
    )
}

function PercentileBars({ buckets }: { buckets: AdminCompileLatencyBucket[] }) {
    const max = Math.max(
        ...buckets.map(
            bucket => bucket.p99_seconds ?? bucket.p95_seconds ?? bucket.p50_seconds ?? 0
        ),
        1
    )
    const rows = useMemo(
        () =>
            buckets.map(bucket => ({
                ...bucket,
                p50Width:
                    bucket.p50_seconds == null ? 0 : Math.max((bucket.p50_seconds / max) * 100, 1),
                p95Width:
                    bucket.p95_seconds == null ? 0 : Math.max((bucket.p95_seconds / max) * 100, 1),
                p99Width:
                    bucket.p99_seconds == null ? 0 : Math.max((bucket.p99_seconds / max) * 100, 1),
            })),
        [buckets, max]
    )

    if (rows.length === 0) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No completed compilations match these filters.
            </div>
        )
    }

    return (
        <div className="space-y-3" aria-hidden="true">
            {rows.map(bucket => (
                <div key={bucket.value}>
                    <div className="flex items-center justify-between gap-3 text-xs">
                        <span className="flex min-w-0 items-center gap-2 font-medium text-fg">
                            <span className="truncate">{formatId(bucket.value)}</span>
                            {bucket.sparse && <SparseBadge />}
                        </span>
                        <span className="shrink-0 text-fg-3">
                            {formatNumber(bucket.samples)} samples
                        </span>
                    </div>
                    <div className="mt-1.5 space-y-1">
                        <div className="flex items-center gap-2">
                            <span className="w-8 shrink-0 text-[10px] uppercase tracking-wider text-fg-3">
                                p50
                            </span>
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                                <div
                                    className="h-full rounded-full bg-accent"
                                    style={{ width: `${bucket.p50Width}%` }}
                                />
                            </div>
                            <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-fg-2">
                                {formatSeconds(bucket.p50_seconds)}
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="w-8 shrink-0 text-[10px] uppercase tracking-wider text-fg-3">
                                p95
                            </span>
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                                <div
                                    className="h-full rounded-full bg-warn"
                                    style={{ width: `${bucket.p95Width}%` }}
                                />
                            </div>
                            <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-fg-2">
                                {formatSeconds(bucket.p95_seconds)}
                            </span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="w-8 shrink-0 text-[10px] uppercase tracking-wider text-fg-3">
                                p99
                            </span>
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                                <div
                                    className="h-full rounded-full bg-err"
                                    style={{ width: `${bucket.p99Width}%` }}
                                />
                            </div>
                            <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-fg-2">
                                {formatSeconds(bucket.p99_seconds)}
                            </span>
                        </div>
                    </div>
                </div>
            ))}
        </div>
    )
}

export default function AdminCompileLatency({ days }: { days: number }) {
    const [dimension, setDimension] = useState<DimensionKey>('plan')
    const [plan, setPlan] = useState('')
    const [compiler, setCompiler] = useState('')
    const [templateInput, setTemplateInput] = useState('')
    const [template, setTemplate] = useState('')
    const [data, setData] = useState<AdminCompileLatencyResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminCompileLatency({
                days,
                plan: plan || undefined,
                compiler: compiler || undefined,
                template: template || undefined,
            })
            if (requestGeneration.current === generation) setData(next)
        } catch (err) {
            if (requestGeneration.current === generation) {
                setError(err instanceof Error ? err.message : 'Failed to load compile latency')
            }
        } finally {
            if (requestGeneration.current === generation) setLoading(false)
        }
    }, [compiler, days, plan, template])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const dimensionConfig = DIMENSIONS.find(entry => entry.key === dimension) ?? DIMENSIONS[0]
    const buckets = data?.[dimensionConfig.bucketKey as DimensionBucketKey] ?? []
    const hasFilters = Boolean(plan || compiler || template)

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Compile latency percentiles</h3>
                    <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
                        p50/p95/p99 over completed compilations in the selected period. Sparse
                        buckets stay visible but are marked below {data?.sparse_threshold ?? 20}{' '}
                        samples; missing attribution is counted, never guessed.
                    </p>
                </div>
                <div
                    className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                    role="group"
                    aria-label="Compile latency dimension"
                >
                    {DIMENSIONS.map(entry => (
                        <button
                            key={entry.key}
                            type="button"
                            aria-pressed={dimension === entry.key}
                            onClick={() => setDimension(entry.key)}
                            className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                                dimension === entry.key
                                    ? 'bg-accent-soft text-accent-strong'
                                    : 'text-fg-3 hover:text-fg'
                            }`}
                        >
                            {entry.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="mt-4 flex flex-wrap items-end gap-2">
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    Plan
                    <select
                        value={plan}
                        onChange={event => setPlan(event.target.value)}
                        className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    >
                        <option value="">All plans</option>
                        {PLAN_OPTIONS.map(value => (
                            <option key={value} value={value}>
                                {value}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    Compiler
                    <select
                        value={compiler}
                        onChange={event => setCompiler(event.target.value)}
                        className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    >
                        <option value="">All compilers</option>
                        {COMPILER_OPTIONS.map(value => (
                            <option key={value} value={value}>
                                {value}
                            </option>
                        ))}
                    </select>
                </label>
                <form
                    className="flex items-end gap-2"
                    onSubmit={event => {
                        event.preventDefault()
                        setTemplate(templateInput.trim())
                    }}
                >
                    <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Template id
                        <input
                            value={templateInput}
                            onChange={event => setTemplateInput(event.target.value)}
                            placeholder="UUID"
                            className="mt-1 block w-48 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg placeholder:text-fg-3"
                        />
                    </label>
                    <button
                        type="submit"
                        className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
                    >
                        Apply
                    </button>
                </form>
                {hasFilters && (
                    <button
                        type="button"
                        onClick={() => {
                            setPlan('')
                            setCompiler('')
                            setTemplate('')
                            setTemplateInput('')
                        }}
                        className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
                    >
                        Clear filters
                    </button>
                )}
                <button
                    type="button"
                    onClick={() => void load()}
                    disabled={loading}
                    className="ml-auto rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                >
                    {loading ? 'Refreshing…' : 'Refresh'}
                </button>
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
                    Loading compile latency…
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        {[
                            { label: 'p50', value: data.overall.p50_seconds },
                            { label: 'p95', value: data.overall.p95_seconds },
                            { label: 'p99', value: data.overall.p99_seconds },
                        ].map(metric => (
                            <div
                                key={metric.label}
                                className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2"
                            >
                                <p className="text-[10px] uppercase tracking-wider text-fg-3">
                                    {metric.label}
                                </p>
                                <p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">
                                    {formatSeconds(metric.value)}
                                </p>
                            </div>
                        ))}
                        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2">
                            <p className="text-[10px] uppercase tracking-wider text-fg-3">
                                Samples
                            </p>
                            <p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">
                                {formatNumber(data.overall.samples)}
                            </p>
                            <p className="text-[10px] text-fg-3">
                                {formatNumber(data.totals.timed_compilations)} timed /{' '}
                                {formatNumber(data.totals.completed_compilations)} completed
                            </p>
                        </div>
                    </div>

                    {data.totals.missing_dimension_fields > 0 && (
                        <p className="mt-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
                            Missing attribution: {formatNumber(data.missing_dimensions.plan)} plan,{' '}
                            {formatNumber(data.missing_dimensions.compiler)} compiler,{' '}
                            {formatNumber(data.missing_dimensions.template)} template
                            {data.overall.sparse ? ' · overall bucket is sparse' : ''}
                        </p>
                    )}

                    <div className="mt-5 grid gap-6 lg:grid-cols-2">
                        <div>
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                {dimensionConfig.label} comparison
                            </h4>
                            <div className="mt-3">
                                <PercentileBars buckets={buckets} />
                            </div>
                        </div>
                        <div className="overflow-x-auto">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Samples and tail latency
                            </h4>
                            <table className="mt-3 w-full min-w-[420px] border-collapse text-left text-xs">
                                <caption className="sr-only">
                                    Compile latency by {dimensionConfig.label.toLowerCase()},
                                    including sample counts and sparse markers
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                        <th scope="col" className="py-2 pr-3 font-semibold">
                                            {dimensionConfig.label}
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Samples
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            p50
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            p95
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            p99
                                        </th>
                                        <th
                                            scope="col"
                                            className="pl-2 py-2 text-right font-semibold"
                                        >
                                            Max
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {buckets.length === 0 && (
                                        <tr>
                                            <td colSpan={6} className="py-6 text-center text-fg-3">
                                                No buckets match these filters.
                                            </td>
                                        </tr>
                                    )}
                                    {buckets.map(bucket => (
                                        <tr key={bucket.value} className="border-t border-line">
                                            <td className="py-2 pr-3">
                                                <span
                                                    className="block truncate font-mono text-[11px] text-fg"
                                                    title={bucket.value}
                                                >
                                                    {formatId(bucket.value)}
                                                </span>
                                                {bucket.sparse && <SparseBadge />}
                                            </td>
                                            <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                {formatNumber(bucket.samples)}
                                            </td>
                                            <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                {formatSeconds(bucket.p50_seconds)}
                                            </td>
                                            <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                {formatSeconds(bucket.p95_seconds)}
                                            </td>
                                            <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                {formatSeconds(bucket.p99_seconds)}
                                            </td>
                                            <td className="pl-2 py-2 text-right tabular-nums text-fg-2">
                                                {formatSeconds(bucket.max_seconds)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="mt-6 overflow-x-auto border-t border-line pt-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                            Slowest buckets
                        </h4>
                        <p className="mt-1 text-[11px] text-fg-3">
                            Ranked by p95 across plan, compiler and template buckets.
                        </p>
                        <table className="mt-3 w-full min-w-[560px] border-collapse text-left text-xs">
                            <caption className="sr-only">
                                Slowest compile-latency buckets by p95
                            </caption>
                            <thead>
                                <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                    <th scope="col" className="py-2 pr-3 font-semibold">
                                        Dimension
                                    </th>
                                    <th scope="col" className="px-2 py-2 font-semibold">
                                        Bucket
                                    </th>
                                    <th scope="col" className="px-2 py-2 text-right font-semibold">
                                        Samples
                                    </th>
                                    <th scope="col" className="px-2 py-2 text-right font-semibold">
                                        p95
                                    </th>
                                    <th scope="col" className="px-2 py-2 text-right font-semibold">
                                        p99
                                    </th>
                                    <th scope="col" className="pl-2 py-2 text-right font-semibold">
                                        Mean
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.slowest.length === 0 && (
                                    <tr>
                                        <td colSpan={6} className="py-6 text-center text-fg-3">
                                            No timed compilations in this period.
                                        </td>
                                    </tr>
                                )}
                                {data.slowest.map(bucket => (
                                    <tr
                                        key={`${bucket.dimension}:${bucket.value}`}
                                        className="border-t border-line"
                                    >
                                        <td className="py-2 pr-3 capitalize text-fg-2">
                                            {bucket.dimension}
                                        </td>
                                        <td className="px-2 py-2">
                                            <span
                                                className="font-mono text-[11px] text-fg"
                                                title={bucket.value}
                                            >
                                                {formatId(bucket.value)}
                                            </span>
                                            {bucket.sparse && <SparseBadge />}
                                        </td>
                                        <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                            {formatNumber(bucket.samples)}
                                        </td>
                                        <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                            {formatSeconds(bucket.p95_seconds)}
                                        </td>
                                        <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                            {formatSeconds(bucket.p99_seconds)}
                                        </td>
                                        <td className="pl-2 py-2 text-right tabular-nums text-fg-2">
                                            {formatSeconds(bucket.mean_seconds)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            ) : null}
        </section>
    )
}
