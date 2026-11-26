'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  apiClient,
  type AdminActivationResponse,
  type AdminAiCostResponse,
  type AdminFeatureDepthResponse,
  type AdminAiUsageResponse,
  type AdminAiUsageRow,
  type AdminFilteredTimeseriesResponse,
  type AdminRetentionResponse,
  type AdminRetentionRow,
  type AdminSignupFunnel,
  type AdminTimeseriesDimension,
  type AdminTimeseriesMetric,
} from '@/lib/api-client'
import { ActivityAreaChart, FeatureUsageBars } from '@/components/analytics/MetricCharts'
import AdminTrafficSources from '@/components/admin/AdminTrafficSources'
import AdminLandingConversion from '@/components/admin/AdminLandingConversion'
import AdminOnboardingAnalytics from '@/components/admin/AdminOnboardingAnalytics'
import AdminPrivacyBreakdowns from '@/components/admin/AdminPrivacyBreakdowns'
import AdminReferralAnalytics from '@/components/admin/AdminReferralAnalytics'
import AdminTrialAttribution from '@/components/admin/AdminTrialAttribution'
import AdminTrialHealth from '@/components/admin/AdminTrialHealth'
import AdminCredentialMix from '@/components/admin/AdminCredentialMix'
import AdminSharePortfolio from '@/components/admin/AdminSharePortfolio'
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

function formatLatency(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1_000) return `${Math.round(ms)}ms`
  return `${(ms / 1_000).toFixed(2)}s`
}

type UsageDimension = 'feature' | 'provider' | 'model' | 'persona' | 'plan' | 'credential_source'

const USAGE_DIMENSIONS: Array<{ key: UsageDimension; label: string }> = [
  { key: 'feature', label: 'Feature' },
  { key: 'provider', label: 'Provider' },
  { key: 'model', label: 'Model' },
  { key: 'persona', label: 'Persona' },
  { key: 'plan', label: 'Plan' },
  { key: 'credential_source', label: 'Credential source' },
]

function usageRows(data: AdminAiUsageResponse, dimension: UsageDimension): AdminAiUsageRow[] {
  switch (dimension) {
    case 'feature':
      return data.by_feature
    case 'provider':
      return data.by_provider
    case 'model':
      return data.by_model
    case 'persona':
      return data.by_persona
    case 'plan':
      return data.by_plan
    case 'credential_source':
      return data.by_credential_source
    default:
      return data.by_feature
  }
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

function SignupFunnel({ data }: { data: AdminSignupFunnel }) {
  const minimum = data.minimum_segment_size ?? 5
  const hidden = data.suppressed_segments?.provider ?? 0
  const failures = data.oauth_failures ?? { total: 0, by_provider: [], by_code: [] }
  const steps = data.steps ?? []

  return (
    <section className="mt-4 rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-fg">Signup funnel by auth provider</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Start → complete → verified for accounts created in the selected period.
            Providers are derived server-side from Better Auth account rows; a
            client-supplied provider is never attributed to an account. Verification
            rate is verified accounts over completed accounts, and median time is
            measured from the first stored verification event.
          </p>
        </div>
        <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
          {formatNumber(data.completed)} accounts
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {steps.map((step) => (
          <div key={step.key} className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">{step.label}</p>
            <p className="mt-1 text-xl font-semibold text-fg">{formatNumber(step.count)}</p>
            <p className="mt-0.5 text-[10px] text-fg-3">
              {step.key === 'signup_started'
                ? '100% of starts'
                : `${step.from_previous ?? 0}% of previous step · ${step.from_start}% of starts`}
            </p>
            {step.key === 'email_verified' && (
              <p className="mt-1 text-[10px] text-fg-3">
                Median time to verify: {formatDuration(step.median_seconds)}
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-4 overflow-x-auto rounded-md border border-line">
        <table className="w-full min-w-[620px] border-collapse text-xs">
          <caption className="sr-only">Signup conversion and median verification time by auth provider</caption>
          <thead>
            <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
              <th scope="col" className="px-3 py-2 text-left font-semibold">Provider</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Starts</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Accounts</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Verified</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Start → account</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Verify rate</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Median to verify</th>
            </tr>
          </thead>
          <tbody>
            {data.by_provider.map((row) => (
              <tr key={row.provider} className="border-t border-line">
                <td className="px-3 py-1.5 text-fg-2">{row.provider_label || row.label}</td>
                <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(row.started)}</td>
                <td className="px-3 py-1.5 text-right text-fg">{formatNumber(row.completed)}</td>
                <td className="px-3 py-1.5 text-right text-fg">{formatNumber(row.verified)}</td>
                <td className="px-3 py-1.5 text-right text-fg-3">{row.conversion_start_to_complete.toFixed(1)}%</td>
                <td className="px-3 py-1.5 text-right text-fg-3">{row.verification_rate.toFixed(1)}%</td>
                <td className="px-3 py-1.5 text-right text-fg-3">{formatDuration(row.median_seconds_to_verify)}</td>
              </tr>
            ))}
            {data.by_provider.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-5 text-center text-fg-3">
                  No provider has at least {minimum} accounts in this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {hidden > 0 && (
          <p className="border-t border-line px-3 py-1.5 text-[10px] text-fg-3">
            {hidden} small provider {hidden === 1 ? 'segment' : 'segments'} hidden ({'<'}
            {minimum} accounts).
          </p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] text-fg-3">
        <span className="font-semibold uppercase tracking-[0.16em]">OAuth failures</span>
        <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 font-semibold text-fg">
          {formatNumber(failures.total)} total
        </span>
        {failures.by_provider.map((row) => (
          <span key={row.provider} className="rounded-full border border-line px-2 py-0.5">
            {row.provider_label || row.label}: {formatNumber(row.count)}
          </span>
        ))}
        {failures.by_provider.length === 0 && <span>No provider failures recorded.</span>}
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

function AiUsage({
  data,
  plan,
  feature,
  provider,
  model,
  persona,
  onPlan,
  onFeature,
  onProvider,
  onModel,
  onPersona,
  onApply,
  loading,
}: {
  data: AdminAiUsageResponse
  plan: string
  feature: string
  provider: string
  model: string
  persona: string
  onPlan: (value: string) => void
  onFeature: (value: string) => void
  onProvider: (value: string) => void
  onModel: (value: string) => void
  onPersona: (value: string) => void
  onApply: () => void
  loading: boolean
}) {
  const [dimension, setDimension] = useState<UsageDimension>('feature')
  const rows = usageRows(data, dimension)
  const hidden = data.suppression.by_dimension[dimension] ?? 0
  const chart = data.by_feature.slice(0, 8).map((row) => ({ name: row.label, value: row.runs }))
  const reconciliation = useMemo(
    () => data.reconciliation.sources.reduce((sum, row) => sum + row.runs, 0),
    [data.reconciliation.sources],
  )

  return (
    <section className="space-y-4">
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">AI usage breakdown</h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Aggregate runs from optimization history and resume-engine stages by feature, provider, model, persona,
              plan, and credential source. No prompts, documents, keys, or per-user rows are read.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
            {data.period_days} days · {data.start_date} → {data.end_date} · UTC
          </span>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-2">
          <label className="text-[11px] text-fg-2">
            Usage plan filter
            <select value={plan} onChange={(event) => onPlan(event.target.value)} className="mt-1 block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg">
              {PLAN_OPTIONS.map((item) => <option key={item || 'all'} value={item}>{item || 'All plans'}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-fg-2">
            Feature
            <input value={feature} onChange={(event) => onFeature(event.target.value)} maxLength={120} placeholder="optimization_patches" className="mt-1 block min-h-[38px] w-44 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
          </label>
          <label className="text-[11px] text-fg-2">
            Provider
            <input value={provider} onChange={(event) => onProvider(event.target.value)} maxLength={80} placeholder="openai" className="mt-1 block min-h-[38px] w-32 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
          </label>
          <label className="text-[11px] text-fg-2">
            Model
            <input value={model} onChange={(event) => onModel(event.target.value)} maxLength={160} placeholder="gpt-4o" className="mt-1 block min-h-[38px] w-40 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
          </label>
          <label className="text-[11px] text-fg-2">
            Persona
            <input value={persona} onChange={(event) => onPersona(event.target.value)} maxLength={64} placeholder="startup" className="mt-1 block min-h-[38px] w-32 rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg" />
          </label>
          <button type="button" onClick={onApply} disabled={loading} className="min-h-[38px] rounded bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40">
            Apply usage filters
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card label="AI runs" value={formatNumber(data.totals.runs)} detail={`${formatNumber(data.totals.users)} users · ${formatNumber(data.totals.tokens)} tokens`} />
        <Card
          label="Success / error"
          value={`${formatNumber(data.totals.successes)} / ${formatNumber(data.totals.errors)}`}
          detail={`${data.totals.success_rate}% success · ${data.totals.pending} pending`}
          tone={data.totals.errors > 0 ? 'text-warn' : 'text-ok'}
        />
        <Card label="p95 latency" value={formatLatency(data.totals.latency_p95_ms)} detail={`p50 ${formatLatency(data.totals.latency_p50_ms)} · ${formatNumber(data.totals.latency_samples)} samples`} />
        <Card label="Suppressed groups" value={formatNumber(data.suppressed_groups)} detail={`Minimum ${data.minimum_group_size} users or runs per row`} />
      </div>

      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <h3 className="text-sm font-semibold text-fg">Runs by feature</h3>
        <p className="mt-1 text-[11px] text-fg-3">Aggregate run counts only. Groups under {data.minimum_group_size} users or runs are hidden.</p>
        <div className="mt-3"><FeatureUsageBars data={chart} /></div>
      </div>

      <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-fg">Usage detail</h3>
            <p className="mt-1 text-[11px] text-fg-3">Aggregate-only rows with success/error, p50/p95 latency, and token counts.</p>
          </div>
          <div className="inline-flex flex-wrap rounded-[var(--radius-md)] border border-line bg-surface p-0.5" role="group" aria-label="AI usage dimension">
            {USAGE_DIMENSIONS.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={dimension === item.key}
                onClick={() => setDimension(item.key)}
                className={`rounded px-2.5 py-1 text-[11px] font-medium ${dimension === item.key ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'}`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-xs">
            <caption className="sr-only">AI usage by {dimension}</caption>
            <thead>
              <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-4 py-2 text-left font-semibold">{USAGE_DIMENSIONS.find((item) => item.key === dimension)?.label}</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Users</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Runs</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Success</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Error</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Pending</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">p50</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">p95</th>
                <th scope="col" className="px-4 py-2 text-right font-semibold">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${dimension}-${row.label}`} className="border-t border-line">
                  <td className="px-4 py-2 text-fg-2">{row.label}</td>
                  <td className="px-4 py-2 text-right text-fg-3">{formatNumber(row.users)}</td>
                  <td className="px-4 py-2 text-right text-fg">{formatNumber(row.runs)}</td>
                  <td className="px-4 py-2 text-right text-ok">{formatNumber(row.successes)}</td>
                  <td className={`px-4 py-2 text-right ${row.errors > 0 ? 'text-err' : 'text-fg-3'}`}>{formatNumber(row.errors)}</td>
                  <td className="px-4 py-2 text-right text-fg-3">{formatNumber(row.pending)}</td>
                  <td className="px-4 py-2 text-right text-fg-3">{formatLatency(row.latency_p50_ms)}</td>
                  <td className="px-4 py-2 text-right text-fg-3">{formatLatency(row.latency_p95_ms)}</td>
                  <td className="px-4 py-2 text-right text-fg-3">{formatNumber(row.tokens)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-fg-3">
                    No {dimension.replace('_', ' ')} row has at least {data.minimum_group_size} users and runs.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-[10px] text-fg-3">
          <span>{hidden > 0 ? `${hidden} small ${dimension.replace('_', ' ')} group${hidden === 1 ? '' : 's'} hidden (<${data.minimum_group_size} users or runs).` : 'No groups hidden for this dimension.'}</span>
          <span>{formatNumber(reconciliation)} reconciled source rows · {formatDateTime(data.generated_at)}</span>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Reconciliation to source tables</h3>
          <p className="mt-1 text-[10px] text-fg-3">Aggregate counts from the same first-party rows used in the breakdown.</p>
          <ul className="mt-2 space-y-1 text-xs">
            {data.reconciliation.sources.map((row) => (
              <li key={row.source} className="flex items-center justify-between gap-2 border-b border-line py-1.5 last:border-0">
                <span className="text-fg-2">{row.source.replace(/_/g, ' ')}</span>
                <span className="text-fg-3">{formatNumber(row.runs)} runs · {formatNumber(row.successes)} ok · {formatNumber(row.errors)} err · {formatNumber(row.tokens)} tokens</span>
              </li>
            ))}
            <li className="flex items-center justify-between gap-2 border-t border-line pt-1.5">
              <span className="text-fg-2">Run admissions</span>
              <span className="text-fg-3">{formatNumber(data.reconciliation.resume_engine_runs.runs)} runs · {formatNumber(data.reconciliation.resume_engine_runs.successes)} completed · {formatNumber(data.reconciliation.resume_engine_runs.errors)} failed/cancelled</span>
            </li>
          </ul>
        </div>
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Privacy and coverage</h3>
          <p className="mt-2 text-[11px] leading-relaxed text-fg-3">{data.persona_source}</p>
          <p className="mt-2 text-[11px] leading-relaxed text-fg-3">{data.credential_source_note}</p>
          <ul className="mt-2 space-y-1 text-[10px] text-fg-3">
            {data.notes.map((note) => <li key={note}>• {note}</li>)}
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

function FeatureDepth({
  data,
  loading,
  error,
  plan,
  cohort,
  planOptions,
  cohortOptions,
  onPlan,
  onCohort,
  onApply,
}: {
  data: AdminFeatureDepthResponse | null
  loading: boolean
  error: string | null
  plan: string
  cohort: string
  planOptions: readonly string[]
  cohortOptions: Array<{ month: string; users: number }>
  onPlan: (value: string) => void
  onCohort: (value: string) => void
  onApply: () => void
}) {
  const minimum = data?.minimum_group_size ?? 5
  const totals = data?.totals
  const breadth = totals?.breadth

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Feature depth &amp; frequency</h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Per-user frequency from first-party usage events. Buckets count users by events per feature; habitual users
              average at least {data?.habitual_weekly_threshold ?? 5} events per week in the selected window. Counts only —
              no event metadata, document text, or per-user logs.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
            {data ? (data.suppressed ? 'cohort hidden' : `${formatNumber(totals?.users ?? 0)} users`) : '—'}
          </span>
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-2">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            Plan
            <select
              aria-label="Feature depth plan filter"
              value={plan}
              onChange={(event) => onPlan(event.target.value)}
              className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            >
              {planOptions.map((item) => (
                <option key={item || 'all'} value={item}>{item || 'All plans'}</option>
              ))}
            </select>
          </label>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            Signup cohort
            <select
              aria-label="Feature depth signup cohort filter"
              value={cohort}
              onChange={(event) => onCohort(event.target.value)}
              className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            >
              <option value="">All cohorts</option>
              {cohortOptions.map((month) => (
                <option key={month.month} value={month.month}>
                  {month.month} · {formatNumber(month.users)} users
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={onApply}
            disabled={loading}
            className="min-h-[36px] rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            {loading ? 'Loading…' : 'Apply filters'}
          </button>
          {data && (
            <span className="text-[10px] text-fg-3">
              {data.filters.plan ? `plan=${data.filters.plan}` : 'all plans'}
              {data.filters.cohort ? ` · cohort=${data.filters.cohort}` : ''} · {data.start_date} → {data.end_date} · UTC
            </span>
          )}
        </div>
        {error && (
          <p role="alert" className="mt-3 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err">
            {error}
          </p>
        )}
      </div>

      {data?.suppressed ? (
        <div className="px-5 py-8 text-center text-sm text-fg-3">
          This cohort has fewer than {minimum} users in the selected window, so its counts are hidden.
        </div>
      ) : data && totals ? (
        <>
          <div className="grid gap-px border-b border-line bg-line sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {[
              { label: 'Users', value: formatNumber(totals.users) },
              { label: 'Events', value: formatNumber(totals.events) },
              { label: 'Median / user', value: totals.median_events_per_user == null ? '—' : totals.median_events_per_user.toFixed(1) },
              { label: 'p95 / user', value: totals.p95_events_per_user == null ? '—' : totals.p95_events_per_user.toFixed(1) },
              { label: 'Repeat rate', value: `${totals.repeat_rate.toFixed(1)}%` },
              { label: 'Habitual users', value: `${formatNumber(totals.habitual_users)} · ${totals.habitual_rate.toFixed(1)}%` },
            ].map((item) => (
              <div key={item.label} className="bg-surface px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">{item.label}</p>
                <p className="mt-1 text-lg font-semibold text-fg">{item.value}</p>
              </div>
            ))}
          </div>

          {breadth && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-5 py-3 text-[11px] text-fg-3">
              <span className="font-semibold text-fg-2">
                Breadth: {breadth.average_features_per_user.toFixed(1)} distinct features/user
                {breadth.median_features_per_user != null ? ` · median ${breadth.median_features_per_user.toFixed(1)}` : ''}
              </span>
              {breadth.distribution.map((bin) => (
                <span key={bin.key}>{bin.label} feature{bin.key === '1' ? '' : 's'}: {formatNumber(bin.users)} users</span>
              ))}
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] border-collapse text-sm">
              <caption className="sr-only">Feature depth, frequency buckets, and habitual usage</caption>
              <thead>
                <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                  <th scope="col" className="px-5 py-3 text-left font-semibold">Feature</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">Users</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">Events</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">Median</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">p95</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">Repeat</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">Habitual</th>
                  <th scope="col" className="px-3 py-3 text-left font-semibold">Frequency mix</th>
                  <th scope="col" className="px-3 py-3 text-right font-semibold">Breadth</th>
                </tr>
              </thead>
              <tbody>
                {data.features.map((row) => (
                  <tr key={row.feature} className="border-t border-line align-top">
                    <td className="px-5 py-3 font-mono text-xs text-fg">{row.feature}</td>
                    <td className="px-3 py-3 text-right text-xs text-fg">{formatNumber(row.users)}</td>
                    <td className="px-3 py-3 text-right text-xs text-fg-2">{formatNumber(row.events)}</td>
                    <td className="px-3 py-3 text-right text-xs text-fg-2">
                      {row.median_events_per_user == null ? '—' : row.median_events_per_user.toFixed(1)}
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-fg-2">
                      {row.p95_events_per_user == null ? '—' : row.p95_events_per_user.toFixed(1)}
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-fg-2">
                      {row.repeat_rate.toFixed(1)}%
                      <span className="block text-[10px] text-fg-3">{formatNumber(row.repeat_users)} users</span>
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-fg-2">
                      {row.habitual_rate.toFixed(1)}%
                      <span className="block text-[10px] text-fg-3">{formatNumber(row.habitual_users)} users</span>
                    </td>
                    <td className="min-w-[260px] px-3 py-3">
                      <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                        {row.buckets.map((bucket, index) => (
                          <span
                            key={bucket.key}
                            className={['bg-fg-3/40', 'bg-accent/70', 'bg-ok/70', 'bg-warn/70'][index] ?? 'bg-fg-3/40'}
                            style={{ width: `${bucket.share}%` }}
                          />
                        ))}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-fg-3">
                        {row.buckets.map((bucket) => (
                          <span key={bucket.key}>{bucket.label}: {formatNumber(bucket.users)}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-right text-xs text-fg-2">
                      {row.breadth.average_features_per_user.toFixed(1)}/user
                      <span className="block text-[10px] text-fg-3">
                        {formatNumber(row.breadth.sole_feature_users)} sole-feature
                      </span>
                    </td>
                  </tr>
                ))}
                {data.features.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-5 py-8 text-center text-sm text-fg-3">
                      No feature group in this selection has at least {minimum} users.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-[10px] text-fg-3">
            <span>
              Habitual threshold: {data.habitual_minimum_events} events in {data.days} days (≥
              {data.habitual_weekly_threshold}/week). {data.habitual_definition}
            </span>
            <span>
              {data.suppressed_features > 0
                ? `${data.suppressed_features} small feature group${data.suppressed_features === 1 ? '' : 's'} hidden (<${minimum} users).`
                : `All visible groups have at least ${minimum} users.`}
              {data.truncated_features > 0 ? ` ${data.truncated_features} lower-volume groups truncated.` : ''}
            </span>
          </div>
        </>
      ) : !data && error ? (
        <div className="px-5 py-8 text-center text-sm text-fg-3">
          Feature depth is unavailable. Adjust the filters or retry.
        </div>
      ) : (
        <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">Loading feature depth…</div>
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
  const [usage, setUsage] = useState<AdminAiUsageResponse | null>(null)
  const [series, setSeries] = useState<AdminFilteredTimeseriesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [plan, setPlan] = useState('')
  const [provider, setProvider] = useState('')
  const [costPlan, setCostPlan] = useState('')
  const [costFeature, setCostFeature] = useState('')
  const [costApplied, setCostApplied] = useState<{ plan: string; feature: string }>({ plan: '', feature: '' })
  const [usagePlan, setUsagePlan] = useState('')
  const [usageFeature, setUsageFeature] = useState('')
  const [usageProvider, setUsageProvider] = useState('')
  const [usageModel, setUsageModel] = useState('')
  const [usagePersona, setUsagePersona] = useState('')
  const [usageApplied, setUsageApplied] = useState<{
    plan: string
    feature: string
    provider: string
    model: string
    persona: string
  }>({ plan: '', feature: '', provider: '', model: '', persona: '' })
  const [metric, setMetric] = useState<AdminTimeseriesMetric>('events')
  const [dimension, setDimension] = useState<'' | AdminTimeseriesDimension>('plan')
  const [value, setValue] = useState('pro')
  const [applied, setApplied] = useState<{
    metric: AdminTimeseriesMetric
    dimension: '' | AdminTimeseriesDimension
    value: string
  }>({ metric: 'events', dimension: 'plan', value: 'pro' })
  const [explorerLoading, setExplorerLoading] = useState(false)
  const [depth, setDepth] = useState<AdminFeatureDepthResponse | null>(null)
  const [depthPlan, setDepthPlan] = useState('')
  const [depthCohort, setDepthCohort] = useState('')
  const [depthApplied, setDepthApplied] = useState<{ plan: string; cohort: string }>({ plan: '', cohort: '' })
  const [depthLoading, setDepthLoading] = useState(false)
  const [depthError, setDepthError] = useState<string | null>(null)
  const loadGeneration = useRef(0)
  const seriesGeneration = useRef(0)
  const depthGeneration = useRef(0)

  const load = useCallback(async () => {
    const generation = ++loadGeneration.current
    setLoading(true)
    setError(null)
    try {
      const [nextActivation, nextRetention, nextCost, nextUsage] = await Promise.all([
        apiClient.getAdminActivation({
          days,
          plan: plan || undefined,
          provider: provider || undefined,
        }),
        apiClient.getAdminRetention(retentionWeeks, signupMonth || undefined),
        apiClient.getAdminAiCost({
          days,
          plan: costApplied.plan || undefined,
          feature: costApplied.feature || undefined,
        }),
        apiClient.getAdminAiUsage({
          days,
          plan: usageApplied.plan || undefined,
          feature: usageApplied.feature || undefined,
          provider: usageApplied.provider || undefined,
          model: usageApplied.model || undefined,
          persona: usageApplied.persona || undefined,
        }),
      ])
      if (loadGeneration.current !== generation) return
      setActivation(nextActivation)
      setRetention(nextRetention)
      setCost(nextCost)
      setUsage(nextUsage)
    } catch (err) {
      if (loadGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load growth analytics')
      }
    } finally {
      if (loadGeneration.current === generation) setLoading(false)
    }
  }, [days, plan, provider, retentionWeeks, signupMonth, costApplied, usageApplied])

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

  const loadDepth = useCallback(async () => {
    const generation = ++depthGeneration.current
    setDepthLoading(true)
    setDepthError(null)
    try {
      const next = await apiClient.getAdminFeatureDepth({
        days,
        plan: depthApplied.plan || undefined,
        cohort: depthApplied.cohort || undefined,
      })
      if (depthGeneration.current === generation) setDepth(next)
    } catch (err) {
      if (depthGeneration.current === generation) {
        setDepthError(err instanceof Error ? err.message : 'Failed to load feature depth')
      }
    } finally {
      if (depthGeneration.current === generation) setDepthLoading(false)
    }
  }, [days, depthApplied])

  useEffect(() => {
    void loadDepth()
  }, [loadDepth])

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
      {activation?.signup_funnel && <SignupFunnel data={activation.signup_funnel} />}
      <AdminTrafficSources days={days} />
      <AdminLandingConversion days={days} />
      <AdminOnboardingAnalytics days={days} />
      <AdminPrivacyBreakdowns days={days} />
      <AdminTrialAttribution days={days} />
      <AdminSharePortfolio />
      <AdminTrialHealth />
      <AdminReferralAnalytics days={days} />
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

      {usage && (
        <AiUsage
          data={usage}
          plan={usagePlan}
          feature={usageFeature}
          provider={usageProvider}
          model={usageModel}
          persona={usagePersona}
          onPlan={setUsagePlan}
          onFeature={setUsageFeature}
          onProvider={setUsageProvider}
          onModel={setUsageModel}
          onPersona={setUsagePersona}
          onApply={() =>
            setUsageApplied({
              plan: usagePlan,
              feature: usageFeature,
              provider: usageProvider,
              model: usageModel,
              persona: usagePersona,
            })
          }
          loading={loading}
        />
      )}

      <AdminCredentialMix days={days} />

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

      <FeatureDepth
        data={depth}
        loading={depthLoading}
        error={depthError}
        plan={depthPlan}
        cohort={depthCohort}
        planOptions={PLAN_OPTIONS}
        cohortOptions={signupMonths}
        onPlan={setDepthPlan}
        onCohort={setDepthCohort}
        onApply={() => setDepthApplied({ plan: depthPlan, cohort: depthCohort })}
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
