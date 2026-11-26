'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminTrialHealthBucket,
    type AdminTrialHealthResponse,
    type AdminTrialHealthWindow,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from './admin-format'

const WINDOWS = [7, 30, 90] as const

function rate(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function count(value: number | null | undefined): string {
    return value == null ? 'suppressed' : formatNumber(value)
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">
                {label}
            </p>
            <p className="mt-1 text-xl font-semibold text-fg">{value}</p>
            {detail && <p className="mt-0.5 text-[10px] text-fg-3">{detail}</p>}
        </div>
    )
}

function DistributionTable({
    caption,
    labelHeading,
    rows,
    metric,
    emptyMessage,
}: {
    caption: string
    labelHeading: string
    rows: AdminTrialHealthBucket[]
    metric: 'devices' | 'clusters'
    emptyMessage: string
}) {
    const values = rows
        .map(row => row[metric] ?? null)
        .filter((value): value is number => value != null)
    const maximum = Math.max(...values, 1)

    return (
        <div className="mt-3 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[420px] border-collapse text-xs">
                <caption className="sr-only">{caption}</caption>
                <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            {labelHeading}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            {metric === 'devices' ? 'Devices' : 'Clusters'}
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Distribution
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => {
                        const value = row[metric] ?? null
                        return (
                            <tr key={row.label} className="border-t border-line">
                                <td className="px-3 py-1.5 text-fg-2">{row.label}</td>
                                <td className="px-3 py-1.5 text-right font-medium text-fg">
                                    {value == null
                                        ? row.suppressed
                                            ? 'suppressed'
                                            : '—'
                                        : formatNumber(value)}
                                </td>
                                <td className="px-3 py-1.5">
                                    <div className="h-1.5 min-w-[80px] rounded-full bg-surface-2">
                                        {value != null && value > 0 && (
                                            <div
                                                className="h-1.5 rounded-full bg-accent/60"
                                                style={{
                                                    width: `${Math.max(
                                                        4,
                                                        Math.round((value / maximum) * 100)
                                                    )}%`,
                                                }}
                                            />
                                        )}
                                    </div>
                                </td>
                            </tr>
                        )
                    })}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={3} className="px-3 py-5 text-center text-fg-3">
                                {emptyMessage}
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

function WindowSummary({ windows }: { windows: AdminTrialHealthWindow[] }) {
    const rows: Array<{
        label: string
        value: (window: AdminTrialHealthWindow) => string
    }> = [
        { label: 'Trial starts', value: window => formatNumber(window.trial_starts) },
        { label: 'Unique devices', value: window => formatNumber(window.unique_devices) },
        { label: 'Blocked devices', value: window => formatNumber(window.blocked_devices) },
        { label: 'Blocked share', value: window => rate(window.blocked_pct) },
        {
            label: 'Linked trials',
            value: window => count(window.conversion.attributed_trials),
        },
        { label: 'Paid trials', value: window => count(window.conversion.paid_trials) },
        { label: 'Trial → paid', value: window => rate(window.conversion.trial_to_paid_pct) },
        {
            label: 'Repeat clusters',
            value: window => count(window.repeat_device_distribution.repeat_clusters),
        },
        {
            label: 'Abuse clusters',
            value: window => count(window.repeat_device_distribution.abuse_clusters),
        },
    ]

    return (
        <div className="mt-3 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[560px] border-collapse text-xs">
                <caption className="sr-only">
                    Trial health signals for 7, 30 and 90 rolling days
                </caption>
                <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Signal
                        </th>
                        {windows.map(window => (
                            <th
                                key={window.days}
                                scope="col"
                                className="px-3 py-2 text-right font-semibold"
                            >
                                {window.days} days
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => (
                        <tr key={row.label} className="border-t border-line">
                            <th scope="row" className="px-3 py-1.5 text-left font-medium text-fg-2">
                                {row.label}
                            </th>
                            {windows.map(window => (
                                <td key={window.days} className="px-3 py-1.5 text-right text-fg">
                                    {row.value(window)}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminTrialHealth() {
    const [data, setData] = useState<AdminTrialHealthResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [selectedDays, setSelectedDays] = useState<number>(30)
    const requestId = useRef(0)

    const load = useCallback(async () => {
        const id = ++requestId.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminTrialHealth()
            if (requestId.current === id) setData(next)
        } catch (err) {
            if (requestId.current === id) {
                setError(
                    err instanceof Error ? err.message : 'Failed to load trial health signals.'
                )
            }
        } finally {
            if (requestId.current === id) setLoading(false)
        }
    }, [])

    useEffect(() => {
        void load()
    }, [load])

    const selected = data?.windows.find(window => window.days === selectedDays) ?? data?.windows[0]
    const noStarts = data?.windows.every(window => window.trial_starts === 0) ?? false

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">
                        Trial health and abuse signals
                    </h3>
                    <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-fg-3">
                        Trial starts, unique hashed devices, repeat-device clusters, usage,
                        conversion and bounded review signals. Device fingerprints and IPs are
                        hashed before aggregation and never displayed. This view is read-only and
                        never blocks or changes a trial.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Trial health period"
                    >
                        {WINDOWS.map(days => (
                            <button
                                key={days}
                                type="button"
                                aria-pressed={selectedDays === days}
                                onClick={() => setSelectedDays(days)}
                                className={`rounded px-2.5 py-1 text-[10px] font-medium ${
                                    selectedDays === days
                                        ? 'bg-accent-soft text-accent-strong'
                                        : 'text-fg-3 hover:text-fg'
                                }`}
                            >
                                {days} days
                            </button>
                        ))}
                    </div>
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                    >
                        Refresh
                    </button>
                </div>
            </div>

            {error && (
                <p
                    role="alert"
                    className="mx-5 mt-4 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
                >
                    {error}
                </p>
            )}

            {data && selected ? (
                <div className="space-y-5 px-5 py-4">
                    {noStarts && (
                        <p
                            role="status"
                            className="rounded-md border border-line bg-surface-2/30 px-3 py-2 text-[11px] text-fg-3"
                        >
                            No trial starts were recorded in the last 90 days. The distributions
                            below are empty but remain available.
                        </p>
                    )}

                    <div>
                        <h4 className="text-xs font-semibold text-fg">Rolling windows</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Counts are device-trial rows created in each window. 1–4 device cells
                            are suppressed; zero remains visible.
                        </p>
                        <WindowSummary windows={data.windows} />
                    </div>

                    <div>
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <h4 className="text-xs font-semibold text-fg">
                                Selected window: {selected.days} days
                            </h4>
                            <span className="text-[10px] text-fg-3">
                                {formatDateTime(selected.start)} → {formatDateTime(selected.end)}
                            </span>
                        </div>
                        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <Metric
                                label="Trial starts"
                                value={formatNumber(selected.trial_starts)}
                                detail={`${formatNumber(
                                    selected.devices_with_usage
                                )} devices used a trial`}
                            />
                            <Metric
                                label="Unique devices"
                                value={formatNumber(selected.unique_devices)}
                                detail="Hashed device keys"
                            />
                            <Metric
                                label="Blocked devices"
                                value={formatNumber(selected.blocked_devices)}
                                detail={`${rate(selected.blocked_pct)} of trial starts`}
                            />
                            <Metric
                                label="Trial → paid"
                                value={rate(selected.conversion.trial_to_paid_pct)}
                                detail={`${count(
                                    selected.conversion.paid_trials
                                )} paid of ${count(selected.conversion.attributed_trials)} linked`}
                            />
                            <Metric
                                label="Repeat clusters"
                                value={count(selected.repeat_device_distribution.repeat_clusters)}
                                detail={`${formatNumber(
                                    selected.repeat_device_distribution.devices_with_ip
                                )} devices have a hashed IP`}
                            />
                            <Metric
                                label="Abuse clusters"
                                value={count(selected.repeat_device_distribution.abuse_clusters)}
                                detail={`≥${selected.repeat_device_distribution.abuse_threshold_devices} devices on one hashed IP`}
                            />
                            <Metric
                                label="At trial limit"
                                value={formatNumber(selected.devices_at_or_above_limit)}
                                detail={`Current limit: ${data.trial_limit} uses`}
                            />
                            <Metric
                                label="Conversion coverage"
                                value={count(selected.conversion.attributed_trials)}
                                detail="Consented trial attribution links"
                            />
                        </div>
                    </div>

                    <div className="grid gap-5 lg:grid-cols-2">
                        <div>
                            <h4 className="text-xs font-semibold text-fg">Usage distribution</h4>
                            <p className="mt-1 text-[10px] text-fg-3">
                                Per-device trial uses in bounded buckets. The current enforcement
                                threshold is {data.trial_limit} uses; this report does not enforce
                                it.
                            </p>
                            <DistributionTable
                                caption="Trial usage distribution per device"
                                labelHeading="Trial uses"
                                rows={selected.usage_distribution.buckets}
                                metric="devices"
                                emptyMessage="No devices in this window."
                            />
                            <p className="mt-2 text-[10px] text-fg-3">
                                {formatNumber(selected.usage_distribution.total_devices)} devices;{' '}
                                {selected.usage_distribution.suppressed_buckets} bucket
                                {selected.usage_distribution.suppressed_buckets === 1
                                    ? ''
                                    : 's'}{' '}
                                suppressed.
                            </p>
                        </div>

                        <div>
                            <h4 className="text-xs font-semibold text-fg">
                                Repeat-device distribution
                            </h4>
                            <p className="mt-1 text-[10px] text-fg-3">
                                Distinct hashed device keys sharing a hashed IP in this window.
                                Shared NAT and office IPs can create false positives, so these are
                                review signals only.
                            </p>
                            <DistributionTable
                                caption="Distinct devices per hashed IP cluster"
                                labelHeading="Cluster size"
                                rows={selected.repeat_device_distribution.buckets}
                                metric="clusters"
                                emptyMessage="No hashed-IP clusters in this window."
                            />
                            <p className="mt-2 text-[10px] text-fg-3">
                                {formatNumber(selected.repeat_device_distribution.devices_with_ip)}{' '}
                                devices with an IP,{' '}
                                {formatNumber(
                                    selected.repeat_device_distribution.devices_without_ip
                                )}{' '}
                                without. {count(selected.repeat_device_distribution.abuse_devices)}{' '}
                                devices are in abuse-threshold clusters.
                            </p>
                        </div>
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">
                            Top bounded rejection and abuse reasons
                        </h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Persisted-state signals in the selected window. They overlap, so a
                            device can match more than one reason; these are not request-time
                            rejection events.
                        </p>
                        <div className="mt-3 overflow-x-auto rounded-md border border-line">
                            <table className="w-full min-w-[720px] border-collapse text-xs">
                                <caption className="sr-only">
                                    Bounded trial rejection and abuse signals
                                </caption>
                                <thead>
                                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Signal
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Devices
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Definition
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {selected.rejection_reasons.items.map(reason => (
                                        <tr key={reason.key} className="border-t border-line">
                                            <th
                                                scope="row"
                                                className="px-3 py-1.5 text-left font-medium text-fg-2"
                                            >
                                                {reason.label}
                                            </th>
                                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                                {reason.suppressed
                                                    ? 'suppressed'
                                                    : formatNumber(reason.devices ?? 0)}
                                            </td>
                                            <td className="px-3 py-1.5 text-fg-3">
                                                {reason.definition}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <p className="mt-2 text-[10px] text-fg-3">
                            {selected.rejection_reasons.suppressed} reason
                            {selected.rejection_reasons.suppressed === 1 ? '' : 's'} suppressed for
                            a 1–4 device cell. Signals are capped at eight fixed categories.
                        </p>
                    </div>

                    <div className="rounded-md border border-line bg-surface-2/30 px-3 py-2 text-[10px] leading-relaxed text-fg-3">
                        <span className="font-semibold text-fg-2">Reconciliation: </span>
                        {formatNumber(data.reconciliation.trial_starts_7d)} starts in 7 days,{' '}
                        {formatNumber(data.reconciliation.trial_starts_30d)} in 30 days and{' '}
                        {formatNumber(data.reconciliation.trial_starts_90d)} in 90 days (
                        {formatNumber(data.reconciliation.trial_starts_8_to_30d)} in days 8–30,{' '}
                        {formatNumber(data.reconciliation.trial_starts_31_to_90d)} in days 31–90).{' '}
                        {formatNumber(data.reconciliation.scanned_rows)} rows scanned
                        {data.reconciliation.rows_truncated
                            ? ' (row cap reached; detail is partial)'
                            : ''}
                        . 90-day conversion uses {count(data.reconciliation.attributed_trials_90d)}{' '}
                        consented linked trials and {count(data.reconciliation.paid_trials_90d)}{' '}
                        paid trials; {count(data.reconciliation.unattributed_trials_90d)} remain
                        unattributed.
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[10px] text-fg-3">
                        <span>
                            Minimum cohort: {data.minimum_cohort_size} devices. Repeat cluster
                            threshold: {data.repeat_device_cluster_threshold} devices per hashed IP.
                        </span>
                        <span>Generated {formatDateTime(data.generated_at)}</span>
                    </div>

                    <ul className="space-y-1 text-[10px] text-fg-3">
                        {data.notes.map(note => (
                            <li key={note}>• {note}</li>
                        ))}
                    </ul>
                </div>
            ) : (
                !error && (
                    <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
                        Loading trial health signals…
                    </div>
                )
            )}
        </section>
    )
}
