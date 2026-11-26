'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  apiClient,
  type AdminOnboardingAnalyticsResponse,
  type AdminOnboardingSegmentRow,
  type AdminOnboardingStepRow,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from './admin-format'

type SegmentDimension = 'plan' | 'provider'

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function formatRate(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function Hidden({ label = 'hidden (<5)' }: { label?: string }) {
  return <span className="text-fg-3">— {label}</span>
}

function Count({ value, suppressed }: { value: number | null; suppressed?: boolean }) {
  if (value == null) return <Hidden label={suppressed ? 'hidden (<5)' : 'not available'} />
  return <>{formatNumber(value)}</>
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
    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">{label}</p>
      <p className="mt-1 text-xl font-semibold text-fg">{value}</p>
      {detail && <p className="mt-0.5 text-[10px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function StepTable({
  rows,
  caption,
  emptyLabel,
}: {
  rows: AdminOnboardingStepRow[]
  caption: string
  emptyLabel: string
}) {
  return (
    <div className="mt-3 overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[980px] border-collapse text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
            <th scope="col" className="px-3 py-2 text-left font-semibold">Step</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Views</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Unique viewers</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Completions</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Skips</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Abandoned</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Drop-off</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Median time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.step_key} className="border-t border-line">
              <td className="px-3 py-1.5">
                <span className="font-medium text-fg">
                  {row.step_index != null ? `${row.step_index + 1}. ` : ''}
                  {row.label}
                </span>
                <span className="ml-1.5 font-mono text-[10px] text-fg-3">{row.step_key}</span>
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.views} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.unique_viewers} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg">
                <Count value={row.completions} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.skips} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.abandoned_accounts} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right font-semibold text-fg">
                {row.suppressed ? <Hidden /> : formatRate(row.drop_off_rate)}
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                {row.suppressed ? <Hidden /> : formatDuration(row.median_duration_seconds)}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} className="px-3 py-5 text-center text-fg-3">
                {emptyLabel}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function SegmentSummaryTable({
  rows,
  dimensionLabel,
}: {
  rows: AdminOnboardingSegmentRow[]
  dimensionLabel: string
}) {
  return (
    <div className="mt-3 overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[720px] border-collapse text-xs">
        <caption className="sr-only">{dimensionLabel} onboarding summary</caption>
        <thead>
          <tr className="border-b border-line bg-surface-2/60 text-[10px] uppercase tracking-wider text-fg-3">
            <th scope="col" className="px-3 py-2 text-left font-semibold">{dimensionLabel}</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Accounts</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Views</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Completions</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Skips</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Drop-off</th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">Median time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-line">
              <td className="px-3 py-1.5 font-medium text-fg">{row.label}</td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.accounts} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.views} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg">
                <Count value={row.completions} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                <Count value={row.skips} suppressed={row.suppressed} />
              </td>
              <td className="px-3 py-1.5 text-right font-semibold text-fg">
                {row.suppressed ? <Hidden /> : formatRate(row.drop_off_rate)}
              </td>
              <td className="px-3 py-1.5 text-right text-fg-2">
                {row.suppressed ? <Hidden /> : formatDuration(row.median_duration_seconds)}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={7} className="px-3 py-5 text-center text-fg-3">
                No {dimensionLabel.toLowerCase()} cohort has at least five accounts in this period.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminOnboardingAnalytics({ days }: { days: number }) {
  const [data, setData] = useState<AdminOnboardingAnalyticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dimension, setDimension] = useState<SegmentDimension>('plan')
  const [segmentKey, setSegmentKey] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminOnboardingAnalytics({ days })
      if (generation.current === current) setData(next)
    } catch (err) {
      if (generation.current === current) {
        setError(err instanceof Error ? err.message : 'Failed to load onboarding analytics')
      }
    } finally {
      if (generation.current === current) setLoading(false)
    }
  }, [days])

  useEffect(() => {
    void load()
    return () => {
      generation.current += 1
    }
  }, [load])

  const dimensionRows = useMemo(
    () => (dimension === 'plan' ? data?.by_plan : data?.by_provider) ?? [],
    [data, dimension],
  )
  const selectedSegment = useMemo(() => {
    if (dimensionRows.length === 0) return null
    return dimensionRows.find((row) => row.key === segmentKey) ?? dimensionRows[0]
  }, [dimensionRows, segmentKey])

  const summary = data?.summary
  const reconciliation = data?.completion_reconciliation
  const hiddenSegments =
    (data?.suppressed_segments.plan ?? 0) + (data?.suppressed_segments.provider ?? 0)

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Onboarding step completion and drop-off</h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              First-party step views, completions, skips, drop-off, median time and
              abandonment by plan and signup provider. Only bounded step/flow labels
              are stored; no form contents, name, email, document text or free-form
              event metadata is available here. Cohorts smaller than{' '}
              {data?.minimum_cohort_size ?? 5} accounts are hidden.
            </p>
          </div>
          <div className="flex items-center gap-2">
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
      </div>

      {error && (
        <p
          role="alert"
          className="mx-5 mt-4 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
        >
          {error}
        </p>
      )}

      {data && summary ? (
        <div className="space-y-5 px-5 py-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Accounts seen"
              value={summary.accounts == null ? 'Hidden (<5)' : formatNumber(summary.accounts)}
              detail="distinct accounts with an onboarding event"
            />
            <Metric
              label="Step views"
              value={summary.views == null ? 'Hidden (<5)' : formatNumber(summary.views)}
              detail={`${formatNumber(summary.step_completions)} step completions`}
            />
            <Metric
              label="Flow completions"
              value={summary.completions == null ? 'Hidden (<5)' : formatNumber(summary.completions)}
              detail={`${formatRate(summary.completion_rate)} of accounts`}
            />
            <Metric
              label="Skips / abandonment"
              value={
                summary.skips == null
                  ? 'Hidden (<5)'
                  : `${formatNumber(summary.skips)} / ${formatNumber(summary.abandoned_accounts)}`
              }
              detail={`${formatRate(summary.skip_rate)} skipped · ${formatRate(summary.drop_off_rate)} abandoned`}
            />
          </div>

          <div>
            <h4 className="text-xs font-semibold text-fg">Per-step funnel</h4>
            <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
              Drop-off is the share of unique viewers who neither completed nor
              skipped that step. Median time is measured from the step view to the
              completion event. A row is hidden when any published account cohort
              is between 1 and 4.
            </p>
            <StepTable
              rows={data.steps}
              caption="Onboarding step views, completions, skips, drop-off and median time"
              emptyLabel="No onboarding steps were viewed in this period."
            />
          </div>

          {reconciliation && (
            <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h4 className="text-xs font-semibold text-fg">Account preference reconciliation</h4>
                  <p className="mt-1 max-w-3xl text-[10px] leading-relaxed text-fg-3">
                    {reconciliation.definition}
                  </p>
                </div>
                <span className="rounded-full border border-line bg-surface px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                  {reconciliation.suppressed
                    ? 'Hidden (<5)'
                    : `${formatRate(reconciliation.reconciled_rate)} reconciled`}
                </span>
              </div>
              <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-3 xl:grid-cols-6">
                <div>
                  <dt className="text-fg-3">Terminal events</dt>
                  <dd className="mt-0.5 font-semibold text-fg">
                    <Count
                      value={reconciliation.terminal_accounts}
                      suppressed={reconciliation.suppressed}
                    />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Completed</dt>
                  <dd className="mt-0.5">
                    <Count
                      value={reconciliation.completed_accounts}
                      suppressed={reconciliation.suppressed}
                    />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Skipped</dt>
                  <dd className="mt-0.5">
                    <Count
                      value={reconciliation.skipped_accounts}
                      suppressed={reconciliation.suppressed}
                    />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Preference on</dt>
                  <dd className="mt-0.5">
                    <Count
                      value={reconciliation.preference_on_accounts}
                      suppressed={reconciliation.suppressed}
                    />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Missing preference</dt>
                  <dd className="mt-0.5">
                    <Count
                      value={reconciliation.missing_preference_accounts}
                      suppressed={reconciliation.suppressed}
                    />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Flagged, no terminal</dt>
                  <dd className="mt-0.5">
                    <Count
                      value={reconciliation.preference_without_terminal_accounts}
                      suppressed={reconciliation.suppressed}
                    />
                  </dd>
                </div>
              </dl>
            </div>
          )}

          <div>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4 className="text-xs font-semibold text-fg">Plan and provider segments</h4>
                <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                  Server-owned plan and signup-provider labels joined from the
                  account row. Select a segment to inspect its per-step funnel.
                </p>
              </div>
              <div className="flex flex-wrap gap-1" role="tablist" aria-label="Onboarding segment dimension">
                {(['plan', 'provider'] as const).map((item) => (
                  <button
                    key={item}
                    type="button"
                    role="tab"
                    aria-selected={dimension === item}
                    onClick={() => {
                      setDimension(item)
                      setSegmentKey(null)
                    }}
                    className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                      dimension === item
                        ? 'border-accent text-accent-strong'
                        : 'border-line text-fg-3 hover:bg-surface-2'
                    }`}
                  >
                    {item === 'plan' ? 'By plan' : 'By provider'}
                  </button>
                ))}
              </div>
            </div>

            <SegmentSummaryTable
              rows={dimensionRows}
              dimensionLabel={dimension === 'plan' ? 'Plan' : 'Signup provider'}
            />

            {dimensionRows.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1" role="tablist" aria-label="Onboarding segment">
                {dimensionRows.map((row) => (
                  <button
                    key={row.key}
                    type="button"
                    role="tab"
                    aria-selected={selectedSegment?.key === row.key}
                    onClick={() => setSegmentKey(row.key)}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${
                      selectedSegment?.key === row.key
                        ? 'border-accent bg-accent-soft text-accent-strong'
                        : 'border-line text-fg-3 hover:bg-surface-2'
                    }`}
                  >
                    {row.label}
                    <span className="ml-1.5 text-[10px] opacity-70">
                      {row.accounts == null ? 'hidden' : `${formatNumber(row.accounts)} accounts`}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {selectedSegment ? (
              <StepTable
                rows={selectedSegment.steps}
                caption={`Onboarding steps for ${selectedSegment.label}`}
                emptyLabel="This segment is hidden or has no visible step data."
              />
            ) : (
              <p className="mt-3 rounded border border-line bg-surface-2/40 px-3 py-4 text-center text-xs text-fg-3">
                No {dimension === 'plan' ? 'plan' : 'provider'} segment has at least five accounts in this period.
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[10px] text-fg-3">
            <span>
              {data.suppressed_rows > 0
                ? `${formatNumber(data.suppressed_rows)} row${data.suppressed_rows === 1 ? '' : 's'} hidden (<${data.minimum_cohort_size} accounts).`
                : `No rows needed suppression at the ${data.minimum_cohort_size}-account minimum.`}
              {hiddenSegments > 0
                ? ` ${formatNumber(hiddenSegments)} segment${hiddenSegments === 1 ? '' : 's'} hidden.`
                : ''}
              {data.truncated_segments.plan + data.truncated_segments.provider > 0
                ? ' Lower-volume segments were truncated.'
                : ''}
              {data.truncated_events ? ' Event scan limit reached; older rows may be omitted.' : ''}
            </span>
            <span>Generated {formatDateTime(data.generated_at)}</span>
          </div>

          <ul className="list-disc space-y-0.5 pl-4 text-[10px] leading-relaxed text-fg-3">
            {data.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      ) : (
        !error && (
          <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
            Loading onboarding analytics…
          </div>
        )
      )}
    </section>
  )
}
