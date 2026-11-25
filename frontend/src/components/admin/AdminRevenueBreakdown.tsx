'use client'

import type {
    AdminBillingChargebackView,
    AdminBillingRefundView,
    AdminBillingRevenueReconciliation,
    AdminBillingSummary,
} from '@/lib/api-client'
import { formatDateTime, formatMoney, formatNumber, shortId } from './admin-format'

type Granularity = 'day' | 'month'

function Panel({
    title,
    description,
    action,
    children,
}: {
    title: string
    description?: string
    action?: React.ReactNode
    children: React.ReactNode
}) {
    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">{title}</h3>
                    {description && (
                        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
                            {description}
                        </p>
                    )}
                </div>
                {action}
            </div>
            {children}
        </section>
    )
}

function Money({ minor, currency }: { minor: number; currency: string }) {
    return <>{formatMoney(minor / 100, currency)}</>
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
        <div className="rounded-[var(--radius-md)] border border-line bg-bg/40 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">
                {label}
            </p>
            <p className={`mt-1.5 text-lg font-semibold tracking-tight ${tone ?? 'text-fg'}`}>
                {value}
            </p>
            {detail && <p className="mt-1 text-[10px] leading-relaxed text-fg-3">{detail}</p>}
        </div>
    )
}

function RefundView({ view }: { view: AdminBillingRefundView }) {
    return (
        <Panel
            title="Refunds"
            description="Succeeded refunds reduce net revenue once. Failed and still-pending attempts stay visible for reconciliation but are never subtracted."
        >
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard
                    label="Succeeded"
                    value={formatMoney(view.succeeded, view.currency)}
                    detail={`${formatNumber(view.succeeded_count)} refunds · ${formatNumber(view.succeeded_minor)} minor`}
                />
                <MetricCard
                    label="Failed"
                    value={formatMoney(view.failed_minor / 100, view.currency)}
                    detail={`${formatNumber(view.failed_count)} failed attempts`}
                />
                <MetricCard
                    label="Pending"
                    value={formatMoney(view.pending_minor / 100, view.currency)}
                    detail={`${formatNumber(view.pending_count)} awaiting settlement`}
                />
                <MetricCard
                    label="Net refund impact"
                    value={`− ${formatMoney(view.total, view.currency)}`}
                    detail="Only succeeded refunds are included"
                />
            </div>
            {view.by_status.length === 0 ? (
                <p className="px-5 pb-6 text-sm text-fg-3">No refunds in this range.</p>
            ) : (
                <div className="overflow-x-auto border-t border-line">
                    <table className="w-full min-w-[520px] border-collapse text-sm">
                        <caption className="sr-only">Refunds grouped by provider status</caption>
                        <thead>
                            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Status
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Count
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Amount
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {view.by_status.map(row => (
                                <tr key={row.status} className="border-t border-line">
                                    <td className="px-4 py-2.5 font-mono text-xs text-fg">
                                        {row.status}
                                    </td>
                                    <td className="px-4 py-2.5 text-right text-xs text-fg-2">
                                        {formatNumber(row.count)}
                                    </td>
                                    <td className="px-4 py-2.5 text-right text-xs font-semibold text-fg">
                                        <Money minor={row.amount_minor} currency={view.currency} />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </Panel>
    )
}

function ChargebackView({ view }: { view: AdminBillingChargebackView }) {
    return (
        <Panel
            title="Chargebacks & disputes"
            description="Dispute webhooks are retained as durable events. Amounts are linked from local payments only; no customer identifier, provider secret or payment credential is shown."
        >
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard
                    label="Disputed exposure"
                    value={formatMoney(view.total, view.currency)}
                    detail={`${formatNumber(view.count)} disputes · ${formatNumber(view.events_count)} events`}
                    tone={view.total_minor > 0 ? 'text-warn' : 'text-fg'}
                />
                <MetricCard
                    label="Open"
                    value={formatNumber(view.open_count)}
                    detail={`${formatMoney(view.open_minor / 100, view.currency)} awaiting outcome`}
                />
                <MetricCard
                    label="Lost"
                    value={formatNumber(view.lost_count)}
                    detail={`${formatMoney(view.lost_minor / 100, view.currency)} charged back`}
                    tone={view.lost_count > 0 ? 'text-err' : 'text-fg'}
                />
                <MetricCard
                    label="Won / resolved"
                    value={formatNumber(view.won_count)}
                    detail={`${formatMoney(view.resolved_minor / 100, view.currency)} resolved`}
                />
            </div>
            {view.unlinked_count > 0 && (
                <p className="px-5 pb-4 text-[11px] leading-relaxed text-warn">
                    {formatNumber(view.unlinked_count)} dispute events have no linked local payment;
                    their amount is not included in the exposure total.
                </p>
            )}
            {view.items.length === 0 ? (
                <p className="px-5 pb-6 text-sm text-fg-3">
                    No chargeback or dispute events in this range.
                </p>
            ) : (
                <div className="overflow-x-auto border-t border-line">
                    <table className="w-full min-w-[720px] border-collapse text-sm">
                        <caption className="sr-only">
                            Chargeback and dispute events, newest first
                        </caption>
                        <thead>
                            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Received
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Event
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Status
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Amount
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Local payment
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {view.items.map(item => (
                                <tr key={item.id} className="border-t border-line">
                                    <td className="whitespace-nowrap px-4 py-2.5 text-xs text-fg-3">
                                        {formatDateTime(item.received_at)}
                                    </td>
                                    <td className="px-4 py-2.5 font-mono text-xs text-fg">
                                        {item.event_type}
                                    </td>
                                    <td className="px-4 py-2.5 text-xs text-fg-2">{item.status}</td>
                                    <td className="whitespace-nowrap px-4 py-2.5 text-right text-xs font-semibold text-fg">
                                        {item.amount_minor == null ? (
                                            <span className="text-fg-3">Amount unavailable</span>
                                        ) : (
                                            <Money
                                                minor={item.amount_minor}
                                                currency={item.currency ?? view.currency}
                                            />
                                        )}
                                    </td>
                                    <td className="px-4 py-2.5 font-mono text-[10px] text-fg-3">
                                        {item.payment_linked
                                            ? shortId(item.payment_id, 14)
                                            : 'Not linked'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </Panel>
    )
}

function ReconciliationView({ view }: { view: AdminBillingRevenueReconciliation }) {
    return (
        <Panel
            title="Revenue reconciliation"
            description="Every total is compared with the payments and payment_refunds ledger. A failed check needs operator review before the revenue figure is trusted."
            action={
                <span
                    className={`inline-flex rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                        view.balanced
                            ? 'border-ok/30 bg-ok/10 text-ok'
                            : 'border-err/30 bg-err/10 text-err'
                    }`}
                >
                    {view.balanced ? 'Balanced' : 'Needs review'}
                </span>
            }
        >
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
                <MetricCard
                    label="Payments"
                    value={formatMoney(view.gross_from_payments_minor / 100, view.currency)}
                    detail={`${formatNumber(view.payments_count)} settled rows`}
                />
                <MetricCard
                    label="Succeeded refunds"
                    value={formatMoney(
                        view.refunded_from_payment_refunds_minor / 100,
                        view.currency
                    )}
                    detail={`${formatNumber(view.refunds_count)} refund rows`}
                />
                <MetricCard
                    label="Expected net"
                    value={formatMoney(view.expected_net_minor / 100, view.currency)}
                    detail="Payments minus succeeded refunds"
                />
                <MetricCard
                    label="Difference"
                    value={formatMoney(view.difference_minor / 100, view.currency)}
                    detail={
                        view.difference_minor === 0
                            ? 'Ledger totals agree'
                            : 'Investigate before relying on net revenue'
                    }
                    tone={view.difference_minor === 0 ? 'text-ok' : 'text-err'}
                />
            </div>
            <ul className="divide-y divide-line border-t border-line">
                {view.checks.map(check => (
                    <li
                        key={check.key}
                        className="flex flex-wrap items-start justify-between gap-2 px-5 py-2.5"
                    >
                        <div className="flex items-start gap-2">
                            <span
                                className={`mt-1 inline-block h-1.5 w-1.5 rounded-full ${check.ok ? 'bg-ok' : 'bg-err'}`}
                            />
                            <span className="text-xs text-fg-2">{check.label}</span>
                        </div>
                        <span
                            className={`font-mono text-[10px] ${check.ok ? 'text-ok' : 'text-err'}`}
                        >
                            Δ {formatMoney(check.difference_minor / 100, view.currency)}
                        </span>
                    </li>
                ))}
            </ul>
            <p className="border-t border-line px-5 py-3 text-[10px] leading-relaxed text-fg-3">
                {view.test_mode_policy} Plan-mix difference:{' '}
                {formatMoney(view.plan_mix_revenue_difference_minor / 100, view.currency)}.
            </p>
        </Panel>
    )
}

export default function AdminRevenueBreakdown({
    summary,
    granularity,
    onGranularity,
}: {
    summary: AdminBillingSummary | null
    granularity: Granularity
    onGranularity: (next: Granularity) => void
}) {
    if (!summary) return null
    const planMix = summary.plan_mix.filter(
        item => item.subscriptions > 0 || item.revenue_minor !== 0 || item.refunded_minor !== 0
    )

    return (
        <div className="space-y-4">
            <Panel
                title="Revenue breakdown"
                description="MRR is normalized from active subscriptions. Gross, refunds, chargebacks and net revenue are calculated from settled ledger rows in the selected window; every amount is in minor units with an explicit currency."
                action={
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-bg p-0.5"
                        role="group"
                        aria-label="Revenue series granularity"
                    >
                        {(['day', 'month'] as const).map(option => (
                            <button
                                key={option}
                                type="button"
                                aria-pressed={granularity === option}
                                onClick={() => onGranularity(option)}
                                className={`rounded px-3 py-1 text-[11px] font-medium ${
                                    granularity === option
                                        ? 'bg-accent-soft text-accent-strong'
                                        : 'text-fg-3 hover:text-fg'
                                }`}
                            >
                                {option === 'day' ? 'Daily' : 'Monthly'}
                            </button>
                        ))}
                    </div>
                }
            >
                <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
                    <MetricCard
                        label="Net revenue"
                        value={formatMoney(summary.net_revenue, summary.currency)}
                        detail={`${formatMoney(summary.gross_revenue, summary.currency)} gross − ${formatMoney(summary.refunded, summary.currency)} refunds`}
                    />
                    <MetricCard
                        label="Chargeback exposure"
                        value={formatMoney(summary.chargebacks, summary.currency)}
                        detail={`${formatNumber(summary.chargebacks_count)} disputes`}
                        tone={summary.chargebacks_minor > 0 ? 'text-warn' : 'text-fg'}
                    />
                    <MetricCard
                        label="Net after chargebacks"
                        value={formatMoney(summary.net_revenue_after_chargebacks, summary.currency)}
                        detail="Refunded net minus disputed exposure"
                    />
                    <MetricCard
                        label="ARPU"
                        value={formatMoney(summary.arpu, summary.currency)}
                        detail={`${formatMoney(summary.mrr, summary.currency)} MRR / ${formatNumber(summary.active_subscriptions)} active`}
                    />
                </div>
                <div className="overflow-x-auto border-t border-line">
                    <table className="w-full min-w-[720px] border-collapse text-sm">
                        <caption className="sr-only">
                            Revenue by {granularity}, including refunds and chargebacks
                        </caption>
                        <thead>
                            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Period
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Gross
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Refunds
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Chargebacks
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Net
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {summary.revenue_series.map(point => (
                                <tr key={point.bucket} className="border-t border-line">
                                    <td className="whitespace-nowrap px-4 py-2 text-xs text-fg-2">
                                        {point.label}
                                    </td>
                                    <td className="px-4 py-2 text-right text-xs text-fg">
                                        <Money
                                            minor={point.gross_revenue_minor}
                                            currency={summary.currency}
                                        />
                                    </td>
                                    <td className="px-4 py-2 text-right text-xs text-fg-2">
                                        <Money
                                            minor={point.refunds_minor}
                                            currency={summary.currency}
                                        />
                                    </td>
                                    <td className="px-4 py-2 text-right text-xs text-fg-2">
                                        <Money
                                            minor={point.chargebacks_minor}
                                            currency={summary.currency}
                                        />
                                    </td>
                                    <td className="px-4 py-2 text-right text-xs font-semibold text-fg">
                                        <Money
                                            minor={point.net_revenue_after_chargebacks_minor}
                                            currency={summary.currency}
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </Panel>

            <Panel
                title="Plan mix & MRR normalization"
                description="Plan revenue is attributed through the payment's subscription. MRR uses the quote when present: annual ÷ 12, weekly × 52/12, and lifetime excluded from recurring revenue."
            >
                <div className="overflow-x-auto">
                    <table className="w-full min-w-[860px] border-collapse text-sm">
                        <caption className="sr-only">Revenue and MRR by plan</caption>
                        <thead>
                            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Plan
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-left font-semibold">
                                    Interval
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Active
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    MRR
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Gross
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Refunds
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Net
                                </th>
                                <th scope="col" className="px-4 py-2.5 text-right font-semibold">
                                    Share
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {planMix.length === 0 ? (
                                <tr>
                                    <td
                                        colSpan={8}
                                        className="px-4 py-8 text-center text-sm text-fg-3"
                                    >
                                        No plan revenue or active subscriptions in this range.
                                    </td>
                                </tr>
                            ) : (
                                planMix.map(item => (
                                    <tr key={item.plan_id} className="border-t border-line">
                                        <td className="px-4 py-2 text-xs font-semibold text-fg">
                                            {item.plan_id}
                                        </td>
                                        <td className="px-4 py-2 text-xs text-fg-3">
                                            {item.interval}
                                        </td>
                                        <td className="px-4 py-2 text-right text-xs text-fg-2">
                                            {formatNumber(item.subscriptions)}
                                        </td>
                                        <td className="px-4 py-2 text-right text-xs text-fg">
                                            <Money
                                                minor={item.mrr_minor}
                                                currency={summary.currency}
                                            />
                                        </td>
                                        <td className="px-4 py-2 text-right text-xs text-fg">
                                            <Money
                                                minor={item.revenue_minor}
                                                currency={summary.currency}
                                            />
                                        </td>
                                        <td className="px-4 py-2 text-right text-xs text-fg-2">
                                            <Money
                                                minor={item.refunded_minor}
                                                currency={summary.currency}
                                            />
                                        </td>
                                        <td className="px-4 py-2 text-right text-xs font-semibold text-fg">
                                            <Money
                                                minor={item.net_revenue_minor}
                                                currency={summary.currency}
                                            />
                                        </td>
                                        <td className="px-4 py-2 text-right text-xs text-fg-3">
                                            {item.share_percent.toFixed(1)}%
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
                <div className="border-t border-line px-5 py-3 text-[10px] leading-relaxed text-fg-3">
                    {summary.mrr_normalization.by_interval.length > 0
                        ? summary.mrr_normalization.by_interval
                              .map(
                                  bucket =>
                                      `${bucket.interval}: ${formatNumber(bucket.subscriptions)} subs · ${formatMoney(bucket.mrr, summary.currency)} MRR`
                              )
                              .join(' · ')
                        : 'No active recurring subscriptions.'}
                    {' · '}
                    {summary.mrr_normalization.lifetime_policy.split('_').join(' ')}.
                </div>
            </Panel>

            <ReconciliationView view={summary.reconciliation} />

            <div className="grid gap-4 xl:grid-cols-2">
                <RefundView view={summary.refund_view} />
                <ChargebackView view={summary.chargeback_view} />
            </div>
        </div>
    )
}
