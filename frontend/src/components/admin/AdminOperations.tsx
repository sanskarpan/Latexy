'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  apiClient,
  type AdminAlert,
  type AdminAlertList,
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

const SOURCE_LABEL: Record<string, string> = {
  'billing.webhooks': 'Billing webhooks',
  'billing.subscriptions': 'Subscriptions',
  'billing.payments': 'Payments',
  'jobs.stuck': 'Job queue',
  'domains.custom': 'Custom domains',
}

const METADATA_STATUS_LABEL: Record<string, string> = {
  complete: 'metadata complete',
  partial: 'metadata partial',
  unknown: 'metadata unknown',
}

const ALERT_SEVERITY_TONE: Record<AdminAlert['severity'], string> = {
  critical: 'border-err/30 bg-err/10 text-err',
  high: 'border-warn/30 bg-warn/10 text-warn',
  medium: 'border-accent/30 bg-accent-soft text-accent-strong',
  low: 'border-line bg-surface-2 text-fg-3',
}

const DEFAULT_ALERT_OWNERS = ['Billing', 'Growth', 'Platform']

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

function formatExpiry(iso: string | null | undefined, days: number | null | undefined): string {
  if (!iso) return 'expiry unknown'
  const parsed = new Date(iso)
  if (!Number.isFinite(parsed.getTime())) return 'expiry unknown'
  const when = parsed.toLocaleDateString()
  if (typeof days !== 'number') return when
  if (days < 0) return `${when} · overdue`
  if (days === 0) return `${when} · today`
  return `${when} · in ${days}d`
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

function AlertRow({ alert, onUpdated }: { alert: AdminAlert; onUpdated: () => void }) {
  const [mode, setMode] = useState<'acknowledge' | 'snooze' | null>(null)
  const [reason, setReason] = useState('')
  const [snoozeMinutes, setSnoozeMinutes] = useState(60)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (nextState: 'acknowledged' | 'snoozed') => {
    if (reason.trim().length < 3 || busy) return
    setBusy(true)
    setError(null)
    try {
      await apiClient.updateAdminAlert(alert.id, {
        state: nextState,
        reason: reason.trim(),
        ...(nextState === 'snoozed' ? { snooze_minutes: snoozeMinutes } : {}),
      })
      setMode(null)
      setReason('')
      onUpdated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Alert action failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${ALERT_SEVERITY_TONE[alert.severity]}`}>
              {alert.severity}
            </span>
            <span className="text-sm font-medium text-fg">{alert.title}</span>
            <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
              {alert.owner}
            </span>
            {alert.state !== 'open' && (
              <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
                {alert.state}
              </span>
            )}
          </div>
          <p className="mt-1 text-[11px] text-fg-3">
            Seen {alert.occurrence_count}× · last {formatAge(alert.last_seen_at)}
            {alert.snooze_until ? ` · snoozed until ${new Date(alert.snooze_until).toLocaleString()}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {alert.runbook_url && (
            <a
              href={alert.runbook_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-[var(--radius-md)] border border-line px-2.5 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2"
            >
              Runbook
            </a>
          )}
          <button
            type="button"
            onClick={() => { setMode(mode === 'acknowledge' ? null : 'acknowledge'); setError(null) }}
            className="rounded-[var(--radius-md)] border border-line px-2.5 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2"
          >
            Acknowledge
          </button>
          <button
            type="button"
            onClick={() => { setMode(mode === 'snooze' ? null : 'snooze'); setError(null) }}
            className="rounded-[var(--radius-md)] border border-line px-2.5 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2"
          >
            Snooze
          </button>
        </div>
      </div>

      {mode && (
        <div className="mt-3 space-y-2 border-t border-line pt-3">
          <label className="block text-[11px] text-fg-2">
            Reason
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              minLength={3}
              maxLength={1000}
              className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
              placeholder="Why is this alert being handled?"
            />
          </label>
          {mode === 'snooze' && (
            <label className="block text-[11px] text-fg-2">
              Snooze for
              <select
                value={snoozeMinutes}
                onChange={(event) => setSnoozeMinutes(Number(event.target.value))}
                className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
              >
                <option value={60}>1 hour</option>
                <option value={240}>4 hours</option>
                <option value={1440}>24 hours</option>
              </select>
            </label>
          )}
          {error && <p role="alert" className="text-[11px] text-err">{error}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy || reason.trim().length < 3}
              onClick={() => void submit(mode === 'snooze' ? 'snoozed' : 'acknowledged')}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40"
            >
              {busy ? 'Saving…' : mode === 'snooze' ? 'Snooze alert' : 'Acknowledge alert'}
            </button>
            <button
              type="button"
              onClick={() => setMode(null)}
              className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function AlertStrip({ refreshKey, onUpdated }: { refreshKey: number; onUpdated: () => void }) {
  const [data, setData] = useState<AdminAlertList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)
  const [owner, setOwner] = useState('')
  const [kind, setKind] = useState('')
  const [seenOwners, setSeenOwners] = useState<string[]>([])
  const [seenKinds, setSeenKinds] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setUnavailable(false)
    try {
      const result = await apiClient.getAdminAlerts({
        state: 'active',
        limit: 20,
        ...(owner ? { owner } : {}),
        ...(kind ? { kind } : {}),
      })
      setData(result)
      // Keep every owner/rule seen across loads so selecting one filter does
      // not erase the other selectable options. These are operational labels,
      // never user data.
      setSeenOwners((current) =>
        Array.from(new Set([...current, ...result.items.map((alert) => alert.owner)])).sort(),
      )
      setSeenKinds((current) =>
        Array.from(new Set([...current, ...result.items.map((alert) => alert.kind)])).sort(),
      )
    } catch (err) {
      if (isMissingEndpoint(err)) {
        setUnavailable(true)
      } else {
        setError(err instanceof Error ? err.message : 'Alerts could not be loaded')
      }
    } finally {
      setLoading(false)
    }
  }, [owner, kind])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  if (unavailable) return null

  const ownerOptions = Array.from(new Set([...DEFAULT_ALERT_OWNERS, ...seenOwners])).sort()
  const kindOptions = seenKinds

  return (
    <section aria-labelledby="admin-alerts-heading" className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="admin-alerts-heading" className="text-sm font-semibold text-fg">Active alerts</h3>
          <p className="mt-1 text-xs text-fg-3">
            Durable incidents with owner, acknowledgement and snooze. Nothing is paged or auto-actioned from this strip.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            <span className="mb-1 block">Source</span>
            <select
              aria-label="Filter alerts by source"
              value={owner}
              onChange={(event) => setOwner(event.target.value)}
              className="block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            >
              <option value="">All sources</option>
              {ownerOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            <span className="mb-1 block">Rule</span>
            <select
              aria-label="Filter alerts by rule"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              className="block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            >
              <option value="">All rules</option>
              {kindOptions.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
          </label>
          {data && (
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              {data.total} active
            </span>
          )}
        </div>
      </div>

      {loading && !data && <p role="status" className="mt-4 text-xs text-fg-3">Loading alerts…</p>}
      {error && (
        <div role="alert" className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          {error}
          {data ? ' Showing the last successful data.' : ''}
        </div>
      )}
      {data && data.items.length === 0 && !error && (
        <p className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-3 text-xs text-fg-3">
          No active alerts.
        </p>
      )}
      {data && data.items.length > 0 && (
        <div className="mt-4 space-y-2">
          {data.items.map((alert) => <AlertRow key={alert.id} alert={alert} onUpdated={onUpdated} />)}
        </div>
      )}
    </section>
  )
}

function AttentionRow({ item }: { item: AdminAttentionItem }) {
  const isDomain = item.key.startsWith('domains.')
  return (
    <a
      href={item.href}
      aria-label={`${item.title}. Open the filtered admin view.`}
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
          {item.metadata_status && item.metadata_status !== 'complete' && (
            <span className="rounded-full border border-warn/30 bg-warn/10 px-2 py-0.5 text-[10px] text-warn">
              {METADATA_STATUS_LABEL[item.metadata_status]}
            </span>
          )}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-fg-3">{item.detail}</p>
        {isDomain && (
          <p className="mt-1 text-[11px] text-fg-3">
            Next expiry: {formatExpiry(item.next_expiry_at, item.days_until_expiry)}
          </p>
        )}
        <p className="mt-1 text-[10px] font-medium text-accent-strong">Open filtered view →</p>
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
          No failed webhooks, past-due subscriptions, failed payments, stuck jobs or expiring custom domains are waiting.
        </p>
      )}

      {partialSources.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-line pt-3">
          {partialSources.map((source) => (
            <p key={source.key} className="text-[11px] text-fg-3">
              <span className="font-medium text-warn">{SOURCE_LABEL[source.key] ?? source.key}</span>
              {` · ${source.status}`}
              {source.metadata_status ? ` · ${METADATA_STATUS_LABEL[source.metadata_status] ?? source.metadata_status}` : ''}
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
      <AlertStrip refreshKey={refreshKey} onUpdated={() => setRefreshKey((value) => value + 1)} />
      <AttentionStrip refreshKey={refreshKey} />
      <HealthPanel refreshKey={refreshKey} />
    </div>
  )
}
