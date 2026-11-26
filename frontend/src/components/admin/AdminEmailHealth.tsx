'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminEmailHealthResponse,
    type AdminEmailHealthStatus,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from './admin-format'

const WINDOWS = [7, 30, 90] as const

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

function rate(value: number | null | undefined, withheld: boolean): string {
    if (withheld) return '—'
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)}%`
}

const STATUS_COPY: Record<AdminEmailHealthStatus, { label: string; tone: string }> = {
    ok: { label: 'Healthy', tone: 'border-ok/30 bg-ok/10 text-ok' },
    watch: { label: 'Watch', tone: 'border-warn/30 bg-warn/10 text-warn' },
    review: { label: 'Review needed', tone: 'border-err/30 bg-err/10 text-err' },
    unconfigured: {
        label: 'Webhook not configured',
        tone: 'border-line bg-surface-2 text-fg-3',
    },
}

export default function AdminEmailHealth() {
    const [days, setDays] = useState<number>(30)
    const [data, setData] = useState<AdminEmailHealthResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const requestId = useRef(0)

    const load = useCallback(async () => {
        const id = ++requestId.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminEmailHealth(days)
            if (requestId.current === id) setData(next)
        } catch (err) {
            if (requestId.current === id) {
                setError(
                    err instanceof Error ? err.message : 'Failed to load email delivery health.'
                )
            }
        } finally {
            if (requestId.current === id) setLoading(false)
        }
    }, [days])

    useEffect(() => {
        void load()
    }, [load])

    const summary = data?.summary
    const suppression = data?.suppression
    const status = suppression?.status ?? 'unconfigured'
    const statusCopy = STATUS_COPY[status]
    const ratesWithheld = summary?.rates_withheld ?? true

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Email delivery health</h3>
                    <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-fg-3">
                        Signed Resend delivery, bounce and complaint evidence mapped to document
                        deliveries. Counts are aggregates only; recipient addresses, subjects and
                        provider payloads are never stored or shown.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <label className="sr-only" htmlFor="admin-email-health-window">
                        Reporting window
                    </label>
                    <select
                        id="admin-email-health-window"
                        value={days}
                        onChange={event => setDays(Number(event.target.value))}
                        className="rounded border border-line bg-surface px-2 py-1 text-[11px] text-fg-2"
                    >
                        {WINDOWS.map(windowDays => (
                            <option key={windowDays} value={windowDays}>
                                Last {windowDays} days
                            </option>
                        ))}
                    </select>
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

            {summary && suppression && data ? (
                <div className="space-y-5 px-5 py-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <span
                                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusCopy.tone}`}
                            >
                                {statusCopy.label}
                            </span>
                            <span className="text-[10px] text-fg-3">
                                Provider {data.provider} · webhook{' '}
                                {data.signature_verification.configured
                                    ? 'signature verified'
                                    : 'secret missing'}
                            </span>
                        </div>
                        <span className="text-[10px] text-fg-3">
                            {formatDateTime(data.generated_at)} · {data.period.days} day window
                        </span>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                        <Metric
                            label="Delivered"
                            value={formatNumber(summary.events.delivered)}
                            detail={`${formatNumber(summary.attempted)} outcomes`}
                        />
                        <Metric
                            label="Bounces"
                            value={formatNumber(summary.events.bounced)}
                            detail={`${formatNumber(summary.events.delayed)} delayed`}
                        />
                        <Metric
                            label="Complaints"
                            value={formatNumber(summary.events.complained)}
                            detail={`${formatNumber(summary.events.failed)} failed`}
                        />
                        <Metric
                            label="Bounce rate"
                            value={rate(summary.bounce_rate_pct, ratesWithheld)}
                            detail={
                                ratesWithheld
                                    ? `Withheld below ${data.minimum_rate_sample} outcomes`
                                    : 'Bounced ÷ attempted'
                            }
                        />
                        <Metric
                            label="Complaint rate"
                            value={rate(summary.complaint_rate_pct, ratesWithheld)}
                            detail={
                                ratesWithheld
                                    ? `Withheld below ${data.minimum_rate_sample} outcomes`
                                    : 'Complaints ÷ attempted'
                            }
                        />
                        <Metric
                            label="Suppressed"
                            value={formatNumber(suppression.active_recipients)}
                            detail={`${formatNumber(suppression.added_in_period)} added · ${formatNumber(suppression.removed_in_period)} removed`}
                        />
                    </div>

                    <div className="grid gap-3 lg:grid-cols-3">
                        <Metric
                            label="Outbound accepted"
                            value={formatNumber(summary.outbound.accepted)}
                            detail={`${formatNumber(summary.outbound.failed)} failed · ${formatNumber(summary.outbound.pending)} pending`}
                        />
                        <Metric
                            label="Delivery rate"
                            value={rate(summary.delivery_rate_pct, ratesWithheld)}
                            detail={`${formatNumber(summary.events.suppression_added)} provider suppressions added`}
                        />
                        <Metric
                            label="Unknown events"
                            value={formatNumber(summary.events.unknown)}
                            detail="Acknowledged without retry"
                        />
                    </div>

                    <div className="rounded-md border border-line bg-surface-2/30 px-3 py-2 text-[10px] leading-relaxed text-fg-3">
                        <span className="font-semibold text-fg-2">
                            Suppression and reputation:{' '}
                        </span>
                        {suppression.policy} Review at{' '}
                        {suppression.review_thresholds.complaint_rate_pct}% complaints or{' '}
                        {suppression.review_thresholds.bounce_rate_pct}% bounces.
                        {ratesWithheld
                            ? ' Rates are withheld until the five-outcome minimum sample is met.'
                            : ''}
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">Recent failures</h4>
                        <div className="mt-3 overflow-x-auto rounded-md border border-line">
                            <table className="w-full min-w-[760px] border-collapse text-xs">
                                <caption className="sr-only">
                                    Recent bounce, complaint and delivery failures
                                </caption>
                                <thead>
                                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Event
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Bounce
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Delivery
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-left font-semibold"
                                        >
                                            Retry
                                        </th>
                                        <th
                                            scope="col"
                                            className="px-3 py-2 text-right font-semibold"
                                        >
                                            Occurred
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.recent_failures.map((item, index) => (
                                        <tr
                                            key={`${item.event_type}:${item.occurred_at}:${index}`}
                                            className="border-t border-line"
                                        >
                                            <td className="px-3 py-1.5 text-fg-2">
                                                {item.event_type}
                                            </td>
                                            <td className="px-3 py-1.5 text-fg-3">
                                                {item.bounce_type ?? '—'}
                                                {item.bounce_subtype
                                                    ? ` · ${item.bounce_subtype}`
                                                    : ''}
                                            </td>
                                            <td className="px-3 py-1.5 text-fg-3">
                                                {item.delivery_mapped
                                                    ? (item.delivery_status ?? 'mapped')
                                                    : 'unmapped'}
                                            </td>
                                            <td className="px-3 py-1.5 text-fg-3">
                                                {item.retryable ? 'transient' : 'no'}
                                            </td>
                                            <td className="px-3 py-1.5 text-right text-fg-3">
                                                {formatDateTime(item.occurred_at)}
                                            </td>
                                        </tr>
                                    ))}
                                    {data.recent_failures.length === 0 && (
                                        <tr>
                                            <td
                                                colSpan={5}
                                                className="px-3 py-5 text-center text-fg-3"
                                            >
                                                No bounce, complaint or delivery failures in this
                                                window.
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <div className="rounded-md border border-line px-3 py-2 text-[10px] leading-relaxed text-fg-3">
                        {data.notes.map(note => (
                            <p key={note}>{note}</p>
                        ))}
                    </div>
                </div>
            ) : (
                !error && (
                    <p role="status" className="px-5 py-6 text-xs text-fg-3">
                        Loading email delivery health…
                    </p>
                )
            )}
        </section>
    )
}
