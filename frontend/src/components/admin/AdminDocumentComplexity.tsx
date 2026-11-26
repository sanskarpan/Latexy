'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminDocumentComplexityBucket,
    type AdminDocumentComplexityResponse,
    type AdminDocumentComplexitySegment,
} from '@/lib/api-client'
import { formatNumber } from '@/components/admin/admin-format'

const RANGES = [
    { days: 7, label: '7d' },
    { days: 30, label: '30d' },
    { days: 90, label: '90d' },
] as const

const PLAN_OPTIONS = ['free', 'basic', 'pro', 'byok', 'team']
const COMPILER_OPTIONS = ['pdflatex', 'xelatex', 'lualatex']

type Dimension = 'plan' | 'compiler' | 'template'

const DIMENSIONS: Array<{ key: Dimension; label: string }> = [
    { key: 'plan', label: 'Plan' },
    { key: 'compiler', label: 'Compiler' },
    { key: 'template', label: 'Template' },
]

function formatPct(value: number | null | undefined): string {
    return `${(Number.isFinite(value) ? Number(value) : 0).toFixed(1)}%`
}

function formatShare(value: number | null | undefined): string {
    return `${((Number.isFinite(value) ? Number(value) : 0) * 100).toFixed(1)}%`
}

function formatSeconds(value: number | null | undefined): string {
    return value == null || !Number.isFinite(Number(value)) ? 'n/a' : `${Number(value).toFixed(2)}s`
}

function formatPages(value: number | null | undefined): string {
    return value == null || !Number.isFinite(Number(value)) ? 'n/a' : Number(value).toFixed(2)
}

function formatId(value: string): string {
    return value.length > 18 ? `${value.slice(0, 8)}...${value.slice(-4)}` : value
}

function dimensionRows(
    data: AdminDocumentComplexityResponse,
    dimension: Dimension
): AdminDocumentComplexitySegment[] {
    if (dimension === 'compiler') return data.by_compiler
    if (dimension === 'template') return data.by_template
    return data.by_plan
}

function SparseBadge() {
    return (
        <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn">
            Sparse
        </span>
    )
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/50 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">{label}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-fg">{value}</p>
            <p className="text-[10px] text-fg-3">{detail}</p>
        </div>
    )
}

function BucketBars({
    buckets,
    emptyLabel,
}: {
    buckets: AdminDocumentComplexityBucket[]
    emptyLabel: string
}) {
    const visible = buckets.filter(bucket => bucket.count > 0 || bucket.pct > 0)
    if (visible.length === 0) {
        return (
            <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                {emptyLabel}
            </div>
        )
    }
    const max = Math.max(...visible.map(bucket => bucket.count), 1)
    return (
        <div className="space-y-2">
            {visible.map(bucket => (
                <div
                    key={bucket.bucket}
                    className="grid grid-cols-[58px_1fr_58px] items-center gap-2"
                >
                    <span className="text-[10px] font-medium text-fg-3">{bucket.bucket}</span>
                    <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                        <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${Math.max(2, (bucket.count / max) * 100)}%` }}
                        />
                    </div>
                    <span className="text-right text-[10px] tabular-nums text-fg-2">
                        {formatNumber(bucket.count)} / {formatPct(bucket.pct)}
                    </span>
                </div>
            ))}
        </div>
    )
}

function FailureClassList({
    summary,
}: {
    summary: AdminDocumentComplexityResponse['failure_classes']
}) {
    const rows = summary.classes.filter(item => item.count > 0)
    if (rows.length === 0) {
        return <p className="text-xs text-fg-3">No failed compilations in this selection.</p>
    }
    return (
        <div className="space-y-2">
            {rows
                .slice()
                .sort((a, b) => b.count - a.count)
                .map(item => (
                    <div
                        key={item.error_class}
                        className="flex items-center justify-between gap-3 text-xs"
                    >
                        <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-medium text-fg">{item.label}</span>
                            {item.sparse && <SparseBadge />}
                        </span>
                        <span className="shrink-0 tabular-nums text-fg-3">
                            {formatNumber(item.count)} / {formatShare(item.share)}
                        </span>
                    </div>
                ))}
            <p className={`pt-1 text-[10px] ${summary.reconciled ? 'text-ok' : 'text-err'}`}>
                {summary.reconciled
                    ? `Classes reconcile to ${formatNumber(summary.failed_compilations)} failed compiles.`
                    : `Class total ${formatNumber(summary.class_total)} does not reconcile to ${formatNumber(
                          summary.failed_compilations
                      )} failed compiles.`}
            </p>
        </div>
    )
}

function SegmentDetail({ segment }: { segment: AdminDocumentComplexitySegment }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        {segment.dimension} detail
                    </p>
                    <h4 className="mt-0.5 text-sm font-semibold text-fg">{segment.label}</h4>
                    <p className="mt-1 text-[11px] text-fg-3">
                        {formatNumber(segment.compilations)} compiles across{' '}
                        {formatNumber(segment.users)} users;{' '}
                        {formatNumber(segment.completed_compilations)} completed,{' '}
                        {formatNumber(segment.failed_compilations)} failed.
                    </p>
                </div>
                <div className="flex flex-wrap gap-2 text-[10px] text-fg-3">
                    <span>Mean pages: {formatPages(segment.page_count.mean)}</span>
                    <span>P95 pages: {formatPages(segment.page_count.p95)}</span>
                    <span>P95 latency: {formatSeconds(segment.latency.p95_seconds)}</span>
                </div>
            </div>
            <div className="mt-4 grid gap-5 lg:grid-cols-2">
                <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Page-count buckets
                    </p>
                    <div className="mt-2">
                        <BucketBars
                            buckets={segment.page_count.buckets}
                            emptyLabel="No page-count samples in this segment."
                        />
                    </div>
                </div>
                <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Latency buckets
                    </p>
                    <div className="mt-2">
                        <BucketBars
                            buckets={segment.latency.buckets}
                            emptyLabel="No timed compiles in this segment."
                        />
                    </div>
                </div>
            </div>
            <div className="mt-4 grid gap-5 lg:grid-cols-2">
                <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Mutually exclusive failure classes
                    </p>
                    <div className="mt-2">
                        <FailureClassList summary={segment.failure_classes} />
                    </div>
                </div>
                <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Overflow indicators
                    </p>
                    <div className="mt-2 space-y-1.5 text-xs">
                        {segment.overflow.thresholds.map(item => (
                            <div
                                key={item.pages}
                                className="flex items-center justify-between gap-3"
                            >
                                <span className="text-fg-2">{item.label}</span>
                                <span className="tabular-nums text-fg-3">
                                    {formatNumber(item.count)} / {formatShare(item.share)}
                                </span>
                            </div>
                        ))}
                        <p className="pt-1 text-[10px] text-fg-3">
                            PDF-limit failures: {formatNumber(segment.overflow.pdf_limit_failures)}
                        </p>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default function AdminDocumentComplexity() {
    const [days, setDays] = useState<number>(30)
    const [plan, setPlan] = useState('')
    const [compiler, setCompiler] = useState('')
    const [templateInput, setTemplateInput] = useState('')
    const [template, setTemplate] = useState('')
    const [dimension, setDimension] = useState<Dimension>('plan')
    const [selectedValue, setSelectedValue] = useState<string | null>(null)
    const [data, setData] = useState<AdminDocumentComplexityResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminDocumentComplexity({
                days,
                plan: plan || undefined,
                compiler: compiler || undefined,
                template: template || undefined,
            })
            if (requestGeneration.current === generation) {
                setData(next)
                setSelectedValue(null)
            }
        } catch (err) {
            if (requestGeneration.current === generation) {
                setError(err instanceof Error ? err.message : 'Failed to load document complexity')
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

    const rows = data ? dimensionRows(data, dimension) : []
    const hiddenRows = data?.suppression.by_dimension[dimension] ?? 0
    const omittedRows = data?.segmentation.omitted_by_dimension[dimension] ?? 0
    const selected = rows.find(row => row.value === selectedValue) ?? rows[0] ?? null
    const hasFilters = Boolean(plan || compiler || template)

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">
                        Document complexity and error classes
                    </h3>
                    <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                        Page-count, section-count and compile-latency distributions for completed
                        compiles, with mutually exclusive failure classes and overflow indicators
                        segmented by plan, compiler and template. Only aggregate counts are read;
                        LaTeX/PDF content, error text and per-user rows are never returned. Cohorts
                        under {data?.minimum_users ?? 5} distinct users are suppressed.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Document complexity period"
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
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        {loading ? 'Refreshing...' : 'Refresh'}
                    </button>
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
                    Loading document complexity...
                </div>
            ) : data ? (
                <>
                    {data.suppressed && (
                        <div className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-4 py-3 text-xs text-warn">
                            Metrics suppressed: this selection contains fewer than{' '}
                            {data.minimum_users} distinct users. Widen the period or change filters.
                        </div>
                    )}

                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                        <MetricCard
                            label="Completed"
                            value={formatNumber(data.totals.completed_compilations)}
                            detail={`${formatNumber(data.totals.distinct_users)} distinct users in scope`}
                        />
                        <MetricCard
                            label="Failed"
                            value={formatNumber(data.totals.failed_compilations)}
                            detail={
                                data.failure_classes.reconciled
                                    ? 'Failure classes reconciled'
                                    : 'Failure class mismatch'
                            }
                        />
                        <MetricCard
                            label="Mean pages"
                            value={formatPages(data.page_count.mean)}
                            detail={`${formatNumber(data.page_count.samples)} page samples, ${formatNumber(
                                data.page_count.missing
                            )} missing`}
                        />
                        <MetricCard
                            label="P95 latency"
                            value={formatSeconds(data.latency.p95_seconds)}
                            detail={`${formatNumber(data.latency.samples)} timed samples`}
                        />
                    </div>

                    <div className="mt-4 grid gap-4 lg:grid-cols-2">
                        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
                            <div className="flex items-center justify-between gap-2">
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                    Page-count distribution
                                </h4>
                                <span className="text-[10px] text-fg-3">
                                    P50 {formatPages(data.page_count.p50)} / P95{' '}
                                    {formatPages(data.page_count.p95)}
                                </span>
                            </div>
                            <div className="mt-3">
                                <BucketBars
                                    buckets={data.page_count.buckets}
                                    emptyLabel="No successful page-count samples match this selection."
                                />
                            </div>
                        </div>
                        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
                            <div className="flex items-center justify-between gap-2">
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                    Compile-latency distribution
                                </h4>
                                <span className="text-[10px] text-fg-3">
                                    P50 {formatSeconds(data.latency.p50_seconds)} / P95{' '}
                                    {formatSeconds(data.latency.p95_seconds)}
                                </span>
                            </div>
                            <div className="mt-3">
                                <BucketBars
                                    buckets={data.latency.buckets}
                                    emptyLabel="No timed successful compiles match this selection."
                                />
                            </div>
                        </div>
                    </div>

                    <div className="mt-4 grid gap-4 lg:grid-cols-3">
                        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Failure classes
                            </h4>
                            <div className="mt-3">
                                <FailureClassList summary={data.failure_classes} />
                            </div>
                        </div>
                        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Overflow indicators
                            </h4>
                            <div className="mt-3 space-y-1.5 text-xs">
                                {data.overflow.thresholds.map(item => (
                                    <div
                                        key={item.pages}
                                        className="flex items-center justify-between gap-3"
                                    >
                                        <span className="text-fg-2">{item.label}</span>
                                        <span className="tabular-nums text-fg-3">
                                            {formatNumber(item.count)} / {formatShare(item.share)}
                                        </span>
                                    </div>
                                ))}
                                <p className="pt-1 text-[10px] text-fg-3">
                                    PDF-limit failures:{' '}
                                    {formatNumber(data.overflow.pdf_limit_failures)}
                                </p>
                            </div>
                        </div>
                        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Section counts
                            </h4>
                            <p className="mt-2 text-xs text-fg-2">
                                {formatNumber(data.sections.samples)} samples,{' '}
                                {formatNumber(data.sections.missing)} missing. Mean{' '}
                                {formatPages(data.sections.mean)}, P95{' '}
                                {formatPages(data.sections.p95)}.
                            </p>
                            <div className="mt-3">
                                <BucketBars
                                    buckets={data.sections.buckets}
                                    emptyLabel="No section-count samples match this selection."
                                />
                            </div>
                        </div>
                    </div>

                    <div className="mt-6 border-t border-line pt-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                    Segments
                                </h4>
                                <p className="mt-1 text-[11px] text-fg-3">
                                    {formatNumber(hiddenRows)} hidden under the five-user rule
                                    {omittedRows > 0
                                        ? `, ${formatNumber(omittedRows)} omitted by the cardinality cap`
                                        : ''}
                                    .
                                </p>
                            </div>
                            <div
                                className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                                role="group"
                                aria-label="Document complexity segment dimension"
                            >
                                {DIMENSIONS.map(entry => (
                                    <button
                                        key={entry.key}
                                        type="button"
                                        aria-pressed={dimension === entry.key}
                                        onClick={() => {
                                            setDimension(entry.key)
                                            setSelectedValue(null)
                                        }}
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

                        <div className="mt-3 overflow-x-auto">
                            <table className="w-full min-w-[760px] border-collapse text-left text-xs">
                                <caption className="sr-only">
                                    Document complexity by {dimension}, with user-suppressed cohorts
                                    hidden.
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                        <th scope="col" className="py-2 pr-3 font-semibold">
                                            {dimension}
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Users
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Compiles
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Failed
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            Mean pages
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            P95 pages
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-2 py-2 text-right font-semibold"
                                        >
                                            P95 latency
                                        </th>
                                        <th
                                            scope="col"
                                            className="pl-2 py-2 text-right font-semibold"
                                        >
                                            &gt; 2 pages
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.length === 0 && (
                                        <tr>
                                            <td colSpan={8} className="py-6 text-center text-fg-3">
                                                {data.suppressed
                                                    ? 'Metrics are suppressed for this selection.'
                                                    : 'No visible segments match these filters.'}
                                            </td>
                                        </tr>
                                    )}
                                    {rows.map(row => {
                                        const overflow = row.overflow.thresholds.find(
                                            item => item.pages === 2
                                        )
                                        const active = selected?.value === row.value
                                        return (
                                            <tr
                                                key={row.value}
                                                className={`border-t border-line ${
                                                    active ? 'bg-accent-soft/40' : ''
                                                }`}
                                            >
                                                <td className="py-2 pr-3">
                                                    <button
                                                        type="button"
                                                        aria-pressed={active}
                                                        onClick={() => setSelectedValue(row.value)}
                                                        className="flex max-w-[260px] items-center gap-2 text-left font-medium text-fg hover:text-accent-strong"
                                                    >
                                                        <span
                                                            className="truncate"
                                                            title={row.label}
                                                        >
                                                            {dimension === 'template'
                                                                ? formatId(row.label)
                                                                : row.label}
                                                        </span>
                                                        {row.sparse && <SparseBadge />}
                                                    </button>
                                                </td>
                                                <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatNumber(row.users)}
                                                </td>
                                                <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatNumber(row.compilations)}
                                                </td>
                                                <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatNumber(row.failed_compilations)}
                                                </td>
                                                <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatPages(row.page_count.mean)}
                                                </td>
                                                <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatPages(row.page_count.p95)}
                                                </td>
                                                <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatSeconds(row.latency.p95_seconds)}
                                                </td>
                                                <td className="pl-2 py-2 text-right tabular-nums text-fg-2">
                                                    {formatNumber(overflow?.count ?? 0)}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>

                        {selected && (
                            <div className="mt-4">
                                <SegmentDetail segment={selected} />
                            </div>
                        )}

                        {data.missing_dimensions.plan +
                            data.missing_dimensions.compiler +
                            data.missing_dimensions.template >
                            0 && (
                            <p className="mt-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
                                Missing attribution: {formatNumber(data.missing_dimensions.plan)}{' '}
                                plan, {formatNumber(data.missing_dimensions.compiler)} compiler,{' '}
                                {formatNumber(data.missing_dimensions.template)} template rows are
                                reported as unknown/untemplated.
                            </p>
                        )}
                    </div>

                    <p className="mt-4 text-[10px] leading-relaxed text-fg-3">
                        {formatNumber(data.reconciliation.anonymous_excluded)} anonymised compiles
                        are excluded from user-cohort segments. Aggregate metadata only: no LaTeX,
                        PDF text, document content, compile error text or per-user rows are
                        returned.
                    </p>
                </>
            ) : (
                <div className="mt-6 rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                    No document-complexity data available.
                </div>
            )}
        </section>
    )
}
