'use client'

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  apiClient,
  type AdminIncident,
  type AdminIncidentInput,
  type AdminIncidentList,
  type AdminIncidentSeverity,
  type AdminIncidentStatus,
} from '@/lib/api-client'
import { formatDateTime, shortId } from './admin-format'

type IncidentStatusFilter = '' | AdminIncidentStatus | 'active'
type IncidentSeverityFilter = '' | AdminIncidentSeverity

type Filters = {
  service: string
  severity: IncidentSeverityFilter
  status: IncidentStatusFilter
  start_date: string
  end_date: string
}

const EMPTY_FILTERS: Filters = {
  service: '',
  severity: '',
  status: '',
  start_date: '',
  end_date: '',
}

const DEFAULT_SERVICES = [
  'api',
  'worker',
  'database',
  'redis',
  'storage',
  'billing',
  'email',
  'frontend',
  'modal',
  'deploy',
  'other',
]

const SEVERITY_TONE: Record<AdminIncidentSeverity, string> = {
  critical: 'border-err/30 bg-err/10 text-err',
  high: 'border-warn/30 bg-warn/10 text-warn',
  medium: 'border-accent/30 bg-accent-soft text-accent-strong',
  low: 'border-line bg-surface-2 text-fg-3',
}

const STATUS_TONE: Record<AdminIncidentStatus, string> = {
  open: 'border-warn/30 bg-warn/10 text-warn',
  resolved: 'border-ok/30 bg-ok/10 text-ok',
}

type Draft = {
  title: string
  summary: string
  severity: AdminIncidentSeverity
  services: string
  owner: string
  links: string
  related_alert_keys: string
  deploy_sha: string
  deploy_url: string
  started_at: string
}

const EMPTY_DRAFT: Draft = {
  title: '',
  summary: '',
  severity: 'high',
  services: '',
  owner: 'Platform',
  links: '',
  related_alert_keys: '',
  deploy_sha: '',
  deploy_url: '',
  started_at: '',
}

function localInputValue(iso: string | null | undefined): string {
  if (!iso) return ''
  const parsed = new Date(iso)
  if (!Number.isFinite(parsed.getTime())) return ''
  const offset = parsed.getTimezoneOffset() * 60_000
  return new Date(parsed.getTime() - offset).toISOString().slice(0, 16)
}

function dateStartIso(value: string): string | undefined {
  if (!value) return undefined
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : undefined
}

function dateEndIso(value: string): string | undefined {
  if (!value) return undefined
  const parsed = new Date(`${value}T23:59:59.999`)
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : undefined
}

function splitLines(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function splitServices(value: string): string[] {
  return splitLines(value).map((item) => item.toLowerCase())
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const value = Math.max(0, Math.round(seconds))
  if (value < 60) return `${value}s`
  const minutes = Math.floor(value / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours < 24) return rest ? `${hours}h ${rest}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d ${hours % 24}h`
}

function dayKey(iso: string): string {
  const parsed = new Date(iso)
  return Number.isFinite(parsed.getTime()) ? parsed.toDateString() : 'Unknown date'
}

function IncidentCard({
  incident,
  onChanged,
  onEdit,
  highlighted,
}: {
  incident: AdminIncident
  onChanged: () => void
  onEdit: (incident: AdminIncident) => void
  highlighted: boolean
}) {
  const [mode, setMode] = useState<'resolve' | 'reopen' | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      if (mode === 'resolve') {
        await apiClient.resolveAdminIncident(incident.id, {
          ...(reason.trim() ? { reason: reason.trim() } : {}),
        })
      } else {
        await apiClient.reopenAdminIncident(incident.id, {
          ...(reason.trim() ? { reason: reason.trim() } : {}),
        })
      }
      setMode(null)
      setReason('')
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Incident action failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article
      id={`admin-incident-${incident.id}`}
      className={`scroll-mt-24 rounded-[var(--radius-lg)] border bg-surface p-4 transition ${
        highlighted ? 'border-accent ring-2 ring-accent/20' : 'border-line'
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${SEVERITY_TONE[incident.severity]}`}>
              {incident.severity}
            </span>
            <span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${STATUS_TONE[incident.status]}`}>
              {incident.status}
            </span>
            <h3 className="text-sm font-semibold text-fg">{incident.title}</h3>
            <span className="rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] text-fg-3">
              {incident.owner}
            </span>
          </div>
          <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-fg-2">{incident.summary}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {incident.services.map((service) => (
              <span key={service} className="rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-3">
                {service}
              </span>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-fg-3">
            Started {formatDateTime(incident.started_at)}
            {incident.ended_at ? ` · Ended ${formatDateTime(incident.ended_at)}` : ' · ongoing'}
            {` · ${formatDuration(incident.duration_seconds)}`}
          </p>
          {(incident.deploy_sha || incident.deploy_url) && (
            <p className="mt-1 text-[11px] text-fg-3">
              Deploy marker:{' '}
              {incident.deploy_url ? (
                <a
                  href={incident.deploy_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-accent-strong hover:underline"
                >
                  {incident.deploy_sha ? shortId(incident.deploy_sha, 12) : 'deployment'}
                </a>
              ) : (
                <span className="font-mono">{shortId(incident.deploy_sha, 12)}</span>
              )}
            </p>
          )}
          {incident.related_alerts.length > 0 ? (
            <div className="mt-2 space-y-1">
              {incident.related_alerts.map((alert) => (
                <p key={alert.id} className="text-[11px] text-fg-3">
                  <span className="font-medium text-fg-2">{alert.title}</span>
                  {` · ${alert.state} · ${alert.owner} · seen ${alert.occurrence_count}×`}
                </p>
              ))}
            </div>
          ) : incident.related_alert_keys.length > 0 ? (
            <p className="mt-2 text-[11px] text-fg-3">
              Related alerts: {incident.related_alert_keys.join(', ')} (none currently present)
            </p>
          ) : null}
          {incident.links.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {incident.links.map((link) => (
                <a
                  key={link}
                  href={link}
                  target="_blank"
                  rel="noreferrer"
                  className="max-w-full truncate rounded border border-line px-2 py-1 text-[10px] text-accent-strong hover:bg-surface-2"
                >
                  {link}
                </a>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onEdit(incident)}
            className="rounded-[var(--radius-md)] border border-line px-2.5 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => {
              setMode(mode === 'resolve' ? null : 'resolve')
              setReason('')
              setError(null)
            }}
            className={`rounded-[var(--radius-md)] border px-2.5 py-1.5 text-[11px] font-medium ${
              incident.status === 'open'
                ? 'border-ok/30 bg-ok/10 text-ok hover:bg-ok/15'
                : 'border-warn/30 bg-warn/10 text-warn hover:bg-warn/15'
            }`}
          >
            {incident.status === 'open' ? 'Resolve' : 'Reopen'}
          </button>
        </div>
      </div>

      {mode && (
        <div className="mt-3 space-y-2 border-t border-line pt-3">
          <label className="block text-[11px] text-fg-2">
            Reason (optional, recorded in the audit log)
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={1000}
              className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
              placeholder={mode === 'resolve' ? 'What confirmed recovery?' : 'Why is this incident active again?'}
            />
          </label>
          {error && <p role="alert" className="text-[11px] text-err">{error}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void submit()}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40"
            >
              {busy ? 'Saving…' : mode === 'resolve' ? 'Mark resolved' : 'Reopen incident'}
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
    </article>
  )
}

export default function AdminIncidentTimeline() {
  const [data, setData] = useState<AdminIncidentList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draftFilters, setDraftFilters] = useState<Filters>(EMPTY_FILTERS)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [reloadKey, setReloadKey] = useState(0)
  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [highlightedId, setHighlightedId] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    setLoading(true)
    setError(null)
    apiClient
      .getAdminIncidents({
        ...(filters.service ? { service: filters.service } : {}),
        ...(filters.severity ? { severity: filters.severity } : {}),
        ...(filters.status ? { status: filters.status } : {}),
        ...(dateStartIso(filters.start_date) ? { start_date: dateStartIso(filters.start_date) } : {}),
        ...(dateEndIso(filters.end_date) ? { end_date: dateEndIso(filters.end_date) } : {}),
        limit: 200,
      })
      .then((result) => {
        if (!stale) setData(result)
      })
      .catch((err: unknown) => {
        if (!stale) setError(err instanceof Error ? err.message : 'Incident timeline could not be loaded')
      })
      .finally(() => {
        if (!stale) setLoading(false)
      })
    return () => {
      stale = true
    }
  }, [filters, reloadKey])

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get('incident')
    if (!requested || !data) return
    const present = data.items.some((item) => item.id === requested)
    setHighlightedId(present ? requested : null)
    if (!present) return
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(`admin-incident-${requested}`)?.scrollIntoView({ block: 'center' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [data])

  const serviceOptions = useMemo(() => {
    const seen = new Set(DEFAULT_SERVICES)
    for (const incident of data?.items ?? []) {
      for (const service of incident.services) seen.add(service)
    }
    return Array.from(seen).sort()
  }, [data])

  const groups = useMemo(() => {
    const map = new Map<string, AdminIncident[]>()
    for (const incident of data?.items ?? []) {
      const key = dayKey(incident.started_at)
      const bucket = map.get(key)
      if (bucket) bucket.push(incident)
      else map.set(key, [incident])
    }
    return Array.from(map.entries())
  }, [data])

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFilters({ ...draftFilters })
  }

  const resetFilters = () => {
    setDraftFilters(EMPTY_FILTERS)
    setFilters(EMPTY_FILTERS)
  }

  const updateFilter = (key: keyof Filters, value: string) => {
    setDraftFilters((current) => ({ ...current, [key]: value }))
  }

  const openCreate = () => {
    setEditingId(null)
    setDraft(EMPTY_DRAFT)
    setFormError(null)
    setFormOpen(true)
  }

  const openEdit = (incident: AdminIncident) => {
    setEditingId(incident.id)
    setDraft({
      title: incident.title,
      summary: incident.summary,
      severity: incident.severity,
      services: incident.services.join(', '),
      owner: incident.owner,
      links: incident.links.join('\n'),
      related_alert_keys: incident.related_alert_keys.join('\n'),
      deploy_sha: incident.deploy_sha ?? '',
      deploy_url: incident.deploy_url ?? '',
      started_at: localInputValue(incident.started_at),
    })
    setFormError(null)
    setFormOpen(true)
  }

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (saving) return
    const services = splitServices(draft.services)
    if (!draft.summary.trim() || !draft.owner.trim() || services.length === 0) {
      setFormError('Summary, owner and at least one affected service are required.')
      return
    }
    const startedAt = draft.started_at ? new Date(draft.started_at) : null
    if (startedAt && !Number.isFinite(startedAt.getTime())) {
      setFormError('Started time is invalid.')
      return
    }
    const payload: AdminIncidentInput = {
      summary: draft.summary.trim(),
      severity: draft.severity,
      services,
      owner: draft.owner.trim(),
      links: splitLines(draft.links),
      related_alert_keys: splitLines(draft.related_alert_keys),
      deploy_sha: draft.deploy_sha.trim() || null,
      deploy_url: draft.deploy_url.trim() || null,
      ...(draft.title.trim() ? { title: draft.title.trim() } : {}),
      ...(startedAt ? { started_at: startedAt.toISOString() } : {}),
    }
    setSaving(true)
    setFormError(null)
    try {
      if (editingId) {
        await apiClient.updateAdminIncident(editingId, payload)
      } else {
        await apiClient.createAdminIncident(payload)
      }
      setFormOpen(false)
      setEditingId(null)
      setDraft(EMPTY_DRAFT)
      setReloadKey((value) => value + 1)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Incident could not be saved')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-labelledby="admin-incident-timeline" id="admin-incident-timeline" className="scroll-mt-20 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-fg">Incident timeline</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Operator-authored incident history with affected services, severity, deploy markers and linked alerts.
            Incident text is validated to reject customer contact details and credentials. Every change is written to
            the append-only admin audit log; active incidents also appear in the needs-attention queue.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {data && (
            <span className="rounded-full border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-warn">
              {data.active_count} active
            </span>
          )}
          <button
            type="button"
            onClick={openCreate}
            className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg"
          >
            Record incident
          </button>
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Refresh
          </button>
        </div>
      </div>

      <form onSubmit={applyFilters} className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-5">
        <label className="text-[11px] text-fg-2">
          Service
          <select
            aria-label="Filter incidents by service"
            value={draftFilters.service}
            onChange={(event) => updateFilter('service', event.target.value)}
            className="mt-1 w-full min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          >
            <option value="">All services</option>
            {serviceOptions.map((service) => (
              <option key={service} value={service}>{service}</option>
            ))}
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Severity
          <select
            aria-label="Filter incidents by severity"
            value={draftFilters.severity}
            onChange={(event) => updateFilter('severity', event.target.value as IncidentSeverityFilter)}
            className="mt-1 w-full min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          >
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          Status
          <select
            aria-label="Filter incidents by status"
            value={draftFilters.status}
            onChange={(event) => updateFilter('status', event.target.value as IncidentStatusFilter)}
            className="mt-1 w-full min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
        <label className="text-[11px] text-fg-2">
          From
          <input
            type="date"
            aria-label="Filter incidents from date"
            value={draftFilters.start_date}
            onChange={(event) => updateFilter('start_date', event.target.value)}
            className="mt-1 w-full min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          />
        </label>
        <label className="text-[11px] text-fg-2">
          To
          <input
            type="date"
            aria-label="Filter incidents to date"
            value={draftFilters.end_date}
            onChange={(event) => updateFilter('end_date', event.target.value)}
            className="mt-1 w-full min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          />
        </label>
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-5">
          <button type="submit" className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg">
            Apply filters
          </button>
          <button
            type="button"
            onClick={resetFilters}
            className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Reset
          </button>
          <span className="ml-auto text-[10px] text-fg-3">
            {data ? `${data.total} matching incident${data.total === 1 ? '' : 's'}` : ''}
          </span>
        </div>
      </form>

      {formOpen && (
        <form onSubmit={save} className="space-y-3 rounded-[var(--radius-lg)] border border-accent/30 bg-surface p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-fg">
              {editingId ? 'Edit incident' : 'Record incident'}
            </h3>
            <button
              type="button"
              onClick={() => { setFormOpen(false); setEditingId(null) }}
              className="rounded border border-line px-2 py-1 text-[11px] text-fg-3 hover:bg-surface-2"
            >
              Close
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-[11px] text-fg-2">
              Title (optional; derived from the summary when omitted)
              <input
                value={draft.title}
                onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                maxLength={200}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Severity
              <select
                value={draft.severity}
                onChange={(event) => setDraft((current) => ({ ...current, severity: event.target.value as AdminIncidentSeverity }))}
                className="mt-1 w-full min-h-[38px] rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
              >
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </label>
            <label className="text-[11px] text-fg-2 sm:col-span-2">
              Summary
              <textarea
                value={draft.summary}
                onChange={(event) => setDraft((current) => ({ ...current, summary: event.target.value }))}
                required
                maxLength={4000}
                rows={3}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                placeholder="What happened, current impact and the next operator step. Do not include customer details."
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Affected services (comma separated)
              <input
                value={draft.services}
                onChange={(event) => setDraft((current) => ({ ...current, services: event.target.value }))}
                required
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                placeholder="api, worker, redis"
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Owner
              <input
                value={draft.owner}
                onChange={(event) => setDraft((current) => ({ ...current, owner: event.target.value }))}
                required
                maxLength={64}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                placeholder="Platform"
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Started (optional)
              <input
                type="datetime-local"
                value={draft.started_at}
                onChange={(event) => setDraft((current) => ({ ...current, started_at: event.target.value }))}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Deploy SHA (optional)
              <input
                value={draft.deploy_sha}
                onChange={(event) => setDraft((current) => ({ ...current, deploy_sha: event.target.value }))}
                maxLength={40}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
                placeholder="7-40 hex characters"
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Deploy URL (optional)
              <input
                value={draft.deploy_url}
                onChange={(event) => setDraft((current) => ({ ...current, deploy_url: event.target.value }))}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                placeholder="https://…"
              />
            </label>
            <label className="text-[11px] text-fg-2">
              Related alert keys (optional, one per line)
              <textarea
                value={draft.related_alert_keys}
                onChange={(event) => setDraft((current) => ({ ...current, related_alert_keys: event.target.value }))}
                rows={2}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
                placeholder="billing.failed_payments"
              />
            </label>
            <label className="text-[11px] text-fg-2 sm:col-span-2">
              Links (optional, one absolute http(s) URL per line)
              <textarea
                value={draft.links}
                onChange={(event) => setDraft((current) => ({ ...current, links: event.target.value }))}
                rows={2}
                className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 text-xs text-fg"
                placeholder="https://github.com/sanskarpan/Latexy/pull/…"
              />
            </label>
          </div>
          {formError && <p role="alert" className="text-[11px] text-err">{formError}</p>}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg disabled:opacity-40"
            >
              {saving ? 'Saving…' : editingId ? 'Save incident' : 'Open incident'}
            </button>
            <button
              type="button"
              onClick={() => { setFormOpen(false); setEditingId(null) }}
              className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {error && (
        <div role="alert" className="rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          {error}
          {data ? ' Showing the last successful data.' : ''}
        </div>
      )}

      {loading && !data && <p role="status" className="text-xs text-fg-3">Loading incident timeline…</p>}

      {data && data.items.length === 0 && !loading && (
        <p className="rounded-[var(--radius-lg)] border border-line bg-surface px-4 py-8 text-center text-xs text-fg-3">
          No incidents match these filters.
        </p>
      )}

      {groups.map(([day, incidents]) => (
        <div key={day} className="space-y-2">
          <h3 className="sticky top-0 z-10 bg-bg/90 py-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-fg-3 backdrop-blur">
            {day}
          </h3>
          {incidents.map((incident) => (
            <IncidentCard
              key={incident.id}
              incident={incident}
              highlighted={highlightedId === incident.id}
              onEdit={openEdit}
              onChanged={() => setReloadKey((value) => value + 1)}
            />
          ))}
        </div>
      ))}
    </section>
  )
}
