'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  apiClient,
  type AdminExportCreateResponse,
  type AdminExportDigestResponse,
  type AdminExportFormat,
  type AdminExportHistoryItem,
  type AdminExportRecipient,
  type AdminExportReport,
  type AdminExportsResponse,
  type AdminDigestFrequency,
} from '@/lib/api-client'
import { downloadBlob } from '@/lib/download'
import { formatDateTime, formatNumber, shortId } from './admin-format'

const RANGES = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
] as const

const REPORT_FILTERS: Record<AdminExportReport, Array<{ key: string; label: string; placeholder: string }>> = {
  overview: [
    { key: 'plan', label: 'Plan', placeholder: 'free, pro…' },
    { key: 'compiler', label: 'Compiler', placeholder: 'pdflatex' },
  ],
  billing: [
    { key: 'plan', label: 'Plan', placeholder: 'pro' },
    { key: 'status', label: 'Status', placeholder: 'active' },
  ],
  users: [
    { key: 'role', label: 'Role', placeholder: 'user, admin' },
    { key: 'plan', label: 'Plan', placeholder: 'pro' },
    { key: 'status', label: 'Subscription status', placeholder: 'active' },
  ],
  audit: [
    { key: 'action', label: 'Action', placeholder: 'admin.export.generated' },
    { key: 'target_type', label: 'Target type', placeholder: 'admin_export' },
  ],
}

type FilterState = Record<string, string>

function reportLabel(data: AdminExportsResponse | null, report: AdminExportReport): string {
  return data?.reports.find(item => item.report === report)?.label ?? report
}

function eventLabel(event: AdminExportHistoryItem['event']): string {
  return event === 'downloaded' ? 'Signed download' : 'Generated'
}

function metadataValue(item: AdminExportHistoryItem, key: string): string {
  const value = item.metadata?.[key]
  return value == null ? 'n/a' : String(value)
}

export default function AdminExports() {
  const [data, setData] = useState<AdminExportsResponse | null>(null)
  const [digest, setDigest] = useState<AdminExportDigestResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const [report, setReport] = useState<AdminExportReport>('overview')
  const [format, setFormat] = useState<AdminExportFormat>('csv')
  const [days, setDays] = useState(30)
  const [filters, setFilters] = useState<FilterState>({})
  const [created, setCreated] = useState<AdminExportCreateResponse | null>(null)

  const [digestEnabled, setDigestEnabled] = useState(false)
  const [digestFrequency, setDigestFrequency] = useState<AdminDigestFrequency>('weekly')
  const [digestReport, setDigestReport] = useState<Exclude<AdminExportReport, 'audit'>>('overview')
  const [digestFormat, setDigestFormat] = useState<'summary' | 'csv'>('summary')
  const [digestDays, setDigestDays] = useState(30)
  const [recipients, setRecipients] = useState<string[]>([])
  const [digestReason, setDigestReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [dryRunText, setDryRunText] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [catalog, digestState] = await Promise.all([
        apiClient.getAdminExports(),
        apiClient.getAdminExportDigest(),
      ])
      setData(catalog)
      setDigest(digestState)
      setDigestEnabled(digestState.enabled)
      setDigestFrequency(digestState.frequency)
      setDigestReport(digestState.report)
      setDigestFormat(digestState.format)
      setDigestDays(digestState.days)
      setRecipients(digestState.recipient_user_ids)
      setReport(digestState.report)
      if (digestState.filters && Object.keys(digestState.filters).length > 0) {
        setFilters(digestState.filters)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load admin exports')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const allowed = REPORT_FILTERS[report].map(item => item.key)
    setFilters(previous =>
      Object.fromEntries(Object.entries(previous).filter(([key]) => allowed.includes(key))),
    )
    if (format === 'pdf' && report === 'audit') {
      setFormat('csv')
    }
  }, [report, format])

  const activeFilters = useMemo(
    () => Object.fromEntries(Object.entries(filters).filter(([, value]) => value.trim() !== '')),
    [filters],
  )

  const requestBody = useMemo(
    () => ({
      report,
      format,
      days,
      ...activeFilters,
    }),
    [report, format, days, activeFilters],
  )

  const digestFilters = useMemo(() => {
    const allowed =
      digestReport === 'overview'
        ? ['plan', 'compiler']
        : digestReport === 'billing'
          ? ['plan', 'status']
          : ['role', 'plan', 'status']
    return Object.fromEntries(
      Object.entries(activeFilters).filter(([key]) => allowed.includes(key)),
    )
  }, [digestReport, activeFilters])

  const downloadStream = async () => {
    setBusy('stream')
    setError(null)
    setStatus(null)
    try {
      const blob = await apiClient.downloadAdminExportStream(requestBody)
      downloadBlob(blob, `latexy-admin-${report}-${days}d.${format}`)
      setStatus(`Streamed ${report} ${format.toUpperCase()} download started.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed')
    } finally {
      setBusy(null)
    }
  }

  const createSigned = async () => {
    setBusy('signed')
    setError(null)
    setStatus(null)
    try {
      const result = await apiClient.createAdminExport(requestBody)
      setCreated(result)
      setStatus(
        `Signed ${report} export ready (${formatNumber(result.row_count)} rows). Link expires ${formatDateTime(result.expires_at)}.`,
      )
      const history = await apiClient.getAdminExportHistory()
      setData(previous => (previous ? { ...previous, history: history.items } : previous))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export request failed')
    } finally {
      setBusy(null)
    }
  }

  const downloadSigned = async (token: string, exportFormat: AdminExportFormat) => {
    setBusy('download')
    setError(null)
    try {
      const blob = await apiClient.downloadAdminExportToken(token)
      downloadBlob(blob, `latexy-admin-export.${exportFormat}`)
      setStatus('Signed download complete.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Signed download failed')
    } finally {
      setBusy(null)
    }
  }

  const saveDigest = async () => {
    if (!confirmed) {
      setError('Confirm the scheduled digest change before saving.')
      return
    }
    setBusy('digest')
    setError(null)
    setStatus(null)
    try {
      const saved = await apiClient.updateAdminExportDigest({
        enabled: digestEnabled,
        frequency: digestFrequency,
        recipient_user_ids: recipients,
        report: digestReport,
        format: digestFormat,
        days: digestDays,
        plan: digestFilters.plan,
        compiler: digestFilters.compiler,
        status: digestFilters.status,
        role: digestFilters.role,
        reason: digestReason.trim(),
        confirm: true,
      })
      setDigest(previous => (previous ? { ...previous, ...saved } : previous))
      setConfirmed(false)
      setDigestReason('')
      setStatus(saved.updated ? 'Digest configuration saved.' : 'Digest configuration was already current.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Digest update failed')
    } finally {
      setBusy(null)
    }
  }

  const dryRun = async () => {
    setBusy('dry-run')
    setError(null)
    setStatus(null)
    setDryRunText(null)
    try {
      const preview = await apiClient.dryRunAdminExportDigest({
        enabled: false,
        frequency: digestFrequency,
        recipient_user_ids: recipients,
        report: digestReport,
        format: digestFormat,
        days: digestDays,
        plan: digestFilters.plan,
        compiler: digestFilters.compiler,
        status: digestFilters.status,
        role: digestFilters.role,
      })
      setDryRunText(preview.text_body)
      setStatus('Dry run complete. No email was sent.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Digest dry run failed')
    } finally {
      setBusy(null)
    }
  }

  const toggleRecipient = (recipient: AdminExportRecipient) => {
    setRecipients(previous =>
      previous.includes(recipient.user_id)
        ? previous.filter(value => value !== recipient.user_id)
        : [...previous, recipient.user_id].slice(0, 10),
    )
  }

  if (loading) {
    return (
      <div role="status" aria-busy="true" className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 text-sm text-fg-3">
        Loading admin exports…
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-fg">CSV and PDF exports</h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Reports are aggregate-only and enforce a five-user suppression floor. CSV streams in bounded batches;
              every file embeds its schema version, generation time, range and filters. Larger jobs return a
              short-lived signed URL bound to the requesting admin.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Refresh
          </button>
        </div>

        {(error || status) && (
          <div className="mt-4 space-y-1 text-xs">
            {error && <p role="alert" className="text-danger">{error}</p>}
            {status && <p role="status" className="text-fg-3">{status}</p>}
          </div>
        )}

        <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <div className="space-y-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Report</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {(data?.reports ?? []).map(item => (
                  <button
                    key={item.report}
                    type="button"
                    onClick={() => setReport(item.report)}
                    aria-pressed={report === item.report}
                    className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-xs font-medium ${
                      report === item.report
                        ? 'border-accent bg-accent-soft text-accent-strong'
                        : 'border-line text-fg-2 hover:bg-surface-2'
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <p className="mt-2 text-[11px] text-fg-3">
                {data?.reports.find(item => item.report === report)?.description}
              </p>
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Range</p>
                <div className="mt-2 flex gap-1">
                  {RANGES.map(item => (
                    <button
                      key={item.days}
                      type="button"
                      onClick={() => setDays(item.days)}
                      aria-pressed={days === item.days}
                      className={`rounded px-2 py-1 text-xs ${
                        days === item.days ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:bg-surface-2'
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Format</p>
                <div className="mt-2 flex gap-1">
                  {(['csv', 'pdf'] as const).map(item => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setFormat(item)}
                      aria-pressed={format === item}
                      className={`rounded px-2 py-1 text-xs uppercase ${
                        format === item ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:bg-surface-2'
                      }`}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              {REPORT_FILTERS[report].map(item => (
                <label key={item.key} className="text-[11px] text-fg-3">
                  {item.label}
                  <input
                    value={filters[item.key] ?? ''}
                    onChange={event =>
                      setFilters(previous => ({ ...previous, [item.key]: event.target.value }))
                    }
                    placeholder={item.placeholder}
                    className="mt-1 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                  />
                </label>
              ))}
            </div>

            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                onClick={() => void downloadStream()}
                disabled={busy !== null}
                className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-bg disabled:opacity-50"
              >
                {busy === 'stream' ? 'Streaming…' : `Stream ${format.toUpperCase()}`}
              </button>
              <button
                type="button"
                onClick={() => void createSigned()}
                disabled={busy !== null}
                className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
              >
                {busy === 'signed' ? 'Preparing…' : 'Create signed link'}
              </button>
            </div>

            {created && (
              <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 text-[11px] text-fg-3">
                <p>
                  {formatNumber(created.row_count)} rows · cap {formatNumber(created.row_cap)} · signed link expires{' '}
                  {formatDateTime(created.expires_at)}
                  {created.large_job ? ' · large job' : ''}
                </p>
                <button
                  type="button"
                  onClick={() => void downloadSigned(created.download_token, created.format)}
                  disabled={busy !== null}
                  className="mt-2 rounded border border-line px-2 py-1 text-[11px] font-medium text-fg hover:bg-surface-2 disabled:opacity-50"
                >
                  {busy === 'download' ? 'Downloading…' : 'Download signed file'}
                </button>
              </div>
            )}
          </div>

          <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-3">
            <h3 className="text-xs font-semibold text-fg">Export limits</h3>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
              <div>
                <dt className="text-fg-3">CSV row cap</dt>
                <dd className="tabular-nums text-fg">{formatNumber(data?.limits.max_rows ?? 0)}</dd>
              </div>
              <div>
                <dt className="text-fg-3">PDF row cap</dt>
                <dd className="tabular-nums text-fg">{formatNumber(data?.limits.max_pdf_rows ?? 0)}</dd>
              </div>
              <div>
                <dt className="text-fg-3">Signed URL TTL</dt>
                <dd className="tabular-nums text-fg">{data?.limits.signed_url_ttl_minutes ?? 0} min</dd>
              </div>
              <div>
                <dt className="text-fg-3">Suppression floor</dt>
                <dd className="tabular-nums text-fg">{data?.limits.minimum_users ?? 0} users</dd>
              </div>
            </dl>
            <p className="mt-3 text-[10px] leading-relaxed text-fg-3">
              No resume/document content, prompts, emails, tokens, raw IPs or provider payloads are included. Exports
              are audited with actor, filters and row count.
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <h2 className="text-lg font-semibold text-fg">Scheduled admin digest</h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Enable an aggregate digest per admin. Recipients must be verified administrators. A dry run builds the exact
          payload without sending email. Last-run status and failures stay visible here and in the audit log.
        </p>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_1fr]">
          <div className="space-y-3">
            <label className="flex items-center gap-2 text-xs text-fg">
              <input
                type="checkbox"
                checked={digestEnabled}
                onChange={event => setDigestEnabled(event.target.checked)}
              />
              Enable scheduled digest
            </label>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-[11px] text-fg-3">
                Frequency
                <select
                  value={digestFrequency}
                  onChange={event => setDigestFrequency(event.target.value as AdminDigestFrequency)}
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </label>
              <label className="text-[11px] text-fg-3">
                Report
                <select
                  value={digestReport}
                  onChange={event => setDigestReport(event.target.value as Exclude<AdminExportReport, 'audit'>)}
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                >
                  <option value="overview">Platform overview</option>
                  <option value="billing">Billing summary</option>
                  <option value="users">User cohorts</option>
                </select>
              </label>
              <label className="text-[11px] text-fg-3">
                Format
                <select
                  value={digestFormat}
                  onChange={event => setDigestFormat(event.target.value as 'summary' | 'csv')}
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                >
                  <option value="summary">Summary email</option>
                  <option value="csv">CSV-style table</option>
                </select>
              </label>
              <label className="text-[11px] text-fg-3">
                Range (days)
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={digestDays}
                  onChange={event => setDigestDays(Number(event.target.value))}
                  className="mt-1 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
                />
              </label>
            </div>

            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Approved recipients</p>
              <div className="mt-2 space-y-1">
                {(digest?.available_recipients ?? []).map(recipient => (
                  <label key={recipient.user_id} className="flex items-center gap-2 text-[11px] text-fg-2">
                    <input
                      type="checkbox"
                      checked={recipients.includes(recipient.user_id)}
                      onChange={() => toggleRecipient(recipient)}
                    />
                    {recipient.is_self ? 'This admin' : `Admin ${shortId(recipient.user_id)}`}
                  </label>
                ))}
                {(digest?.available_recipients ?? []).length === 0 && (
                  <p className="text-[11px] text-fg-3">No verified administrator recipients are available.</p>
                )}
              </div>
            </div>

            <label className="text-[11px] text-fg-3">
              Reason
              <input
                value={digestReason}
                onChange={event => setDigestReason(event.target.value)}
                placeholder="Why is this schedule changing?"
                className="mt-1 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
              />
            </label>
            <label className="flex items-center gap-2 text-[11px] text-fg-2">
              <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
              I confirm this scheduled digest change.
            </label>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void saveDigest()}
                disabled={busy !== null || digestReason.trim().length < 3}
                className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-bg disabled:opacity-50"
              >
                {busy === 'digest' ? 'Saving…' : 'Save digest'}
              </button>
              <button
                type="button"
                onClick={() => void dryRun()}
                disabled={busy !== null}
                className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
              >
                {busy === 'dry-run' ? 'Running…' : 'Dry run (no email)'}
              </button>
            </div>
          </div>

          <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-3 text-[11px] text-fg-3">
            <h3 className="text-xs font-semibold text-fg">Last run</h3>
            {digest?.last_run ? (
              <dl className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <dt>Status</dt>
                  <dd className={digest.last_run.status === 'failed' ? 'text-danger' : 'text-fg'}>
                    {digest.last_run.status}
                  </dd>
                </div>
                <div>
                  <dt>Finished</dt>
                  <dd>{digest.last_run.finished_at ? formatDateTime(digest.last_run.finished_at) : 'n/a'}</dd>
                </div>
                <div>
                  <dt>Rows</dt>
                  <dd className="tabular-nums">{formatNumber(digest.last_run.row_count ?? 0)}</dd>
                </div>
                <div>
                  <dt>Delivered</dt>
                  <dd className="tabular-nums">
                    {formatNumber(digest.last_run.delivered_count ?? 0)} /{' '}
                    {formatNumber(digest.last_run.recipient_count ?? 0)}
                  </dd>
                </div>
                {digest.last_run.error_class && (
                  <div className="col-span-2">
                    <dt>Failure</dt>
                    <dd className="text-danger">{digest.last_run.error_class}</dd>
                  </div>
                )}
              </dl>
            ) : (
              <p className="mt-2">No digest run recorded yet.</p>
            )}
            {dryRunText && (
              <div className="mt-3">
                <h4 className="text-xs font-semibold text-fg">Dry-run payload</h4>
                <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded border border-line bg-bg p-2 text-[10px]">
                  {dryRunText}
                </pre>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
        <h2 className="text-lg font-semibold text-fg">Export history</h2>
        <p className="mt-1 text-xs text-fg-3">
          Newest audit events for this admin only. Every request and signed delivery records the report, filters and row
          count.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-fg-3">
              <tr>
                <th className="py-2 pr-3">When</th>
                <th className="py-2 pr-3">Event</th>
                <th className="py-2 pr-3">Report</th>
                <th className="py-2 pr-3">Rows</th>
                <th className="py-2 pr-3">Delivery</th>
              </tr>
            </thead>
            <tbody>
              {(data?.history ?? []).map(item => (
                <tr key={item.id} className="border-t border-line/70">
                  <td className="py-2 pr-3 text-fg-3">{formatDateTime(item.created_at)}</td>
                  <td className="py-2 pr-3 text-fg">{eventLabel(item.event)}</td>
                  <td className="py-2 pr-3 text-fg-2">{metadataValue(item, 'report')}</td>
                  <td className="py-2 pr-3 tabular-nums text-fg-2">{metadataValue(item, 'row_count')}</td>
                  <td className="py-2 pr-3 text-fg-3">{metadataValue(item, 'delivery')}</td>
                </tr>
              ))}
              {(data?.history ?? []).length === 0 && (
                <tr>
                  <td colSpan={5} className="py-4 text-center text-fg-3">
                    No exports recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
