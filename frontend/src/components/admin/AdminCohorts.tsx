'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminCohort,
  type AdminCohortListResponse,
  type AdminCohortStatus,
} from '@/lib/api-client'

interface AdminFlagRow {
  key: string
  enabled: boolean
  label: string
  description: string | null
  updated_at: string | null
}

const STATUS_LABEL: Record<AdminCohortStatus, string> = {
  never_synced: 'Never synced',
  synced: 'Synced',
  stale: 'Stale',
  error: 'Sync error',
  below_minimum: 'Below minimum',
}

const STATUS_STYLE: Record<AdminCohortStatus, string> = {
  never_synced: 'border-line bg-surface-2 text-fg-3',
  synced: 'border-ok/30 bg-ok/10 text-ok',
  stale: 'border-warn/30 bg-warn/10 text-warn',
  error: 'border-danger/30 bg-danger/10 text-danger',
  below_minimum: 'border-warn/30 bg-warn/10 text-warn',
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString()
}

function parseMembers(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
}

function Stat({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/60 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-fg-3">{label}</p>
      <p className="mt-0.5 text-lg font-semibold text-fg">{value}</p>
      <p className="text-[11px] text-fg-3">{detail}</p>
    </div>
  )
}

function CohortCard({
  cohort,
  flags,
  reason,
  onChanged,
}: {
  cohort: AdminCohort
  flags: AdminFlagRow[]
  reason: string
  onChanged: () => Promise<void>
}) {
  const [flagKey, setFlagKey] = useState('')
  const [members, setMembers] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)

  const ready = reason.trim().length >= 3 && confirm

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (!ready) {
      toast.error('Enter a reason and tick the confirmation box first')
      return
    }
    setBusy(true)
    try {
      await action()
      toast.success(success)
      await onChanged()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      toast.error(message || 'The cohort action failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-fg">{cohort.name}</h3>
          <p className="mt-0.5 font-mono text-[11px] text-fg-3">{cohort.key}</p>
          {cohort.description ? (
            <p className="mt-1 text-xs text-fg-3">{cohort.description}</p>
          ) : null}
          {cohort.posthog_cohort_id ? (
            <p className="mt-1 text-[10px] text-fg-3">
              PostHog cohort <span className="font-mono">{cohort.posthog_cohort_id}</span>
              {cohort.tenant_slug ? ` · tenant ${cohort.tenant_slug}` : ' · platform scope'}
            </p>
          ) : null}
        </div>
        <span
          className={`rounded-full border px-2.5 py-1 text-[10px] font-medium ${STATUS_STYLE[cohort.status]}`}
        >
          {STATUS_LABEL[cohort.status]}
        </span>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <Stat
          label="Synced size"
          value={cohort.size == null ? 'Hidden' : cohort.size.toLocaleString()}
          detail={
            cohort.size_suppressed
              ? 'Suppressed under the five-user minimum'
              : `Minimum ${cohort.minimum_size}`
          }
        />
        <Stat
          label="Last successful sync"
          value={formatDate(cohort.last_synced_at)}
          detail={`Freshness window ${Math.round(cohort.stale_after_seconds / 3600)}h`}
        />
        <Stat
          label="Exposures (30d)"
          value={
            cohort.exposures_30d == null
              ? 'Hidden'
              : cohort.exposures_30d.toLocaleString()
          }
          detail="Consent-covered evaluations"
        />
      </div>

      {cohort.last_sync_error ? (
        <p
          role="status"
          className="mt-3 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger"
        >
          Last sync failed with code <span className="font-mono">{cohort.last_sync_error}</span>.
          Evaluation is fail-closed until a successful sync.
        </p>
      ) : null}
      {cohort.status === 'stale' ? (
        <p
          role="status"
          className="mt-3 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
        >
          Sync state is stale. Every mapped flag is disabled until the cohort is
          synced again.
        </p>
      ) : null}
      {cohort.status === 'below_minimum' ? (
        <p
          role="status"
          className="mt-3 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
        >
          This cohort is below the five-user minimum. Size is hidden and mapped
          flags never enable.
        </p>
      ) : null}

      <div className="mt-4">
        <p className="text-[10px] uppercase tracking-wider text-fg-3">Flags using this cohort</p>
        {cohort.flags.length === 0 ? (
          <p className="mt-1 text-xs text-fg-3">No flag mappings yet.</p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-2">
            {cohort.flags.map((flag) => (
              <li
                key={flag.key}
                className="flex items-center gap-2 rounded border border-line bg-surface-2/60 px-2 py-1 text-[11px] text-fg-2"
              >
                <span className="font-mono">{flag.key}</span>
                <span className="text-fg-3">{flag.enabled ? 'on' : 'off'}</span>
                <button
                  type="button"
                  aria-label={`Remove ${flag.key} from ${cohort.key}`}
                  className="text-fg-3 hover:text-danger disabled:opacity-50"
                  disabled={busy}
                  onClick={() =>
                    run(
                      () =>
                        apiClient.unmapAdminCohortFlag(
                          cohort.id,
                          flag.key,
                          reason.trim(),
                        ),
                      'Flag mapping removed',
                    )
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-3">
          <label className="block text-[10px] uppercase tracking-wider text-fg-3">
            Map a feature flag
            <select
              value={flagKey}
              onChange={(event) => setFlagKey(event.target.value)}
              className="mt-1 w-full rounded border border-line bg-bg px-2 py-2 text-xs text-fg"
            >
              <option value="">Select a flag…</option>
              {flags.map((flag) => (
                <option key={flag.key} value={flag.key}>
                  {flag.label} ({flag.key})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={busy || !flagKey}
            onClick={() =>
              run(
                () => apiClient.mapAdminCohortFlag(cohort.id, flagKey, reason.trim()),
                'Flag mapped to cohort',
              )
            }
            className="mt-2 rounded border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg disabled:opacity-50"
          >
            Map flag
          </button>
          <p className="mt-1 text-[10px] text-fg-3">
            A mapped public operational flag is fail-closed on the anonymous config
            surface; clients resolve treatment through the authenticated,
            consent-gated cohort evaluation route.
          </p>
        </div>

        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-3">
          <label className="block text-[10px] uppercase tracking-wider text-fg-3">
            Sync consent-filtered members
            <textarea
              value={members}
              onChange={(event) => setMembers(event.target.value)}
              rows={3}
              spellCheck={false}
              placeholder="Opaque account UUIDs, one per line or comma separated"
              className="mt-1 w-full rounded border border-line bg-bg px-2 py-2 font-mono text-[11px] text-fg"
            />
          </label>
          <p className="mt-1 text-[10px] text-fg-3">
            Members without a current first-party analytics grant are never treated or
            exposed. Sync status replaces the previous snapshot atomically.
          </p>
          <button
            type="button"
            disabled={busy || parseMembers(members).length === 0}
            onClick={() =>
              run(
                () =>
                  apiClient.syncAdminCohort(cohort.id, {
                    members: parseMembers(members),
                    reason: reason.trim(),
                    confirm: true,
                  }),
                'Cohort membership synced',
              )
            }
            className="mt-2 rounded border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg disabled:opacity-50"
          >
            Sync members
          </button>
        </div>
      </div>

      <label className="mt-3 flex items-center gap-2 text-[11px] text-fg-3">
        <input
          type="checkbox"
          checked={confirm}
          onChange={(event) => setConfirm(event.target.checked)}
        />
        I confirm these audited cohort changes.
      </label>
    </article>
  )
}

export default function AdminCohorts() {
  const [data, setData] = useState<AdminCohortListResponse | null>(null)
  const [flags, setFlags] = useState<AdminFlagRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [newCohort, setNewCohort] = useState({
    key: '',
    name: '',
    posthog_cohort_id: '',
    tenant_id: '',
    minimum_size: '5',
  })
  const generation = useRef(0)

  const load = useCallback(async () => {
    const requestGeneration = ++generation.current
    setLoading(true)
    try {
      const [cohorts, featureFlags] = await Promise.all([
        apiClient.getAdminCohorts(),
        apiClient.getAdminFeatureFlags(),
      ])
      if (requestGeneration !== generation.current) return
      setData(cohorts)
      setFlags(featureFlags)
      setError(null)
    } catch (loadError) {
      if (requestGeneration !== generation.current) return
      const message = loadError instanceof Error ? loadError.message : String(loadError)
      setError(message || 'Failed to load cohort sync state')
    } finally {
      if (requestGeneration === generation.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    return () => {
      generation.current += 1
    }
  }, [load])

  const create = async () => {
    const cleanedReason = reason.trim()
    if (cleanedReason.length < 3) {
      toast.error('Enter a reason of at least 3 characters')
      return
    }
    if (!newCohort.key.trim() || !newCohort.name.trim()) {
      toast.error('A cohort key and name are required')
      return
    }
    setBusy(true)
    try {
      await apiClient.createAdminCohort({
        key: newCohort.key.trim(),
        name: newCohort.name.trim(),
        posthog_cohort_id: newCohort.posthog_cohort_id.trim() || null,
        tenant_id: newCohort.tenant_id.trim() || null,
        minimum_size: Number(newCohort.minimum_size) || 5,
        reason: cleanedReason,
        confirm: true,
      })
      toast.success('Cohort created')
      setNewCohort({
        key: '',
        name: '',
        posthog_cohort_id: '',
        tenant_id: '',
        minimum_size: '5',
      })
      await load()
    } catch (createError) {
      const message = createError instanceof Error ? createError.message : String(createError)
      toast.error(message || 'Failed to create cohort')
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 text-xs text-fg-3">
        Loading cohort sync state…
      </div>
    )
  }
  if (error) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-danger/30 bg-danger/10 p-5 text-xs text-danger">
        {error}
      </div>
    )
  }

  const summary = data?.summary
  return (
    <div className="space-y-4">
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-fg">PostHog cohort sync</h3>
          <p className="text-[10px] text-fg-3">
            Aggregate-only · five-user minimum · no member identifiers
          </p>
        </div>
        <p className="mt-1 text-xs text-fg-3">{data?.consent_basis}</p>
        {summary ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Cohorts" value={String(summary.total)} detail="Configured definitions" />
            <Stat label="Synced" value={String(summary.synced)} detail="Evaluation allowed" />
            <Stat label="Stale" value={String(summary.stale)} detail="Fail-closed" />
            <Stat label="Errors" value={String(summary.error)} detail="Last sync failed" />
            <Stat
              label="Below minimum"
              value={String(summary.below_minimum)}
              detail={`Under ${data?.minimum_size ?? 5} members`}
            />
            <Stat
              label="Mapped flags"
              value={String(summary.with_flag_mappings)}
              detail={`${summary.evaluation_allowed} evaluating`}
            />
          </div>
        ) : null}
      </div>

      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <label className="block text-[11px] text-fg-2">
          Reason for cohort changes
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={1000}
            placeholder="Ticket or incident reference (required)"
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
          />
        </label>
        <p className="mt-1 text-[10px] text-fg-3">
          Required. Every create, map, unmap and sync stores this reason with
          before/after state in the immutable admin audit log.
        </p>

        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
          <input
            value={newCohort.key}
            onChange={(event) =>
              setNewCohort((current) => ({ ...current, key: event.target.value }))
            }
            maxLength={64}
            placeholder="cohort_key"
            aria-label="Cohort key"
            className="rounded border border-line bg-bg px-2 py-2 font-mono text-xs text-fg"
          />
          <input
            value={newCohort.name}
            onChange={(event) =>
              setNewCohort((current) => ({ ...current, name: event.target.value }))
            }
            maxLength={255}
            placeholder="Cohort name"
            aria-label="Cohort name"
            className="rounded border border-line bg-bg px-2 py-2 text-xs text-fg"
          />
          <input
            value={newCohort.posthog_cohort_id}
            onChange={(event) =>
              setNewCohort((current) => ({
                ...current,
                posthog_cohort_id: event.target.value,
              }))
            }
            maxLength={64}
            placeholder="PostHog cohort id"
            aria-label="PostHog cohort id"
            className="rounded border border-line bg-bg px-2 py-2 font-mono text-xs text-fg"
          />
          <input
            value={newCohort.tenant_id}
            onChange={(event) =>
              setNewCohort((current) => ({ ...current, tenant_id: event.target.value }))
            }
            maxLength={36}
            placeholder="Tenant UUID (optional)"
            aria-label="Tenant UUID"
            className="rounded border border-line bg-bg px-2 py-2 font-mono text-xs text-fg"
          />
          <div className="flex gap-2">
            <input
              value={newCohort.minimum_size}
              onChange={(event) =>
                setNewCohort((current) => ({
                  ...current,
                  minimum_size: event.target.value,
                }))
              }
              type="number"
              min={5}
              max={100000}
              aria-label="Minimum cohort size"
              className="w-20 rounded border border-line bg-bg px-2 py-2 text-xs text-fg"
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => void create()}
              className="flex-1 rounded border border-line bg-surface-2 px-3 py-1.5 text-xs font-medium text-fg disabled:opacity-50"
            >
              Create cohort
            </button>
          </div>
        </div>
      </div>

      {data?.cohorts.length === 0 ? (
        <p className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 text-xs text-fg-3">
          No cohort definitions yet. Create one, sync its consent-filtered PostHog
          membership, then map it to a feature flag.
        </p>
      ) : null}

      <div className="space-y-3">
        {data?.cohorts.map((cohort) => (
          <CohortCard
            key={cohort.id}
            cohort={cohort}
            flags={flags}
            reason={reason}
            onChanged={load}
          />
        ))}
      </div>
    </div>
  )
}
