'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminLinterRuleRow,
  type AdminLinterRulesResponse,
} from '@/lib/api-client'
import { formatNumber } from './admin-format'

const RANGES = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
  { days: 365, label: '365d' },
] as const

function rate(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail?: string
}) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function RuleTable({ rows }: { rows: AdminLinterRuleRow[] }) {
  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="min-w-[820px] w-full text-left text-xs">
        <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
          <tr>
            <th className="px-3 py-2 font-semibold">Rule</th>
            <th className="px-3 py-2 font-semibold">Severity</th>
            <th className="px-3 py-2 text-right font-semibold">Frequency</th>
            <th className="px-3 py-2 text-right font-semibold">Issues found</th>
            <th className="px-3 py-2 text-right font-semibold">Fixes applied</th>
            <th className="px-3 py-2 text-right font-semibold">Issues fixed</th>
            <th className="px-3 py-2 text-right font-semibold">Fix rate</th>
            <th className="px-3 py-2 text-right font-semibold">Users</th>
            <th className="px-3 py-2 text-right font-semibold">Share</th>
            <th className="px-3 py-2 font-semibold">Top route</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => {
            const topRoute = row.top_routes[0]
            return (
              <tr key={row.rule_id}>
                <td className="px-3 py-1.5 font-mono font-medium text-fg">{row.rule_id}</td>
                <td className="px-3 py-1.5 text-fg-3">{row.severity}</td>
                <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(row.frequency)}</td>
                <td className="px-3 py-1.5 text-right font-semibold text-fg">
                  {formatNumber(row.issues_detected)}
                </td>
                <td className="px-3 py-1.5 text-right text-fg-3">
                  {formatNumber(row.fixes_applied)}
                </td>
                <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(row.issues_fixed)}</td>
                <td className="px-3 py-1.5 text-right font-medium text-fg">
                  {rate(row.fix_rate_pct)}
                </td>
                <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(row.users)}</td>
                <td className="px-3 py-1.5 text-right text-fg-3">{rate(row.share_pct)}</td>
                <td className="px-3 py-1.5 text-fg-3">
                  {topRoute ? (
                    <span>
                      {topRoute.route}{' '}
                      <span className="text-fg-3">({formatNumber(topRoute.issues_detected)})</span>
                    </span>
                  ) : (
                    '—'
                  )}
                  {row.suppressed_routes > 0 && (
                    <span className="ml-1 text-[10px] text-fg-3">
                      · {row.suppressed_routes} route
                      {row.suppressed_routes === 1 ? '' : 's'} hidden
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={10} className="px-3 py-6 text-center text-fg-3">
                No rule has reached the minimum cohort of 5 distinct users in this period.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function TrendChart({ data }: { data: AdminLinterRulesResponse }) {
  if (data.trend.length === 0) {
    return (
      <div className="rounded border border-dashed border-line px-4 py-6 text-center text-xs text-fg-3">
        No daily rule trend is visible for this period.
      </div>
    )
  }
  const max = Math.max(...data.trend.map((point) => point.issues_detected), 1)
  return (
    <div>
      <div className="flex items-end gap-[3px] border-b border-line h-28" aria-hidden="true">
        {data.trend.map((point) => (
          <div
            key={point.date}
            className="relative min-w-[2px] flex-1 rounded-t bg-accent/70"
            style={{ height: `${Math.max(2, (point.issues_detected / max) * 100)}%` }}
            title={`${point.date}: ${formatNumber(point.issues_detected)} issues found, ${rate(point.fix_rate_pct)} fixed`}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-fg-3">
        <span>
          {data.trend[0]?.date} → {data.trend[data.trend.length - 1]?.date}
        </span>
        <span>Peak {formatNumber(max)} issues found in a visible day</span>
      </div>
    </div>
  )
}

export default function AdminLinterRules({ days: initialDays = 30 }: { days?: number }) {
  const [days, setDays] = useState(initialDays)
  const [data, setData] = useState<AdminLinterRulesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminLinterRules(days)
      if (generation.current === current) setData(next)
    } catch (err) {
      if (generation.current === current) {
        setError(err instanceof Error ? err.message : 'Failed to load linter rule telemetry')
      }
    } finally {
      if (generation.current === current) setLoading(false)
    }
  }, [days])

  useEffect(() => {
    void load()
  }, [load])

  const summary = data?.summary
  const hasData = (summary?.events ?? 0) > 0

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Linter rule frequency and fix rate</h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Aggregated, consent-gated client lint outcomes. Only an allowlisted rule id,
              severity, canonical route label, fixed flag and issue count are stored. Document
              content, line text, lint messages and per-user history are never returned. Cohorts
              below {data?.minimum_users ?? 5} distinct users are suppressed.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center rounded border border-line bg-surface-2 p-0.5">
              {RANGES.map((range) => (
                <button
                  key={range.days}
                  type="button"
                  onClick={() => setDays(range.days)}
                  aria-pressed={days === range.days}
                  className={`rounded px-2 py-1 text-[10px] font-medium transition ${
                    days === range.days ? 'bg-surface text-fg shadow-sm' : 'text-fg-3 hover:text-fg'
                  }`}
                >
                  {range.label}
                </button>
              ))}
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

      {summary && data ? (
        <div className="space-y-5 px-5 py-4">
          {data.suppressed ? (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
              Hidden: fewer than {data.minimum_users} distinct users reported lint outcomes in
              this period. Aggregate counts are suppressed to protect small cohorts.
            </div>
          ) : !hasData ? (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
              No linter telemetry has been recorded for this period.
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                <Metric label="Lint runs observed" value={formatNumber(summary.events)} />
                <Metric label="Issues found" value={formatNumber(summary.issues_detected)} />
                <Metric label="Issues fixed" value={formatNumber(summary.issues_fixed)} />
                <Metric
                  label="Fix rate"
                  value={rate(summary.fix_rate_pct)}
                  detail="Issues fixed ÷ issues found (capped at 100%)"
                />
                <Metric
                  label="Rules seen"
                  value={formatNumber(summary.rules_seen)}
                  detail={`${formatNumber(summary.distinct_users)} distinct users`}
                />
              </div>

              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h4 className="text-xs font-semibold text-fg">Top noisy rules</h4>
                  <span className="text-[10px] text-fg-3">Ranked by issues found</span>
                </div>
                <div className="mt-2">
                  <RuleTable rows={data.rules} />
                </div>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-fg">Daily rule trend</h4>
                <div className="mt-2">
                  <TrendChart data={data} />
                </div>
              </div>

              <p className="text-[10px] text-fg-3">
                Period: {new Date(data.period.start).toLocaleDateString()} –{' '}
                {new Date(data.period.end).toLocaleDateString()} ({data.period.timezone}).
                {data.suppression.suppressed_rules > 0
                  ? ` ${data.suppression.suppressed_rules} rule${data.suppression.suppressed_rules === 1 ? '' : 's'} hidden below ${data.minimum_users} users.`
                  : ''}
                {data.suppression.suppressed_days > 0
                  ? ` ${data.suppression.suppressed_days} day${data.suppression.suppressed_days === 1 ? '' : 's'} hidden below ${data.minimum_users} users.`
                  : ''}
                {data.reconciliation.invalid_rows > 0
                  ? ` ${data.reconciliation.invalid_rows} malformed row${data.reconciliation.invalid_rows === 1 ? '' : 's'} ignored.`
                  : ''}
                {data.reconciliation.truncated
                  ? ` Report truncated at ${formatNumber(data.reconciliation.max_rows)} rows.`
                  : ''}
              </p>
            </>
          )}

          <ul className="list-disc space-y-0.5 pl-4 text-[10px] leading-relaxed text-fg-3">
            {data.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : (
        !error && (
          <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
            Loading linter rule telemetry…
          </div>
        )
      )}
    </section>
  )
}
