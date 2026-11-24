'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, type AdminAnalyticsOverviewResponse, type AdminKpiTrend } from '@/lib/api-client'
import { ActivityAreaChart, FeatureUsageBars } from '@/components/analytics/MetricCharts'
import AdminCompileLatency from '@/components/admin/AdminCompileLatency'
import AdminOperations from '@/components/admin/AdminOperations'
import { analyticsDashboardLinks, analyticsReplayTriageLinks } from '@/lib/analytics/posthog'

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
] as const

const numberFormatter = new Intl.NumberFormat('en-IN')
const currencyFormatter = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})

function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(Number.isFinite(value ?? NaN) ? Number(value) : 0)
}

function formatCurrency(value: number | null | undefined): string {
  return currencyFormatter.format(Number.isFinite(value ?? NaN) ? Number(value) : 0)
}

function formatPercent(value: number | null | undefined): string {
  return `${(Number.isFinite(value ?? NaN) ? Number(value) : 0).toFixed(1)}%`
}

function shortId(value: string | null): string {
  if (!value) return 'anonymous'
  return value.length > 12 ? `${value.slice(0, 8)}…` : value
}

function metadataSummary(metadata: Record<string, unknown>): string {
  const entries = Object.entries(metadata).slice(0, 4)
  if (entries.length === 0) return '—'
  return entries
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value.slice(0, 40) : String(value)}`)
    .join(' · ')
}

function Sparkline({ points, label }: { points: AdminKpiTrend['sparkline']; label: string }) {
  const values = points
    .map((point) => point.value)
    .filter((value) => Number.isFinite(value))
  if (values.length < 2) return null
  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min || 1
  const width = 100
  const height = 24
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width
      const y = height - ((value - min) / range) * height
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <div className="mt-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-6 w-full text-accent"
        aria-hidden="true"
        focusable="false"
        preserveAspectRatio="none"
      >
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <span className="sr-only">
        {label} trend from {formatNumber(values[0])} to {formatNumber(values[values.length - 1])} over the selected period.
      </span>
    </div>
  )
}

function TrendNote({ trend }: { trend: AdminKpiTrend }) {
  const percent = Number.isFinite(trend.percent_delta ?? NaN) ? trend.percent_delta : null
  const neutral = percent === null || trend.baseline_zero
  const tone = neutral ? 'text-fg-3' : percent >= 0 ? 'text-ok' : 'text-err'
  const absolute = trend.unit === 'currency'
    ? formatCurrency(trend.absolute_delta)
    : trend.unit === 'percent'
      ? `${trend.absolute_delta >= 0 ? '+' : ''}${trend.absolute_delta.toFixed(1)}pp`
      : formatNumber(trend.absolute_delta)
  return (
    <div className="mt-1">
      <p className={`text-[11px] ${tone}`}>
        {percent === null || trend.baseline_zero ? (
          <span className="font-medium">{trend.baseline_zero ? 'No prior baseline' : 'No prior comparison'}</span>
        ) : (
          <span className="font-medium">
            {percent >= 0 ? '+' : ''}{percent.toFixed(1)}% vs prior period
          </span>
        )}
        <span className="text-fg-3"> · {absolute} change</span>
      </p>
      <Sparkline points={trend.sparkline} label={trend.label} />
    </div>
  )
}

function KpiCard({
  label,
  value,
  detail,
  trend,
}: {
  label: string
  value: string
  detail?: string
  trend?: AdminKpiTrend
}) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{value}</p>
      {detail && <p className="mt-1 text-[11px] text-fg-3">{detail}</p>}
      {trend && <TrendNote trend={trend} />}
    </div>
  )
}

function OperationsStrip({ data }: { data: AdminAnalyticsOverviewResponse['operations'] }) {
  const items = [
    { label: 'Queued', value: data.queued_jobs, tone: 'text-fg' },
    { label: 'Processing', value: data.processing_jobs, tone: 'text-fg' },
    { label: 'Completed 24h', value: data.completed_jobs_24h, tone: 'text-ok' },
    { label: 'Failed 24h', value: data.failed_jobs_24h, tone: data.failed_jobs_24h > 0 ? 'text-err' : 'text-fg' },
    { label: 'Webhook failures 24h', value: data.webhook_failures_24h, tone: data.webhook_failures_24h > 0 ? 'text-err' : 'text-fg' },
    { label: 'Active users 24h', value: data.active_users_24h, tone: 'text-fg' },
  ]
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {items.map((item) => (
        <div key={item.label} className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wider text-fg-3">{item.label}</p>
          <p className={`mt-0.5 text-lg font-semibold ${item.tone}`}>{formatNumber(item.value)}</p>
        </div>
      ))}
    </div>
  )
}

function Funnel({ data }: { data: AdminAnalyticsOverviewResponse['conversion_funnel'] }) {
  const steps = [
    { key: 'landing_visits', label: 'Landing visits' },
    { key: 'trial_starts', label: 'Trial starts' },
    { key: 'registrations', label: 'Registrations' },
    { key: 'subscriptions', label: 'Subscriptions' },
  ] as const
  const max = Math.max(...steps.map((step) => data.funnel_steps[step.key] ?? 0), 1)
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <h3 className="text-sm font-semibold text-fg">Conversion funnel</h3>
      <p className="mt-1 text-xs text-fg-3">First-party events and billing records for the selected period.</p>
      <div className="mt-4 space-y-3">
        {steps.map((step) => {
          const value = data.funnel_steps[step.key] ?? 0
          const width = Math.max(3, Math.round((value / max) * 100))
          return (
            <div key={step.key}>
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-fg-2">{step.label}</span>
                <span className="font-semibold text-fg">{formatNumber(value)}</span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
                <div className="h-full rounded-full bg-accent" style={{ width: `${width}%` }} />
              </div>
            </div>
          )
        })}
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-3 border-t border-line pt-4 text-xs">
        <div>
          <dt className="text-fg-3">Landing → trial</dt>
          <dd className="mt-0.5 font-semibold text-fg">{formatPercent(data.conversion_rates.landing_to_trial)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Trial → registration</dt>
          <dd className="mt-0.5 font-semibold text-fg">{formatPercent(data.conversion_rates.trial_to_registration)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Registration → subscription</dt>
          <dd className="mt-0.5 font-semibold text-fg">{formatPercent(data.conversion_rates.registration_to_subscription)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Overall</dt>
          <dd className="mt-0.5 font-semibold text-fg">{formatPercent(data.conversion_rates.overall_conversion)}</dd>
        </div>
      </dl>
    </div>
  )
}

function RecentEvents({ events }: { events: AdminAnalyticsOverviewResponse['recent_events'] }) {
  if (events.length === 0) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center text-sm text-fg-3">
        No first-party events recorded yet.
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">Recent product events</h3>
        <p className="mt-1 text-xs text-fg-3">Redacted first-party stream. Document content and direct identifiers are removed.</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <caption className="sr-only">Recent product analytics events, newest first</caption>
          <thead>
            <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
              <th scope="col" className="px-5 py-3 text-left font-semibold">Time</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Event</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">User</th>
              <th scope="col" className="px-4 py-3 text-left font-semibold">Properties</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id} className="border-t border-line align-top">
                <td className="whitespace-nowrap px-5 py-3 text-xs text-fg-3">
                  {event.created_at ? new Date(event.created_at).toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-fg">{event.action}</td>
                <td className="px-4 py-3 font-mono text-xs text-fg-3">{shortId(event.user_id)}</td>
                <td className="max-w-[360px] px-4 py-3 text-xs text-fg-3">{metadataSummary(event.metadata)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function AdminAnalytics() {
  const [days, setDays] = useState<number>(30)
  const [data, setData] = useState<AdminAnalyticsOverviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)
  const posthogLinks = analyticsDashboardLinks()
  const replayTriageLinks = useMemo(() => analyticsReplayTriageLinks(days), [days])

  const load = useCallback(async (range: number) => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminAnalyticsOverview(range)
      if (requestGeneration.current === generation) setData(next)
    } catch (err) {
      if (requestGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load analytics')
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

  const activitySeries = useMemo(
    () => (data?.timeseries ?? []).map((point) => ({ date: point.date, value: point.events })),
    [data],
  )
  const compileSeries = useMemo(
    () => (data?.timeseries ?? []).map((point) => ({ date: point.date, value: point.compilations })),
    [data],
  )
  const featureSeries = useMemo(
    () => (data?.top_features ?? []).map((feature) => ({ name: feature.feature, value: feature.count })),
    [data],
  )
  const trendMap = useMemo(
    () => new Map((data?.kpi_trends ?? []).map((trend) => [trend.key, trend])),
    [data],
  )

  if (loading && !data) {
    return (
      <div role="status" className="flex min-h-[40vh] items-center justify-center text-sm text-fg-3">
        Loading analytics…
      </div>
    )
  }

  if (error && !data) {
    return (
      <div role="alert" className="rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.06] px-5 py-6">
        <p className="text-sm font-semibold text-err">Analytics could not be loaded</p>
        <p className="mt-1 text-xs text-err/80">{error}</p>
        <button
          type="button"
          onClick={() => void load(days)}
          className="mt-3 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null
  const { system, operations } = data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-fg">Product analytics</h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            First-party usage, billing and operational health. Session replays and deeper exploration open in PostHog;
            replay is consent-based, fully text-masked, and blocked on résumé surfaces.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5" role="group" aria-label="Analytics period">
            {RANGES.map((range) => (
              <button
                key={range.days}
                type="button"
                aria-pressed={days === range.days}
                onClick={() => setDays(range.days)}
                className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                  days === range.days ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void load(days)}
            disabled={loading}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-4 py-3 text-xs text-warn">
          Showing the last successful data. Refresh failed: {error}
        </div>
      )}

      <AdminOperations />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard label="Total users" value={formatNumber(system.total_users)} detail={`${formatNumber(system.new_users)} new in period`} trend={trendMap.get('total_users')} />
        <KpiCard label="Active subscriptions" value={formatNumber(system.active_subscriptions)} detail={`${formatPercent(system.conversion_rate)} trial conversion`} trend={trendMap.get('active_subscriptions')} />
        <KpiCard label="Revenue" value={formatCurrency(system.total_revenue_inr)} detail="Net of succeeded refunds" trend={trendMap.get('total_revenue_inr')} />
        <KpiCard label="Compilations" value={formatNumber(system.total_compilations)} detail={`${formatPercent(system.success_rate)} success`} trend={trendMap.get('total_compilations')} />
        <KpiCard label="Optimizations" value={formatNumber(system.total_optimizations)} detail="AI rewrite runs" trend={trendMap.get('total_optimizations')} />
        <KpiCard label="Trial users" value={formatNumber(system.trial_users)} detail="Anonymous trial starts" trend={trendMap.get('trial_users')} />
        <KpiCard label="Conversion" value={formatPercent(system.conversion_rate)} detail="Trial → registration" trend={trendMap.get('conversion_rate')} />
      </div>

      <OperationsStrip data={operations} />

      <AdminCompileLatency days={days} />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
          <h3 className="text-sm font-semibold text-fg">Product events per day</h3>
          <p className="mt-1 text-xs text-fg-3">All first-party analytics actions in the selected period.</p>
          <div className="mt-3">
            <ActivityAreaChart data={activitySeries} />
          </div>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
          <h3 className="text-sm font-semibold text-fg">Compilations per day</h3>
          <p className="mt-1 text-xs text-fg-3">Submitted compile jobs, including failures.</p>
          <div className="mt-3">
            <ActivityAreaChart data={compileSeries} />
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Funnel data={data.conversion_funnel} />
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
          <h3 className="text-sm font-semibold text-fg">Top features</h3>
          <p className="mt-1 text-xs text-fg-3">Ranked by recorded feature events or action fallback.</p>
          <div className="mt-3">
            <FeatureUsageBars data={featureSeries} />
          </div>
        </div>
      </div>

      <RecentEvents events={data.recent_events} />

      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">PostHog · replays and exploration</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Replays are recorded only after consent, with every text node and input masked. The résumé editor,
              public share pages, and portfolio pages are excluded. Use PostHog for funnels, retention, paths, and
              replay review; use this page for authoritative billing and operational counts.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            US Cloud
          </span>
        </div>
        {posthogLinks && replayTriageLinks ? (
          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap gap-2">
              <a href="/admin?tab=replays" className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110">
                Replay library
              </a>
              <a href={posthogLinks.replays} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                Open session replays
              </a>
              <a href={posthogLinks.dashboards} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                Dashboards
              </a>
              <a href={posthogLinks.people} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                People
              </a>
              <a href={posthogLinks.settings} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                Replay privacy settings
              </a>
            </div>
            <div className="border-t border-line pt-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
                Pre-filtered replay triage · {days} days
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <a href={replayTriageLinks.checkoutFailures} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                  Checkout failures
                </a>
                <a href={replayTriageLinks.jsErrors} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                  JS errors
                </a>
                <a href={replayTriageLinks.longSessions} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                  Long sessions
                </a>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">By route</span>
                {replayTriageLinks.routes.map((link) => (
                  <a key={link.label} href={link.href} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                    {link.label}
                  </a>
                ))}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">By plan</span>
                {replayTriageLinks.plans.map((link) => (
                  <a key={link.label} href={link.href} target="_blank" rel="noreferrer" className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
                    {link.label}
                  </a>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <p className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            Set NEXT_PUBLIC_POSTHOG_PROJECT_ID to show direct PostHog links here.
          </p>
        )}
      </div>
    </div>
  )
}
