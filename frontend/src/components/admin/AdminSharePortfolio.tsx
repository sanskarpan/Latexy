'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminSharePortfolioPortfolioResponse,
  type AdminSharePortfolioPortfolioRow,
  type AdminSharePortfolioResponse,
  type AdminSharePortfolioResumeResponse,
  type AdminSharePortfolioSharePayload,
} from '@/lib/api-client'

const RANGES = [7, 30, 90] as const
const PLAN_OPTIONS = ['', 'free', 'basic', 'pro', 'byok', 'team', 'student']
const numberFormatter = new Intl.NumberFormat('en-IN')

function formatNumber(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value)
    ? '—'
    : numberFormatter.format(Number(value))
}

function formatPercent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function Suppressed({ minimum }: { minimum: number }) {
  return (
    <span className="text-fg-3" title={`Hidden: fewer than ${minimum} distinct viewers`}>
      Suppressed
    </span>
  )
}

function Kpi({
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
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function ShareBreakdown({
  title,
  description,
  header,
  rows,
  hidden,
  minimum,
  valueKey,
}: {
  title: string
  description: string
  header: string
  rows: Array<{ label: string; views: number; unique_viewers: number }>
  hidden: number
  minimum: number
  valueKey: 'referrer' | 'country_code'
}) {
  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-fg">{title}</h4>
        <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{description}</p>
      </div>
      {rows.length === 0 ? (
        <p className="px-5 py-6 text-center text-xs text-fg-3">No visible group in this period.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[340px] border-collapse text-xs">
            <caption className="sr-only">{title}</caption>
            <thead>
              <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                <th scope="col" className="px-5 py-2.5 font-semibold">{header}</th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Views</th>
                <th scope="col" className="px-5 py-2.5 text-right font-semibold">Unique viewers</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label} className="border-b border-line last:border-0">
                  <th scope="row" className="max-w-[260px] truncate px-5 py-2 text-left font-medium text-fg" title={row.label}>
                    {row.label}
                  </th>
                  <td className="px-3 py-2 text-right text-fg-2">{formatNumber(row.views)}</td>
                  <td className="px-5 py-2 text-right text-fg-2">{formatNumber(row.unique_viewers)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hidden > 0 && (
        <p className="border-t border-line px-5 py-2 text-[10px] text-fg-3">
          {formatNumber(hidden)} {hidden === 1 ? 'group' : 'groups'} hidden ({'<'}
          {minimum} distinct viewers). {valueKey === 'country_code' ? 'Country is ISO alpha-2 only.' : 'Host only; no path or query.'}
        </p>
      )}
    </section>
  )
}

function ShareSection({
  data,
  minimum,
  onDrillResume,
  detail,
  detailLoading,
}: {
  data: AdminSharePortfolioSharePayload
  minimum: number
  onDrillResume: (resumeId: string) => void
  detail: AdminSharePortfolioResumeResponse | null
  detailLoading: boolean
}) {
  const summary = data.summary
  const conversion = data.conversion
  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-fg">Public share-link performance</h3>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Views and distinct hashed viewers from <code className="text-[11px]">resume_views</code>, joined to
          the owning resume and plan. The viewer key is a truncated SHA-256 of IP and user-agent and is never
          returned. Referrers are host-only; geography is country-only.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Share views"
          value={formatNumber(summary.views)}
          detail={`${formatNumber(summary.active_share_links)} active link${summary.active_share_links === 1 ? '' : 's'} created in period`}
        />
        <Kpi
          label="Unique viewers"
          value={formatNumber(summary.unique_viewers)}
          detail={`${formatNumber(summary.repeat_views)} repeat view${summary.repeat_views === 1 ? '' : 's'} · ${formatPercent(summary.repeat_view_rate_pct)} repeat rate`}
        />
        <Kpi
          label="Share-link conversion"
          value={formatPercent(summary.share_link_view_rate_pct)}
          detail={`${formatNumber(conversion.numerator)} viewed / ${formatNumber(conversion.denominator)} links created`}
        />
        <Kpi
          label="Views per viewed link"
          value={summary.views_per_viewed_link == null ? '—' : summary.views_per_viewed_link.toFixed(2)}
          detail={conversion.definition}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ShareBreakdown
          title="Referrers"
          description="External host that sent the viewer to the share link. Direct or unknown is shown as direct."
          header="Referrer"
          rows={data.by_referrer.map((row) => ({ label: row.referrer, views: row.views, unique_viewers: row.unique_viewers }))}
          hidden={data.suppressed_groups.referrer}
          minimum={minimum}
          valueKey="referrer"
        />
        <ShareBreakdown
          title="Countries"
          description="Country only, validated ISO 3166-1 alpha-2. No city, region, or raw IP is stored or shown."
          header="Country"
          rows={data.by_country.map((row) => ({ label: row.country_code, views: row.views, unique_viewers: row.unique_viewers }))}
          hidden={data.suppressed_groups.country}
          minimum={minimum}
          valueKey="country_code"
        />
      </div>

      <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
        <div className="border-b border-line px-5 py-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-fg">Per-resume drill-down</h4>
          <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
            Only resumes with at least {minimum} distinct viewers are listed. Selecting a row loads that
            resume&apos;s suppressed referrer and country breakdown.
          </p>
        </div>
        {data.by_resume.length === 0 ? (
          <p className="px-5 py-6 text-center text-xs text-fg-3">No resume meets the suppression floor.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] border-collapse text-xs">
              <caption className="sr-only">Share performance by resume</caption>
              <thead>
                <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                  <th scope="col" className="px-5 py-2.5 font-semibold">Resume</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Views</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Unique viewers</th>
                  <th scope="col" className="px-5 py-2.5 text-right font-semibold">Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.by_resume.map((row) => (
                  <tr key={row.resume_id} className="border-b border-line last:border-0">
                    <th scope="row" className="px-5 py-2 text-left font-mono text-[10px] font-medium text-fg-2" title={row.resume_id}>
                      {row.resume_id}
                    </th>
                    <td className="px-3 py-2 text-right text-fg-2">{formatNumber(row.views)}</td>
                    <td className="px-3 py-2 text-right text-fg-2">{formatNumber(row.unique_viewers)}</td>
                    <td className="px-5 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => onDrillResume(row.resume_id)}
                        className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2"
                      >
                        Drill down
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {detailLoading && <p className="border-t border-line px-5 py-2 text-[10px] text-fg-3">Loading resume detail…</p>}
        {detail && (
          <div className="border-t border-line p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-mono text-[10px] text-fg-3">{detail.resume_id}</p>
              <p className="text-[11px] text-fg-2">
                {formatNumber(detail.share.summary.views)} views · {formatNumber(detail.share.summary.unique_viewers)} unique viewers
              </p>
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <ShareBreakdown
                title="Resume referrers"
                description="Host-only referrers for this resume."
                header="Referrer"
                rows={detail.share.by_referrer.map((row) => ({ label: row.referrer, views: row.views, unique_viewers: row.unique_viewers }))}
                hidden={detail.share.suppressed_groups.referrer}
                minimum={minimum}
                valueKey="referrer"
              />
              <ShareBreakdown
                title="Resume countries"
                description="Country-only geography for this resume."
                header="Country"
                rows={detail.share.by_country.map((row) => ({ label: row.country_code, views: row.views, unique_viewers: row.unique_viewers }))}
                hidden={detail.share.suppressed_groups.country}
                minimum={minimum}
                valueKey="country_code"
              />
            </div>
          </div>
        )}
      </section>
    </section>
  )
}

function PortfolioRow({
  row,
  minimum,
  onDrill,
}: {
  row: AdminSharePortfolioPortfolioRow
  minimum: number
  onDrill: (username: string) => void
}) {
  return (
    <tr className="border-b border-line last:border-0">
      <th scope="row" className="px-5 py-2 text-left font-medium text-fg">
        @{row.portfolio_username}
      </th>
      <td className="px-3 py-2 text-right text-fg-2">{formatNumber(row.views)}</td>
      <td className="px-3 py-2 text-right text-fg-2">{formatNumber(row.unique_viewers)}</td>
      <td className="px-3 py-2 text-right text-fg-2">
        {row.unique_contact_viewers == null ? <Suppressed minimum={minimum} /> : formatNumber(row.unique_contact_viewers)}
      </td>
      <td className="px-3 py-2 text-right text-fg-2">
        {row.unique_signup_viewers == null ? <Suppressed minimum={minimum} /> : formatNumber(row.unique_signup_viewers)}
      </td>
      <td className="px-5 py-2 text-right">
        <button
          type="button"
          onClick={() => onDrill(row.portfolio_username)}
          className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2"
        >
          Drill down
        </button>
      </td>
    </tr>
  )
}

function PortfolioSection({
  data,
  minimum,
  onDrillPortfolio,
  detail,
  detailLoading,
}: {
  data: NonNullable<AdminSharePortfolioResponse['portfolio']>
  minimum: number
  onDrillPortfolio: (username: string) => void
  detail: AdminSharePortfolioPortfolioResponse | null
  detailLoading: boolean
}) {
  const summary = data.summary
  const maxStep = Math.max(...data.funnel.steps.map((step) => step.count ?? 0), 1)
  return (
    <section className="mt-8 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-fg">Public portfolio funnel</h3>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Consent-gated first-party capture only. A contact must follow a portfolio view, and a signup must
          follow that contact, so every conversion has an explicit unique-viewer denominator. No contact
          message, email, name, IP, user-agent, or viewer identifier is stored or returned.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Portfolio views"
          value={formatNumber(summary.views)}
          detail={`${formatNumber(summary.unique_viewers)} unique viewer${summary.unique_viewers === 1 ? '' : 's'}`}
        />
        <Kpi
          label="Contact"
          value={formatNumber(summary.unique_contact_viewers)}
          detail={`${formatPercent(summary.contact_rate_pct)} of unique portfolio viewers`}
        />
        <Kpi
          label="Signup"
          value={formatNumber(summary.unique_signup_viewers)}
          detail={`${formatPercent(summary.signup_rate_pct)} of unique contact viewers`}
        />
        <Kpi
          label="View → signup"
          value={formatPercent(summary.view_to_signup_rate_pct)}
          detail={data.funnel.definition}
        />
      </div>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <div className="space-y-3">
          {data.funnel.steps.map((step) => (
            <div key={step.step}>
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="text-fg-2">{step.label}</span>
                <span className="font-semibold text-fg">
                  {formatNumber(step.count)}
                  <span className="ml-2 font-normal text-fg-3">
                    {formatNumber(step.unique_viewers)} unique viewers
                  </span>
                </span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{ width: `${Math.max(2, Math.round(((step.count ?? 0) / maxStep) * 100))}%` }}
                />
              </div>
              <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-fg-3">
                <span>Denominator: {step.denominator} ({formatNumber(step.denominator_value)})</span>
                <span>From previous: {formatPercent(step.conversion_from_previous_pct)}</span>
                <span>From views: {formatPercent(step.conversion_from_start_pct)}</span>
                {step.suppressed && <span className="text-warn">Suppressed (&lt;{minimum} viewers)</span>}
              </p>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <ShareBreakdown
          title="Portfolio referrers"
          description="Host-only referrers for consent-gated portfolio views."
          header="Referrer"
          rows={data.by_referrer.map((row) => ({ label: row.referrer, views: row.views, unique_viewers: row.unique_viewers }))}
          hidden={data.suppressed_groups.referrer}
          minimum={minimum}
          valueKey="referrer"
        />
        <ShareBreakdown
          title="Portfolio countries"
          description="Country only, validated ISO 3166-1 alpha-2."
          header="Country"
          rows={data.by_country.map((row) => ({ label: row.country_code, views: row.views, unique_viewers: row.unique_viewers }))}
          hidden={data.suppressed_groups.country}
          minimum={minimum}
          valueKey="country_code"
        />
      </div>

      <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
        <div className="border-b border-line px-5 py-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-fg">Per-portfolio drill-down</h4>
          <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
            Only portfolios with at least {minimum} distinct viewers are listed. Contact and signup cells of
            1-4 are suppressed independently.
          </p>
        </div>
        {data.by_portfolio.length === 0 ? (
          <p className="px-5 py-6 text-center text-xs text-fg-3">No portfolio meets the suppression floor.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse text-xs">
              <caption className="sr-only">Portfolio funnel by public username</caption>
              <thead>
                <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                  <th scope="col" className="px-5 py-2.5 font-semibold">Portfolio</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Views</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Unique viewers</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Contact</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Signup</th>
                  <th scope="col" className="px-5 py-2.5 text-right font-semibold">Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.by_portfolio.map((row) => (
                  <PortfolioRow
                    key={row.portfolio_username}
                    row={row}
                    minimum={minimum}
                    onDrill={onDrillPortfolio}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {detailLoading && <p className="border-t border-line px-5 py-2 text-[10px] text-fg-3">Loading portfolio detail…</p>}
        {detail && (
          <div className="border-t border-line p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-semibold text-fg">@{detail.portfolio_username}</p>
              <p className="text-[11px] text-fg-2">
                {formatNumber(detail.portfolio.summary.views)} views · {formatNumber(detail.portfolio.summary.unique_viewers)} unique viewers
              </p>
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <ShareBreakdown
                title="Portfolio referrers"
                description="Host-only referrers for this portfolio."
                header="Referrer"
                rows={detail.portfolio.by_referrer.map((row) => ({ label: row.referrer, views: row.views, unique_viewers: row.unique_viewers }))}
                hidden={detail.portfolio.suppressed_groups.referrer}
                minimum={minimum}
                valueKey="referrer"
              />
              <ShareBreakdown
                title="Portfolio countries"
                description="Country-only geography for this portfolio."
                header="Country"
                rows={detail.portfolio.by_country.map((row) => ({ label: row.country_code, views: row.views, unique_viewers: row.unique_viewers }))}
                hidden={detail.portfolio.suppressed_groups.country}
                minimum={minimum}
                valueKey="country_code"
              />
            </div>
          </div>
        )}
      </section>
    </section>
  )
}

export default function AdminSharePortfolio() {
  const [range, setRange] = useState<number>(30)
  const [plan, setPlan] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [applied, setApplied] = useState({ range: 30, plan: '', from: '', to: '' })
  const [data, setData] = useState<AdminSharePortfolioResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resumeDetail, setResumeDetail] = useState<AdminSharePortfolioResumeResponse | null>(null)
  const [portfolioDetail, setPortfolioDetail] = useState<AdminSharePortfolioPortfolioResponse | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const requestGeneration = useRef(0)

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminSharePortfolio({
        days: applied.range,
        start_date: applied.from || undefined,
        end_date: applied.to || undefined,
        plan: applied.plan || undefined,
      })
      if (generation === requestGeneration.current) {
        setData(next)
        setResumeDetail(null)
        setPortfolioDetail(null)
      }
    } catch (err) {
      if (generation === requestGeneration.current) {
        setError(err instanceof Error ? err.message : 'Failed to load share and portfolio analytics')
      }
    } finally {
      if (generation === requestGeneration.current) setLoading(false)
    }
  }, [applied])

  useEffect(() => {
    void load()
  }, [load])

  const apply = (next: Partial<typeof applied>) => {
    setApplied((current) => ({ ...current, ...next }))
  }

  const drillResume = useCallback(
    async (resumeId: string) => {
      setDetailLoading(true)
      try {
        const next = await apiClient.getAdminSharePortfolioResume(resumeId, {
          days: applied.range,
          start_date: applied.from || undefined,
          end_date: applied.to || undefined,
          plan: applied.plan || undefined,
        })
        setResumeDetail(next)
        setPortfolioDetail(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load resume detail')
      } finally {
        setDetailLoading(false)
      }
    },
    [applied],
  )

  const drillPortfolio = useCallback(
    async (username: string) => {
      setDetailLoading(true)
      try {
        const next = await apiClient.getAdminSharePortfolioPortfolio(username, {
          days: applied.range,
          start_date: applied.from || undefined,
          end_date: applied.to || undefined,
          plan: applied.plan || undefined,
        })
        setPortfolioDetail(next)
        setResumeDetail(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load portfolio detail')
      } finally {
        setDetailLoading(false)
      }
    },
    [applied],
  )

  const minimum = data?.minimum_cohort_size ?? 5

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">Share and portfolio performance</h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Admin-only aggregate views, unique hashed viewers, referrer/country breakdowns, share-link
              conversion, and the portfolio view → contact → signup funnel. Cohorts below {minimum} distinct
              viewers are suppressed; counts of 1-4 are hidden. No raw IP, viewer identity, document content,
              contact message, email, or name is returned.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5" role="group" aria-label="Share and portfolio date range">
              {RANGES.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={range === value}
                  onClick={() => {
                    setRange(value)
                    apply({ range: value })
                  }}
                  className={`rounded px-2.5 py-1 text-[11px] font-medium ${range === value ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'}`}
                >
                  {value}d
                </button>
              ))}
            </div>
            <select
              aria-label="Share and portfolio plan filter"
              value={plan}
              onChange={(event) => {
                setPlan(event.target.value)
                apply({ plan: event.target.value })
              }}
              className="min-h-[34px] rounded border border-line bg-bg px-2.5 py-1.5 text-[11px] text-fg"
            >
              {PLAN_OPTIONS.map((item) => (
                <option key={item || 'all'} value={item}>{item || 'All plans'}</option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-[10px] text-fg-3">
              From
              <input
                type="date"
                aria-label="Share and portfolio start date"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
                className="min-h-[34px] rounded border border-line bg-bg px-2 py-1 text-[11px] text-fg"
              />
            </label>
            <label className="flex items-center gap-1 text-[10px] text-fg-3">
              To
              <input
                type="date"
                aria-label="Share and portfolio end date"
                value={to}
                onChange={(event) => setTo(event.target.value)}
                className="min-h-[34px] rounded border border-line bg-bg px-2 py-1 text-[11px] text-fg"
              />
            </label>
            <button
              type="button"
              onClick={() => apply({ from, to })}
              disabled={loading}
              className="min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
        {data && (
          <p className="mt-3 text-[10px] text-fg-3">
            {data.period.start} → {data.period.end} · UTC · minimum cohort {data.minimum_cohort_size} ·
            {data.filters.plan ? ` plan ${data.filters.plan}` : ' all plans'}
          </p>
        )}
      </div>

      {error && (
        <div role="alert" className="mx-5 mt-4 rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err">
          {error}
        </div>
      )}

      {loading && !data ? (
        <div className="space-y-3 p-5">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-16 animate-pulse rounded-md bg-surface-2" />
          ))}
        </div>
      ) : data ? (
        <div className="p-5">
          <ShareSection
            data={data.share}
            minimum={minimum}
            onDrillResume={(resumeId) => void drillResume(resumeId)}
            detail={resumeDetail}
            detailLoading={detailLoading}
          />
          {data.portfolio && (
            <PortfolioSection
              data={data.portfolio}
              minimum={minimum}
              onDrillPortfolio={(username) => void drillPortfolio(username)}
              detail={portfolioDetail}
              detailLoading={detailLoading}
            />
          )}
          <p className="mt-5 border-t border-line pt-3 text-[10px] leading-relaxed text-fg-3">
            Share rows come from owner-facing <code>resume_views</code>; portfolio rows come only from
            consent-gated first-party capture in <code>usage_analytics</code>. The report is aggregate-only:
            no resume text, share token, contact message, email, name, raw IP, user-agent, session id, or
            viewer key is selected or returned.
          </p>
        </div>
      ) : null}
    </section>
  )
}
