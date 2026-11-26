'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  apiClient,
  type AdminAiLatencyRetryBucket,
  type AdminAiLatencyRetryResponse,
} from '@/lib/api-client'
import { formatNumber } from '@/components/admin/admin-format'

const DIMENSIONS = [
  { key: 'provider', label: 'Provider', bucketKey: 'by_provider' },
  { key: 'model', label: 'Model', bucketKey: 'by_model' },
  { key: 'feature', label: 'Feature', bucketKey: 'by_feature' },
  { key: 'plan', label: 'Plan', bucketKey: 'by_plan' },
] as const

const PLAN_OPTIONS = ['free', 'basic', 'pro', 'byok', 'team']
const PROVIDER_OPTIONS = ['openai', 'anthropic', 'gemini', 'openrouter']

type DimensionKey = (typeof DIMENSIONS)[number]['key']
type DimensionBucketKey = (typeof DIMENSIONS)[number]['bucketKey']

function formatMs(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`
  return `${Math.round(value)}ms`
}

function formatPct(value: number | null | undefined): string {
  return `${Number.isFinite(value ?? NaN) ? Number(value).toFixed(1) : '0.0'}%`
}

function formatId(value: string): string {
  return value.length > 32 ? `${value.slice(0, 20)}…${value.slice(-6)}` : value
}

function SparseBadge() {
  return (
    <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warn">
      Sparse
    </span>
  )
}

export default function AdminAiLatencyRetry({ days }: { days: number }) {
  const [dimension, setDimension] = useState<DimensionKey>('provider')
  const [plan, setPlan] = useState('')
  const [provider, setProvider] = useState('')
  const [modelInput, setModelInput] = useState('')
  const [model, setModel] = useState('')
  const [featureInput, setFeatureInput] = useState('')
  const [feature, setFeature] = useState('')
  const [data, setData] = useState<AdminAiLatencyRetryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminAiLatencyRetry({
        days,
        plan: plan || undefined,
        provider: provider || undefined,
        model: model || undefined,
        feature: feature || undefined,
      })
      if (requestGeneration.current === generation) setData(next)
    } catch (err) {
      if (requestGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load AI latency and retries')
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false)
    }
  }, [days, feature, model, plan, provider])

  useEffect(() => {
    void load()
    return () => {
      requestGeneration.current += 1
    }
  }, [load])

  const dimensionConfig = DIMENSIONS.find(entry => entry.key === dimension) ?? DIMENSIONS[0]
  const buckets = (data?.[dimensionConfig.bucketKey as DimensionBucketKey] ??
    []) as AdminAiLatencyRetryBucket[]
  const cardinality = data?.cardinality[dimension]
  const hasFilters = Boolean(plan || provider || model || feature)

  const statusSummary = useMemo(() => {
    if (!data) return []
    return [
      { label: 'Success', value: data.overall.successes, tone: 'text-ok' },
      { label: 'Error', value: data.overall.errors, tone: 'text-err' },
      { label: 'Timeout', value: data.overall.timeouts, tone: 'text-warn' },
      { label: 'Cancelled', value: data.overall.cancelled, tone: 'text-fg-3' },
    ]
  }, [data])

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-fg">AI latency and retry rate</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            p50/p95/p99 provider-call latency, retry rate and timeout/error rate for the
            selected period. Every attempt is counted once; grouped totals reconcile to the
            raw attempt count. Only aggregate dimensions are stored — never prompts,
            documents or raw provider errors.
          </p>
        </div>
        <div
          className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
          role="group"
          aria-label="AI latency dimension"
        >
          {DIMENSIONS.map(entry => (
            <button
              key={entry.key}
              type="button"
              aria-pressed={dimension === entry.key}
              onClick={() => setDimension(entry.key)}
              className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                dimension === entry.key
                  ? 'bg-accent-soft text-accent-strong'
                  : 'text-fg-3 hover:text-fg'
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
          Plan
          <select
            value={plan}
            onChange={event => setPlan(event.target.value)}
            className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
          >
            <option value="">All plans</option>
            {PLAN_OPTIONS.map(value => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
          Provider
          <select
            value={provider}
            onChange={event => setProvider(event.target.value)}
            className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
          >
            <option value="">All providers</option>
            {PROVIDER_OPTIONS.map(value => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <form
          className="flex items-end gap-2"
          onSubmit={event => {
            event.preventDefault()
            setModel(modelInput.trim().toLowerCase())
            setFeature(featureInput.trim().toLowerCase())
          }}
        >
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            Model
            <input
              value={modelInput}
              onChange={event => setModelInput(event.target.value)}
              placeholder="gpt-4o-mini"
              className="mt-1 block w-40 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg placeholder:text-fg-3"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            Feature
            <input
              value={featureInput}
              onChange={event => setFeatureInput(event.target.value)}
              placeholder="resume_optimization"
              className="mt-1 block w-48 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg placeholder:text-fg-3"
            />
          </label>
          <button
            type="submit"
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Apply
          </button>
        </form>
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setPlan('')
              setProvider('')
              setModel('')
              setModelInput('')
              setFeature('')
              setFeatureInput('')
            }}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Clear filters
          </button>
        )}
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="ml-auto rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
        >
          {data ? 'Showing the last successful data. ' : ''}
          Refresh failed: {error}
        </div>
      )}

      {!data && loading ? (
        <div role="status" className="mt-6 text-center text-xs text-fg-3">
          Loading AI latency…
        </div>
      ) : data ? (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: 'p50 latency', value: formatMs(data.overall.p50_ms) },
              { label: 'p95 latency', value: formatMs(data.overall.p95_ms) },
              { label: 'p99 latency', value: formatMs(data.overall.p99_ms) },
              { label: 'Retry rate', value: formatPct(data.overall.retry_rate_pct) },
            ].map(metric => (
              <div
                key={metric.label}
                className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2"
              >
                <p className="text-[10px] uppercase tracking-wider text-fg-3">
                  {metric.label}
                </p>
                <p className="mt-0.5 text-lg font-semibold tabular-nums text-fg">
                  {metric.value}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: 'Timeout rate', value: formatPct(data.overall.timeout_rate_pct) },
              { label: 'Error rate', value: formatPct(data.overall.error_rate_pct) },
              {
                label: 'Attempts',
                value: `${formatNumber(data.overall.attempts)} · ${formatNumber(data.overall.runs)} runs`,
              },
              {
                label: 'First-attempt success',
                value: formatPct(data.overall.first_attempt_success_rate_pct),
              },
            ].map(metric => (
              <div
                key={metric.label}
                className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2"
              >
                <p className="text-[10px] uppercase tracking-wider text-fg-3">
                  {metric.label}
                </p>
                <p className="mt-0.5 text-sm font-semibold tabular-nums text-fg">
                  {metric.value}
                </p>
              </div>
            ))}
          </div>

          {data.overall.attempts === 0 ? (
            <div className="mt-4 rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
              No LLM attempts recorded for these filters yet.
            </div>
          ) : (
            <>
              <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div className="overflow-x-auto">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                    {dimensionConfig.label} breakdown
                  </h4>
                  <table className="mt-3 w-full min-w-[520px] border-collapse text-left text-xs">
                    <caption className="sr-only">
                      LLM latency and retries by {dimensionConfig.label.toLowerCase()}
                    </caption>
                    <thead>
                      <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                        <th scope="col" className="py-2 pr-3 font-semibold">
                          {dimensionConfig.label}
                        </th>
                        <th scope="col" className="px-2 py-2 text-right font-semibold">
                          Attempts
                        </th>
                        <th scope="col" className="px-2 py-2 text-right font-semibold">
                          p50
                        </th>
                        <th scope="col" className="px-2 py-2 text-right font-semibold">
                          p95
                        </th>
                        <th scope="col" className="px-2 py-2 text-right font-semibold">
                          p99
                        </th>
                        <th scope="col" className="px-2 py-2 text-right font-semibold">
                          Retry
                        </th>
                        <th scope="col" className="pl-2 py-2 text-right font-semibold">
                          Timeout
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {buckets.length === 0 && (
                        <tr>
                          <td colSpan={7} className="py-6 text-center text-fg-3">
                            No {dimensionConfig.label.toLowerCase()} buckets match these filters.
                          </td>
                        </tr>
                      )}
                      {buckets.map(bucket => (
                        <tr key={`${bucket.dimension}:${bucket.value}`} className="border-t border-line">
                          <td className="py-2 pr-3">
                            <span
                              className="block max-w-[220px] truncate font-mono text-[11px] text-fg"
                              title={bucket.value}
                            >
                              {formatId(bucket.label)}
                            </span>
                            {bucket.sparse && <SparseBadge />}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                            {formatNumber(bucket.attempts)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                            {formatMs(bucket.p50_ms)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                            {formatMs(bucket.p95_ms)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                            {formatMs(bucket.p99_ms)}
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums text-fg-2">
                            {formatPct(bucket.retry_rate_pct)}
                          </td>
                          <td className="pl-2 py-2 text-right tabular-nums text-fg-2">
                            {formatPct(bucket.timeout_rate_pct)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {cardinality?.truncated && (
                    <p className="mt-2 text-[11px] text-fg-3">
                      Showing the {formatNumber(cardinality.returned_groups)} busiest of{' '}
                      {formatNumber(cardinality.groups)} groups;{' '}
                      {formatNumber(cardinality.truncated_attempts)} attempts are counted in
                      totals but omitted from this table.
                    </p>
                  )}
                </div>

                <div className="space-y-4">
                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                      Outcomes
                    </h4>
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      {statusSummary.map(item => (
                        <div
                          key={item.label}
                          className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2"
                        >
                          <p className="text-[10px] uppercase tracking-wider text-fg-3">
                            {item.label}
                          </p>
                          <p className={`mt-0.5 text-sm font-semibold tabular-nums ${item.tone}`}>
                            {formatNumber(item.value)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                      Retry reasons
                    </h4>
                    {data.retry_reasons.length === 0 ? (
                      <p className="mt-2 text-[11px] text-fg-3">
                        No retries in this period.
                      </p>
                    ) : (
                      <ul className="mt-2 space-y-1.5">
                        {data.retry_reasons.map(reason => (
                          <li
                            key={reason.reason}
                            className="flex items-center justify-between gap-3 text-xs"
                          >
                            <span className="text-fg-2">{reason.label}</span>
                            <span className="tabular-nums text-fg-3">
                              {formatNumber(reason.attempts)} · {formatPct(reason.share_pct)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-4 border-t border-line pt-3 text-[11px] text-fg-3">
                <p>
                  Reconciliation: {formatNumber(data.reconciliation.total_attempts)} attempts ·{' '}
                  {formatNumber(data.reconciliation.retry_reason_attempts)} retry reasons ·{' '}
                  {formatNumber(data.reconciliation.status_attempts)} statuses
                  {data.reconciliation.all_dimensions_reconcile &&
                  data.reconciliation.retry_reasons_reconcile &&
                  data.reconciliation.statuses_reconcile
                    ? ' — all dimensions reconcile.'
                    : ' — see truncated groups above.'}
                </p>
                <p className="mt-1">
                  Missing attribution: {formatNumber(data.missing_dimensions.provider)} provider,{' '}
                  {formatNumber(data.missing_dimensions.model)} model,{' '}
                  {formatNumber(data.missing_dimensions.feature)} feature,{' '}
                  {formatNumber(data.missing_dimensions.plan)} plan. Groups below{' '}
                  {formatNumber(data.sparse_threshold)} attempts stay visible but are marked
                  sparse; the ledger stores no user dimension.
                </p>
              </div>
            </>
          )}
        </>
      ) : null}
    </section>
  )
}
