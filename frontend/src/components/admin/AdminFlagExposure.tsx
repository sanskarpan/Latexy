'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminFlagExposureFlag,
  type AdminFlagExposureMetric,
  type AdminFlagExposureMetricCell,
  type AdminFlagExposureResponse,
  type AdminFlagExposureWindow,
} from '@/lib/api-client'

const numberFormatter = new Intl.NumberFormat('en-IN')

function formatCount(value: number | null | undefined): string {
  return Number.isFinite(value ?? NaN) ? numberFormatter.format(Number(value)) : '—'
}

function cellText(cell: AdminFlagExposureMetricCell): string {
  if (cell.rate_pct == null) return '—'
  return `${cell.rate_pct.toFixed(1)}%`
}

function cellDetail(cell: AdminFlagExposureMetricCell): string {
  if (cell.numerator == null || cell.denominator == null) {
    return cell.suppressed ? 'Hidden under the five-user rule' : 'No observations'
  }
  return `${numberFormatter.format(cell.numerator)} of ${numberFormatter.format(cell.denominator)}`
}

function differenceText(metric: AdminFlagExposureMetric): string {
  if (metric.difference_pp == null || !metric.comparable) return '—'
  const value = metric.difference_pp
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)} pp`
}

function Stat({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-fg-3">{label}</p>
      <p className="mt-0.5 text-lg font-semibold text-fg">{value}</p>
      <p className="text-[11px] text-fg-3">{detail}</p>
    </div>
  )
}

function WindowPanel({
  window,
  horizonDays,
}: {
  window: AdminFlagExposureWindow
  horizonDays: number
}) {
  const treatment = window.groups.treatment
  const control = window.groups.control
  const censored = (treatment.right_censored_subjects ?? 0) + (control.right_censored_subjects ?? 0)
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-fg">{window.days}-day window</h4>
        <p className="text-[10px] text-fg-3">
          {window.start_date} to {window.end_date} · {horizonDays}-day outcome horizon
        </p>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat
          label="Exposed (treatment)"
          value={formatCount(treatment.exposure_events)}
          detail={`${formatCount(treatment.sample_size)} subject sample`}
        />
        <Stat
          label="Control (flag off)"
          value={formatCount(control.exposure_events)}
          detail={`${formatCount(control.sample_size)} subject sample`}
        />
      </div>

      <p className="mt-2 text-[10px] text-fg-3">
        Exposure events count one deduplicated evaluation per subject/flag/variant/day.
        Right-censored subjects (incomplete outcome horizon): {formatCount(censored)}.
        Groups with 1–4 subjects are hidden as “—”.
      </p>

      {window.suppressed ? (
        <p role="status" className="mt-3 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          Both groups are below five subjects, so counts and rates are suppressed for this window.
        </p>
      ) : null}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-xs">
          <caption className="sr-only">
            Feature flag outcomes and guardrails for the {window.days}-day window
          </caption>
          <thead>
            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
              <th scope="col" className="py-2 pr-3 text-left font-semibold">Metric</th>
              <th scope="col" className="px-3 py-2 text-left font-semibold">Exposed</th>
              <th scope="col" className="px-3 py-2 text-left font-semibold">Control</th>
              <th scope="col" className="px-3 py-2 text-left font-semibold">Difference</th>
            </tr>
          </thead>
          <tbody>
            {window.metrics.map((metric) => (
              <tr key={metric.key} className="border-t border-line align-top">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  <span className="font-medium text-fg">{metric.label}</span>
                  {metric.kind === 'guardrail' ? (
                    <span className="ml-1 rounded bg-surface-2 px-1 py-0.5 text-[9px] uppercase tracking-wide text-fg-3">
                      Guardrail
                    </span>
                  ) : null}
                  <span className="block text-[10px] text-fg-3">{metric.definition}</span>
                </th>
                <td className="px-3 py-2 text-fg-2">
                  <span className="font-medium text-fg">{cellText(metric.treatment)}</span>
                  <span className="block text-[10px] text-fg-3">{cellDetail(metric.treatment)}</span>
                </td>
                <td className="px-3 py-2 text-fg-2">
                  <span className="font-medium text-fg">{cellText(metric.control)}</span>
                  <span className="block text-[10px] text-fg-3">{cellDetail(metric.control)}</span>
                </td>
                <td className="px-3 py-2 text-fg-2">
                  {differenceText(metric)}
                  <span className="block text-[10px] text-fg-3">Descriptive only</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-[10px] text-fg-3">
        Guardrails in this window:{' '}
        {window.guardrails.length > 0
          ? window.guardrails.map((metric) => metric.label).join(', ')
          : 'none'}
        . Lower is better for guardrails marked “down”.
      </p>
    </div>
  )
}

function FlagCard({
  flag,
  windowOrder,
  horizonDays,
}: {
  flag: AdminFlagExposureFlag
  windowOrder: number[]
  horizonDays: number
}) {
  return (
    <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-fg">{flag.label}</h3>
          <p className="mt-0.5 font-mono text-[11px] text-fg-3">{flag.key}</p>
          {flag.description ? <p className="mt-1 text-xs text-fg-3">{flag.description}</p> : null}
        </div>
        <span
          className={`rounded-full border px-2.5 py-1 text-[10px] font-medium ${
            flag.enabled
              ? 'border-ok/30 bg-ok/10 text-ok'
              : 'border-line bg-surface-2 text-fg-3'
          }`}
        >
          {flag.enabled ? 'Flag on · treatment' : 'Flag off · control'}
        </span>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {windowOrder.map((days) => {
          const window = flag.windows[String(days)]
          if (!window) return null
          return <WindowPanel key={days} window={window} horizonDays={horizonDays} />
        })}
      </div>
    </article>
  )
}

export default function AdminFlagExposure() {
  const [data, setData] = useState<AdminFlagExposureResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const requestGeneration = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminFlagExposure()
      if (generation.current === requestGeneration) setData(next)
    } catch (err) {
      if (generation.current === requestGeneration) {
        setError(err instanceof Error ? err.message : 'Failed to load flag exposure metrics')
      }
    } finally {
      if (generation.current === requestGeneration) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    return () => {
      generation.current += 1
    }
  }, [load])

  if (loading && !data) {
    return (
      <div role="status" className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 text-sm text-fg-3">
        Loading flag exposure metrics…
      </div>
    )
  }

  if (error && !data) {
    return (
      <div role="alert" className="rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.06] px-5 py-4">
        <p className="text-sm font-semibold text-err">Flag exposure metrics could not be loaded</p>
        <p className="mt-1 text-xs text-err/80">{error}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-3 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null
  const windowOrder = data.windows ?? [7, 30]

  return (
    <section aria-labelledby="flag-exposure-heading" className="space-y-4">
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="flag-exposure-heading" className="text-sm font-semibold text-fg">
              Flag exposure and outcome guardrails
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Consent-covered first-party exposures joined to activation, compile success,
              checkout and return behaviour for 7- and 30-day lookbacks. Only aggregate counts
              are returned; groups with fewer than {data.minimum_group_size} subjects are
              suppressed.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
            Metric definitions and claim policy
          </h4>
          <dl className="mt-2 grid gap-2 md:grid-cols-2">
            {data.metric_definitions.map((definition) => (
              <div key={definition.key}>
                <dt className="text-[11px] font-medium text-fg-2">
                  {definition.label}
                  <span className="ml-1 text-[9px] uppercase tracking-wide text-fg-3">
                    {definition.kind === 'guardrail' ? 'guardrail' : 'outcome'} ·{' '}
                    {definition.direction === 'down' ? 'lower is better' : 'higher is better'}
                  </span>
                </dt>
                <dd className="text-[10px] leading-relaxed text-fg-3">{definition.definition}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-[10px] leading-relaxed text-fg-3">
            <span className="font-medium text-fg-2">No causal claim.</span> {data.claim.message}{' '}
            Outcome horizon: {data.outcome_horizon_days} days from first exposure. Exposure groups
            are observational and are not randomly assigned.
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
            {data.notes.join(' ')}
          </p>
        </div>
      </div>

      {error ? (
        <div role="alert" className="rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-4 py-3 text-xs text-warn">
          Showing the last successful data. Refresh failed: {error}
        </div>
      ) : null}

      {data.flags.map((flag) => (
        <FlagCard
          key={flag.key}
          flag={flag}
          windowOrder={windowOrder}
          horizonDays={data.outcome_horizon_days}
        />
      ))}

      <p className="text-[10px] text-fg-3">
        Generated {new Date(data.generated_at).toLocaleString()}. Exposure capture is skipped
        when analytics consent is denied or withdrawn; the backend verifies the same first-party
        grant before storing.
      </p>
    </section>
  )
}
