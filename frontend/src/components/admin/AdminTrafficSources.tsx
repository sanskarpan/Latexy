'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminTrafficSourceRow,
  type AdminTrafficSourcesResponse,
} from '@/lib/api-client'

const numberFormatter = new Intl.NumberFormat('en-IN')

function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(Number.isFinite(value ?? NaN) ? Number(value) : 0)
}

function formatPercent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function formatDate(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString()
}

function SuppressedCell({ minimum }: { minimum: number }) {
  return (
    <span className="text-fg-3" title={`Hidden: fewer than ${minimum} users`}>
      Suppressed
    </span>
  )
}

function TrafficTable({
  title,
  description,
  labelHeader,
  rows,
  hidden,
  minimum,
}: {
  title: string
  description: string
  labelHeader: string
  rows: AdminTrafficSourceRow[]
  hidden: number
  minimum: number
}) {
  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">{description}</p>
      </div>
      {rows.length === 0 ? (
        <p className="px-5 py-8 text-center text-xs text-fg-3">
          No rows in this period.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                <th scope="col" className="px-5 py-2.5 font-semibold">{labelHeader}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Sessions</th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Visitors</th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Signups</th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Signup conv.</th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Paid</th>
                <th scope="col" className="px-5 py-2.5 text-right font-semibold">Paid conv.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label} className="border-b border-line last:border-0">
                  <th scope="row" className="max-w-[240px] truncate px-5 py-2.5 text-left font-medium text-fg" title={row.label}>
                    {row.label}
                  </th>
                  <td className="px-3 py-2.5 text-right text-fg-2">{formatNumber(row.sessions)}</td>
                  <td className="px-3 py-2.5 text-right text-fg-2">{formatNumber(row.visitors)}</td>
                  <td className="px-3 py-2.5 text-right text-fg-2">
                    {row.signups == null ? <SuppressedCell minimum={minimum} /> : formatNumber(row.signups)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-fg-2">{formatPercent(row.signup_conversion)}</td>
                  <td className="px-3 py-2.5 text-right text-fg-2">
                    {row.paid_users == null ? <SuppressedCell minimum={minimum} /> : formatNumber(row.paid_users)}
                  </td>
                  <td className="px-5 py-2.5 text-right text-fg-2">{formatPercent(row.paid_conversion)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hidden > 0 && (
        <p className="border-t border-line px-5 py-2.5 text-[10px] text-fg-3">
          {formatNumber(hidden)} {hidden === 1 ? 'group' : 'groups'} hidden ({'<'}
          {minimum} distinct visitors).
        </p>
      )}
    </section>
  )
}

export default function AdminTrafficSources({ days }: { days: number }) {
  const [data, setData] = useState<AdminTrafficSourcesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)

  const load = useCallback(async () => {
    const current = ++generation.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminTrafficSources({ days })
      if (generation.current === current) setData(next)
    } catch (err) {
      if (generation.current === current) {
        setError(err instanceof Error ? err.message : 'Failed to load traffic sources')
      }
    } finally {
      if (generation.current === current) setLoading(false)
    }
  }, [days])

  useEffect(() => {
    void load()
  }, [load])

  const minimum = data?.minimum_cohort_size ?? 5

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-fg">Traffic sources</h3>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            First-touch UTM source, campaign and external referrer from first-party landing records.
            Signups are attributed by the server-stored landing within the attribution window; paid
            conversion uses settled payments. Only aggregate rows are returned — no IP, email, name,
            token or full URL is stored or shown.
          </p>
        </div>
        {data && (
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
            {formatDate(data.period.start)} – {formatDate(data.period.end)}
          </span>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err">
          {error}
        </div>
      )}
      {loading && !data && (
        <div role="status" className="py-8 text-center text-sm text-fg-3">
          Loading traffic sources…
        </div>
      )}

      {data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
            {[
              { label: 'Sessions', value: formatNumber(data.totals.sessions) },
              { label: 'Visitors', value: formatNumber(data.totals.visitors) },
              { label: 'Attributed signups', value: formatNumber(data.totals.signups) },
              { label: 'Paid users', value: formatNumber(data.totals.paid_users) },
              { label: 'Signup conversion', value: formatPercent(data.totals.signup_conversion) },
              { label: 'Paid conversion', value: formatPercent(data.totals.paid_conversion) },
            ].map((item) => (
              <div key={item.label} className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{item.label}</p>
                <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{item.value}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-fg-3">
            <span>
              {formatNumber(data.unattributed_signups)} signups in this period had no first-party
              landing attribution.
            </span>
            <span>Attribution window: {data.attribution_window_days} days.</span>
            <span>Minimum cohort: {minimum} visitors; 1–4 user cells are suppressed.</span>
            <span>Signup conversion = signups / visitors; paid conversion = paid / attributed signups.</span>
          </div>

          <TrafficTable
            title="By source"
            description="The allowlisted utm_source value. Direct means no UTM source was present."
            labelHeader="Source"
            rows={data.by_source}
            hidden={data.suppressed.source ?? 0}
            minimum={minimum}
          />
          <TrafficTable
            title="By campaign"
            description="The allowlisted utm_campaign value, with signup and paid conversion for the landing cohort."
            labelHeader="Campaign"
            rows={data.by_campaign}
            hidden={data.suppressed.campaign ?? 0}
            minimum={minimum}
          />
          <TrafficTable
            title="By referrer"
            description="External referrer host only. Query strings, paths, IP hosts and same-site navigations are discarded."
            labelHeader="Referrer host"
            rows={data.by_referrer}
            hidden={data.suppressed.referrer ?? 0}
            minimum={minimum}
          />
          <TrafficTable
            title="By medium"
            description="The allowlisted utm_medium value. “not set” means the landing had no medium parameter."
            labelHeader="Medium"
            rows={data.by_medium}
            hidden={data.suppressed.medium ?? 0}
            minimum={minimum}
          />
        </>
      )}
    </section>
  )
}
