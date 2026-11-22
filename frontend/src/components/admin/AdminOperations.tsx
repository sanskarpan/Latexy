'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  apiClient,
  type AdminAttentionItem,
  type AdminAttentionResponse,
  type AdminOperationsHealthResponse,
  type AdminOperationsStatus,
} from '@/lib/api-client'

const STATUS_TONE: Record<AdminOperationsStatus, string> = {
  healthy: 'border-ok/30 bg-ok/10 text-ok',
  degraded: 'border-warn/30 bg-warn/10 text-warn',
  unhealthy: 'border-err/30 bg-err/10 text-err',
}

const SEVERITY_TONE: Record<AdminAttentionItem['severity'], string> = {
  critical: 'text-err',
  high: 'text-warn',
  low: 'text-fg-3',
}

const SEVERITY_LABEL: Record<AdminAttentionItem['severity'], string> = {
  critical: 'Critical',
  high: 'High',
  low: 'Low',
}

const SECTION_LABEL: Record<string, string> = {
  database: 'Database',
  redis: 'Redis',
  redis_cache: 'Redis cache',
  storage: 'Object storage',
  capacity: 'Redis capacity',
  job_queue: 'Job queue',
  billing: 'Billing',
  compilations: 'Compilations',
}

const SECTION_ORDER = [
  'database',
  'redis',
  'redis_cache',
  'storage',
  'capacity',
  'job_queue',
  'billing',
  'compilations',
]

function isMissingEndpoint(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /^HTTP 404\b/.test(message)
}

function formatAge(iso: string | null): string {
  if (!iso) return 'unknown age'
  const value = new Date(iso).getTime()
  if (!Number.isFinite(value)) return 'unknown age'
  const seconds = Math.max(0, Math.round((Date.now() - value) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function statusClass(status: AdminOperationsStatus): string {
  return STATUS_TONE[status] ?? STATUS_TONE.degraded
}

function metricText(section: Record<string, unknown>): string[] {
  const parts: string[] = []
  const number = (value: unknown): number | null =>
    typeof value === 'number' && Number.isFinite(value) ? value : null

  const queued = number(section.queued)
  const processing = number(section.processing)
  const stuck = number(section.stuck)
  if (queued !== null) parts.push(`${queued} queued`)
  if (processing !== null) parts.push(`${processing} processing`)
  if (stuck !== null) parts.push(`${stuck} stuck`)

  const failedWebhooks = number(section.failed_webhooks)
  const failedPayments = number(section.failed_payments)
  const pastDue = number(section.past_due_subscriptions)
  if (failedWebhooks !== null) parts.push(`${failedWebhooks} webhook failures`)
  if (failedPayments !== null) parts.push(`${failedPayments} failed payments`)
  if (pastDue !== null) parts.push(`${pastDue} past due`)

  const completed = number(section.completed_24h)
  const failed = number(section.failed_24h)
  const failureRate = number(section.failure_rate)
  const p95 = number(section.p95_seconds)
  if (completed !== null) parts.push(`${completed} completed / 24h`)
  if (failed !== null) parts.push(`${failed} failed`)
  if (failureRate !== null) parts.push(`${failureRate.toFixed(1)}% failure rate`)
  if (p95 !== null) parts.push(`p95 ${p95.toFixed(1)}s`)

  const utilization = number(section.utilization_ratio)
  if (utilization !== null) parts.push(`${(utilization * 100).toFixed(1)}% capacity`)

  return parts
}

function AttentionRow({ item }: { item: AdminAttentionItem }) {
  return (
    <a
      href={item.href}
      className="flex flex-wrap items-start justify-between gap-3 rounded-[var(--radius-md)] border border-line bg-surface px-4 py-3 transition hover:border-line-2 hover:bg-surface-2"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-[10px] font-semibold uppercase tracking-wider ${SEVERITY_TONE[item.severity]}`}>
            {SEVERITY_LABEL[item.severity]}
          </span>
          <span className="text-sm font-medium text-fg">{item.title}</span>
          <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
            {item.owner}
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-fg-3">{item.detail}</p>
      </div>
      <div className="text-right">
        <p className="text-lg font-semibold text-fg">{item.count}</p>
        <p className="text-[10px] text-fg-3">{formatAge(item.oldest_at)}</p>
      </div>
    </a>
  )
}

function AttentionStrip({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<AdminAttentionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setUnavailable(false)
    try {
      setData(await apiClient.getAdminAttention())
    } catch (err) {
      if (isMissingEndpoint(err)) {
        setUnavailable(true)
      } else {
        setError(err instanceof Error ? err.message : 'Attention queue could not be loaded')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  if (unavailable) return null

  const partialSources = (data?.sources ?? []).filter((source) => source.status !== 'ok')

  return (
    <section aria-labelledby="admin-attention-heading" className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="admin-attention-heading" className="text-sm font-semibold text-fg">
            Needs attention
          </h3>
          <p className="mt-1 text-xs text-fg-3">
            Billing, queue and domain signals that need an operator within five minutes.
          </p>
        </div>
        {data && (
          <span
            className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${
              data.overall === 'attention'
                ? 'border-warn/30 bg-warn/10 text-warn'
                : 'border-ok/30 bg-ok/10 text-ok'
            }`}
          >
            {data.overall === 'attention' ? `${data.items.length} open` : 'All clear'}
          </span>
        )}
      </div>

      {loading && !data && <p role="status" className="mt-4 text-xs text-fg-3">Loading attention queue…</p>}
      {error && (
        <div role="alert" className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          {error}
          {data ? ' Showing the last successful data.' : ''}
        </div>
      )}

      {data && data.items.length > 0 && (
        <div className="mt-4 space-y-2">
          {data.items.map((item) => <AttentionRow key={item.key} item={item} />)}
        </div>
      )}
      {data && data.items.length === 0 && !error && (
        <p className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-3 text-xs text-fg-3">
          No failed webhooks, past-due subscriptions, failed payments or stuck jobs are waiting.
        </p>
      )}

      {partialSources.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-line pt-3">
          {partialSources.map((source) => (
            <p key={source.key} className="text-[11px] text-fg-3">
              <span className="font-medium text-warn">{source.key}</span>
              {source.detail ? ` · ${source.detail}` : ' · source unavailable'}
            </p>
          ))}
        </div>
      )}
    </section>
  )
}

function HealthPanel({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<AdminOperationsHealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setUnavailable(false)
    try {
      setData(await apiClient.getAdminOperationsHealth())
    } catch (err) {
      if (isMissingEndpoint(err)) {
        setUnavailable(true)
      } else {
        setError(err instanceof Error ? err.message : 'Operations health could not be loaded')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  if (unavailable) return null

  const sections = data?.sections ?? {}
  const ordered = SECTION_ORDER.filter((key) => key in sections)
    .concat(Object.keys(sections).filter((key) => !SECTION_ORDER.includes(key)))

  return (
    <details
      className="rounded-[var(--radius-lg)] border border-line bg-surface"
      open={data ? data.status !== 'healthy' : false}
    >
      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <span className="text-sm font-semibold text-fg">System health</span>
          <span className="ml-2 text-xs text-fg-3">Dependencies, queue age, billing and compile health</span>
        </div>
        {data && (
          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${statusClass(data.status)}`}>
            {data.status}
          </span>
        )}
      </summary>
      <div className="border-t border-line p-4">
        {loading && !data && <p role="status" className="text-xs text-fg-3">Checking dependencies…</p>}
        {error && (
          <div role="alert" className="mb-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            {error}
            {data ? ' Showing the last successful data.' : ''}
          </div>
        )}
        {data && (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {ordered.map((key) => {
              const section = sections[key]
              const metrics = metricText(section)
              return (
                <div key={key} className="rounded-[var(--radius-md)] border border-line bg-surface-2/50 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                      {SECTION_LABEL[key] ?? key}
                    </p>
                    <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase ${statusClass(section.status)}`}>
                      {section.status}
                    </span>
                  </div>
                  {metrics.length > 0 && (
                    <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{metrics.join(' · ')}</p>
                  )}
                  {section.detail && <p className="mt-1 text-[11px] text-fg-3">{section.detail}</p>}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </details>
  )
}

export default function AdminOperations() {
  const [refreshKey, setRefreshKey] = useState(0)
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setRefreshKey((value) => value + 1)}
          className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
        >
          Refresh operations
        </button>
      </div>
      <AttentionStrip refreshKey={refreshKey} />
      <HealthPanel refreshKey={refreshKey} />
    </div>
  )
}
