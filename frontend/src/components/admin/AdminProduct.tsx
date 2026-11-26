'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  apiClient,
  type AdminFeatureAdoptionDimension,
  type AdminFeatureAdoptionResponse,
  type AdminFeatureAdoptionSegment,
} from '@/lib/api-client'
import AdminEditorModeUsage from './AdminEditorModeUsage'

const DIMENSIONS: Array<{ id: AdminFeatureAdoptionDimension; label: string }> = [
  { id: 'plan', label: 'Plan' },
  { id: 'role', label: 'Account role' },
  { id: 'cohort', label: 'Signup cohort' },
]

const RANGES = [7, 30, 90, 180] as const

const numberFormatter = new Intl.NumberFormat('en-IN')

function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(Number(value ?? 0))
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)}%`
}

function formatTimestamp(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString()
}

function PenetrationBar({ value }: { value: number }) {
  const width = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
  return (
    <div className="min-w-[110px]">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
        <div className="h-full rounded-full bg-accent" style={{ width: `${width}%` }} />
      </div>
      <span className="mt-1 block text-[10px] text-fg-3">{formatPercent(value)}</span>
    </div>
  )
}

function SummaryCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">{label}</p>
      <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
      {detail && <p className="mt-0.5 text-[10px] text-fg-3">{detail}</p>}
    </div>
  )
}

function SegmentMatrix({ segment }: { segment: AdminFeatureAdoptionSegment }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[940px] border-collapse text-sm">
        <caption className="sr-only">
          Feature adoption for {segment.label}; denominator {segment.denominator} users
        </caption>
        <thead>
          <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
            <th scope="col" className="px-5 py-3 text-left font-semibold">Feature</th>
            <th scope="col" className="px-3 py-3 text-left font-semibold">Category</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Used at least once</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Weekly active</th>
            <th scope="col" className="px-3 py-3 text-left font-semibold">Penetration</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Weekly penetration</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Events</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Last used</th>
          </tr>
        </thead>
        <tbody>
          {segment.features.map((row) => (
            <tr key={row.key} className="border-t border-line align-top">
              <td className="px-5 py-3">
                <p className="text-xs font-medium text-fg">{row.label}</p>
                <p className="mt-0.5 font-mono text-[10px] text-fg-3">{row.key}</p>
              </td>
              <td className="px-3 py-3 text-xs capitalize text-fg-2">{row.category}</td>
              <td className="px-3 py-3 text-right text-xs text-fg">
                {formatNumber(row.used_at_least_once)}
                <span className="block text-[10px] text-fg-3">of {formatNumber(segment.denominator)}</span>
              </td>
              <td className="px-3 py-3 text-right text-xs text-fg">{formatNumber(row.weekly_active)}</td>
              <td className="px-3 py-3">
                <PenetrationBar value={row.penetration} />
              </td>
              <td className="px-3 py-3 text-right text-xs text-fg-2">
                {formatPercent(row.weekly_active_penetration)}
              </td>
              <td className="px-3 py-3 text-right text-xs text-fg-2">{formatNumber(row.events)}</td>
              <td className="px-3 py-3 text-right text-[10px] text-fg-3">{formatTimestamp(row.last_used_at)}</td>
            </tr>
          ))}
          {segment.features.length === 0 && (
            <tr>
              <td colSpan={8} className="px-5 py-8 text-center text-sm text-fg-3">
                No registry feature matches this search.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminProduct() {
  const [days, setDays] = useState<number>(30)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [applied, setApplied] = useState<{ days: number; from: string; to: string }>({
    days: 30,
    from: '',
    to: '',
  })
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [dimension, setDimension] = useState<AdminFeatureAdoptionDimension>('plan')
  const [segmentKey, setSegmentKey] = useState<string | null>(null)
  const [data, setData] = useState<AdminFeatureAdoptionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [query])

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminFeatureAdoption({
        days: applied.days,
        start_date: applied.from || undefined,
        end_date: applied.to || undefined,
        feature: debouncedQuery || undefined,
      })
      if (generation === requestGeneration.current) setData(next)
    } catch (err) {
      if (generation === requestGeneration.current) {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      if (generation === requestGeneration.current) setLoading(false)
    }
  }, [applied, debouncedQuery])

  useEffect(() => {
    void load()
  }, [load])

  const dimensionSegments = useMemo(
    () => (data?.segments ?? []).filter((segment) => segment.dimension === dimension),
    [data, dimension],
  )
  const selectedSegment = useMemo(() => {
    if (!dimensionSegments.length) return null
    return dimensionSegments.find((segment) => segment.key === segmentKey) ?? dimensionSegments[0]
  }, [dimensionSegments, segmentKey])

  const suppressed = data?.suppressed_segments ?? { plan: 0, role: 0, cohort: 0 }
  const suppressedTotal = suppressed.plan + suppressed.role + suppressed.cohort
  const featureSearchApplied = Boolean(data?.filters.feature)
  const visibleFeatureCount = data?.visible_feature_count ?? 0
  const featureCount = data?.feature_count ?? 0

  const applyPreset = (range: number) => {
    setDays(range)
    setFrom('')
    setTo('')
    setApplied({ days: range, from: '', to: '' })
  }

  return (
    <div className="space-y-5">
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">Feature adoption matrix</h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Registry features by plan, account role and signup cohort. “Used at least once” is a distinct-user
              count in the selected range; “weekly active” is a distinct-user count in the final seven days.
              Denominators are segment users. Aggregate counts only — never event metadata, document text, or
              entitlement grants.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
            {data ? `${data.start_date} → ${data.end_date} · UTC` : 'Loading window…'}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div role="group" aria-label="Feature adoption date range" className="flex flex-wrap gap-1">
            {RANGES.map((range) => {
              const active = !applied.from && !applied.to && applied.days === range
              return (
                <button
                  key={range}
                  type="button"
                  aria-pressed={active}
                  onClick={() => applyPreset(range)}
                  className={`min-h-[36px] rounded border px-3 py-1.5 text-xs font-medium ${
                    active ? 'border-accent text-accent-strong' : 'border-line text-fg-2 hover:bg-surface-2'
                  }`}
                >
                  {range}d
                </button>
              )
            })}
          </div>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            From
            <input
              type="date"
              aria-label="Feature adoption start date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            To
            <input
              type="date"
              aria-label="Feature adoption end date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
              className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            />
          </label>
          <button
            type="button"
            onClick={() => setApplied({ days, from, to })}
            disabled={loading}
            className="min-h-[36px] rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            {loading ? 'Loading…' : 'Apply range'}
          </button>
          <label className="min-w-[220px] flex-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            Feature search
            <input
              type="search"
              aria-label="Search registry features"
              placeholder="Compile, ATS, integration…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="mt-1 block w-full min-h-[36px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            />
          </label>
        </div>

        {error && (
          <p role="alert" className="mt-3 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err">
            {error}
          </p>
        )}
      </div>

      {data && (
        <>
          <div className="grid gap-px border-b border-line bg-line sm:grid-cols-2 lg:grid-cols-5">
            <SummaryCard
              label="Audience"
              value={formatNumber(data.reconciliation.audience_users)}
              detail="users in the selected population"
            />
            <SummaryCard
              label="Usage events"
              value={formatNumber(data.reconciliation.usage_events)}
              detail="rows in usage_analytics"
            />
            <SummaryCard
              label="Matrix events"
              value={formatNumber(data.reconciliation.matrix_events)}
              detail={`${data.reconciliation.matched_rate.toFixed(1)}% mapped to registry features`}
            />
            <SummaryCard
              label="Features used"
              value={`${formatNumber(data.reconciliation.features_with_usage)} / ${formatNumber(featureCount)}`}
              detail="registry features with at least one event"
            />
            <SummaryCard
              label="Hidden segments"
              value={formatNumber(suppressedTotal)}
              detail={`below ${data.minimum_segment_size} users`}
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="Feature adoption segment dimension">
              {DIMENSIONS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={dimension === item.id}
                  onClick={() => {
                    setDimension(item.id)
                    setSegmentKey(null)
                  }}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium ${
                    dimension === item.id
                      ? 'border-accent text-accent-strong'
                      : 'border-line text-fg-3 hover:bg-surface-2'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-fg-3">
              {featureSearchApplied
                ? `${formatNumber(visibleFeatureCount)} of ${formatNumber(featureCount)} registry features match “${data.filters.feature}”.`
                : `All ${formatNumber(featureCount)} registry features are listed for every visible segment.`}
            </p>
          </div>

          {dimensionSegments.length > 0 ? (
            <>
              <div className="flex flex-wrap gap-1 border-b border-line px-5 py-3" role="tablist" aria-label="Feature adoption segment">
                {dimensionSegments.map((segment) => (
                  <button
                    key={segment.key}
                    type="button"
                    role="tab"
                    aria-selected={selectedSegment?.key === segment.key}
                    onClick={() => setSegmentKey(segment.key)}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${
                      selectedSegment?.key === segment.key
                        ? 'border-accent bg-accent-soft text-accent-strong'
                        : 'border-line text-fg-3 hover:bg-surface-2'
                    }`}
                  >
                    {segment.label}
                    <span className="ml-1.5 text-[10px] opacity-70">{formatNumber(segment.denominator)} users</span>
                  </button>
                ))}
              </div>
              {selectedSegment ? (
                <SegmentMatrix segment={selectedSegment} />
              ) : null}
            </>
          ) : (
            <div className="px-5 py-10 text-center text-sm text-fg-3">
              {data.suppressed
                ? `All selected segments have fewer than ${data.minimum_segment_size} users, so their counts are hidden.`
                : `No ${DIMENSIONS.find((item) => item.id === dimension)?.label.toLowerCase()} segment has at least ${data.minimum_segment_size} users in this selection.`}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-[10px] text-fg-3">
            <span>
              Used at least once / weekly active are distinct users. Penetration = used ÷ segment denominator.
              {suppressedTotal > 0 ? ` ${suppressedTotal} segment${suppressedTotal === 1 ? '' : 's'} hidden (<${data.minimum_segment_size} users).` : ''}
            </span>
            <span>Source: usage_analytics · no entitlement grants counted as usage</span>
          </div>
        </>
      )}

      {!data && error && (
        <div className="px-5 py-10 text-center text-sm text-fg-3">
          Feature adoption is unavailable. Adjust the range or retry.
        </div>
      )}
      {!data && !error && (
        <div role="status" className="px-5 py-10 text-center text-sm text-fg-3">
          Loading feature adoption…
        </div>
      )}
    </section>
    <AdminEditorModeUsage />
    </div>
  )
}
