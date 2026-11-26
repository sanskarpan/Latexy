'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type AdminReferralSummaryResponse } from '@/lib/api-client'
import { formatDateTime, formatNumber } from './admin-format'

const PLAN_OPTIONS = ['', 'free', 'basic', 'pro', 'byok', 'team'] as const
const PROGRAMME_ISSUE_URL = 'https://github.com/sanskarpan/Latexy/issues/1341'

type AppliedFilters = {
    plan: string
    startDate: string
    endDate: string
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

function count(value: number | null | undefined): string {
    return value == null ? 'suppressed' : formatNumber(value)
}

function rate(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? 'suppressed' : `${value.toFixed(2)}%`
}

function statusLabel(status: string): string {
    return status.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase())
}

export default function AdminReferralAnalytics({ days }: { days: number }) {
    const [plan, setPlan] = useState('')
    const [startDate, setStartDate] = useState('')
    const [endDate, setEndDate] = useState('')
    const [applied, setApplied] = useState<AppliedFilters>({
        plan: '',
        startDate: '',
        endDate: '',
    })
    const [data, setData] = useState<AdminReferralSummaryResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [downloading, setDownloading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const generation = useRef(0)

    const load = useCallback(async () => {
        const current = ++generation.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminReferralSummary({
                days,
                plan: applied.plan || undefined,
                start_date: applied.startDate || undefined,
                end_date: applied.endDate || undefined,
            })
            if (generation.current === current) setData(next)
        } catch (err) {
            if (generation.current === current) {
                setError(err instanceof Error ? err.message : 'Failed to load referral analytics')
            }
        } finally {
            if (generation.current === current) setLoading(false)
        }
    }, [applied, days])

    useEffect(() => {
        void load()
    }, [load])

    const downloadCsv = useCallback(async () => {
        setDownloading(true)
        setError(null)
        try {
            const blob = await apiClient.downloadAdminReferralSummaryCsv({
                days,
                plan: applied.plan || undefined,
                start_date: applied.startDate || undefined,
                end_date: applied.endDate || undefined,
            })
            const url = URL.createObjectURL(blob)
            const anchor = document.createElement('a')
            anchor.href = url
            anchor.download = `referral-analytics-${data?.start_date ?? 'report'}-${data?.end_date ?? ''}.csv`
            document.body.appendChild(anchor)
            anchor.click()
            anchor.remove()
            URL.revokeObjectURL(url)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to download referral CSV')
        } finally {
            setDownloading(false)
        }
    }, [applied, data, days])

    const apply = () => {
        setApplied({ plan, startDate, endDate })
    }

    const suppressed = data?.suppressed ?? false
    const funnel = data?.funnel
    const rewards = data?.reward_summary
    const timing = data?.time_to_qualify
    const fraud = data?.fraud_review
    const reconciliation = data?.reconciliation

    return (
        <section
            className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
            aria-labelledby="admin-referral-analytics-heading"
        >
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h3
                        id="admin-referral-analytics-heading"
                        className="text-sm font-semibold text-fg"
                    >
                        Referral programme analytics
                    </h3>
                    <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-fg-3">
                        Aggregate referral capture, first-paid qualification, reward ledger,
                        rejection reasons and a manual fraud-review queue. Referral click-throughs
                        are not persisted; capture is the first reportable stage. Programme
                        ownership remains with{' '}
                        <a
                            className="font-medium text-accent-strong underline"
                            href={PROGRAMME_ISSUE_URL}
                            target="_blank"
                            rel="noreferrer"
                        >
                            issue #1341
                        </a>
                        ; this report is read-only.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => void downloadCsv()}
                    disabled={downloading || loading}
                    className="rounded border border-line bg-surface-2 px-3 py-1.5 text-xs font-medium text-fg-2 hover:text-fg disabled:opacity-50"
                >
                    {downloading ? 'Preparing CSV…' : 'Download CSV'}
                </button>
            </div>

            <div className="mt-4 flex flex-wrap items-end gap-2">
                <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                    {data ? `${data.start_date} to ${data.end_date}` : `${days}-day period`}
                </span>
                <select
                    aria-label="Referral plan filter"
                    value={plan}
                    onChange={event => setPlan(event.target.value)}
                    className="min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
                >
                    {PLAN_OPTIONS.map(item => (
                        <option key={item || 'all'} value={item}>
                            {item ? statusLabel(item) : 'All plans'}
                        </option>
                    ))}
                </select>
                <label className="text-[10px] text-fg-3">
                    Start
                    <input
                        type="date"
                        aria-label="Referral start date"
                        value={startDate}
                        onChange={event => setStartDate(event.target.value)}
                        className="ml-1 min-h-[38px] rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                    />
                </label>
                <label className="text-[10px] text-fg-3">
                    End
                    <input
                        type="date"
                        aria-label="Referral end date"
                        value={endDate}
                        onChange={event => setEndDate(event.target.value)}
                        className="ml-1 min-h-[38px] rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                    />
                </label>
                <button
                    type="button"
                    onClick={apply}
                    className="min-h-[38px] rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg"
                >
                    Apply
                </button>
            </div>

            {error && (
                <div
                    role="alert"
                    className="mt-4 rounded border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"
                >
                    {error}
                </div>
            )}

            {loading ? (
                <div role="status" className="px-3 py-8 text-center text-sm text-fg-3">
                    Loading referral analytics…
                </div>
            ) : !data ? (
                <div className="px-3 py-8 text-center text-sm text-fg-3">
                    Referral analytics unavailable.
                </div>
            ) : (
                <div className="mt-5 space-y-6">
                    {suppressed ? (
                        <div className="rounded-[var(--radius-md)] border border-dashed border-line bg-surface-2/30 px-4 py-6 text-center text-xs text-fg-3">
                            The selected referral cohort is below the five-user floor, so all
                            funnel, reward and fraud metrics are suppressed.
                        </div>
                    ) : (
                        <>
                            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
                                <Metric
                                    label="Captured"
                                    value={count(funnel?.captured)}
                                    detail="Attributed accounts"
                                />
                                <Metric
                                    label="Qualified"
                                    value={count(funnel?.qualified)}
                                    detail="First paid event verified"
                                />
                                <Metric
                                    label="Paid"
                                    value={count(funnel?.paid)}
                                    detail="Paid payment row present"
                                />
                                <Metric
                                    label="Paid conversion"
                                    value={rate(funnel?.paid_conversion_pct)}
                                    detail="Paid ÷ captured"
                                />
                                <Metric
                                    label="Currently qualified"
                                    value={count(funnel?.currently_qualified)}
                                    detail="Not reversed"
                                />
                                <Metric
                                    label="Reversed"
                                    value={count(funnel?.reversed)}
                                    detail={`${rate(funnel?.reversal_pct)} of qualified`}
                                />
                            </div>

                            <div className="grid gap-5 lg:grid-cols-2">
                                <div>
                                    <h4 className="text-xs font-semibold text-fg">Reward ledger</h4>
                                    <p className="mt-1 text-[10px] text-fg-3">
                                        Status and recorded extension days from referral_rewards.
                                        Values are ledger entries, not payouts.
                                    </p>
                                    <div className="mt-3 overflow-x-auto rounded-md border border-line">
                                        <table className="w-full min-w-[360px] border-collapse text-xs">
                                            <caption className="sr-only">
                                                Referral reward status and value
                                            </caption>
                                            <thead>
                                                <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                                    <th
                                                        scope="col"
                                                        className="px-3 py-2 text-left font-semibold"
                                                    >
                                                        Status
                                                    </th>
                                                    <th
                                                        scope="col"
                                                        className="px-3 py-2 text-right font-semibold"
                                                    >
                                                        Rewards
                                                    </th>
                                                    <th
                                                        scope="col"
                                                        className="px-3 py-2 text-right font-semibold"
                                                    >
                                                        Days
                                                    </th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {(rewards?.statuses ?? []).map(item => (
                                                    <tr
                                                        key={item.status}
                                                        className="border-t border-line"
                                                    >
                                                        <td className="px-3 py-1.5 text-fg-2">
                                                            {item.label}
                                                        </td>
                                                        <td className="px-3 py-1.5 text-right text-fg">
                                                            {formatNumber(item.rewards)}
                                                        </td>
                                                        <td className="px-3 py-1.5 text-right text-fg">
                                                            {formatNumber(item.value_days)}
                                                        </td>
                                                    </tr>
                                                ))}
                                                {(rewards?.statuses ?? []).length === 0 && (
                                                    <tr>
                                                        <td
                                                            colSpan={3}
                                                            className="px-3 py-5 text-center text-fg-3"
                                                        >
                                                            No visible reward groups.
                                                        </td>
                                                    </tr>
                                                )}
                                            </tbody>
                                        </table>
                                    </div>
                                    <p className="mt-2 text-[10px] text-fg-3">
                                        {count(rewards?.total_rewards)} rewards ·{' '}
                                        {count(rewards?.total_value_days)} recorded days · issued{' '}
                                        {count(rewards?.issued_value_days)}d, pending{' '}
                                        {count(rewards?.pending_value_days)}d, reversed{' '}
                                        {count(rewards?.reversed_value_days)}d. Payout status:{' '}
                                        {statusLabel(rewards?.payout_status ?? 'not_applicable')} —
                                        no cash payout path exists.
                                        {(rewards?.suppressed_statuses ?? 0) > 0 &&
                                            ` ${rewards?.suppressed_statuses} status group(s) suppressed.`}
                                    </p>
                                </div>

                                <div>
                                    <h4 className="text-xs font-semibold text-fg">
                                        Time to qualify
                                    </h4>
                                    <p className="mt-1 text-[10px] text-fg-3">
                                        Captured at to first paid qualification. Small samples and
                                        buckets are suppressed.
                                    </p>
                                    <div className="mt-3 grid gap-2 sm:grid-cols-3">
                                        <Metric
                                            label="Median"
                                            value={
                                                timing?.median_days == null
                                                    ? 'suppressed'
                                                    : `${timing.median_days.toFixed(2)}d`
                                            }
                                        />
                                        <Metric
                                            label="Average"
                                            value={
                                                timing?.average_days == null
                                                    ? 'suppressed'
                                                    : `${timing.average_days.toFixed(2)}d`
                                            }
                                        />
                                        <Metric
                                            label="P90"
                                            value={
                                                timing?.p90_days == null
                                                    ? 'suppressed'
                                                    : `${timing.p90_days.toFixed(2)}d`
                                            }
                                        />
                                    </div>
                                    <p className="mt-2 text-[10px] text-fg-3">
                                        Sample {count(timing?.sample_size)} qualified referrals.
                                        {(timing?.buckets ?? []).length > 0 &&
                                            ` Visible buckets: ${(timing?.buckets ?? [])
                                                .map(
                                                    item =>
                                                        `${item.label} (${formatNumber(item.count)})`
                                                )
                                                .join(', ')}.`}
                                    </p>
                                </div>
                            </div>

                            <div>
                                <h4 className="text-xs font-semibold text-fg">Rejection reasons</h4>
                                <p className="mt-1 text-[10px] text-fg-3">
                                    Persisted rejection and reversal reasons only. Claim attempts
                                    rejected before an attribution row exists are not stored, so
                                    they are not reported here.
                                </p>
                                <div className="mt-3 overflow-x-auto rounded-md border border-line">
                                    <table className="w-full min-w-[420px] border-collapse text-xs">
                                        <caption className="sr-only">
                                            Referral rejection reasons
                                        </caption>
                                        <thead>
                                            <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-left font-semibold"
                                                >
                                                    Reason
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Attributions
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {(data.rejection_reasons.items ?? []).map(item => (
                                                <tr
                                                    key={item.reason}
                                                    className="border-t border-line"
                                                >
                                                    <td
                                                        className="px-3 py-1.5 text-fg-2"
                                                        title={item.reason}
                                                    >
                                                        {item.label}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.count)}
                                                    </td>
                                                </tr>
                                            ))}
                                            {(data.rejection_reasons.items ?? []).length === 0 && (
                                                <tr>
                                                    <td
                                                        colSpan={2}
                                                        className="px-3 py-5 text-center text-fg-3"
                                                    >
                                                        No visible rejection reasons.
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                                {data.rejection_reasons.suppressed_reasons > 0 && (
                                    <p className="mt-2 text-[10px] text-fg-3">
                                        {data.rejection_reasons.suppressed_reasons} reason group(s)
                                        suppressed for fewer than five users.
                                    </p>
                                )}
                            </div>

                            <div>
                                <h4 className="text-xs font-semibold text-fg">
                                    Fraud review queue
                                </h4>
                                <p className="mt-1 text-[10px] text-fg-3">
                                    Aggregate, overlapping signals only. No referral is paid out,
                                    paused or punished automatically; an operator must review each
                                    signal.
                                </p>
                                <div className="mt-3 overflow-x-auto rounded-md border border-line">
                                    <table className="w-full min-w-[680px] border-collapse text-xs">
                                        <caption className="sr-only">
                                            Aggregate referral fraud-review signals
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
                                                    className="px-3 py-2 text-left font-semibold"
                                                >
                                                    Threshold
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Referrers
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Captured
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Qualified
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Reversed
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {(fraud?.signals ?? []).map(item => (
                                                <tr key={item.key} className="border-t border-line">
                                                    <td className="px-3 py-1.5 text-fg-2">
                                                        {item.label}
                                                        {item.priority === 'high' && (
                                                            <span className="ml-1 text-[10px] font-semibold text-err">
                                                                high
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-fg-3">
                                                        {item.threshold}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.referrers)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.captured)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.qualified)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.reversed)}
                                                    </td>
                                                </tr>
                                            ))}
                                            {(fraud?.signals ?? []).length === 0 && (
                                                <tr>
                                                    <td
                                                        colSpan={6}
                                                        className="px-3 py-5 text-center text-fg-3"
                                                    >
                                                        No visible fraud-review signal groups.
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                                <p className="mt-2 text-[10px] text-fg-3">
                                    {(fraud?.queue ?? []).length} manual-review item(s);
                                    {(fraud?.suppressed_signals ?? 0) > 0
                                        ? ` ${fraud?.suppressed_signals} signal group(s) suppressed.`
                                        : ' no signal is below the five-referrer floor.'}{' '}
                                    Signals may overlap.
                                </p>
                            </div>

                            <div>
                                <h4 className="text-xs font-semibold text-fg">By plan</h4>
                                <div className="mt-3 overflow-x-auto rounded-md border border-line">
                                    <table className="w-full min-w-[560px] border-collapse text-xs">
                                        <caption className="sr-only">
                                            Referral funnel by referred account plan
                                        </caption>
                                        <thead>
                                            <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-left font-semibold"
                                                >
                                                    Plan
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Captured
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Qualified
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Paid
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Reversed
                                                </th>
                                                <th
                                                    scope="col"
                                                    className="px-3 py-2 text-right font-semibold"
                                                >
                                                    Paid conversion
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {data.by_plan.map(item => (
                                                <tr
                                                    key={item.plan}
                                                    className="border-t border-line"
                                                >
                                                    <td className="px-3 py-1.5 text-fg-2">
                                                        {statusLabel(item.plan)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.captured)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.qualified)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.paid)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {formatNumber(item.reversed)}
                                                    </td>
                                                    <td className="px-3 py-1.5 text-right text-fg">
                                                        {rate(item.paid_conversion_pct)}
                                                    </td>
                                                </tr>
                                            ))}
                                            {data.by_plan.length === 0 && (
                                                <tr>
                                                    <td
                                                        colSpan={6}
                                                        className="px-3 py-5 text-center text-fg-3"
                                                    >
                                                        No visible plan group; small groups are
                                                        suppressed.
                                                    </td>
                                                </tr>
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </>
                    )}

                    <div className="grid gap-4 rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-3 text-[10px] text-fg-3 sm:grid-cols-2">
                        <div>
                            <p className="font-semibold uppercase tracking-[0.16em] text-fg-3">
                                Reconciliation
                            </p>
                            <p className="mt-1 leading-relaxed">
                                Source: {reconciliation?.source ?? 'referral tables'}.{' '}
                                {reconciliation?.reconciled == null
                                    ? 'Suppressed with the cohort.'
                                    : reconciliation.reconciled
                                      ? 'Funnel and reward totals reconcile with the source rows.'
                                      : 'Counts do not reconcile; investigate before acting.'}
                            </p>
                            <p className="mt-1 leading-relaxed">
                                Missing payments {count(reconciliation?.missing_payments)} ·
                                qualified without reward{' '}
                                {count(reconciliation?.qualified_without_reward)} · invalid
                                time-to-qualify {count(reconciliation?.invalid_time_to_qualify)}.
                            </p>
                        </div>
                        <div>
                            <p className="font-semibold uppercase tracking-[0.16em] text-fg-3">
                                Privacy
                            </p>
                            <p className="mt-1 leading-relaxed">
                                Five-user suppression; aggregate-only. No bearer code, code digest,
                                email, raw fingerprint, provider payment id or payment credential is
                                returned. Consent-gated behavioural analytics are not read.
                            </p>
                            <p className="mt-1 leading-relaxed">
                                Generated {formatDateTime(data.generated_at)} · {data.minimum_users}
                                -user floor.
                            </p>
                        </div>
                    </div>
                </div>
            )}
        </section>
    )
}
