'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, type AdminCheckoutFailureBucket, type AdminCheckoutFunnel } from '@/lib/api-client'
import { analyticsReplayTriageLinks } from '@/lib/analytics/posthog'
import { formatDateTime, formatMoney, formatNumber } from './admin-format'

const RANGES = [7, 30, 90] as const

const BUCKET_TONE: Record<AdminCheckoutFailureBucket['bucket'], string> = {
  provider_declined: 'border-err/30 bg-err/10 text-err',
  validation: 'border-warn/30 bg-warn/10 text-warn',
  abandoned: 'border-line bg-surface-2 text-fg-3',
  unavailable: 'border-warn/30 bg-warn/10 text-warn',
  unknown: 'border-line bg-surface-2 text-fg-3',
}

function Kpi({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tracking-tight ${tone ?? 'text-fg'}`}>{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function moneySummary(data: AdminCheckoutFunnel): string {
  if (data.paid_amounts.length === 0) return 'No settled payment amount'
  return data.paid_amounts
    .map(
      (amount) =>
        `${formatMoney(amount.amount_minor / 100, amount.currency)} · ${formatNumber(amount.amount_minor)} minor`,
    )
    .join(' · ')
}

export default function AdminCheckoutFunnel() {
  const [days, setDays] = useState<number>(30)
  const [data, setData] = useState<AdminCheckoutFunnel | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)

  const load = useCallback(async (range: number) => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminCheckoutFunnel(range)
      if (requestGeneration.current === generation) setData(next)
    } catch (err) {
      if (requestGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load the checkout funnel')
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(days)
    return () => {
      requestGeneration.current += 1
    }
  }, [days, load])

  const replayLink = useMemo(() => analyticsReplayTriageLinks(days)?.checkoutFailures ?? null, [days])
  const maxStep = useMemo(
    () => Math.max(...(data?.steps.map((step) => step.count) ?? [0]), 1),
    [data],
  )
  const reconciliation = data?.reconciliation
  const reconciled =
    reconciliation?.started_equals_paid_plus_failed === true &&
    reconciliation?.completed_at_least_paid === true &&
    reconciliation?.failure_buckets_match === true

  return (
    <section className="mt-4 overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Checkout funnel &amp; failure reasons</h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Server-authoritative counts from subscription intents, settled payments, and provider webhook
              rows. Every started checkout that has not paid is assigned exactly one normalized reason.
              Duplicate webhook deliveries and duplicate payment rows are deduplicated per checkout intent.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5" role="group" aria-label="Checkout funnel date range">
              {RANGES.map((range) => (
                <button
                  key={range}
                  type="button"
                  aria-pressed={days === range}
                  onClick={() => setDays(range)}
                  className={`rounded px-2.5 py-1 text-[11px] font-medium ${
                    days === range ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'
                  }`}
                >
                  {range}d
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void load(days)}
              disabled={loading}
              className="min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              Refresh
            </button>
          </div>
        </div>
        {data && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-fg-3">
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-semibold">
              {data.billing_mode} billing
            </span>
            <span>
              {data.range_days}d window · {formatDateTime(data.period_start)} →{' '}
              {formatDateTime(data.period_end)} · UTC
            </span>
            {data.excluded_other_mode_attempts > 0 && (
              <span className="rounded-full border border-line px-2 py-0.5">
                {formatNumber(data.excluded_other_mode_attempts)} other-mode attempts excluded
              </span>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="mx-5 mt-4 rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-4 py-3 text-xs text-err">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="space-y-3 p-5">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-16 animate-pulse rounded-md bg-surface-2" />
          ))}
        </div>
      ) : data ? (
        <div className="space-y-5 p-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi
              label="Started"
              value={formatNumber(data.reconciliation.started)}
              detail={`${data.range_days} day cohort`}
            />
            <Kpi
              label="Provider checkout created"
              value={formatNumber(data.reconciliation.completed)}
              detail={`${data.conversion.started_to_completed.toFixed(1)}% of starts`}
            />
            <Kpi
              label="Paid"
              value={formatNumber(data.reconciliation.paid)}
              detail={`${data.conversion.started_to_paid.toFixed(1)}% of starts · ${data.conversion.completed_to_paid.toFixed(1)}% of completed`}
              tone={data.reconciliation.paid > 0 ? 'text-ok' : 'text-fg'}
            />
            <Kpi
              label="Paid amount"
              value={data.paid_amounts.length > 0 ? formatMoney(data.paid_amounts[0].amount_minor / 100, data.paid_amounts[0].currency) : '—'}
              detail={moneySummary(data)}
            />
          </div>

          <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2/30 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-fg-3">Funnel</h4>
              <span
                className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${
                  reconciled
                    ? 'border-ok/30 bg-ok/10 text-ok'
                    : 'border-warn/30 bg-warn/10 text-warn'
                }`}
              >
                {reconciled ? 'Counts reconcile' : 'Reconciliation needs review'}
              </span>
            </div>
            <div className="mt-4 space-y-3">
              {data.steps.map((step) => (
                <div key={step.key}>
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="text-fg-2">{step.label}</span>
                    <span className="font-semibold text-fg">
                      {formatNumber(step.count)}{' '}
                      <span className="font-normal text-fg-3">({step.from_start.toFixed(1)}% of starts)</span>
                    </span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.max(2, Math.round((step.count / maxStep) * 100))}%` }}
                    />
                  </div>
                  {step.key !== 'checkout_started' && (
                    <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-fg-3">
                      <span>Step conversion: {step.from_previous.toFixed(1)}%</span>
                      <span>
                        Drop-off: {formatNumber(step.drop_off)} ({step.drop_off_pct.toFixed(1)}%)
                      </span>
                    </p>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-3 text-[10px] leading-relaxed text-fg-3">
              Reconciliation: started {formatNumber(data.reconciliation.started)} = paid{' '}
              {formatNumber(data.reconciliation.paid)} + failed {formatNumber(data.reconciliation.failed)}.
              Completed-not-paid: {formatNumber(data.reconciliation.completed_not_paid)}.
            </p>
          </div>

          <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line">
            <div className="border-b border-line bg-surface-2/40 px-4 py-3">
              <h4 className="text-sm font-semibold text-fg">Failure reasons</h4>
              <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                Every started checkout without a settled payment has one bucket. No raw provider error, card
                data, or customer identifier is returned.
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-xs">
                <caption className="sr-only">Checkout failure reasons with counts and share of failures</caption>
                <thead>
                  <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Reason</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Count</th>
                    <th scope="col" className="px-4 py-2 text-right font-semibold">Share</th>
                    <th scope="col" className="px-4 py-2 text-left font-semibold">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {data.failures.buckets.map((bucket) => (
                    <tr key={bucket.bucket} className="border-t border-line align-top">
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${BUCKET_TONE[bucket.bucket]}`}>
                          {bucket.label}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold text-fg">{formatNumber(bucket.count)}</td>
                      <td className="px-4 py-2.5 text-right text-fg-3">{bucket.share.toFixed(1)}%</td>
                      <td className="max-w-[420px] px-4 py-2.5 text-[11px] leading-relaxed text-fg-3">
                        {bucket.description}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-line bg-surface-2/30">
                    <td className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-fg-3">Total failures</td>
                    <td className="px-4 py-2.5 text-right font-semibold text-fg">{formatNumber(data.failures.total)}</td>
                    <td className="px-4 py-2.5 text-right text-fg-3">
                      {data.failures.total > 0 ? '100.0%' : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-[11px] text-fg-3">
                      Started minus paid. Duplicate webhook deliveries never add a second failure.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line">
              <div className="border-b border-line bg-surface-2/40 px-4 py-3">
                <h4 className="text-sm font-semibold text-fg">By plan</h4>
                <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                  Plan segments with fewer than {data.minimum_segment_size} started checkouts are suppressed.
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-xs">
                  <caption className="sr-only">Checkout conversion by plan</caption>
                  <thead>
                    <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                      <th scope="col" className="px-3 py-2 text-left font-semibold">Plan</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold">Started</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold">Completed</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold">Paid</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold">Failed</th>
                      <th scope="col" className="px-3 py-2 text-right font-semibold">Conversion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_plan.map((plan) => (
                      <tr key={plan.plan_id} className="border-t border-line">
                        <td className="px-3 py-2 capitalize text-fg-2">{plan.plan_id.replace(/_/g, ' ')}</td>
                        <td className="px-3 py-2 text-right text-fg">{formatNumber(plan.started)}</td>
                        <td className="px-3 py-2 text-right text-fg-3">{formatNumber(plan.completed)}</td>
                        <td className="px-3 py-2 text-right text-fg">{formatNumber(plan.paid)}</td>
                        <td className="px-3 py-2 text-right text-fg-3">{formatNumber(plan.failed)}</td>
                        <td className="px-3 py-2 text-right text-fg-3">{plan.conversion_pct.toFixed(1)}%</td>
                      </tr>
                    ))}
                    {data.by_plan.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-3 py-5 text-center text-fg-3">
                          No plan has at least {data.minimum_segment_size} started checkouts in this period.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {data.suppressed_segments > 0 && (
                <p className="border-t border-line px-4 py-2 text-[10px] text-fg-3">
                  {formatNumber(data.suppressed_segments)} small plan{' '}
                  {data.suppressed_segments === 1 ? 'segment' : 'segments'} hidden (&lt;
                  {data.minimum_segment_size} starts).
                </p>
              )}
            </div>

            <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2/30 p-4">
              <h4 className="text-sm font-semibold text-fg">PostHog replay triage</h4>
              <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                Replays are recorded only after analytics consent, with every text node and input masked.
                Document, share, portfolio, and editor surfaces are excluded. This panel links to PostHog;
                it never embeds or returns replay data.
              </p>
              {replayLink ? (
                <a
                  href={replayLink}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110"
                >
                  Open checkout-failure replays ({data.range_days}d)
                </a>
              ) : (
                <p className="mt-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
                  Set NEXT_PUBLIC_POSTHOG_PROJECT_ID to show the consent-safe checkout-failure replay link.
                </p>
              )}
              <dl className="mt-4 grid grid-cols-2 gap-2 text-[11px]">
                <dt className="text-fg-3">Abandonment window</dt>
                <dd className="text-right text-fg-2">{data.abandonment_hours} hours</dd>
                <dt className="text-fg-3">Failure buckets</dt>
                <dd className="text-right text-fg-2">{data.failures.buckets.length}</dd>
                <dt className="text-fg-3">Generated</dt>
                <dd className="text-right text-fg-2">{formatDateTime(data.generated_at)}</dd>
              </dl>
              <ul className="mt-3 space-y-1 text-[10px] text-fg-3">
                {data.notes.map((note) => (
                  <li key={note}>• {note}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : (
        <p className="px-5 py-10 text-center text-sm text-fg-3">No checkout funnel data is available.</p>
      )}
    </section>
  )
}
