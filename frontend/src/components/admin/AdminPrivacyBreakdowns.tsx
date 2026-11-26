'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminPrivacyBreakdownDimension,
  type AdminPrivacyBreakdownResponse,
  type AdminPrivacyBreakdownRow,
} from '@/lib/api-client'
import { formatNumber } from './admin-format'

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

function Cell({ value, suppressed }: { value: number | null; suppressed: boolean }) {
  if (value == null) {
    return (
      <td className="px-3 py-1.5 text-right text-fg-3">
        <span
          title={suppressed ? 'Hidden because the cohort is smaller than 5' : 'Not available'}
        >
          —
        </span>
      </td>
    )
  }
  return <td className="px-3 py-1.5 text-right text-fg-3">{formatNumber(value)}</td>
}

function BreakdownTable({ dimension }: { dimension: AdminPrivacyBreakdownDimension }) {
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-semibold text-fg">{dimension.label}</h4>
        <span className="text-[10px] text-fg-3">
          {dimension.rows.length} visible
          {dimension.suppressed_rows > 0
            ? ` · ${dimension.suppressed_rows} suppressed (<5)`
            : ''}
          {dimension.truncated_rows > 0 ? ` · ${dimension.truncated_rows} truncated` : ''}
        </span>
      </div>
      <div className="mt-2 overflow-x-auto rounded border border-line">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
            <tr>
              <th className="px-3 py-2 font-semibold">{dimension.label}</th>
              <th className="px-3 py-2 text-right font-semibold">Page views</th>
              <th className="px-3 py-2 text-right font-semibold">Sessions</th>
              <th className="px-3 py-2 text-right font-semibold">Signups</th>
              <th className="px-3 py-2 text-right font-semibold">Signup conversion</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {dimension.rows.map((row: AdminPrivacyBreakdownRow) => (
              <tr key={row.value}>
                <td className="px-3 py-1.5 font-medium text-fg">{row.label}</td>
                <Cell
                  value={row.page_views}
                  suppressed={row.suppressed_cells.includes('page_views')}
                />
                <Cell
                  value={row.sessions}
                  suppressed={row.suppressed_cells.includes('sessions')}
                />
                <Cell value={row.signups} suppressed={row.suppressed_cells.includes('signups')} />
                <td className="px-3 py-1.5 text-right font-semibold text-fg">
                  {rate(row.signup_conversion)}
                </td>
              </tr>
            ))}
            {dimension.rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-5 text-center text-fg-3">
                  No {dimension.label.toLowerCase()} cohort has reached the minimum size of 5 in
                  this period.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function AdminPrivacyBreakdowns({ days }: { days: number }) {
  const [data, setData] = useState<AdminPrivacyBreakdownResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminPrivacyBreakdowns({ days })
      if (generation.current === current) setData(next)
    } catch (err) {
      if (generation.current === current) {
        setError(
          err instanceof Error ? err.message : 'Failed to load privacy-safe breakdowns',
        )
      }
    } finally {
      if (generation.current === current) setLoading(false)
    }
  }, [days])

  useEffect(() => {
    void load()
  }, [load])

  const summary = data?.summary
  const attribution = data?.signup_attribution
  const dimensions = data
    ? [data.dimensions.device, data.dimensions.browser, data.dimensions.os, data.dimensions.country]
    : []
  const hasRows = dimensions.some((dimension) => dimension.rows.length > 0)

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">
              Privacy-safe device, browser, OS and country
            </h3>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Aggregate sessions/page views and signups. Device, browser and OS are fixed
              labels parsed server-side; country is a validated ISO alpha-2 code only. Raw IP
              addresses, full user agents and city-level data are never returned. Cohorts below{' '}
              {data?.minimum_cohort_size ?? 5} are suppressed.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
              {loading
                ? 'Loading…'
                : data
                  ? `${data.days} days · UTC`
                  : '—'}
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
            <Metric label="Page views" value={formatNumber(summary.page_views)} />
            <Metric label="Sessions" value={formatNumber(summary.sessions)} />
            <Metric
              label="Signups"
              value={summary.signups == null ? '—' : formatNumber(summary.signups)}
              detail={summary.signups == null ? 'Hidden: cohort below 5' : undefined}
            />
            <Metric
              label="Signup conversion"
              value={rate(summary.signup_conversion)}
              detail={
                attribution
                  ? `${attribution.attributed ?? '—'} attributed · ${attribution.unattributed ?? '—'} unknown`
                  : undefined
              }
            />
          </div>

          <p className="text-[10px] text-fg-3">
            Period: {new Date(data.period.start).toLocaleDateString()} –{' '}
            {new Date(data.period.end).toLocaleDateString()} ({data.period.timezone}).{' '}
            {data.suppressed_rows > 0
              ? `${data.suppressed_rows} row${data.suppressed_rows === 1 ? '' : 's'} hidden because every cell was below ${data.minimum_cohort_size}.`
              : `All visible cohorts have at least ${data.minimum_cohort_size}.`}
            {data.truncated_rows > 0
              ? ` ${data.truncated_rows} lower-volume groups truncated.`
              : ''}
          </p>

          {hasRows ? (
            dimensions.map((dimension) => (
              <BreakdownTable key={dimension.key} dimension={dimension} />
            ))
          ) : (
            <div className="rounded border border-line bg-surface-2 px-4 py-8 text-center text-xs text-fg-3">
              No page views or signups are available for this period.
            </div>
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
            Loading privacy-safe breakdowns…
          </div>
        )
      )}
    </section>
  )
}
