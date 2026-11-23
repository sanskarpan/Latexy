'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  apiClient,
  type AdminActivationResponse,
  type AdminAiCostResponse,
  type AdminFilteredTimeseriesResponse,
  type AdminRetentionResponse,
  type AdminRetentionRow,
  type AdminTimeseriesDimension,
  type AdminTimeseriesMetric,
} from '@/lib/api-client'
import { ActivityAreaChart, FeatureUsageBars } from '@/components/analytics/MetricCharts'
import { formatDateTime, formatMoney, formatNumber, percentage } from './admin-format'

const RANGES = [7, 30, 90] as const
const RETENTION_WEEKS = [8, 12, 26] as const
const PLAN_OPTIONS = ['', 'free', 'basic', 'pro', 'byok', 'team', 'student']

function Card({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tracking-tight ${tone ?? 'text-fg'}`}>{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3_600) return `${(seconds / 60).toFixed(1)}m`
  if (seconds < 86_400) return `${(seconds / 3_600).toFixed(1)}h`
  return `${(seconds / 86_400).toFixed(1)}d`
}

function retentionCell(cell: { numerator: number; denominator: number; rate: number | null }): string {
  return `${formatNumber(cell.numerator)} / ${formatNumber(cell.denominator)} · ${
    cell.rate == null ? '—' : `${cell.rate}%`
  }`
}

function cohortLabel(row: AdminRetentionRow): string {
  return row.signup_month ?? row.week_start ?? '—'
}

function Funnel({ data }: { data: AdminActivationResponse }) {
  const max = Math.max(...data.steps.map((step) => step.count), 1)
  const windows = data.windows ?? {}
  const windowKeys = Object.keys(windows).sort((left, right) => Number(left) - Number(right))
  const minimum = data.minimum_segment_size ?? 5
  const segmentTables = [
    { key: 'by_plan', title: 'By current plan', rows: data.by_plan, hidden: data.suppressed_segments?.plan ?? 0 },
    {
      key: 'by_provider',
      title: 'By auth provider',
      rows: data.by_provider,
      hidden: data.suppressed_segments?.provider ?? 0,
    },
    {
      key: 'by_signup_cohort',
      title: 'By signup cohort',
      rows: data.by_signup_cohort ?? [],
      hidden: data.suppressed_segments?.signup_cohort ?? 0,
    },
  ] as const

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-fg">Activation funnel</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Users who signed up in the selected period and reached each milestone within {data.activation_window_days} days.
            Each milestone is the first occurrence per account from first-party tables; no document content is read.
          </p>
        </div>
        <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
          {formatNumber(data.cohort_size)} signups
        </span>
      </div>
      <div className="mt-4 space-y-3">
        {data.steps.map((step) => (
          <div key={step.key}>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="text-fg-2">{step.label}</span>
              <span className="font-semibold text-fg">
                {formatNumber(step.count)} <span className="font-normal text-fg-3">({step.from_signup}% of signup)</span>
              </span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(2, Math.round((step.count / max) * 100))}%` }} />
            </div>
            {step.key !== 'signup' && (
              <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-fg-3">
                <span>Step conversion: {step.from_previous}%</span>
                <span>
                  Drop-off: {formatNumber(step.drop_off ?? 0)} ({(step.drop_off_pct ?? 0).toFixed(1)}%)
                </span>
                <span>Median time: {formatDuration(step.median_seconds_from_previous)}</span>
              </p>
            )}
          </div>
        ))}
      </div>

      {windowKeys.length > 0 && (
        <div className="mt-5 overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[420px] border-collapse text-xs">
            <caption className="sr-only">Activation counts by 7, 30 and 90 day window</caption>
            <thead>
              <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-3 py-2 text-left font-semibold">Milestone</th>
                {windowKeys.map((key) => (
                  <th key={key} scope="col" className="px-3 py-2 text-right font-semibold">{key}d</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.steps.map((step) => (
                <tr key={step.key} className="border-t border-line">
                  <td className="px-3 py-1.5 text-fg-2">{step.label}</td>
                  {windowKeys.map((key) => (
                    <td key={key} className="px-3 py-1.5 text-right text-fg">
                      {formatNumber(windows[key]?.steps.find((item) => item.key === step.key)?.count ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        {segmentTables.map((table) => (
          <div key={table.key} className="overflow-hidden rounded-md border border-line">
            <p className="border-b border-line bg-surface-2/60 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              {table.title}
            </p>
            <table className="w-full border-collapse text-xs">
              <caption className="sr-only">Activation segments {table.key}</caption>
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-fg-3">
                  <th className="px-3 py-1.5">Segment</th>
                  <th className="px-3 py-1.5 text-right">Users</th>
                  <th className="px-3 py-1.5 text-right">Compiled</th>
                  <th className="px-3 py-1.5 text-right">Paid</th>
                </tr>
              </thead>
              <tbody>
                {table.rows.slice(0, 8).map((segment) => (
                  <tr key={segment.label} className="border-t border-line">
                    <td className="px-3 py-1.5 capitalize text-fg-2">{segment.label}</td>
                    <td className="px-3 py-1.5 text-right text-fg">{formatNumber(segment.users)}</td>
                    <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(segment.steps.first_compile)}</td>
                    <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(segment.steps.first_paid)}</td>
                  </tr>
                ))}
                {table.rows.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-center text-fg-3">
                      No segment has at least {minimum} users.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            {table.hidden > 0 && (
              <p className="border-t border-line px-3 py-1.5 text-[10px] text-fg-3">
                {table.hidden} small {table.hidden === 1 ? 'segment' : 'segments'} hidden ({'<'}
                {minimum} users).
              </p>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

function Retention({ data }: { data: AdminRetentionResponse }) {
  const monthlyRows = data.monthly ?? []
  const rows = data.signup_month ? monthlyRows : data.cohorts
  const selectedWeekly = data.signup_month ? monthlyRows[0]?.weekly ?? [] : data.curves?.weekly ?? []
  const hidden = (data.hidden_weekly_cohorts ?? 0) + (data.hidden_monthly_cohorts ?? 0)

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">Retention cohorts</h3>
        <p className="mt-1 text-xs leading-relaxed text-fg-3">
          Activity in the exact day/week window after signup. D1 is day 1, not day 0. Cohorts below{' '}
          {data.minimum_cohort_size} users are hidden; missing activity is a zero point. {data.activity_definition}
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <caption className="sr-only">Retention cohorts by signup week or month</caption>
          <thead>
            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
              <th scope="col" className="px-4 py-3 text-left font-semibold">{data.signup_month ? 'Signup month' : 'Cohort week'}</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">Users</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">D1</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">D7</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">D30</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">W1</th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">W2+</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={cohortLabel(row)} className="border-t border-line">
                <td className="px-4 py-2.5 text-xs text-fg-2">{cohortLabel(row)}</td>
                <td className="px-4 py-2.5 text-right text-xs text-fg">{formatNumber(row.cohort_size)}</td>
                {[row.d1, row.d7, row.d30, row.w1, row.w2_plus].map((cell, index) => (
                  <td key={index} className="px-4 py-2.5 text-right text-xs text-fg-3">
                    {retentionCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-fg-3">
                  No cohort in this selection has at least {data.minimum_cohort_size} users.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="border-t border-line px-5 py-4">
        <h4 className="text-xs font-semibold text-fg">Weekly curve</h4>
        <p className="mt-1 text-[10px] text-fg-3">
          Weekly activity windows for the selected {data.signup_month ? 'signup month' : 'visible weekly cohorts'}.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[420px] border-collapse text-xs">
            <caption className="sr-only">Weekly retention curve</caption>
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-3 py-2 text-left font-semibold">Week</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Retained / eligible</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Cohort size</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Rate</th>
              </tr>
            </thead>
            <tbody>
              {selectedWeekly.map((point) => (
                <tr key={point.week} className="border-t border-line">
                  <td className="px-3 py-1.5 text-fg-2">W{point.week}</td>
                  <td className="px-3 py-1.5 text-right text-fg-3">
                    {formatNumber(point.numerator)} / {formatNumber(point.denominator)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(point.cohort_size)}</td>
                  <td className="px-3 py-1.5 text-right text-fg">{point.rate == null ? '—' : `${point.rate}%`}</td>
                </tr>
              ))}
              {selectedWeekly.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-fg-3">No weekly points for this selection.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {hidden > 0 && (
          <p className="mt-2 text-[10px] text-fg-3">
            {hidden} cohort{hidden === 1 ? '' : 's'} below {data.minimum_cohort_size} users hidden.
          </p>
        )}
      </div>
    </section>
  )
}

function Cost({ data }: { data: AdminAiCostResponse }) {
  const dailySeries = useMemo(
    () => data.by_day.map((row) => ({ date: row.date, value: row.cost_usd })),
    [data.by_day],
  )
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="Estimated AI cost" value={formatMoney(data.total_cost_inr, 'INR')} detail={`$${data.total_cost_usd} · ${formatNumber(data.total_tokens)} tokens`} />
        <Card label="Optimizations" value={formatNumber(data.optimizations)} detail={`Last ${data.period_days} days`} />
        <Card
          label="Monthly cap"
          value={data.monthly_spend_cap_usd == null ? 'Not set' : `$${data.monthly_spend_cap_usd}`}
          detail={data.alerts.some((alert) => alert.code === 'ai_monthly_cap') ? 'Cap reached' : 'Within configured cap'}
          tone={data.alerts.some((alert) => alert.code === 'ai_monthly_cap') ? 'text-err' : 'text-fg'}
        />
        <Card label="USD → INR" value={String(data.usd_inr_rate)} detail="Operator-configured estimate" />
      </div>
      {data.alerts.length > 0 && (
        <div className="space-y-2">
          {data.alerts.map((alert, index) => (
            <div key={`${alert.code}-${index}`} role="alert" className={`rounded-md border px-4 py-3 text-xs ${alert.severity === 'critical' ? 'border-err/30 bg-err/10 text-err' : 'border-warn/30 bg-warn/10 text-warn'}`}>
              {alert.message}
            </div>
          ))}
        </div>
      )}
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <h3 className="text-sm font-semibold text-fg">Estimated cost per day</h3>
        <p className="mt-1 text-[11px] text-fg-3">{data.price_note}</p>
        <div className="mt-3"><ActivityAreaChart data={dailySeries} /></div>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">By model</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {data.by_model.slice(0, 8).map((row) => (
              <li key={`${row.provider}:${row.model}`} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="truncate text-fg-2">{row.provider}/{row.model}</span>
                <span className="shrink-0 text-fg-3">
                  ${row.cost_usd} · {formatNumber(row.tokens)}
                  {row.fallback_price ? ' · fallback price' : ''}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Top users</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {data.top_users.slice(0, 8).map((row) => (
              <li key={row.user_id} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="font-mono text-[10px] text-fg-2">{row.user_id.slice(0, 10)}…</span>
                <span className="shrink-0 text-fg-3">{row.plan} · ${row.cost_usd}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Margin by plan</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {data.margin_by_plan.map((row) => (
              <li key={row.plan} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="capitalize text-fg-2">{row.plan}</span>
                <span className={`shrink-0 ${row.gross_margin_inr < 0 ? 'text-err' : 'text-ok'}`}>
                  {formatMoney(row.gross_margin_inr)} <span className="text-fg-3">margin</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

function Explorer({
  data,
  metric,
  dimension,
  value,
  onMetric,
  onDimension,
  onValue,
  onApply,
  loading,
}: {
  data: AdminFilteredTimeseriesResponse | null
  metric: AdminTimeseriesMetric
  dimension: '' | AdminTimeseriesDimension
  value: string
  onMetric: (value: AdminTimeseriesMetric) => void
  onDimension: (value: '' | AdminTimeseriesDimension) => void
  onValue: (value: string) => void
  onApply: () => void
  loading: boolean
}) {
  const placeholder = dimension === 'feature'
    ? 'export'
    : dimension === 'provider'
      ? 'google, github…'
      : dimension === 'signup_cohort'
        ? '2026-11'
        : 'pro'
  const minimum = data?.minimum_group_size ?? 5

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <h3 className="text-sm font-semibold text-fg">Dimension explorer</h3>
      <p className="mt-1 text-xs leading-relaxed text-fg-3">
        Daily UTC buckets for account and product activity with a plan, provider, feature, or signup-cohort filter.
        Small groups under {minimum} users are suppressed; totals stay aggregate only.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-[11px] text-fg-2">
          Metric
          <select value={metric} onChange={(event) => onMetric(event.target.value as AdminTimeseriesMetric)} className="mt-1 block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            <option value="events">Events</option>
            <option value="new_users">New users</option>
            <option value="active_users">Active users</option>
            <option value="compilations">Compilations</option>
            <option value="optimizations">Optimizations</option>
            <option value="revenue">Revenue (INR)</option>
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Dimension
          <select value={dimension} onChange={(event) => onDimension(event.target.value as '' | AdminTimeseriesDimension)} className="mt-1 block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            <option value="">Overall</option>
            <option value="plan">Plan</option>
            <option value="provider">Auth provider</option>
            <option value="feature" disabled={metric !== 'events'}>Feature / action</option>
            <option value="signup_cohort">Signup cohort</option>
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Filter value
          <input value={value} onChange={(event) => onValue(event.target.value)} maxLength={120} placeholder={placeholder} className="mt-1 block min-h-[38px] w-44 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
        </label>
        <button type="button" onClick={onApply} disabled={loading} className="min-h-[38px] rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40">
          Apply
        </button>
      </div>
      {data && (
        <>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-fg-3">
            <span>
              Echo: {data.days ?? '—'} days · {data.filters?.metric ?? data.metric}
              {data.dimension ? ` by ${data.dimension}` : ''}
              {data.value ? ` = ${data.value}` : ''} · UTC
            </span>
            {data.suppressed && (
              <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 font-semibold text-warn">
                Filtered cohort suppressed ({'<'}
                {minimum} users)
              </span>
            )}
            {(data.suppressed_groups ?? 0) > 0 && (
              <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5">
                {data.suppressed_groups} small group{data.suppressed_groups === 1 ? '' : 's'} hidden
              </span>
            )}
          </div>
          <div className="mt-4"><ActivityAreaChart data={data.points} /></div>
          <div className="mt-3 grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Total</p>
              <p className="text-lg font-semibold text-fg">{data.metric === 'revenue' ? formatMoney(data.total) : formatNumber(data.total)}</p>
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Breakdown</p>
              <FeatureUsageBars data={data.breakdown.slice(0, 8).map((row) => ({ name: row.label, value: row.value }))} />
            </div>
          </div>
        </>
      )}
    </section>
  )
}

export default function AdminGrowth() {
  const [days, setDays] = useState<number>(30)
  const [retentionWeeks, setRetentionWeeks] = useState<number>(8)
  const [signupMonth, setSignupMonth] = useState('')
  const [activation, setActivation] = useState<AdminActivationResponse | null>(null)
  const [retention, setRetention] = useState<AdminRetentionResponse | null>(null)
  const [cost, setCost] = useState<AdminAiCostResponse | null>(null)
  const [series, setSeries] = useState<AdminFilteredTimeseriesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [plan, setPlan] = useState('')
  const [provider, setProvider] = useState('')
  const [metric, setMetric] = useState<AdminTimeseriesMetric>('events')
  const [dimension, setDimension] = useState<'' | AdminTimeseriesDimension>('plan')
  const [value, setValue] = useState('pro')
  const [applied, setApplied] = useState<{
    metric: AdminTimeseriesMetric
    dimension: '' | AdminTimeseriesDimension
    value: string
  }>({ metric: 'events', dimension: 'plan', value: 'pro' })
  const [explorerLoading, setExplorerLoading] = useState(false)
  const loadGeneration = useRef(0)
  const seriesGeneration = useRef(0)

  const load = useCallback(async () => {
    const generation = ++loadGeneration.current
    setLoading(true)
    setError(null)
    try {
      const [nextActivation, nextRetention, nextCost] = await Promise.all([
        apiClient.getAdminActivation({
          days,
          plan: plan || undefined,
          provider: provider || undefined,
        }),
        apiClient.getAdminRetention(retentionWeeks, signupMonth || undefined),
        apiClient.getAdminAiCost(days),
      ])
      if (loadGeneration.current !== generation) return
      setActivation(nextActivation)
      setRetention(nextRetention)
      setCost(nextCost)
    } catch (err) {
      if (loadGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load growth analytics')
      }
    } finally {
      if (loadGeneration.current === generation) setLoading(false)
    }
  }, [days, plan, provider, retentionWeeks, signupMonth])

  useEffect(() => {
    void load()
  }, [load])

  const loadSeries = useCallback(async () => {
    const generation = ++seriesGeneration.current
    setExplorerLoading(true)
    try {
      const next = await apiClient.getAdminFilteredTimeseries({
        days,
        metric: applied.metric,
        dimension: applied.dimension || undefined,
        value: applied.value || undefined,
      })
      if (seriesGeneration.current === generation) setSeries(next)
    } catch (err) {
      if (seriesGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load filtered series')
      }
    } finally {
      if (seriesGeneration.current === generation) setExplorerLoading(false)
    }
  }, [applied, days])

  useEffect(() => {
    void loadSeries()
  }, [loadSeries])

  const signupMonths = retention?.available_signup_months ?? []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-fg">Growth, retention, and AI cost</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Milestone activation, D1/D7/D30 and weekly cohorts, dimension-filtered daily series, and estimated provider
            spend from first-party records. Amounts and margins are labeled estimates; they are not an invoice or a
            substitute for provider billing.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5" role="group" aria-label="Growth period">
            {RANGES.map((range) => (
              <button key={range} type="button" aria-pressed={days === range} onClick={() => setDays(range)} className={`rounded px-3 py-1.5 text-xs font-medium ${days === range ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'}`}>
                {range} days
              </button>
            ))}
          </div>
          <select aria-label="Activation plan filter" value={plan} onChange={(event) => setPlan(event.target.value)} className="min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            {PLAN_OPTIONS.map((item) => <option key={item || 'all'} value={item}>{item || 'All plans'}</option>)}
          </select>
          <input aria-label="Activation provider filter" value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="provider" className="min-h-[38px] w-28 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
          <select aria-label="Retention weeks" value={retentionWeeks} onChange={(event) => setRetentionWeeks(Number(event.target.value))} className="min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            {RETENTION_WEEKS.map((weeks) => <option key={weeks} value={weeks}>{weeks} weeks</option>)}
          </select>
          <select aria-label="Signup month" value={signupMonth} onChange={(event) => setSignupMonth(event.target.value)} className="min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            <option value="">All signup months</option>
            {signupMonths.map((month) => (
              <option key={month.month} value={month.month}>{month.month} · {formatNumber(month.users)} users</option>
            ))}
          </select>
          <button type="button" onClick={() => void load()} disabled={loading} className="rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <div role="alert" className="rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err">{error}</div>}
      {loading && !activation && <div role="status" className="py-12 text-center text-sm text-fg-3">Loading growth analytics…</div>}

      {activation && <Funnel data={activation} />}
      {retention && <Retention data={retention} />}
      {cost && <Cost data={cost} />}

      <Explorer
        data={series}
        metric={metric}
        dimension={dimension}
        value={value}
        onMetric={(next) => {
          setMetric(next)
          if (next !== 'events' && dimension === 'feature') {
            setDimension('plan')
            setValue('pro')
          }
        }}
        onDimension={(next) => {
          if (metric !== 'events' && next === 'feature') return
          setDimension(next)
          setValue(
            next === 'plan'
              ? 'pro'
              : next === 'feature'
                ? 'export'
                : next === 'signup_cohort'
                  ? new Date().toISOString().slice(0, 7)
                  : '',
          )
        }}
        onValue={setValue}
        onApply={() => setApplied({ metric, dimension, value })}
        loading={explorerLoading}
      />

      <p className="text-[10px] text-fg-3">
        Retention requires at least {retention?.minimum_cohort_size ?? 5} users per cohort before rates are shown.
        Activation and timeseries segments below 5 users are hidden. AI cost uses {cost?.price_note ?? 'configured provider prices'} Last generated {formatDateTime(cost?.generated_at)}.
      </p>
      {activation && activation.cohort_size > 0 && (
        <p className="text-[10px] text-fg-3">
          Activation cohort size {formatNumber(activation.cohort_size)}. Paid conversion{' '}
          {percentage(activation.steps.find((step) => step.key === 'first_paid')?.count ?? 0, activation.cohort_size)}.
        </p>
      )}
    </div>
  )
}
