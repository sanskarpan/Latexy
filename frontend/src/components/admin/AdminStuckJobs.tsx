'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  apiClient,
  type AdminStuckJobAction,
  type AdminStuckJobActionResponse,
  type AdminStuckJobItem,
  type AdminStuckJobList,
} from '@/lib/api-client'

const ACTION_LABEL: Record<AdminStuckJobAction, string> = {
  retry: 'Retry',
  cancel: 'Cancel',
  fence: 'Fence',
}

const ACTION_HELP: Record<AdminStuckJobAction, string> = {
  retry: 'Fence the stuck original and dispatch one linked replacement job.',
  cancel: 'Durably cancel the job so no worker can publish a late success.',
  fence: 'Fence the stale worker and leave a non-revivable failed tombstone.',
}

const STATUS_TONE: Record<string, string> = {
  queued: 'border-warn/30 bg-warn/10 text-warn',
  pending: 'border-warn/30 bg-warn/10 text-warn',
  processing: 'border-accent/30 bg-accent-soft text-accent-strong',
  running: 'border-accent/30 bg-accent-soft text-accent-strong',
  committing: 'border-accent/30 bg-accent-soft text-accent-strong',
  completed: 'border-ok/30 bg-ok/10 text-ok',
  failed: 'border-err/30 bg-err/10 text-err',
  cancelled: 'border-line bg-surface-2 text-fg-3',
  fenced: 'border-err/30 bg-err/10 text-err',
}

function isMissingEndpoint(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /^HTTP 404\b/.test(message)
}

function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'unknown age'
  const value = Math.max(0, Math.round(seconds))
  if (value < 60) return `${value}s`
  const minutes = Math.floor(value / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

function shortId(value: string | null | undefined): string {
  if (!value) return '—'
  return value.length > 12 ? `${value.slice(0, 8)}…` : value
}

function statusTone(status: string): string {
  return STATUS_TONE[status] ?? 'border-line bg-surface-2 text-fg-2'
}

function ActionPanel({
  job,
  action,
  onClose,
  onDone,
}: {
  job: AdminStuckJobItem
  action: AdminStuckJobAction
  onClose: () => void
  onDone: (result: AdminStuckJobActionResponse) => void
}) {
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Stable for this confirmation panel so a double-click cannot create a
  // second replacement job or a second audit row.
  const [idempotencyKey] = useState(
    () => `${action}-${job.job_id}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  )

  const submit = async () => {
    if (busy || reason.trim().length < 3 || !confirmed) return
    setBusy(true)
    setError(null)
    try {
      const body = {
        reason: reason.trim(),
        confirm: true as const,
        idempotency_key: idempotencyKey,
      }
      const result =
        action === 'retry'
          ? await apiClient.retryAdminStuckJob(job.job_id, body)
          : action === 'cancel'
            ? await apiClient.cancelAdminStuckJob(job.job_id, body)
            : await apiClient.fenceAdminStuckJob(job.job_id, body)
      onDone(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : `${ACTION_LABEL[action]} failed`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/5 p-3">
      <p className="text-xs font-semibold text-fg">
        Confirm {ACTION_LABEL[action].toLowerCase()} for {shortId(job.job_id)}
      </p>
      <p className="mt-1 text-[11px] text-fg-3">{ACTION_HELP[action]}</p>
      <label className="mt-3 block text-[11px] font-medium text-fg-2">
        Reason (required)
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          minLength={3}
          maxLength={1000}
          rows={2}
          className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
          placeholder="Why is this job being remediated?"
        />
      </label>
      <label className="mt-2 flex items-start gap-2 text-[11px] text-fg-2">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
          className="mt-0.5"
        />
        <span>
          I confirm this action is audited against my admin account and that no automatic retry or
          cancellation will occur.
        </span>
      </label>
      {error && (
        <p role="alert" className="mt-2 text-[11px] text-err">
          {error}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || reason.trim().length < 3 || !confirmed}
          onClick={() => void submit()}
          className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40"
        >
          {busy ? 'Applying…' : `Confirm ${ACTION_LABEL[action].toLowerCase()}`}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
        >
          Close
        </button>
      </div>
    </div>
  )
}

function StuckJobCard({
  job,
  selectedAction,
  onSelect,
  onClose,
  onDone,
}: {
  job: AdminStuckJobItem
  selectedAction: AdminStuckJobAction | null
  onSelect: (action: AdminStuckJobAction) => void
  onClose: () => void
  onDone: (result: AdminStuckJobActionResponse) => void
}) {
  const actions = job.recommended_actions ?? []
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${statusTone(job.status)}`}>
              {job.status}
            </span>
            <span className="font-mono text-xs font-semibold text-fg" title={job.job_id}>
              {shortId(job.job_id)}
            </span>
            <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
              {job.job_type}
            </span>
            <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
              {job.queue} queue
            </span>
            {job.owner_kind === 'anonymous' && (
              <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
                anonymous
              </span>
            )}
            {job.terminal && (
              <span className="rounded-full border border-err/30 bg-err/10 px-2 py-0.5 text-[10px] font-medium text-err">
                terminal
              </span>
            )}
          </div>
          <p className="mt-2 text-xs leading-relaxed text-fg-2">{job.reason}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-3">
            <span>Age {formatAge(job.age_seconds)}</span>
            <span>Heartbeat {formatAge(job.heartbeat_age_seconds)}</span>
            <span>Worker {job.worker ?? 'unclaimed'}</span>
            <span>
              Lease{' '}
              {job.lease_expires_at
                ? job.lease_active
                  ? `active until ${new Date(job.lease_expires_at).toLocaleTimeString()}`
                  : `expired ${formatAge(job.heartbeat_age_seconds)} ago`
                : 'none'}
            </span>
            <span title={job.owner_user_id ?? undefined}>Owner {shortId(job.owner_user_id)}</span>
            <span>Stage {job.stage ?? job.status}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <button
              key={action}
              type="button"
              disabled={action === 'retry' && !job.retry_supported}
              title={
                action === 'retry' && !job.retry_supported
                  ? 'This job family does not persist enough input to be re-dispatched safely.'
                  : ACTION_HELP[action]
              }
              onClick={() => onSelect(action)}
              className={`rounded-[var(--radius-md)] border px-2.5 py-1.5 text-[11px] font-medium disabled:cursor-not-allowed disabled:opacity-40 ${
                action === 'retry'
                  ? 'border-accent/40 bg-accent-soft text-accent-strong hover:brightness-110'
                  : action === 'cancel'
                    ? 'border-line text-fg-2 hover:bg-surface-2'
                    : 'border-warn/30 bg-warn/10 text-warn hover:brightness-110'
              }`}
            >
              {ACTION_LABEL[action]}
            </button>
          ))}
          {actions.length === 0 && (
            <span className="text-[11px] text-fg-3">No safe remediation actions.</span>
          )}
        </div>
      </div>
      {selectedAction && (
        <ActionPanel
          key={`${job.job_id}-${selectedAction}`}
          job={job}
          action={selectedAction}
          onClose={onClose}
          onDone={onDone}
        />
      )}
    </div>
  )
}

export default function AdminStuckJobs({ refreshKey = 0 }: { refreshKey?: number }) {
  const [data, setData] = useState<AdminStuckJobList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)
  const [minAge, setMinAge] = useState(15)
  const [selected, setSelected] = useState<{ jobId: string; action: AdminStuckJobAction } | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setUnavailable(false)
    try {
      setData(await apiClient.getAdminStuckJobs({ min_age_minutes: minAge, limit: 50 }))
    } catch (err) {
      if (isMissingEndpoint(err)) {
        setUnavailable(true)
      } else {
        setError(err instanceof Error ? err.message : 'Stuck jobs could not be loaded')
      }
    } finally {
      setLoading(false)
    }
  }, [minAge])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  if (unavailable) return null

  const onDone = (result: AdminStuckJobActionResponse) => {
    setSelected(null)
    const verb = result.action === 'retry' ? 'Retry' : result.action === 'cancel' ? 'Cancellation' : 'Fence'
    if (result.changed) {
      setNotice(
        result.new_job_id
          ? `${verb} recorded. Replacement job ${shortId(result.new_job_id)} is linked in the audit log.`
          : `${verb} recorded and audited.`,
      )
    } else {
      setNotice(`${verb} was already applied; no second audit row was written.`)
    }
    void load()
  }

  return (
    <section
      id="admin-stuck-jobs"
      aria-labelledby="admin-stuck-jobs-heading"
      className="rounded-[var(--radius-lg)] border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="admin-stuck-jobs-heading" className="text-sm font-semibold text-fg">
            Stuck job diagnosis
          </h3>
          <p className="mt-1 text-xs text-fg-3">
            Queued, processing and stale jobs with durable lease/worker context. Retry fences and
            requeues into a linked replacement, cancel is durable, and fence leaves a non-revivable
            tombstone. Every action requires a reason and confirmation; nothing runs automatically.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            <span className="mb-1 block">Stale after</span>
            <select
              aria-label="Minimum stale age"
              value={minAge}
              onChange={(event) => setMinAge(Number(event.target.value))}
              className="block min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            >
              <option value={5}>5 minutes</option>
              <option value={15}>15 minutes</option>
              <option value={30}>30 minutes</option>
              <option value={60}>1 hour</option>
            </select>
          </label>
          {data && (
            <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              {data.total} stuck
            </span>
          )}
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {notice && (
        <div role="status" className="mt-3 rounded-[var(--radius-md)] border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok">
          {notice}
        </div>
      )}
      {loading && !data && <p role="status" className="mt-4 text-xs text-fg-3">Loading stuck jobs…</p>}
      {error && (
        <div role="alert" className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          {error}
          {data ? ' Showing the last successful data.' : ''}
        </div>
      )}

      {data && data.items.length === 0 && !error && (
        <p className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-3 text-xs text-fg-3">
          No queued, processing or stale jobs older than {data.min_age_minutes} minutes.
        </p>
      )}

      {data && data.items.length > 0 && (
        <div className="mt-4 space-y-2">
          {data.items.map((job) => (
            <StuckJobCard
              key={job.job_id}
              job={job}
              selectedAction={selected?.jobId === job.job_id ? selected.action : null}
              onSelect={(action) => {
                setNotice(null)
                setSelected({ jobId: job.job_id, action })
              }}
              onClose={() => setSelected(null)}
              onDone={onDone}
            />
          ))}
        </div>
      )}
      {data && data.truncated && (
        <p className="mt-3 text-[11px] text-fg-3">
          Showing the first {data.items.length} of {data.total} stuck jobs. Narrow by stale age or
          resolve the oldest entries first.
        </p>
      )}
    </section>
  )
}
