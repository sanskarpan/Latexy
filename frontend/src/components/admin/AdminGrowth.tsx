'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  apiClient,
  type AdminActivationResponse,
  type AdminAiCostResponse,
  type AdminFilteredTimeseriesResponse,
  type AdminRetentionResponse,
} from '@/lib/api-client'
import { ActivityAreaChart, FeatureUsageBars } from '@/components/analytics/MetricCharts'
import { formatDateTime, formatMoney, formatNumber, percentage } from './admin-format'

const RANGES = [30, 90] as const
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

function Funnel({ data }: { data: AdminActivationResponse }) {
  const max = Math.max(...data.steps.map((step) => step.count), 1)
  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-fg">Activation funnel</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Users who signed up in the period and reached each milestone within {data.activation_window_days} days.
            No document content is read for this view.
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
            {step.key !== 'signup' && <p className="mt-1 text-[10px] text-fg-3">Step conversion: {step.from_previous}%</p>}
          </div>
        ))}
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        {(['by_plan', 'by_provider'] as const).map((key) => (
          <div key={key} className="overflow-hidden rounded-md border border-line">
            <p className="border-b border-line bg-surface-2/60 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              {key === 'by_plan' ? 'By current plan' : 'By auth provider'}
            </p>
            <table className="w-full border-collapse text-xs">
              <caption className="sr-only">Activation segments {key}</caption>
              <thead><tr className="text-left text-[10px] uppercase tracking-wider text-fg-3"><th className="px-3 py-1.5">Segment</th><th className="px-3 py-1.5 text-right">Users</th><th className="px-3 py-1.5 text-right">Compiled</th><th className="px-3 py-1.5 text-right">Paid</th></tr></thead>
              <tbody>
                {data[key].slice(0, 8).map((segment) => (
                  <tr key={segment.label} className="border-t border-line">
                    <td className="px-3 py-1.5 capitalize text-fg-2">{segment.label}</td>
                    <td className="px-3 py-1.5 text-right text-fg">{formatNumber(segment.users)}</td>
                    <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(segment.steps.first_compile)}</td>
                    <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(segment.steps.first_paid)}</td>
                  </tr>
                ))}
                {data[key].length === 0 && <tr><td colSpan={4} className="px-3 py-4 text-center text-fg-3">No segments.</td></tr>}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </section>
  )
}

function Retention({ data }: { data: AdminRetentionResponse }) {
  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">Weekly retention</h3>
        <p className="mt-1 text-xs leading-relaxed text-fg-3">
          Activity in the exact day window after signup (D1 = day 1, not day 0). Cohorts below {data.minimum_cohort_size} users
          do not show rates. Activity is any first-party event, completed compile, or optimization.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-sm">
          <caption className="sr-only">Weekly retention cohorts</caption>
          <thead>
            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
              <th className="px-4 py-3 text-left font-semibold">Cohort week</th>
              <th className="px-4 py-3 text-right font-semibold">Users</th>
              <th className="px-4 py-3 text-right font-semibold">D1</th>
              <th className="px-4 py-3 text-right font-semibold">D7</th>
              <th className="px-4 py-3 text-right font-semibold">D30</th>
            </tr>
          </thead>
          <tbody>
            {data.cohorts.map((row) => (
              <tr key={row.week_start} className="border-t border-line">
                <td className="px-4 py-2.5 text-xs text-fg-2">{row.week_start}</td>
                <td className="px-4 py-2.5 text-right text-xs text-fg">{formatNumber(row.cohort_size)}</td>
                {[row.d1, row.d7, row.d30].map((cell, index) => (
                  <td key={index} className="px-4 py-2.5 text-right text-xs text-fg-3">
                    {cell.rate == null
                      ? `${formatNumber(cell.count)} / ${formatNumber(cell.eligible)} · —`
                      : `${formatNumber(cell.count)} / ${formatNumber(cell.eligible)} · ${cell.rate}%`}
                  </td>
                ))}
              </tr>
            ))}
            {data.cohorts.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-fg-3">No cohorts in this window.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function Cost({
  data,
  plan,
  feature,
  onPlan,
  onFeature,
  onApply,
  loading,
}: {
  data: AdminAiCostResponse
  plan: string
  feature: string
  onPlan: (value: string) => void
  onFeature: (value: string) => void
  onApply: () => void
  loading: boolean
}) {
  const dailySeries = useMemo(
    () => data.by_day.map((row) => ({ date: row.date, value: row.cost_usd })),
    [data.by_day],
  )
  const hardCapReached = data.caps.global.decision === 'block'
  const capDetail = data.caps.global.monthly_hard_cap_usd == null
    ? 'No monthly cap configured'
    : `${formatMoney(data.caps.global.month_to_date_usd, 'USD')} of ${formatMoney(data.caps.global.monthly_hard_cap_usd, 'USD')} month-to-date`
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="Estimated AI cost" value={formatMoney(data.total_cost_inr, 'INR')} detail={`$${data.total_cost_usd} · ${formatNumber(data.total_tokens)} tokens`} />
        <Card
          label="Gross margin"
          value={formatMoney(data.gross_margin_inr, 'INR')}
          detail={`${formatMoney(data.total_revenue_inr, 'INR')} revenue`}
          tone={data.gross_margin_inr < 0 ? 'text-err' : 'text-ok'}
        />
        <Card
          label="Monthly cap"
          value={data.caps.global.monthly_hard_cap_usd == null ? 'Not set' : formatMoney(data.caps.global.monthly_hard_cap_usd, 'USD')}
          detail={capDetail}
          tone={hardCapReached ? 'text-err' : 'text-fg'}
        />
        <Card label="Pricing version" value={data.pricing_version} detail={`${data.pricing.models.length} configured models`} />
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
      <div className="flex flex-wrap items-end gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <label className="text-[11px] text-fg-2">
          Cost plan filter
          <select value={plan} onChange={(event) => onPlan(event.target.value)} className="mt-1 block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            {PLAN_OPTIONS.map((item) => <option key={item || 'all'} value={item}>{item || 'All plans'}</option>)}
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Cost feature filter
          <input value={feature} onChange={(event) => onFeature(event.target.value)} maxLength={120} placeholder="optimization_patches" className="mt-1 block min-h-[38px] w-48 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
        </label>
        <button type="button" onClick={onApply} disabled={loading} className="min-h-[38px] rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40">
          Apply cost filters
        </button>
        <span className="text-[10px] text-fg-3">
          Costs in USD minor units (cents); revenue and margin in INR minor units (paise).
        </span>
      </div>
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
                <span className="font-mono text-[10px] text-fg-2">{(row.user_id ?? row.label).slice(0, 10)}…</span>
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
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">By feature</h3>
          <p className="mt-1 text-[10px] text-fg-3">Revenue is apportioned proportional to AI cost when a feature is selected.</p>
          <ul className="mt-2 space-y-1 text-xs">
            {data.by_feature.slice(0, 10).map((row) => (
              <li key={row.feature ?? row.label} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="truncate text-fg-2">{row.feature ?? row.label}</span>
                <span className="shrink-0 text-fg-3">${row.cost_usd} · {row.revenue_attribution ?? 'unattributed'}</span>
              </li>
            ))}
            {data.by_feature.length === 0 && <li className="py-3 text-center text-fg-3">No feature cost rows.</li>}
          </ul>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">By persona</h3>
          <p className="mt-1 text-[10px] text-fg-3">Best-effort from the resume&apos;s last saved persona; missing values stay unknown.</p>
          <ul className="mt-2 space-y-1 text-xs">
            {data.by_persona.map((row) => (
              <li key={row.persona ?? row.label} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="truncate text-fg-2">{row.persona ?? row.label}</span>
                <span className="shrink-0 text-fg-3">${row.cost_usd} · {formatNumber(row.tokens)}</span>
              </li>
            ))}
            {data.by_persona.length === 0 && <li className="py-3 text-center text-fg-3">No persona cost rows.</li>}
          </ul>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Cap status</h3>
          <p className="mt-1 text-[10px] text-fg-3">
            Hard caps stop new jobs only. In-flight jobs are never interrupted and no account is auto-suspended.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <span className="text-fg-3">Users over hard cap</span>
            <span className="text-right font-semibold text-fg">{formatNumber(data.caps.summary.users_over_hard_cap)}</span>
            <span className="text-fg-3">Users over soft cap</span>
            <span className="text-right font-semibold text-fg">{formatNumber(data.caps.summary.users_over_soft_cap)}</span>
            <span className="text-fg-3">Unknown pricing users</span>
            <span className="text-right font-semibold text-fg">{formatNumber(data.caps.summary.users_with_unknown_pricing)}</span>
            <span className="text-fg-3">Day resets</span>
            <span className="text-right text-fg-2">{formatDateTime(data.caps.window.day_resets_at)}</span>
            <span className="text-fg-3">Month resets</span>
            <span className="text-right text-fg-2">{formatDateTime(data.caps.window.month_resets_at)}</span>
          </div>
          <ul className="mt-3 space-y-1 text-xs">
            {data.caps.users.filter((row) => row.decision !== 'allow').slice(0, 8).map((row) => (
              <li key={row.user_id} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="font-mono text-[10px] text-fg-2">{row.user_id.slice(0, 10)}…</span>
                <span className={row.decision === 'block' ? 'text-err' : 'text-warn'}>
                  {row.decision} · ${row.month_to_date_usd} month / ${row.today_usd} day
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Rolling outliers</h3>
          <p className="mt-1 text-[10px] text-fg-3">
            Median + MAD over {data.outliers[0]?.baseline_days ?? 'the configured'} baseline days; a minimum sample window is required before alerting.
          </p>
          <ul className="mt-2 space-y-1 text-xs">
            {data.outliers.slice(0, 10).map((row) => (
              <li key={`${row.dimension}-${row.key}`} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="truncate text-fg-2">{row.dimension} · {row.key.slice(0, 24)}</span>
                <span className="shrink-0 text-warn">${row.today_usd} today vs ${row.baseline_median_usd} median</span>
              </li>
            ))}
            {data.outliers.length === 0 && <li className="py-3 text-center text-fg-3">No rolling outliers today.</li>}
          </ul>
        </div>
      </div>
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <h3 className="text-sm font-semibold text-fg">Sampled invoice reconciliation</h3>
        <p className="mt-1 text-[11px] text-fg-3">
          Contract {data.reconciliation.contract_version}. No provider credential is read. Status: {data.reconciliation.status}.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3 text-xs">
          <div><p className="text-fg-3">Ledger</p><p className="font-semibold text-fg">${(data.reconciliation.ledger_total_minor / 100).toFixed(2)}</p></div>
          <div><p className="text-fg-3">Sampled invoice</p><p className="font-semibold text-fg">{data.reconciliation.sampled_invoice.total_minor == null ? 'Not supplied' : `$${(data.reconciliation.sampled_invoice.total_minor / 100).toFixed(2)}`}</p></div>
          <div><p className="text-fg-3">Variance</p><p className={`font-semibold ${data.reconciliation.sampled_invoice.variance_minor != null && !data.reconciliation.sampled_invoice.within_tolerance ? 'text-err' : 'text-fg'}`}>{data.reconciliation.sampled_invoice.variance_minor == null ? '—' : `$${(data.reconciliation.sampled_invoice.variance_minor / 100).toFixed(2)}`}</p></div>
        </div>
        <ul className="mt-3 space-y-1 text-xs">
          {data.reconciliation.sources.map((row) => (
            <li key={row.source} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
              <span className="text-fg-2">{row.source.replace(/_/g, ' ')}</span>
              <span className="text-fg-3">{row.runs} runs · ${row.cost_usd} · {formatNumber(row.tokens)} tokens</span>
            </li>
          ))}
        </ul>
        {data.pricing_complete ? null : (
          <p className="mt-3 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            {formatNumber(data.unknown_pricing.runs)} unpriced run(s) use a visible fallback estimate. Add their provider/model price before trusting margin.
          </p>
        )}
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
  metric: 'events' | 'compilations' | 'optimizations' | 'revenue'
  dimension: '' | 'plan' | 'provider' | 'feature'
  value: string
  onMetric: (value: 'events' | 'compilations' | 'optimizations' | 'revenue') => void
  onDimension: (value: '' | 'plan' | 'provider' | 'feature') => void
  onValue: (value: string) => void
  onApply: () => void
  loading: boolean
}) {
  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <h3 className="text-sm font-semibold text-fg">Dimension explorer</h3>
      <p className="mt-1 text-xs leading-relaxed text-fg-3">
        The same first-party series with a plan, provider, or feature filter. Provider labels come from the auth account
        table; unknown users are grouped as unknown.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-[11px] text-fg-2">
          Metric
          <select value={metric} onChange={(event) => onMetric(event.target.value as typeof metric)} className="mt-1 block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            <option value="events">Events</option>
            <option value="compilations">Compilations</option>
            <option value="optimizations">Optimizations</option>
            <option value="revenue">Revenue (INR)</option>
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Dimension
          <select value={dimension} onChange={(event) => onDimension(event.target.value as typeof dimension)} className="mt-1 block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
            <option value="">Overall</option>
            <option value="plan">Plan</option>
            <option value="provider">Auth provider</option>
            <option value="feature" disabled={metric !== 'events'}>Feature / action</option>
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Filter value
          <input value={value} onChange={(event) => onValue(event.target.value)} maxLength={120} placeholder={dimension === 'feature' ? 'export' : dimension === 'provider' ? 'google, github…' : 'pro'} className="mt-1 block min-h-[38px] w-44 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
        </label>
        <button type="button" onClick={onApply} disabled={loading} className="min-h-[38px] rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40">
          Apply
        </button>
      </div>
      {data && (
        <>
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
  const [activation, setActivation] = useState<AdminActivationResponse | null>(null)
  const [retention, setRetention] = useState<AdminRetentionResponse | null>(null)
  const [cost, setCost] = useState<AdminAiCostResponse | null>(null)
  const [series, setSeries] = useState<AdminFilteredTimeseriesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [plan, setPlan] = useState('')
  const [provider, setProvider] = useState('')
  const [costPlan, setCostPlan] = useState('')
  const [costFeature, setCostFeature] = useState('')
  const [costApplied, setCostApplied] = useState<{ plan: string; feature: string }>({ plan: '', feature: '' })
  const [metric, setMetric] = useState<'events' | 'compilations' | 'optimizations' | 'revenue'>('events')
  const [dimension, setDimension] = useState<'' | 'plan' | 'provider' | 'feature'>('plan')
  const [value, setValue] = useState('pro')
  const [applied, setApplied] = useState<{
    metric: 'events' | 'compilations' | 'optimizations' | 'revenue'
    dimension: '' | 'plan' | 'provider' | 'feature'
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
        apiClient.getAdminRetention(8),
        apiClient.getAdminAiCost({
          days,
          plan: costApplied.plan || undefined,
          feature: costApplied.feature || undefined,
        }),
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
  }, [days, plan, provider, costApplied])

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

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-fg">Growth, retention, and AI cost</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Milestone activation, weekly cohorts, and estimated provider spend from first-party records. Amounts and
            margins are labeled estimates; they are not an invoice or a substitute for provider billing.
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
          <button type="button" onClick={() => void load()} disabled={loading} className="rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <div role="alert" className="rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err">{error}</div>}
      {loading && !activation && <div role="status" className="py-12 text-center text-sm text-fg-3">Loading growth analytics…</div>}

      {activation && <Funnel data={activation} />}
      {retention && <Retention data={retention} />}
      {cost && (
        <Cost
          data={cost}
          plan={costPlan}
          feature={costFeature}
          onPlan={setCostPlan}
          onFeature={setCostFeature}
          onApply={() => setCostApplied({ plan: costPlan, feature: costFeature })}
          loading={loading}
        />
      )}

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
          setValue(next === 'plan' ? 'pro' : next === 'feature' ? 'export' : '')
        }}
        onValue={setValue}
        onApply={() => setApplied({ metric, dimension, value })}
        loading={explorerLoading}
      />

      <p className="text-[10px] text-fg-3">
        Retention requires at least {retention?.minimum_cohort_size ?? 5} users per cohort before rates are shown.
        AI cost uses {cost?.price_note ?? 'configured provider prices'} Last generated {formatDateTime(cost?.generated_at)}.
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
