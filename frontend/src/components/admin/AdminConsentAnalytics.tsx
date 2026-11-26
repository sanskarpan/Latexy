'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminConsentAnalyticsResponse,
  type AdminConsentCountRow,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from './admin-format'

function formatCount(value: number | null | undefined): string {
  return value == null ? 'Hidden' : formatNumber(value)
}

function formatRate(value: number | null | undefined): string {
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

function CountCell({ value, suppressed }: { value: number | null; suppressed: boolean }) {
  return (
    <td className="px-3 py-1.5 text-right text-fg-3">
      {value == null ? (
        <span title={suppressed ? 'Hidden because the cohort is smaller than 5' : 'Not available'}>
          —
        </span>
      ) : (
        formatNumber(value)
      )}
    </td>
  )
}

function MaybeHidden({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="text-fg-3">— hidden (&lt;5)</span>
  }
  return <span className="font-semibold text-fg">{formatNumber(value)}</span>
}

function CountTable<T extends AdminConsentCountRow>({
  rows,
  firstColumnLabel,
  firstColumn,
}: {
  rows: T[]
  firstColumnLabel: string
  firstColumn: (row: T) => string
}) {
  return (
    <div className="overflow-x-auto rounded border border-line">
      <table className="min-w-full text-left text-xs">
        <caption className="sr-only">
          Consent decisions by {firstColumnLabel.toLowerCase()} with small-cohort suppression
        </caption>
        <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
          <tr>
            <th scope="col" className="px-3 py-2 font-semibold">
              {firstColumnLabel}
            </th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">
              Granted
            </th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">
              Denied
            </th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">
              Withdrawn
            </th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">
              Total
            </th>
            <th scope="col" className="px-3 py-2 text-right font-semibold">
              Sessions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row, index) => (
            <tr key={`${firstColumn(row)}:${index}`}>
              <td className="px-3 py-1.5 font-medium text-fg">{firstColumn(row)}</td>
              <CountCell
                value={row.granted}
                suppressed={row.suppressed_cells.includes('granted')}
              />
              <CountCell
                value={row.denied}
                suppressed={row.suppressed_cells.includes('denied')}
              />
              <CountCell
                value={row.withdrawn}
                suppressed={row.suppressed_cells.includes('withdrawn')}
              />
              <CountCell value={row.total} suppressed={row.suppressed_cells.includes('total')} />
              <CountCell
                value={row.unique_sessions}
                suppressed={row.suppressed_cells.includes('unique_sessions')}
              />
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-5 text-center text-fg-3">
                No consent decisions in this period.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminConsentAnalytics({ days }: { days: number }) {
  const [data, setData] = useState<AdminConsentAnalyticsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminConsentAnalytics({ days })
      if (generation.current === current) setData(next)
    } catch (err) {
      if (generation.current === current) {
        setError(err instanceof Error ? err.message : 'Failed to load consent analytics')
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

  const summary = data?.summary
  const withdrawal = data?.withdrawal_trend
  const replay = data?.replay_coverage

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Analytics consent and replay coverage</h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              First-party grant, deny, and withdrawal counts by day and surface. Only
              aggregate counts leave the backend; no email, name, account id, document
              text, replay payload, IP address, or user agent is available here.
              Counts of 1-4 are suppressed.
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

      {summary && data ? (
        <div className="space-y-5 px-5 py-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric
              label="Granted"
              value={formatCount(summary.granted)}
              detail={
                summary.unique_sessions == null
                  ? 'Session count hidden (<5)'
                  : `${formatNumber(summary.unique_sessions)} sessions in period`
              }
            />
            <Metric label="Denied" value={formatCount(summary.denied)} />
            <Metric
              label="Withdrawn"
              value={formatCount(summary.withdrawn)}
              detail="Stops browser capture and replay immediately"
            />
            <Metric
              label="Consent coverage"
              value={formatRate(summary.consent_coverage_pct)}
              detail="Granted share of recorded choices"
            />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4">
              <h4 className="text-xs font-semibold text-fg">Withdrawal trend</h4>
              <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                {withdrawal?.description}
              </p>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div>
                  <dt className="text-fg-3">Current</dt>
                  <dd className="mt-0.5">
                    <MaybeHidden value={withdrawal?.current} />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Previous</dt>
                  <dd className="mt-0.5">
                    <MaybeHidden value={withdrawal?.previous} />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Change</dt>
                  <dd className="mt-0.5">
                    {withdrawal?.suppressed ? (
                      <span className="text-fg-3">— hidden (&lt;5)</span>
                    ) : withdrawal?.percent_delta == null ? (
                      <span className="text-fg-2">
                        {withdrawal?.baseline_zero ? 'No prior baseline' : '—'}
                      </span>
                    ) : (
                      <span className="font-semibold text-fg">
                        {withdrawal.percent_delta >= 0 ? '+' : ''}
                        {withdrawal.percent_delta.toFixed(1)}%
                      </span>
                    )}
                  </dd>
                </div>
              </dl>
            </div>

            <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4">
              <h4 className="text-xs font-semibold text-fg">Replay coverage</h4>
              <p className="mt-1 text-[10px] leading-relaxed text-fg-3">{replay?.definition}</p>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                <div>
                  <dt className="text-fg-3">Eligible</dt>
                  <dd className="mt-0.5">
                    <MaybeHidden value={replay?.eligible_sessions} />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Consent sessions</dt>
                  <dd className="mt-0.5">
                    <MaybeHidden value={replay?.sessions_with_consent} />
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Coverage</dt>
                  <dd className="mt-0.5 font-semibold text-fg">
                    {formatRate(replay?.coverage_pct)}
                  </dd>
                </div>
              </dl>
              <p className="mt-2 text-[10px] leading-relaxed text-fg-3">{replay?.posthog_capture}</p>
            </div>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-fg">By day</h4>
            <p className="mt-1 text-[10px] text-fg-3">
              Daily first-party consent decisions. The total is hidden when a small cell
              could otherwise be recovered by subtraction.
            </p>
            <div className="mt-2">
              <CountTable
                rows={data.by_day}
                firstColumnLabel="Day"
                firstColumn={(row) => row.date}
              />
            </div>
          </div>

          <div>
            <h4 className="text-xs font-semibold text-fg">By surface</h4>
            <p className="mt-1 text-[10px] text-fg-3">
              Where the choice was made. Unknown or unrecognized surfaces are bucketed,
              never passed through as free text.
            </p>
            <div className="mt-2">
              <CountTable
                rows={data.by_surface}
                firstColumnLabel="Surface"
                firstColumn={(row) => row.label ?? row.surface}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[10px] text-fg-3">
            <span>
              {data.suppressed_cells > 0
                ? `${formatNumber(data.suppressed_cells)} cell${data.suppressed_cells === 1 ? '' : 's'} hidden (<${data.minimum_cohort_size}).`
                : `No cells needed suppression at the ${data.minimum_cohort_size}-session minimum.`}
              {data.suppressed_rows > 0
                ? ` ${formatNumber(data.suppressed_rows)} row${data.suppressed_rows === 1 ? '' : 's'} fully hidden.`
                : ''}
              {data.truncated_surfaces > 0
                ? ` ${formatNumber(data.truncated_surfaces)} lower-volume surfaces truncated.`
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
            Loading consent analytics…
          </div>
        )
      )}
    </section>
  )
}
