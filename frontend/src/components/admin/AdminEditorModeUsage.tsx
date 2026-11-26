'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminEditorModeCompileRow,
  type AdminEditorModeUsageResponse,
} from '@/lib/api-client'
import { formatNumber } from './admin-format'

const RANGES = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
  { days: 365, label: '365d' },
] as const

function count(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : formatNumber(value)
}

function rate(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function seconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(2)}s`
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function AdoptionTable({ data }: { data: AdminEditorModeUsageResponse }) {
  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="min-w-[760px] w-full text-left text-xs">
        <caption className="sr-only">Editor mode adoption by plan</caption>
        <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
          <tr>
            <th className="px-3 py-2 font-semibold">Plan</th>
            <th className="px-3 py-2 font-semibold">Mode</th>
            <th className="px-3 py-2 text-right font-semibold">Selections</th>
            <th className="px-3 py-2 text-right font-semibold">Users</th>
            <th className="px-3 py-2 text-right font-semibold">Documents</th>
            <th className="px-3 py-2 text-right font-semibold">Share</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {data.adoption_by_plan_mode.map((row) => (
            <tr key={`${row.plan}:${row.mode}`}>
              <td className="px-3 py-1.5 font-medium text-fg">{row.plan_label}</td>
              <td className="px-3 py-1.5 text-fg-3">{row.mode_label}</td>
              <td className="px-3 py-1.5 text-right font-semibold text-fg">
                {formatNumber(row.selections)}
              </td>
              <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(row.users)}</td>
              <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(row.documents)}</td>
              <td className="px-3 py-1.5 text-right text-fg-3">{rate(row.share_pct)}</td>
            </tr>
          ))}
          {data.adoption_by_plan_mode.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-6 text-center text-fg-3">
                No plan/mode cohort has reached {data.minimum_cohort_size} distinct users in this
                period.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function CompileTable({ rows }: { rows: AdminEditorModeCompileRow[] }) {
  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="min-w-[820px] w-full text-left text-xs">
        <caption className="sr-only">Compile success rate and latency by editor mode</caption>
        <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
          <tr>
            <th className="px-3 py-2 font-semibold">Mode</th>
            <th className="px-3 py-2 text-right font-semibold">Compiles</th>
            <th className="px-3 py-2 text-right font-semibold">Completed</th>
            <th className="px-3 py-2 text-right font-semibold">Failed</th>
            <th className="px-3 py-2 text-right font-semibold">Success rate</th>
            <th className="px-3 py-2 text-right font-semibold">p50</th>
            <th className="px-3 py-2 text-right font-semibold">p95</th>
            <th className="px-3 py-2 text-right font-semibold">Samples</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.mode}>
              <td className="px-3 py-1.5 font-medium text-fg">
                {row.label}
                {row.sparse && !row.suppressed && (
                  <span className="ml-1.5 text-[10px] font-normal text-fg-3">sparse</span>
                )}
              </td>
              <td className="px-3 py-1.5 text-right text-fg-3">{count(row.compilations)}</td>
              <td className="px-3 py-1.5 text-right text-fg-3">{count(row.completed)}</td>
              <td className="px-3 py-1.5 text-right text-fg-3">{count(row.failed)}</td>
              <td className="px-3 py-1.5 text-right font-medium text-fg">
                {rate(row.success_rate_pct)}
              </td>
              <td className="px-3 py-1.5 text-right text-fg-3">{seconds(row.p50_seconds)}</td>
              <td className="px-3 py-1.5 text-right text-fg-3">{seconds(row.p95_seconds)}</td>
              <td className="px-3 py-1.5 text-right text-fg-3">{count(row.samples)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} className="px-3 py-6 text-center text-fg-3">
                No compile outcomes are visible for this period.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminEditorModeUsage({ days: initialDays = 30 }: { days?: number }) {
  const [days, setDays] = useState(initialDays)
  const [plan, setPlan] = useState('')
  const [appliedPlan, setAppliedPlan] = useState('')
  const [data, setData] = useState<AdminEditorModeUsageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminEditorModeUsage({
        days,
        plan: appliedPlan || undefined,
      })
      if (generation.current === current) setData(next)
    } catch (err) {
      if (generation.current === current) {
        setError(err instanceof Error ? err.message : 'Failed to load editor mode analytics')
      }
    } finally {
      if (generation.current === current) setLoading(false)
    }
  }, [appliedPlan, days])

  useEffect(() => {
    void load()
  }, [load])

  const summary = data?.summary
  const hasData =
    (summary?.mode_selections ?? 0) > 0 ||
    (summary?.auto_compile_toggles ?? 0) > 0 ||
    (summary?.synctex_events ?? 0) > 0 ||
    (summary?.compilations ?? 0) > 0

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">Editor modes, auto-compile and SyncTeX</h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Consent-gated editor mode adoption by plan and period, joined to compile outcomes and
              latency. Stored events contain only the mode enum, plan, canonical route, a SHA-256
              document hash and an optional toggle/direction. Document content, source, prompts,
              filenames and per-user rows are never stored or returned. Cohorts below{' '}
              {data?.minimum_cohort_size ?? 5} distinct users are suppressed.
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
                    days === range.days
                      ? 'bg-surface text-fg shadow-sm'
                      : 'text-fg-3 hover:text-fg'
                  }`}
                >
                  {range.label}
                </button>
              ))}
            </div>
            <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              Plan
              <input
                type="text"
                aria-label="Filter editor mode analytics by plan"
                placeholder="All plans"
                value={plan}
                onChange={(event) => setPlan(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') setAppliedPlan(plan.trim().toLowerCase())
                }}
                className="ml-2 min-h-[30px] w-24 rounded border border-line bg-bg px-2 py-1 text-xs font-normal normal-case tracking-normal text-fg"
              />
            </label>
            <button
              type="button"
              onClick={() => setAppliedPlan(plan.trim().toLowerCase())}
              disabled={loading}
              className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              Apply
            </button>
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
              Hidden: fewer than {data.minimum_cohort_size} distinct users used the editor in this
              period. Aggregate counts are suppressed to protect small cohorts.
            </div>
          ) : !hasData ? (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
              No editor mode telemetry has been recorded for this period.
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                <Metric
                  label="Mode selections"
                  value={count(summary.mode_selections)}
                  detail={`${count(summary.mode_users)} users · ${count(summary.documents)} documents`}
                />
                <Metric
                  label="Auto-compile toggles"
                  value={count(summary.auto_compile_toggles)}
                  detail={`${count(summary.auto_compile_enabled_toggles)} on · ${count(
                    summary.auto_compile_disabled_toggles,
                  )} off`}
                />
                <Metric
                  label="SyncTeX uses"
                  value={count(summary.synctex_events)}
                  detail={`${count(summary.synctex_source_to_pdf)} source→PDF · ${count(
                    summary.synctex_pdf_to_source,
                  )} PDF→source`}
                />
                <Metric
                  label="Compiles"
                  value={count(summary.compilations)}
                  detail={`${count(summary.attributed_compilations)} attributed to a mode`}
                />
                <Metric
                  label="Success rate"
                  value={rate(summary.success_rate_pct)}
                  detail="Completed ÷ (completed + failed)"
                />
                <Metric
                  label="Compile latency"
                  value={`${seconds(summary.p50_seconds)} / ${seconds(summary.p95_seconds)}`}
                  detail="p50 / p95 across completed compiles"
                />
              </div>

              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-xs font-semibold text-fg">Mode adoption by plan</h3>
                  <span className="text-[10px] text-fg-3">Distinct users per cohort</span>
                </div>
                <div className="mt-2">
                  <AdoptionTable data={data} />
                </div>
              </div>

              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-xs font-semibold text-fg">Compile outcomes by mode</h3>
                  <span className="text-[10px] text-fg-3">
                    Latest mode before each compile · 12h window
                  </span>
                </div>
                <div className="mt-2">
                  <CompileTable rows={data.compile_by_mode} />
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded border border-line bg-surface-2 p-4">
                  <h3 className="text-xs font-semibold text-fg">Auto-compile</h3>
                  {data.auto_compile.suppressed ? (
                    <p className="mt-2 text-[11px] text-fg-3">
                      Hidden: fewer than {data.minimum_cohort_size} distinct users toggled
                      auto-compile.
                    </p>
                  ) : (
                    <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <dt className="text-[10px] uppercase tracking-wider text-fg-3">Toggles</dt>
                        <dd className="font-semibold text-fg">
                          {count(data.auto_compile.toggles)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[10px] uppercase tracking-wider text-fg-3">On / off</dt>
                        <dd className="font-semibold text-fg">
                          {count(data.auto_compile.enabled)} /{' '}
                          {count(data.auto_compile.disabled)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[10px] uppercase tracking-wider text-fg-3">Users</dt>
                        <dd className="font-semibold text-fg">
                          {count(data.auto_compile.users)}
                        </dd>
                      </div>
                    </dl>
                  )}
                </div>
                <div className="rounded border border-line bg-surface-2 p-4">
                  <h3 className="text-xs font-semibold text-fg">SyncTeX</h3>
                  {data.synctex.suppressed ? (
                    <p className="mt-2 text-[11px] text-fg-3">
                      Hidden: fewer than {data.minimum_cohort_size} distinct users used SyncTeX.
                    </p>
                  ) : (
                    <ul className="mt-2 space-y-1 text-xs">
                      {data.synctex.by_direction.map((row) => (
                        <li key={row.direction} className="flex items-center justify-between">
                          <span className="text-fg-3">{row.label}</span>
                          <span className="font-semibold text-fg">{count(row.count)}</span>
                        </li>
                      ))}
                      <li className="flex items-center justify-between border-t border-line pt-1">
                        <span className="text-fg-3">Distinct users</span>
                        <span className="font-semibold text-fg">
                          {count(data.synctex.users)}
                        </span>
                      </li>
                    </ul>
                  )}
                </div>
              </div>

              <p className="text-[10px] text-fg-3">
                Period: {new Date(data.period.start).toLocaleDateString()} –{' '}
                {new Date(data.period.end).toLocaleDateString()} ({data.period.timezone}).
                {data.suppression.suppressed_plan_mode_rows > 0
                  ? ` ${data.suppression.suppressed_plan_mode_rows} plan/mode cohort${
                      data.suppression.suppressed_plan_mode_rows === 1 ? '' : 's'
                    } hidden below ${data.minimum_cohort_size} users.`
                  : ''}
                {data.reconciliation.invalid_rows > 0
                  ? ` ${data.reconciliation.invalid_rows} malformed row${
                      data.reconciliation.invalid_rows === 1 ? '' : 's'
                    } ignored.`
                  : ''}
                {data.reconciliation.truncated_events || data.reconciliation.truncated_compilations
                  ? ' Report truncated at the configured row cap.'
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
            Loading editor mode analytics…
          </div>
        )
      )}
    </section>
  )
}
