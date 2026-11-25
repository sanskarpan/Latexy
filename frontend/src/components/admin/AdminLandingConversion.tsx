'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminLandingConversionResponse,
    type AdminLandingConversionRow,
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

function VariantCell({ row }: { row: AdminLandingConversionRow }) {
    if (row.missing_variant) {
        return (
            <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] font-medium text-warn">
                {row.variant_label ?? 'Variant not recorded'}
            </span>
        )
    }
    return <span className="text-fg-2">{row.variant_label ?? '—'}</span>
}

function PageVariantTable({ rows }: { rows: AdminLandingConversionRow[] }) {
    return (
        <div className="mt-4 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[760px] border-collapse text-xs">
                <caption className="sr-only">
                    Landing conversion by page and experiment variant
                </caption>
                <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Page
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Experiment
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Variant
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Visits (n)
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Trials
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Registrations
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Visit → registration
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => (
                        <tr
                            key={`${row.page_key ?? 'missing'}:${row.experiment ?? ''}:${row.variant ?? ''}`}
                            className="border-t border-line"
                        >
                            <td className="px-3 py-1.5 text-fg-2">{row.page_label ?? '—'}</td>
                            <td className="px-3 py-1.5 text-fg-3">{row.experiment_label ?? '—'}</td>
                            <td className="px-3 py-1.5">
                                <VariantCell row={row} />
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg">
                                {formatNumber(row.visits)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.trial_starts)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.registrations)}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                {rate(row.conversion_rate)}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={7} className="px-3 py-5 text-center text-fg-3">
                                No page/variant has at least five visits in this period.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

function DeviceTable({ rows }: { rows: AdminLandingConversionRow[] }) {
    return (
        <div className="mt-4 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[560px] border-collapse text-xs">
                <caption className="sr-only">
                    Mobile, tablet, and desktop landing conversion comparison
                </caption>
                <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Device
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Visits (n)
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Trials
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Registrations
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Conversion
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => (
                        <tr key={row.device_class ?? 'unknown'} className="border-t border-line">
                            <td className="px-3 py-1.5 text-fg-2">
                                {row.device_label ?? 'Unknown device'}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg">
                                {formatNumber(row.visits)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.trial_starts)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.registrations)}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                {rate(row.conversion_rate)}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={5} className="px-3 py-5 text-center text-fg-3">
                                No device cohort has at least five visits in this period.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

function DetailTable({ rows }: { rows: AdminLandingConversionRow[] }) {
    return (
        <div className="mt-4 overflow-x-auto rounded-md border border-line">
            <table className="w-full min-w-[920px] border-collapse text-xs">
                <caption className="sr-only">
                    Detailed landing conversion by page, variant, and device
                </caption>
                <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Page
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Experiment
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Variant
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Device
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Visits (n)
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Trials
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Registrations
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Subscriptions
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Conversion
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {rows.map(row => (
                        <tr
                            key={`${row.page_key ?? 'missing'}:${row.experiment ?? ''}:${row.variant ?? ''}:${row.device_class}`}
                            className="border-t border-line"
                        >
                            <td className="px-3 py-1.5 text-fg-2">{row.page_label ?? '—'}</td>
                            <td className="px-3 py-1.5 text-fg-3">{row.experiment_label ?? '—'}</td>
                            <td className="px-3 py-1.5">
                                <VariantCell row={row} />
                            </td>
                            <td className="px-3 py-1.5 text-fg-3">
                                {row.device_label ?? 'Unknown device'}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg">
                                {formatNumber(row.visits)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.trial_starts)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.registrations)}
                            </td>
                            <td className="px-3 py-1.5 text-right text-fg-3">
                                {formatNumber(row.subscriptions)}
                            </td>
                            <td className="px-3 py-1.5 text-right font-semibold text-fg">
                                {rate(row.conversion_rate)}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={9} className="px-3 py-5 text-center text-fg-3">
                                No page/variant/device cell has at least five visits in this period.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminLandingConversion({ days }: { days: number }) {
    const [data, setData] = useState<AdminLandingConversionResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const generation = useRef(0)

    const load = useCallback(async () => {
        const current = ++generation.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminLandingConversion(days)
            if (generation.current === current) setData(next)
        } catch (err) {
            if (generation.current === current) {
                setError(err instanceof Error ? err.message : 'Failed to load landing conversion')
            }
        } finally {
            if (generation.current === current) setLoading(false)
        }
    }, [days])

    useEffect(() => {
        void load()
    }, [load])

    const summary = data?.summary
    const steps = summary?.funnel_steps
    const rates = summary?.conversion_rates
    const attribution = summary?.attribution

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h3 className="text-sm font-semibold text-fg">
                            Landing conversion by page, variant, and device
                        </h3>
                        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                            First-party landing visits with same-device first-touch attribution.
                            Each cell shows its visit sample size; cells below{' '}
                            {data?.minimum_segment_size ?? 5} visits are hidden. Missing variant
                            data is labelled, never replaced with an assumed control group.
                        </p>
                    </div>
                    <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                        {loading ? 'Loading…' : data ? `${data.days} days · UTC` : '—'}
                    </span>
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

            {summary && steps && rates ? (
                <div className="space-y-5 px-5 py-4">
                    <div>
                        <h4 className="text-xs font-semibold text-fg">Overall funnel summary</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            The existing landing → trial → registration → subscription funnel is
                            kept as the authoritative summary. Sample sizes are the step counts for{' '}
                            {data?.days} days.
                        </p>
                        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <Metric
                                label="Landing visits"
                                value={formatNumber(steps.landing_visits)}
                                detail={`n = ${formatNumber(summary.sample_sizes.landing_visits)}`}
                            />
                            <Metric
                                label="Trial starts"
                                value={formatNumber(steps.trial_starts)}
                                detail={`n = ${formatNumber(summary.sample_sizes.trial_starts)} · ${rate(rates.landing_to_trial)} of visits`}
                            />
                            <Metric
                                label="Registrations"
                                value={formatNumber(steps.registrations)}
                                detail={`n = ${formatNumber(summary.sample_sizes.registrations)} · ${rate(rates.trial_to_registration)} of trials`}
                            />
                            <Metric
                                label="Subscriptions"
                                value={formatNumber(steps.subscriptions)}
                                detail={`n = ${formatNumber(summary.sample_sizes.subscriptions)} · ${rate(rates.overall_conversion)} of visits`}
                            />
                        </div>
                        {attribution && (
                            <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
                                {attribution.description} Attributed{' '}
                                {formatNumber(attribution.attributed_registrations)} of{' '}
                                {formatNumber(steps.registrations)} registrations (
                                {rate(attribution.registration_coverage_pct)}); unattributed rows
                                remain in the summary and are not assigned to a page or device.
                            </p>
                        )}
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">Mobile vs desktop</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Same date range and the same same-device attribution rules. Unknown
                            device data is labelled, not guessed.
                        </p>
                        <DeviceTable rows={data?.by_device ?? []} />
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">By page and variant</h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Visits, trial starts, registrations, and visit → registration conversion
                            per page/variant.
                        </p>
                        <PageVariantTable rows={data?.by_page_variant ?? []} />
                    </div>

                    <div>
                        <h4 className="text-xs font-semibold text-fg">
                            Page × variant × device detail
                        </h4>
                        <p className="mt-1 text-[10px] text-fg-3">
                            Each row is an aggregate cell with its own sample size. No account id,
                            path, query string, share token, or document content is returned.
                        </p>
                        <DetailTable rows={data?.by_page_variant_device ?? []} />
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[10px] text-fg-3">
                        <span>
                            {data?.suppressed_cells
                                ? `${formatNumber(data.suppressed_cells)} small cell${data.suppressed_cells === 1 ? '' : 's'} hidden (<${data.minimum_segment_size} visits).`
                                : 'No cells were suppressed for this period.'}
                            {data?.truncated_cells
                                ? ` ${formatNumber(data.truncated_cells)} lower-volume cells truncated.`
                                : ''}
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
                        Loading landing conversion…
                    </div>
                )
            )}
        </section>
    )
}
