'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminContentLibraryResponse,
    type AdminContentLibraryRow,
    type AdminContentLibraryStatus,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from '@/components/admin/admin-format'

const RANGES = [7, 30, 90, 365] as const

const CATEGORY_OPTIONS = [
    { value: '', label: 'All categories' },
    { value: 'header', label: 'Header' },
    { value: 'experience', label: 'Experience' },
    { value: 'skills', label: 'Skills' },
    { value: 'education', label: 'Education' },
    { value: 'misc', label: 'Misc' },
] as const

const STATUS_OPTIONS: Array<{ value: AdminContentLibraryStatus; label: string }> = [
    { value: 'all', label: 'All items' },
    { value: 'active', label: 'Active in range' },
    { value: 'stale', label: 'Stale' },
    { value: 'unused', label: 'Never used' },
    { value: 'deleted', label: 'Deleted' },
]

const SCOPE_OPTIONS = [
    { value: '', label: 'Official and community' },
    { value: 'official', label: 'Official only' },
    { value: 'community', label: 'Community only' },
] as const

function formatPercent(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '0.0%'
    return `${value.toFixed(1)}%`
}

function rowLabel(row: AdminContentLibraryRow): string {
    if (row.title) return row.title
    return `Deleted snippet ${row.snippet_id.slice(0, 8)}`
}

function SummaryCard({
    label,
    value,
    detail,
    tone,
}: {
    label: string
    value: string
    detail: string
    tone?: string
}) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">{label}</p>
            <p className={`mt-1 text-lg font-semibold ${tone ?? 'text-fg'}`}>{value}</p>
            <p className="text-[10px] text-fg-3">{detail}</p>
        </div>
    )
}

export default function AdminContentLibraryQuality() {
    const [days, setDays] = useState(30)
    const [from, setFrom] = useState('')
    const [to, setTo] = useState('')
    const [category, setCategory] = useState('')
    const [status, setStatus] = useState<AdminContentLibraryStatus>('all')
    const [scope, setScope] = useState('')
    const [data, setData] = useState<AdminContentLibraryResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [exporting, setExporting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const requestGeneration = useRef(0)

    const params = useMemo(
        () => ({
            days,
            start_date: from || undefined,
            end_date: to || undefined,
            category: category || undefined,
            status,
            official: scope === 'official' ? true : scope === 'community' ? false : undefined,
        }),
        [days, from, to, category, status, scope]
    )

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminContentLibraryAdoption(params)
            if (generation === requestGeneration.current) setData(next)
        } catch (err) {
            if (generation === requestGeneration.current) {
                setError(
                    err instanceof Error ? err.message : 'Failed to load content library adoption'
                )
            }
        } finally {
            if (generation === requestGeneration.current) setLoading(false)
        }
    }, [params])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const downloadCsv = useCallback(async () => {
        setExporting(true)
        try {
            const blob = await apiClient.downloadAdminContentLibraryAdoptionCsv(params)
            const url = URL.createObjectURL(blob)
            const anchor = document.createElement('a')
            anchor.href = url
            anchor.download = `content-library-adoption-${days}d.csv`
            document.body.appendChild(anchor)
            anchor.click()
            anchor.remove()
            URL.revokeObjectURL(url)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'CSV export failed')
        } finally {
            setExporting(false)
        }
    }, [days, params])

    const macro = data?.macro_summary ?? null

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Content library adoption</h3>
                    <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                        Snippet installs, recorded uses, upvotes and macro execution by existing
                        content. Only aggregate counts are returned: snippet titles are the sole
                        stored label and no snippet body, macro source, document text, author or
                        per-user history is read. Snippet rows with one to four users are
                        suppressed; unused rows stay visible because they identify nobody. Deleted
                        snippets keep only an id/title/counter snapshot.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Content library adoption period"
                    >
                        {RANGES.map(range => (
                            <button
                                key={range}
                                type="button"
                                aria-pressed={days === range}
                                onClick={() => {
                                    setDays(range)
                                    setFrom('')
                                    setTo('')
                                }}
                                className={`rounded px-2.5 py-1.5 text-xs font-medium transition ${
                                    days === range
                                        ? 'bg-accent-soft text-accent-strong'
                                        : 'text-fg-3 hover:text-fg'
                                }`}
                            >
                                {range}d
                            </button>
                        ))}
                    </div>
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        {loading ? 'Refreshing…' : 'Refresh'}
                    </button>
                    <button
                        type="button"
                        onClick={() => void downloadCsv()}
                        disabled={exporting || !data}
                        className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
                    >
                        {exporting ? 'Preparing CSV…' : 'Export CSV'}
                    </button>
                </div>
            </div>

            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    Category
                    <select
                        value={category}
                        onChange={event => setCategory(event.target.value)}
                        className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    >
                        {CATEGORY_OPTIONS.map(option => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    Status
                    <select
                        value={status}
                        onChange={event =>
                            setStatus(event.target.value as AdminContentLibraryStatus)
                        }
                        className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    >
                        {STATUS_OPTIONS.map(option => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    Scope
                    <select
                        value={scope}
                        onChange={event => setScope(event.target.value)}
                        className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    >
                        {SCOPE_OPTIONS.map(option => (
                            <option key={option.value} value={option.value}>
                                {option.label}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    From
                    <input
                        type="date"
                        value={from}
                        onChange={event => setFrom(event.target.value)}
                        className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    />
                </label>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                    To
                    <input
                        type="date"
                        value={to}
                        onChange={event => setTo(event.target.value)}
                        className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                    />
                </label>
                <div className="self-end text-[10px] text-fg-3">
                    {data ? `${data.start_date} → ${data.end_date} · UTC` : 'Loading window…'}
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
                    Loading content library adoption…
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                        <SummaryCard
                            label="Visible snippets"
                            value={formatNumber(data.totals.snippets)}
                            detail={`${formatNumber(data.suppressed_snippets)} suppressed`}
                        />
                        <SummaryCard
                            label="Installs in range"
                            value={formatNumber(data.totals.installs)}
                            detail={`${formatNumber(data.totals.uses)} recorded uses`}
                        />
                        <SummaryCard
                            label="Upvotes (lifetime)"
                            value={formatNumber(data.totals.upvotes)}
                            detail={`${formatPercent(data.totals.upvote_ratio)} of installs`}
                        />
                        <SummaryCard
                            label="Stale / unused"
                            value={`${formatNumber(data.totals.stale_snippets)} / ${formatNumber(
                                data.totals.unused_snippets
                            )}`}
                            detail="No activity in range / ever"
                            tone="text-warn"
                        />
                        <SummaryCard
                            label="Deleted snapshots"
                            value={formatNumber(data.totals.deleted_snippets)}
                            detail="Id/title/counter only"
                        />
                    </div>

                    {data.suppressed && (
                        <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 text-xs text-fg-3">
                            Every matching snippet has fewer than {data.minimum_users} distinct
                            users. Widen the date range or remove a filter to view aggregates.
                        </div>
                    )}

                    <div className="mt-6">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                Snippet adoption
                            </h4>
                            <span className="text-[10px] text-fg-3">
                                {formatNumber(data.candidate_snippets)} candidate rows · floor{' '}
                                {data.minimum_users} users
                            </span>
                        </div>
                        <div className="mt-3 overflow-x-auto">
                            <table className="w-full min-w-[1180px] border-collapse text-sm">
                                <caption className="sr-only">
                                    Content library adoption by snippet, sorted by recorded uses
                                    then installs.
                                </caption>
                                <thead>
                                    <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                                        <th scope="col" className="px-2 py-2">
                                            #
                                        </th>
                                        <th scope="col" className="px-2 py-2">
                                            Snippet
                                        </th>
                                        <th scope="col" className="px-2 py-2">
                                            Category
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Users
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Active users
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Installers
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Inserts
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Uses
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Upvotes
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Upvote ratio
                                        </th>
                                        <th scope="col" className="px-2 py-2 text-right">
                                            Lifetime installs
                                        </th>
                                        <th scope="col" className="px-2 py-2">
                                            Last used
                                        </th>
                                        <th scope="col" className="px-2 py-2">
                                            Flags
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.ranking.map(row => (
                                        <tr
                                            key={row.snippet_id}
                                            className="border-b border-line/60 align-top"
                                        >
                                            <td className="px-2 py-2.5 text-xs text-fg-3">
                                                {row.rank}
                                            </td>
                                            <td className="px-2 py-2.5">
                                                <div className="flex flex-wrap items-center gap-1.5">
                                                    <span className="text-sm font-medium text-fg">
                                                        {rowLabel(row)}
                                                    </span>
                                                    {row.deleted && (
                                                        <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn">
                                                            Deleted
                                                        </span>
                                                    )}
                                                    {row.is_official && (
                                                        <span className="rounded-full border border-accent/30 bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent-strong">
                                                            Official
                                                        </span>
                                                    )}
                                                </div>
                                            </td>
                                            <td className="px-2 py-2.5 text-xs capitalize text-fg-2">
                                                {row.category?.replace(/_/g, ' ') ?? '—'}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.users)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.active_users)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.installers)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.inserts)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs font-semibold text-fg">
                                                {formatNumber(row.uses)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.upvotes)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatPercent(row.upvote_ratio)}
                                            </td>
                                            <td className="px-2 py-2.5 text-right text-xs text-fg-2">
                                                {formatNumber(row.lifetime_installs)}
                                            </td>
                                            <td className="px-2 py-2.5 text-xs text-fg-3">
                                                {formatDateTime(row.last_used_at)}
                                            </td>
                                            <td className="px-2 py-2.5 text-[10px] text-fg-3">
                                                {row.unused
                                                    ? 'Never used'
                                                    : row.stale
                                                      ? `Stale (${row.age_days}d)`
                                                      : row.active
                                                        ? 'Active'
                                                        : 'No range activity'}
                                            </td>
                                        </tr>
                                    ))}
                                    {data.ranking.length === 0 && (
                                        <tr>
                                            <td
                                                colSpan={13}
                                                className="px-2 py-8 text-center text-xs text-fg-3"
                                            >
                                                No snippet aggregates are visible for this range.
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="mt-6">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                            Macro adoption
                        </h4>
                        {!macro ? (
                            <div className="mt-3 rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 text-xs text-fg-3">
                                {data.macro_suppressed
                                    ? `Macro adoption is suppressed because fewer than ${data.minimum_users} macro owners exist in this window. No per-macro rows are ever emitted.`
                                    : 'No macro adoption is recorded for this window.'}
                            </div>
                        ) : (
                            <>
                                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                                    <SummaryCard
                                        label="Owners"
                                        value={formatNumber(macro.owners)}
                                        detail={`${formatNumber(macro.total_macros)} macros`}
                                    />
                                    <SummaryCard
                                        label="Script / recorded"
                                        value={`${formatNumber(macro.script_macros)} / ${formatNumber(
                                            macro.recorded_macros
                                        )}`}
                                        detail={`${formatNumber(macro.created_in_range)} created in range`}
                                    />
                                    <SummaryCard
                                        label="Used macros"
                                        value={formatNumber(macro.used_macros)}
                                        detail={`${formatNumber(macro.use_events)} executions`}
                                    />
                                    <SummaryCard
                                        label="Active owners"
                                        value={formatNumber(macro.active_owners)}
                                        detail={`Last ${formatDateTime(macro.last_used_at)}`}
                                    />
                                    <SummaryCard
                                        label="Stale / unused"
                                        value={`${formatNumber(macro.stale_macros)} / ${formatNumber(
                                            macro.unused_macros
                                        )}`}
                                        detail="No execution in range / ever"
                                        tone="text-warn"
                                    />
                                </div>
                                <p className="mt-2 text-[10px] text-fg-3">
                                    Aggregate-only because a macro has one owner. Names, recorded
                                    actions and script source are never selected.
                                </p>
                            </>
                        )}
                    </div>

                    <div className="mt-4 grid gap-2 rounded-[var(--radius-md)] border border-line bg-surface-2/30 px-3 py-2.5 text-[10px] text-fg-3 sm:grid-cols-2">
                        <p>
                            Reconciliation: {formatNumber(data.reconciliation.source_installs)}{' '}
                            installs / {formatNumber(data.reconciliation.source_uses)} uses /{' '}
                            {formatNumber(data.reconciliation.source_upvotes)} upvotes across{' '}
                            {formatNumber(data.reconciliation.candidate_snippets)} candidates;
                            suppressed residual{' '}
                            {formatNumber(data.reconciliation.suppressed_installs)} /{' '}
                            {formatNumber(data.reconciliation.suppressed_uses)} /{' '}
                            {formatNumber(data.reconciliation.suppressed_upvotes)}.{' '}
                            {data.reconciliation.reconciled
                                ? 'Reconciled.'
                                : 'Reconciliation pending.'}
                        </p>
                        <p>
                            Counter drift: {formatNumber(data.reconciliation.counter_install_drift)}{' '}
                            installs and {formatNumber(data.reconciliation.counter_upvote_drift)}{' '}
                            upvotes between snippet counters and row history. Upvotes are lifetime
                            because the source table has no timestamp; installs and uses obey the
                            selected range. Stale means no range activity and at least{' '}
                            {data.stale_after_days} days old.
                        </p>
                    </div>
                </>
            ) : null}
        </section>
    )
}
