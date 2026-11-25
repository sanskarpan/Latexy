'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  apiClient,
  type AdminOperationsHealthResponse,
  type AdminOperationsStatus,
  type AdminWorkerHealthComponent,
  type AdminWorkerProviderLink,
} from '@/lib/api-client'

const STATUS_TONE: Record<AdminOperationsStatus, string> = {
  healthy: 'border-ok/30 bg-ok/10 text-ok',
  degraded: 'border-warn/30 bg-warn/10 text-warn',
  unhealthy: 'border-err/30 bg-err/10 text-err',
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

const WORKER_KIND_LABEL: Record<string, string> = {
  celery: 'Celery worker',
  modal: 'Modal container',
}

const DEFAULT_PROVIDER_LINKS: AdminWorkerProviderLink[] = [
  { name: 'Modal', console_url: 'https://modal.com/apps' },
  { name: 'Upstash Redis', console_url: 'https://console.upstash.com' },
  { name: 'Neon Postgres', console_url: 'https://console.neon.tech' },
  { name: 'Cloudflare R2', console_url: 'https://dash.cloudflare.com' },
]

function isMissingEndpoint(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /^HTTP 404\b/.test(message)
}

function formatAge(iso: string | null | undefined): string {
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

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'missing'
  return `${value.toFixed(1)}%`
}

function formatMemory(component: AdminWorkerHealthComponent): string {
  const percent = formatPercent(component.memory_percent)
  if (component.memory_mb == null || !Number.isFinite(component.memory_mb)) {
    return percent
  }
  return `${percent} · ${component.memory_mb.toFixed(1)} MB`
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

function ProviderLinks({ providers }: { providers: AdminWorkerProviderLink[] }) {
  if (providers.length === 0) return null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
        Provider consoles
      </span>
      {providers.map((provider) => (
        <a
          key={`${provider.name}:${provider.console_url}`}
          href={provider.console_url}
          target="_blank"
          rel="noreferrer"
          className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-fg-2 hover:border-line-2 hover:text-fg"
        >
          {provider.name} ↗
        </a>
      ))}
    </div>
  )
}

function WorkerCard({ component, staleAfter }: { component: AdminWorkerHealthComponent; staleAfter: number }) {
  const stale = component.age_seconds > staleAfter || component.status === 'unhealthy'
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-xs font-semibold text-fg" title={component.worker_id}>
            {component.worker_id}
          </p>
          <p className="text-[10px] text-fg-3">{WORKER_KIND_LABEL[component.kind] ?? component.kind}</p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${statusClass(component.status)}`}>
          {component.status}
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
        <div>
          <dt className="text-fg-3">Last seen</dt>
          <dd className={`font-semibold tabular-nums ${stale ? 'text-err' : 'text-fg'}`}>
            {formatAge(component.last_seen)}
          </dd>
        </div>
        <div>
          <dt className="text-fg-3">CPU</dt>
          <dd className="font-semibold tabular-nums text-fg">{formatPercent(component.cpu_percent)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Memory</dt>
          <dd className="font-semibold tabular-nums text-fg">{formatMemory(component)}</dd>
        </div>
        <div>
          <dt className="text-fg-3">Queues</dt>
          <dd className="font-semibold text-fg">
            {component.queues.length > 0 ? component.queues.join(', ') : 'none reported'}
          </dd>
        </div>
      </dl>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {stale && (
          <span className="rounded-full border border-err/30 bg-err/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-err">
            stale
          </span>
        )}
        {component.missing_metrics && (
          <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-warn">
            missing CPU/memory
          </span>
        )}
        {component.missing_queue_ownership && (
          <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-warn">
            no queue ownership
          </span>
        )}
      </div>
      <p className="mt-2 text-[10px] text-fg-3">
        Last seen {new Date(component.last_seen).toLocaleString()} · sample age {component.age_seconds}s
      </p>
    </div>
  )
}

export default function AdminOperationsHealth({ refreshKey = 0 }: { refreshKey?: number }) {
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
    .concat(Object.keys(sections).filter((key) => key !== 'workers' && !SECTION_ORDER.includes(key)))
  const workers = data?.workers
  const providers = workers?.providers?.length ? workers.providers : DEFAULT_PROVIDER_LINKS

  return (
    <details
      className="rounded-[var(--radius-lg)] border border-line bg-surface"
      open={data ? data.status !== 'healthy' : false}
    >
      <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div>
          <span className="text-sm font-semibold text-fg">System health</span>
          <span className="ml-2 text-xs text-fg-3">
            Dependencies, worker containers, queue ownership, billing and compile health
          </span>
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

        {workers && (
          <section aria-labelledby="admin-worker-health-heading" className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 id="admin-worker-health-heading" className="text-sm font-semibold text-fg">
                  Worker &amp; container health
                </h3>
                <p className="mt-1 text-xs text-fg-3">
                  Aggregate heartbeats with CPU, memory, last-seen and queue ownership. No host or container identifiers.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${statusClass(workers.status)}`}>
                  {workers.status}
                </span>
                <span className="rounded-full border border-line bg-surface px-2.5 py-1 text-[10px] font-medium text-fg-3">
                  Checked {formatAge(workers.last_check_at)}
                </span>
              </div>
            </div>

            {!workers.read_ok && (
              <div role="alert" className="mt-3 rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
                {workers.detail ?? 'Worker heartbeats could not be read'}
              </div>
            )}

            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
              <div className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-2">
                <p className="text-fg-3">Active</p>
                <p className="font-semibold tabular-nums text-fg">{workers.active_workers}</p>
              </div>
              <div className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-2">
                <p className="text-fg-3">Stale</p>
                <p className={`font-semibold tabular-nums ${workers.stale_workers > 0 ? 'text-err' : 'text-fg'}`}>
                  {workers.stale_workers}
                </p>
              </div>
              <div className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-2">
                <p className="text-fg-3">Missing metrics</p>
                <p className={`font-semibold tabular-nums ${workers.missing_metrics > 0 ? 'text-warn' : 'text-fg'}`}>
                  {workers.missing_metrics}
                </p>
              </div>
              <div className="rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-2">
                <p className="text-fg-3">Unowned queues</p>
                <p className={`font-semibold tabular-nums ${workers.unowned_queues.length > 0 ? 'text-warn' : 'text-fg'}`}>
                  {workers.unowned_queues.length}
                </p>
              </div>
            </div>

            {workers.detail && workers.read_ok && (
              <p className="mt-2 text-[11px] text-warn">{workers.detail}</p>
            )}

            {workers.read_ok && workers.components.length === 0 && (
              <p className="mt-3 rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg-3">
                No worker heartbeats have been received.
              </p>
            )}

            {workers.components.length > 0 && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {workers.components.map((component) => (
                  <WorkerCard
                    key={component.worker_id}
                    component={component}
                    staleAfter={workers.stale_after_seconds}
                  />
                ))}
              </div>
            )}

            {workers.unowned_queues.length > 0 && (
              <p className="mt-3 text-[11px] text-fg-3">
                <span className="font-medium text-warn">No active owner:</span>{' '}
                {workers.unowned_queues.join(', ')}
              </p>
            )}

            <ProviderLinks providers={providers} />

            <p className="mt-2 text-[10px] text-fg-3">
              Heartbeat TTL {workers.ttl_seconds}s · stale after {workers.stale_after_seconds}s · checked{' '}
              {new Date(workers.last_check_at).toLocaleString()}
            </p>
          </section>
        )}
      </div>
    </details>
  )
}
