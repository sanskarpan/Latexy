'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminTrialAttributionResponse,
    type AdminTrialAttributionRow,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from './admin-format'

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

function rate(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function days(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}d`
}

function count(value: number | null | undefined): string {
    return value == null ? '—' : formatNumber(value)
}

function CohortTable({
    caption,
    labelHeading,
    rows,
    emptyMessage,
}: {
    caption: string
    labelHeading: string
    rows: AdminTrialAttributionRow[]
    emptyMessage: string
}) {
    return (
        <div className="mt-3 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[1040px] border-collapse text-xs">
                <caption className="sr-only">{caption}</caption>
                <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            {labelHeading}
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Trials
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Signups
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Paid
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Trial → paid
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Median → signup
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Median → paid
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Paid ≤ 7d
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Paid ≤ 30d
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Paid ≤ 90d
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => (
                        <tr
                            key={row.label}
                            className="border-t border-line"
                            aria-label={
                                row.suppressed_cells.length > 0
                                    ? `${row.label}; some cells suppressed for privacy`
                                    : row.label
                            }
                        >
                            <td className="px-3 py-1.5 text-fg-2">
                                <span>{row.label}</span>
                                {row.suppressed_cells.length > 0 && (
                                    <span className="ml-2 rounded-full border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[9px] font-medium text-warn">
                                        suppressed cells
                                    </span>
                                )}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg">
                                {formatNumber(row.trial_starts)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {count(row.signups)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {count(row.paid_users)}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                {rate(row.trial_to_paid_pct)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {days(row.median_days_to_signup)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {days(row.median_days_to_paid)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {count(row.paid_within_7d)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {count(row.paid_within_30d)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {count(row.paid_within_90d)}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={10} className="px-3 py-5 text-center text-fg-3">
                                {emptyMessage}
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminTrialAttribution({ days: windowDays }: { days: number }) {
    const [data, setData] = useState<AdminTrialAttributionResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const requestId = useRef(0)

    const load = useCallback(async () => {
        const id = ++requestId.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminTrialAttribution({ days: windowDays })
            if (requestId.current === id) setData(next)
        } catch (err) {
            if (requestId.current === id) {
                setError(
                    err instanceof Error
                        ? err.message
                        : 'Failed to load trial attribution cohorts.',
                )
            }
        } finally {
            if (requestId.current === id) setLoading(false)
        }
    }, [windowDays])

    useEffect(() => {
        void load()
    }, [load])

    const totals = data?.totals
    const reconciliation = data?.reconciliation

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">
                        Trial-to-paid cohorts by acquisition source
                    </h3>
                    <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-fg-3">
                        Trial starts in the selected period, linked to signup and the first paid
                        subscription. Sources are consented first-touch campaign labels; plan and
                        signup month come from the account/subscription link. Aggregates only.
                    </p>
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

            {error && (
                <p
                    role="alert"
                    className="mx-5 mt-4 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
                >
                    {error}
                </p>
            )}

            {totals && reconciliation ? (
                <div className="space-y-5 px-5 py-4">
                    <div>
                        <h4 className="text-xs font-semibold text-fg">Cohort summary</h4>
                        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                            <Metric
                                label="Trial starts"
                                value={formatNumber(totals.trial_starts)}
                                detail={`n = ${formatNumber(reconciliation.period_trial_starts)} in period`}
                            />
                            <Metric
                                label="Linked trials"
                                value={formatNumber(totals.linked_trials)}
                                detail={`${formatNumber(totals.unlinked_trials)} anonymous/unlinked`}
                            />
                            <Metric
                                label="Paid users"
                                value={count(totals.paid_users)}
                                detail={`${formatNumber(reconciliation.subscriptions_linked_to_cohort)} linked subscriptions`}
                            />
                            <Metric
                                label="Trial → paid"
                                value={rate(totals.trial_to_paid_pct)}
                                detail={`${rate(totals.signup_to_paid_pct)} of signups`}
                            />
                            <Metric
                                label="Median to paid"
                                value={days(totals.median_days_to_paid)}
                                detail={`${days(totals.median_days_to_signup)} to signup`}
                            />
                            <Metric
                                label="Source coverage"
                                value={rate(totals.source_coverage_pct)}
                                detail={`${rate(totals.linkage_coverage_pct)} account linkage`}
                            />
                        </div>
                    </div>

                    <div className="rounded-md border border-line bg-surface-2/30 px-3 py-2 text-[10px] leading-relaxed text-fg-3">
                        <span className="font-semibold text-fg-2">Reconciliation: </span>
                        {formatNumber(reconciliation.period_trial_starts)} trials and{' '}
                        {formatNumber(reconciliation.period_paid_subscriptions)} paid subscriptions
                        in the period. {formatNumber(reconciliation.source_attributed_trials)} trials
                        have a consented source; {formatNumber(reconciliation.anonymous_trials)} are
                        anonymous or unlinked. Outside the attributed cohort:{' '}
                        {formatNumber(reconciliation.unattributed_signups)} signups and{' '}
                        {formatNumber(reconciliation.unattributed_paid_users)} paid users. Deleted
                        accounts are removed by cascade.
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">By acquisition source</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Includes anonymous trials that carry a consented first-touch source, so
                            trial → signup is an end-to-end rate.
                        </p>
                        <CohortTable
                            caption="Trial-to-paid conversion by acquisition source"
                            labelHeading="Source"
                            rows={data?.by_source ?? []}
                            emptyMessage="No source cohort has at least five trials in this period."
                        />
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">By plan</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Linked accounts only. Accounts without a paid subscription are grouped
                            as “no paid plan”; an unexpected missing plan is labelled, not guessed.
                        </p>
                        <CohortTable
                            caption="Trial-to-paid conversion by paid plan"
                            labelHeading="Plan"
                            rows={data?.by_plan ?? []}
                            emptyMessage="No plan cohort has at least five linked trials in this period."
                        />
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">By signup month</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Cohort month comes from the linked account&apos;s signup timestamp.
                        </p>
                        <CohortTable
                            caption="Trial-to-paid conversion by signup month"
                            labelHeading="Signup month"
                            rows={data?.by_signup_month ?? []}
                            emptyMessage="No signup-month cohort has at least five linked trials in this period."
                        />
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[10px] text-fg-3">
                        <span>
                            {data?.suppressed
                                ? `${formatNumber(
                                      Object.values(data.suppressed).reduce(
                                          (sum, value) => sum + value,
                                          0,
                                      ),
                                  )} small cohort${Object.values(data.suppressed).reduce(
                                      (sum, value) => sum + value,
                                      0,
                                  ) === 1
                                      ? ''
                                      : 's'} hidden (<{data.minimum_cohort_size} trials or a 1–4 user cell).`
                                : 'No cohorts were suppressed for this period.'}
                        </span>
                        <span>Generated {formatDateTime(data?.generated_at)}</span>
                    </div>
                    <ul className="space-y-1 text-[10px] text-fg-3">
                        {(data?.notes ?? []).map(note => (
                            <li key={note}>• {note}</li>
                        ))}
                    </ul>
                </div>
            ) : (
                !error && (
                    <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
                        Loading trial attribution cohorts…
                    </div>
                )
            )}
        </section>
    )
}
