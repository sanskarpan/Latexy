'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminTemplateHealthResponse,
  type AdminTemplateHealthRow,
  type AdminTemplateHealthStatus,
} from '@/lib/api-client'
import { formatDateTime, formatNumber } from '@/components/admin/admin-format'

const STATUS_OPTIONS: Array<{ value: '' | AdminTemplateHealthStatus; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'pass', label: 'Pass' },
  { value: 'fail', label: 'Fail' },
  { value: 'unknown', label: 'Unknown' },
]

function statusClasses(status: AdminTemplateHealthStatus): string {
  if (status === 'pass') return 'border-ok/30 bg-ok/10 text-ok'
  if (status === 'fail') return 'border-err/30 bg-err/10 text-err'
  return 'border-warn/30 bg-warn/10 text-warn'
}

function statusLabel(row: AdminTemplateHealthRow): string {
  if (row.status === 'unknown' && row.stale) return 'Unknown (stale)'
  return row.status.charAt(0).toUpperCase() + row.status.slice(1)
}

function compileSummary(row: AdminTemplateHealthRow): string {
  if (row.recent_compile_samples === 0) return 'No recent compiles'
  return `${formatNumber(row.recent_compile_success)} ok / ${formatNumber(row.recent_compile_failed)} failed`
}

function reasonLabel(row: AdminTemplateHealthRow): string {
  if (row.status_reason === 'no_evidence') return 'No verification evidence yet'
  if (row.status_reason === 'stale_evidence') return 'Newest evidence is stale'
  return row.error_class ? `${row.error_class.replace(/_/g, ' ')} · ${row.status_reason}` : row.status_reason
}

export default function AdminTemplateHealth() {
  const [data, setData] = useState<AdminTemplateHealthResponse | null>(null)
  const [status, setStatus] = useState<'' | AdminTemplateHealthStatus>('')
  const [includeInactive, setIncludeInactive] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryTarget, setRetryTarget] = useState<AdminTemplateHealthRow | null>(null)
  const [retryReason, setRetryReason] = useState('Re-run bounded template verification')
  const [retryRequestId, setRetryRequestId] = useState('')
  const [retrying, setRetrying] = useState(false)
  const requestGeneration = useRef(0)

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminTemplateHealth({
        status: status || undefined,
        include_inactive: includeInactive,
      })
      if (requestGeneration.current === generation) setData(next)
    } catch (err) {
      if (requestGeneration.current === generation) {
        setError(err instanceof Error ? err.message : 'Failed to load template health')
      }
    } finally {
      if (requestGeneration.current === generation) setLoading(false)
    }
  }, [status, includeInactive])

  useEffect(() => {
    void load()
    return () => {
      requestGeneration.current += 1
    }
  }, [load])

  const beginRetry = useCallback((row: AdminTemplateHealthRow) => {
    setRetryTarget(row)
    setRetryReason('Re-run bounded template verification')
    setRetryRequestId(
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? `tmpl-health-${crypto.randomUUID()}`
        : `tmpl-health-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    )
  }, [])

  const confirmRetry = useCallback(async () => {
    if (!retryTarget) return
    if (retryReason.trim().length < 3) {
      setError('A reason of at least 3 characters is required')
      return
    }
    setRetrying(true)
    setError(null)
    try {
      const result = await apiClient.retryAdminTemplateHealth(retryTarget.template_id, {
        reason: retryReason.trim(),
        confirm: true,
        request_id: retryRequestId,
      })
      setRetryTarget(null)
      setRetryRequestId('')
      await load()
      if (result.duplicate) {
        setError('This retry was already recorded; the existing evidence was returned.')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Template health retry failed')
    } finally {
      setRetrying(false)
    }
  }, [load, retryReason, retryRequestId, retryTarget])

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-fg">Template compile and visual health</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Persisted pass/fail/unknown verification for each active catalog template. Missing or
            stale evidence is shown as unknown, failures link to CI/commit evidence, and a retry
            re-runs only bounded asset and aggregate compile checks. No template source, document
            content, compiler log, or per-user history is read or returned.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            Status
            <select
              value={status}
              onChange={event => setStatus(event.target.value as '' | AdminTemplateHealthStatus)}
              className="mt-1 block rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            >
              {STATUS_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pb-2 text-xs text-fg-3">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={event => setIncludeInactive(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-line"
            />
            Include inactive
          </label>
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

      {error && (
        <div
          role="alert"
          className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
        >
          {data ? 'Showing the last successful data. ' : ''}
          {error}
        </div>
      )}

      {retryTarget && (
        <div className="mt-4 rounded-[var(--radius-md)] border border-accent/30 bg-accent-soft/40 p-3">
          <p className="text-xs font-semibold text-fg">
            Re-verify {retryTarget.template_name}
          </p>
          <p className="mt-1 text-[11px] text-fg-3">
            This records an audited evidence snapshot and never re-activates, edits, or deletes the
            template. Replaying the same request id returns the existing snapshot.
          </p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="flex-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
              Reason
              <input
                value={retryReason}
                onChange={event => setRetryReason(event.target.value)}
                maxLength={1000}
                className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
              />
            </label>
            <button
              type="button"
              onClick={() => void confirmRetry()}
              disabled={retrying}
              className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
            >
              {retrying ? 'Verifying…' : 'Confirm retry'}
            </button>
            <button
              type="button"
              onClick={() => {
                setRetryTarget(null)
                setRetryRequestId('')
              }}
              disabled={retrying}
              className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!data && loading ? (
        <div role="status" className="mt-6 text-center text-xs text-fg-3">
          Loading template health…
        </div>
      ) : data ? (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {[
              { label: 'Templates', value: data.summary.templates, detail: 'In this view' },
              { label: 'Pass', value: data.summary.pass, detail: 'Current evidence' },
              { label: 'Fail', value: data.summary.fail, detail: 'Needs attention' },
              { label: 'Unknown', value: data.summary.unknown, detail: `${formatNumber(data.summary.stale)} stale` },
              { label: 'No evidence', value: data.summary.without_evidence, detail: 'Never verified' },
            ].map(card => (
              <div
                key={card.label}
                className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5"
              >
                <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                  {card.label}
                </p>
                <p className="mt-1 text-lg font-semibold text-fg">{formatNumber(card.value)}</p>
                <p className="text-[10px] text-fg-3">{card.detail}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 overflow-x-auto">
            <table className="w-full min-w-[1080px] border-collapse text-sm">
              <caption className="sr-only">
                Per-template compile and visual verification status with CI evidence.
              </caption>
              <thead>
                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                  <th scope="col" className="px-2 py-2">Template</th>
                  <th scope="col" className="px-2 py-2">Status</th>
                  <th scope="col" className="px-2 py-2">Last verified</th>
                  <th scope="col" className="px-2 py-2">Commit</th>
                  <th scope="col" className="px-2 py-2">Recent compiles</th>
                  <th scope="col" className="px-2 py-2">Visual test</th>
                  <th scope="col" className="px-2 py-2">Evidence</th>
                  <th scope="col" className="px-2 py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.templates.map(row => (
                  <tr key={row.template_id} className="border-b border-line/60 align-top">
                    <td className="px-2 py-2.5">
                      <a
                        href={row.template_url}
                        className="text-sm font-medium text-fg hover:text-accent-strong"
                      >
                        {row.template_name}
                      </a>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-fg-3">
                        <span>{row.category.replace(/_/g, ' ')}</span>
                        {!row.active && <span className="text-warn">inactive</span>}
                      </div>
                    </td>
                    <td className="px-2 py-2.5">
                      <span
                        className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${statusClasses(row.status)}`}
                      >
                        {statusLabel(row)}
                      </span>
                      <p className="mt-1 max-w-[190px] text-[10px] text-fg-3">{reasonLabel(row)}</p>
                    </td>
                    <td className="px-2 py-2.5 text-xs text-fg-3">{formatDateTime(row.last_verified_at)}</td>
                    <td className="px-2 py-2.5 font-mono text-[10px] text-fg-3">
                      {row.commit_sha ? row.commit_sha.slice(0, 10) : 'unknown'}
                    </td>
                    <td className="px-2 py-2.5 text-xs text-fg-2">
                      <div>{compileSummary(row)}</div>
                      <div className="text-[10px] text-fg-3">
                        {row.recent_compile_samples > 0
                          ? `${row.recent_failure_rate.toFixed(1)}% failed over ${data.recent_compile_days}d`
                          : `Needs ${data.minimum_compile_samples} samples`}
                      </div>
                    </td>
                    <td className="px-2 py-2.5 text-xs text-fg-2">{row.visual_test}</td>
                    <td className="px-2 py-2.5 text-[10px]">
                      <div className="flex flex-col gap-1">
                        <a
                          href={row.evidence.ci_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-accent-strong hover:underline"
                        >
                          CI evidence
                        </a>
                        {row.evidence.log_url && (
                          <a
                            href={row.evidence.log_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-accent-strong hover:underline"
                          >
                            CI logs
                          </a>
                        )}
                        {row.evidence.commit_url && (
                          <a
                            href={row.evidence.commit_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-accent-strong hover:underline"
                          >
                            Commit
                          </a>
                        )}
                        <a
                          href={row.evidence.runbook_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-fg-3 hover:underline"
                        >
                          Runbook
                        </a>
                      </div>
                    </td>
                    <td className="px-2 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => beginRetry(row)}
                        className="rounded-[var(--radius-md)] border border-line px-2.5 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2"
                      >
                        Retry check
                      </button>
                    </td>
                  </tr>
                ))}
                {data.templates.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-2 py-8 text-center text-xs text-fg-3">
                      No templates match this status filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-[10px] text-fg-3">
            Stale evidence becomes unknown after {data.stale_after_hours}h. Recent compile health
            covers {data.recent_compile_days} days and requires {data.minimum_compile_samples}{' '}
            finished compiles before it can fail a template. Retry writes one append-only audited
            snapshot and is idempotent per request id.
          </p>
        </>
      ) : null}
    </section>
  )
}
