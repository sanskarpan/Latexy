'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminCredentialMixResponse,
    type AdminCredentialMixRow,
    type AdminCredentialSource,
} from '@/lib/api-client'
import { formatDateTime, formatMoney, formatNumber } from './admin-format'

const SOURCES: AdminCredentialSource[] = ['byok', 'platform', 'unknown']

const SOURCE_LABELS: Record<AdminCredentialSource, string> = {
    byok: 'BYOK',
    platform: 'Platform key',
    unknown: 'Unknown',
}

const SOURCE_TONES: Record<AdminCredentialSource, string> = {
    byok: 'bg-accent',
    platform: 'bg-ok',
    unknown: 'bg-fg-3',
}

type Dimension = 'feature' | 'plan' | 'provider' | 'model' | 'persona' | 'day'

const DIMENSIONS: Array<{ key: Dimension; label: string; field: keyof AdminCredentialMixRow }> = [
    { key: 'feature', label: 'Feature', field: 'feature' },
    { key: 'plan', label: 'Plan', field: 'plan' },
    { key: 'provider', label: 'Provider', field: 'provider' },
    { key: 'model', label: 'Model', field: 'model' },
    { key: 'persona', label: 'Persona', field: 'persona' },
    { key: 'day', label: 'Day', field: 'date' },
]

function formatPercent(value: number | null | undefined): string {
    return `${(Number.isFinite(value ?? NaN) ? Number(value) : 0).toFixed(1)}%`
}

function sourceLabel(source: AdminCredentialSource): string {
    return SOURCE_LABELS[source] ?? 'Unknown'
}

function MetricCard({
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
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">
                {label}
            </p>
            <p className={`mt-1 text-xl font-semibold tracking-tight ${tone ?? 'text-fg'}`}>
                {value}
            </p>
            {detail && <p className="mt-1 text-[10px] leading-relaxed text-fg-3">{detail}</p>}
        </div>
    )
}

function DailyMix({ data }: { data: AdminCredentialMixResponse }) {
    const days = useMemo(() => {
        const grouped = new Map<string, Record<AdminCredentialSource, number>>()
        for (const row of data.by_day) {
            if (!row.date) continue
            const bucket = grouped.get(row.date) ?? { byok: 0, platform: 0, unknown: 0 }
            bucket[row.credential_source] += row.calls
            grouped.set(row.date, bucket)
        }
        return [...grouped.entries()]
            .sort(([left], [right]) => left.localeCompare(right))
            .slice(-30)
    }, [data.by_day])

    if (days.length === 0) {
        return (
            <p className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-4 text-xs text-fg-3">
                No daily mix is visible for this selection; small daily cohorts are suppressed.
            </p>
        )
    }

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3 text-[10px] text-fg-3">
                {SOURCES.map(source => (
                    <span key={source} className="inline-flex items-center gap-1.5">
                        <span
                            className={`h-2 w-2 rounded-sm ${SOURCE_TONES[source]}`}
                            aria-hidden="true"
                        />
                        {sourceLabel(source)}
                    </span>
                ))}
                <span className="ml-auto">
                    Last {days.length} visible day{days.length === 1 ? '' : 's'}
                </span>
            </div>
            <div
                className="space-y-1.5"
                role="img"
                aria-label="Daily BYOK, platform and unknown call mix"
            >
                {days.map(([day, bucket]) => {
                    const total = bucket.byok + bucket.platform + bucket.unknown
                    return (
                        <div key={day} className="flex items-center gap-2">
                            <span className="w-20 shrink-0 font-mono text-[10px] text-fg-3">
                                {day.slice(5)}
                            </span>
                            <div className="flex h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-2">
                                {SOURCES.map(source => (
                                    <span
                                        key={source}
                                        className={SOURCE_TONES[source]}
                                        style={{
                                            width: `${total > 0 ? (bucket[source] / total) * 100 : 0}%`,
                                        }}
                                        title={`${day} · ${sourceLabel(source)}: ${formatNumber(bucket[source])} calls`}
                                    />
                                ))}
                            </div>
                            <span className="w-14 shrink-0 text-right text-[10px] text-fg-3">
                                {formatNumber(total)}
                            </span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

export default function AdminCredentialMix({ days }: { days: number }) {
    const [data, setData] = useState<AdminCredentialMixResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [dimension, setDimension] = useState<Dimension>('feature')
    const [draft, setDraft] = useState({
        plan: '',
        feature: '',
        provider: '',
        model: '',
        persona: '',
    })
    const [applied, setApplied] = useState({
        plan: '',
        feature: '',
        provider: '',
        model: '',
        persona: '',
    })
    const generation = useRef(0)

    const load = useCallback(async () => {
        const current = ++generation.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminCredentialMix({
                days,
                plan: applied.plan || undefined,
                feature: applied.feature || undefined,
                provider: applied.provider || undefined,
                model: applied.model || undefined,
                persona: applied.persona || undefined,
            })
            if (generation.current === current) setData(next)
        } catch (err) {
            if (generation.current === current) {
                setError(err instanceof Error ? err.message : 'Failed to load credential mix')
            }
        } finally {
            if (generation.current === current) setLoading(false)
        }
    }, [applied, days])

    useEffect(() => {
        void load()
        return () => {
            generation.current += 1
        }
    }, [load])

    const rows = useMemo(() => {
        if (!data) return []
        if (dimension === 'feature') return data.by_feature
        if (dimension === 'plan') return data.by_plan
        if (dimension === 'provider') return data.by_provider
        if (dimension === 'model') return data.by_model
        if (dimension === 'persona') return data.by_persona
        return data.by_day
    }, [data, dimension])

    const labelField = DIMENSIONS.find(item => item.key === dimension)?.field ?? 'feature'
    const filterCount = Object.values(applied).filter(Boolean).length

    return (
        <section
            aria-labelledby="admin-credential-mix-heading"
            className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface"
        >
            <div className="border-b border-line px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h3
                            id="admin-credential-mix-heading"
                            className="text-sm font-semibold text-fg"
                        >
                            BYOK vs platform-key mix
                        </h3>
                        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                            Calls, tokens and estimated provider cost split by credential ownership.
                            Key ownership is shown as counts only; key material, ciphertext, key
                            names and fingerprints are never returned.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-[10px] text-fg-3">
                        <span className="rounded-full border border-line bg-surface-2 px-2 py-1">
                            {formatDateTime(data?.generated_at)}
                        </span>
                        {filterCount > 0 && (
                            <span className="rounded-full border border-accent/30 bg-accent-soft px-2 py-1 text-accent-strong">
                                {filterCount} filter{filterCount === 1 ? '' : 's'} applied
                            </span>
                        )}
                    </div>
                </div>

                <div className="mt-3 flex flex-wrap items-end gap-2">
                    {(
                        [
                            ['plan', 'Plan', 50],
                            ['feature', 'Feature', 120],
                            ['provider', 'Provider', 80],
                            ['model', 'Model', 160],
                            ['persona', 'Persona', 64],
                        ] as const
                    ).map(([key, label, maxLength]) => (
                        <label key={key} className="text-[10px] text-fg-3">
                            {label}
                            <input
                                value={draft[key]}
                                maxLength={maxLength}
                                onChange={event =>
                                    setDraft(current => ({ ...current, [key]: event.target.value }))
                                }
                                onKeyDown={event => {
                                    if (event.key === 'Enter') setApplied(draft)
                                }}
                                className="mt-0.5 block min-h-[34px] w-28 rounded border border-line bg-bg px-2 py-1 text-xs text-fg"
                            />
                        </label>
                    ))}
                    <button
                        type="button"
                        onClick={() => setApplied(draft)}
                        disabled={loading}
                        className="min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        Apply filters
                    </button>
                    {filterCount > 0 && (
                        <button
                            type="button"
                            onClick={() => {
                                const empty = {
                                    plan: '',
                                    feature: '',
                                    provider: '',
                                    model: '',
                                    persona: '',
                                }
                                setDraft(empty)
                                setApplied(empty)
                            }}
                            className="min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-3 hover:bg-surface-2"
                        >
                            Clear
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="ml-auto min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        {loading ? 'Refreshing…' : 'Refresh'}
                    </button>
                </div>
            </div>

            {error && (
                <div
                    role="alert"
                    className="border-b border-err/20 bg-err/[0.06] px-5 py-3 text-xs text-err"
                >
                    {data
                        ? 'Showing the last successful mix. Refresh failed: '
                        : 'Credential mix could not be loaded: '}
                    {error}
                </div>
            )}

            {!data ? (
                <div role="status" className="px-5 py-10 text-center text-sm text-fg-3">
                    {loading
                        ? 'Loading credential mix…'
                        : 'No credential mix is available for this selection.'}
                </div>
            ) : (
                <div className="space-y-5 p-5">
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
                        <MetricCard
                            label="Total calls"
                            value={formatNumber(data.totals.calls)}
                            detail={`${formatNumber(data.totals.tokens)} tokens · ${formatNumber(data.totals.users)} users`}
                        />
                        <MetricCard
                            label="BYOK calls"
                            value={formatNumber(data.totals.mix.byok.calls)}
                            detail={`${formatPercent(data.totals.mix.byok.call_share_pct)} of calls · ${formatPercent(
                                data.totals.mix.byok.cost_share_pct
                            )} of cost`}
                            tone="text-accent-strong"
                        />
                        <MetricCard
                            label="Platform calls"
                            value={formatNumber(data.totals.mix.platform.calls)}
                            detail={`${formatPercent(data.totals.mix.platform.call_share_pct)} of calls · ${formatPercent(
                                data.totals.mix.platform.cost_share_pct
                            )} of cost`}
                            tone="text-ok"
                        />
                        <MetricCard
                            label="Unknown source"
                            value={formatNumber(data.totals.mix.unknown.calls)}
                            detail={`${formatPercent(data.totals.mix.unknown.call_share_pct)} of calls · older rows without a source`}
                        />
                        <MetricCard
                            label="Estimated AI cost"
                            value={formatMoney(data.totals.cost_usd, data.currency)}
                            detail={`${formatNumber(data.totals.classified_calls)} classified · ${formatPercent(
                                data.totals.classified_share_pct
                            )} of calls`}
                        />
                    </div>

                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                        <div className="overflow-x-auto rounded-md border border-line">
                            <table className="w-full min-w-[460px] border-collapse text-xs">
                                <caption className="sr-only">
                                    Call, token and cost mix by credential source
                                </caption>
                                <thead>
                                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Source
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Calls
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Call share
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Tokens
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Token share
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Est. cost
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Cost share
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {SOURCES.map(source => {
                                        const row = data.totals.mix[source]
                                        return (
                                            <tr key={source} className="border-t border-line">
                                                <th
                                                    scope="row"
                                                    className="px-3 py-2 text-left font-medium text-fg"
                                                >
                                                    <span className="inline-flex items-center gap-1.5">
                                                        <span
                                                            className={`h-2 w-2 rounded-sm ${SOURCE_TONES[source]}`}
                                                            aria-hidden="true"
                                                        />
                                                        {sourceLabel(source)}
                                                    </span>
                                                </th>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                                    {formatNumber(row.calls)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                                    {formatPercent(row.call_share_pct)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                                    {formatNumber(row.tokens)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                                    {formatPercent(row.token_share_pct)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                                    {formatMoney(row.cost_usd, data.currency)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                                    {formatPercent(row.cost_share_pct)}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>

                        <div className="rounded-md border border-line p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                    <h4 className="text-xs font-semibold text-fg">Key ownership</h4>
                                    <p className="mt-0.5 text-[10px] text-fg-3">
                                        Active accounts and stored keys; no key data.
                                    </p>
                                </div>
                                <span className="rounded-full border border-line bg-surface-2 px-2 py-1 text-[10px] text-fg-3">
                                    {formatNumber(data.key_ownership.users_with_active_keys)} users
                                </span>
                            </div>
                            <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                                <div className="rounded border border-line bg-surface-2/50 px-2 py-2">
                                    <p className="text-[10px] text-fg-3">Active keys</p>
                                    <p className="mt-0.5 text-sm font-semibold text-fg">
                                        {formatNumber(data.key_ownership.active_keys)}
                                    </p>
                                </div>
                                <div className="rounded border border-line bg-surface-2/50 px-2 py-2">
                                    <p className="text-[10px] text-fg-3">Inactive</p>
                                    <p className="mt-0.5 text-sm font-semibold text-fg">
                                        {formatNumber(data.key_ownership.inactive_keys)}
                                    </p>
                                </div>
                                <div className="rounded border border-line bg-surface-2/50 px-2 py-2">
                                    <p className="text-[10px] text-fg-3">Any key</p>
                                    <p className="mt-0.5 text-sm font-semibold text-fg">
                                        {formatNumber(data.key_ownership.users_with_any_keys)}
                                    </p>
                                </div>
                            </div>
                            <div className="mt-3 overflow-x-auto">
                                <table className="w-full border-collapse text-[11px]">
                                    <caption className="sr-only">
                                        Active BYOK key ownership by provider
                                    </caption>
                                    <thead>
                                        <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                            <th
                                                scope="col"
                                                className="py-1.5 text-left font-semibold"
                                            >
                                                Provider
                                            </th>
                                            <th
                                                scope="col"
                                                className="py-1.5 text-right font-semibold"
                                            >
                                                Active
                                            </th>
                                            <th
                                                scope="col"
                                                className="py-1.5 text-right font-semibold"
                                            >
                                                Users
                                            </th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.key_ownership.by_provider.map(row => (
                                            <tr key={row.provider} className="border-t border-line">
                                                <th
                                                    scope="row"
                                                    className="py-1.5 text-left font-medium text-fg-2"
                                                >
                                                    {row.provider}
                                                </th>
                                                <td className="py-1.5 text-right tabular-nums text-fg">
                                                    {formatNumber(row.active_keys)}
                                                </td>
                                                <td className="py-1.5 text-right tabular-nums text-fg-2">
                                                    {formatNumber(row.users)}
                                                </td>
                                            </tr>
                                        ))}
                                        {data.key_ownership.by_provider.length === 0 && (
                                            <tr>
                                                <td
                                                    colSpan={3}
                                                    className="py-3 text-center text-fg-3"
                                                >
                                                    No provider group has at least{' '}
                                                    {data.key_ownership.minimum_group_size}{' '}
                                                    key-owning users.
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>
                            <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
                                {data.key_ownership.note}
                            </p>
                        </div>
                    </div>

                    <DailyMix data={data} />

                    <div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                                <h4 className="text-xs font-semibold text-fg">
                                    Breakdown by dimension
                                </h4>
                                <p className="mt-0.5 text-[10px] text-fg-3">
                                    Rows below {data.minimum_group_size} users or{' '}
                                    {data.minimum_group_size} calls are hidden.
                                </p>
                            </div>
                            <div
                                className="inline-flex flex-wrap rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                                role="group"
                                aria-label="Credential mix dimension"
                            >
                                {DIMENSIONS.map(item => (
                                    <button
                                        key={item.key}
                                        type="button"
                                        aria-pressed={dimension === item.key}
                                        onClick={() => setDimension(item.key)}
                                        className={`rounded px-2.5 py-1 text-[11px] font-medium transition ${
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
                        <div className="mt-2 overflow-x-auto rounded-md border border-line">
                            <table className="w-full min-w-[560px] border-collapse text-xs">
                                <caption className="sr-only">Credential mix by {dimension}</caption>
                                <thead>
                                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            {DIMENSIONS.find(item => item.key === dimension)
                                                ?.label ?? 'Group'}
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Source
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Calls
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Share
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Tokens
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Est. cost
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Users
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map((row, index) => {
                                        const label = String(row[labelField] ?? 'unknown')
                                        return (
                                            <tr
                                                key={`${label}-${row.credential_source}-${index}`}
                                                className="border-t border-line"
                                            >
                                                <th
                                                    scope="row"
                                                    className="px-3 py-2 text-left font-medium text-fg"
                                                >
                                                    {label}
                                                </th>
                                                <td className="px-3 py-2 text-fg-2">
                                                    {sourceLabel(row.credential_source)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                                    {formatNumber(row.calls)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                                    {formatPercent(row.call_share_pct)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                                    {formatNumber(row.tokens)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                                    {formatMoney(row.cost_usd, data.currency)}
                                                </td>
                                                <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                                    {formatNumber(row.users)}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                    {rows.length === 0 && (
                                        <tr>
                                            <td
                                                colSpan={7}
                                                className="px-3 py-6 text-center text-fg-3"
                                            >
                                                No {dimension} group in this selection has at least{' '}
                                                {data.minimum_group_size} users and calls.
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
                        <div className="rounded-md border border-line p-3">
                            <h4 className="text-xs font-semibold text-fg">Reconciliation</h4>
                            <ul className="mt-2 space-y-1.5">
                                {data.reconciliation.checks.map(check => (
                                    <li
                                        key={check.key}
                                        className="flex items-start justify-between gap-3 text-[11px]"
                                    >
                                        <span className="text-fg-2">{check.label}</span>
                                        <span
                                            className={`shrink-0 font-medium ${check.ok ? 'text-ok' : 'text-err'}`}
                                        >
                                            {check.ok
                                                ? 'Balanced'
                                                : `Mismatch · ${formatNumber(check.actual)} vs ${formatNumber(check.expected)}`}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                            <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-line pt-3 text-[11px]">
                                {data.reconciliation.ledgers.map(ledger => (
                                    <div key={ledger.source}>
                                        <dt className="text-fg-3">{ledger.table}</dt>
                                        <dd className="mt-0.5 font-medium text-fg">
                                            {formatNumber(ledger.calls)} calls ·{' '}
                                            {formatNumber(ledger.tokens)} tokens
                                        </dd>
                                    </div>
                                ))}
                                <div>
                                    <dt className="text-fg-3">Unknown source</dt>
                                    <dd className="mt-0.5 font-medium text-fg">
                                        {formatNumber(data.reconciliation.unknown_calls)} calls
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Share total</dt>
                                    <dd className="mt-0.5 font-medium text-fg">
                                        {formatPercent(data.reconciliation.call_share_total_pct)}
                                    </dd>
                                </div>
                            </dl>
                        </div>

                        <div className="rounded-md border border-line p-3">
                            <h4 className="text-xs font-semibold text-fg">Privacy and coverage</h4>
                            <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                                {data.credential_source_note}
                            </p>
                            <p className="mt-2 text-[11px] leading-relaxed text-fg-3">
                                {data.reconciliation.unknown_policy}
                            </p>
                            <p className="mt-2 text-[11px] leading-relaxed text-fg-3">
                                {data.suppressed_groups > 0
                                    ? `${formatNumber(data.suppressed_groups)} small breakdown group${
                                          data.suppressed_groups === 1 ? '' : 's'
                                      } hidden.`
                                    : `All visible groups have at least ${data.minimum_group_size} users and calls.`}{' '}
                                {data.privacy.aggregate_only
                                    ? 'Aggregate-only; no per-user rows.'
                                    : ''}
                            </p>
                        </div>
                    </div>
                </div>
            )}
        </section>
    )
}
