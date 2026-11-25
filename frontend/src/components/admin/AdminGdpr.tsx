'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { CircleAlert, Gavel, Loader2, RefreshCw, ShieldAlert, ShieldCheck } from 'lucide-react'
import {
  apiClient,
  type GdprLegalHold,
  type GdprRequestStatus,
  type GdprRequestSummary,
  type GdprRequestType,
} from '@/lib/api-client'
import { formatDateTime, shortId } from './admin-format'

const STATUS_OPTIONS: Array<{ value: '' | GdprRequestStatus; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'legal_review', label: 'Awaiting legal review' },
  { value: 'approved', label: 'Approved' },
  { value: 'processing', label: 'Processing' },
  { value: 'failed', label: 'Failed / retry' },
  { value: 'blocked', label: 'Blocked by legal hold' },
  { value: 'completed', label: 'Completed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'cancelled', label: 'Cancelled' },
]

function statusTone(status: GdprRequestStatus): string {
  if (status === 'completed') return 'bg-ok/10 text-ok ring-ok/20'
  if (status === 'failed' || status === 'blocked' || status === 'rejected') {
    return 'bg-err/10 text-err ring-err/20'
  }
  if (status === 'approved' || status === 'legal_review') {
    return 'bg-accent-soft text-accent-strong ring-accent/20'
  }
  return 'bg-surface-2 text-fg-3 ring-line'
}

export default function AdminGdpr() {
  const [items, setItems] = useState<GdprRequestSummary[]>([])
  const [holds, setHolds] = useState<GdprLegalHold[]>([])
  const [total, setTotal] = useState(0)
  const [status, setStatus] = useState<'' | GdprRequestStatus>('legal_review')
  const [requestType, setRequestType] = useState<'' | GdprRequestType>('deletion')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [holdUserId, setHoldUserId] = useState('')
  const [holdReason, setHoldReason] = useState('')
  const [releaseReasons, setReleaseReasons] = useState<Record<string, string>>({})

  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) ?? null,
    [items, selectedId],
  )

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [next, nextHolds] = await Promise.all([
        apiClient.getAdminGdprRequests({
          status: status || undefined,
          request_type: requestType || undefined,
          limit: 100,
        }),
        apiClient.getAdminGdprLegalHolds(true),
      ])
      setItems(next.items)
      setTotal(next.total)
      setHolds(nextHolds.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the GDPR queue')
    } finally {
      setLoading(false)
    }
  }, [requestType, status])

  useEffect(() => {
    void reload()
  }, [reload])

  const runAction = async (
    action: string,
    fn: () => Promise<unknown>,
    success: string,
  ) => {
    setBusy(action)
    setError(null)
    setNotice(null)
    try {
      await fn()
      setNotice(success)
      setNote('')
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(null)
    }
  }

  const review = (decision: 'approved' | 'rejected') => {
    if (!selected) return
    if (note.trim().length < 3) {
      setError('A review note of at least 3 characters is required')
      return
    }
    void runAction(
      `review:${decision}`,
      () => apiClient.reviewAdminGdprRequest(selected.id, { decision, note: note.trim() }),
      `Request ${decision}.`,
    )
  }

  const execute = () => {
    if (!selected) return
    void runAction(
      'execute',
      () => apiClient.executeAdminGdprDeletion(selected.id, note.trim() || undefined),
      'Deletion job finished; review the per-table report.',
    )
  }

  const placeHold = () => {
    if (!holdUserId.trim() || holdReason.trim().length < 5) {
      setError('A user id and a reason of at least 5 characters are required')
      return
    }
    void runAction(
      'place-hold',
      () =>
        apiClient.placeAdminGdprLegalHold({
          user_id: holdUserId.trim(),
          reason: holdReason.trim(),
        }),
      'Legal hold placed. Deletion execution is now blocked for this account.',
    )
  }

  const releaseHold = (hold: GdprLegalHold) => {
    const reason = (releaseReasons[hold.id] || '').trim()
    if (reason.length < 5) {
      setError('A release reason of at least 5 characters is required')
      return
    }
    void runAction(
      `release:${hold.id}`,
      () => apiClient.releaseAdminGdprLegalHold(hold.id, reason),
      'Legal hold released.',
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-fg">Privacy & deletion review</h2>
          <p className="text-xs text-fg-3">
            Legal review is admin-only. Approval never executes automatically; execution records a
            per-table result and is blocked while a legal hold is active.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void reload()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:opacity-60"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value as '' | GdprRequestStatus)}
          className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          value={requestType}
          onChange={(event) => setRequestType(event.target.value as '' | GdprRequestType)}
          className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
        >
          <option value="">All request types</option>
          <option value="deletion">Deletion</option>
          <option value="export">Export</option>
        </select>
        <span className="self-center text-xs text-fg-3">{total} matching request(s)</span>
      </div>

      {error && (
        <p className="flex items-start gap-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-xs text-err ring-1 ring-err/20">
          <CircleAlert size={14} className="mt-0.5 shrink-0" />
          {error}
        </p>
      )}
      {notice && (
        <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-xs text-ok ring-1 ring-ok/20">
          {notice}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-2 text-fg-3">
              <tr>
                <th className="px-3 py-2 font-medium">Request</th>
                <th className="px-3 py-2 font-medium">User</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => setSelectedId(item.id)}
                  className={`cursor-pointer border-t border-line hover:bg-surface-2 ${
                    selectedId === item.id ? 'bg-surface-2' : ''
                  }`}
                >
                  <td className="px-3 py-2">
                    <p className="font-medium text-fg">{item.request_type}</p>
                    <p className="font-mono text-[10px] text-fg-3">{shortId(item.id)}</p>
                  </td>
                  <td className="px-3 py-2">
                    <p className="text-fg-2">{item.user_email_masked || 'anonymized'}</p>
                    {item.legal_hold_active && (
                      <p className="text-[10px] font-semibold text-err">LEGAL HOLD</p>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 ring-1 ${statusTone(item.status)}`}
                    >
                      {item.status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-fg-3">{formatDateTime(item.created_at)}</td>
                </tr>
              ))}
              {!items.length && !loading && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-fg-3">
                    No requests match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          {selected ? (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-fg">
                    {selected.request_type === 'deletion' ? 'Deletion' : 'Export'} request
                  </p>
                  <p className="font-mono text-[10px] text-fg-3">{selected.id}</p>
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] ring-1 ${statusTone(selected.status)}`}
                >
                  {selected.status.replace(/_/g, ' ')}
                </span>
              </div>

              <dl className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <dt className="text-fg-3">User</dt>
                  <dd className="text-fg-2">{selected.user_email_masked || 'anonymized'}</dd>
                </div>
                <div>
                  <dt className="text-fg-3">User id</dt>
                  <dd className="break-all font-mono text-[10px] text-fg-2">
                    {selected.user_id || 'â€”'}
                  </dd>
                </div>
                <div>
                  <dt className="text-fg-3">Legal review</dt>
                  <dd className="text-fg-2">{selected.legal_review_status.replace(/_/g, ' ')}</dd>
                </div>
                <div>
                  <dt className="text-fg-3">Attempts</dt>
                  <dd className="text-fg-2">{selected.attempts}</dd>
                </div>
                <div>
                  <dt className="text-fg-3">Confirmed</dt>
                  <dd className="text-fg-2">{formatDateTime(selected.confirmed_at)}</dd>
                </div>
                <div>
                  <dt className="text-fg-3">Re-authenticated</dt>
                  <dd className="text-fg-2">{formatDateTime(selected.reauthenticated_at)}</dd>
                </div>
              </dl>

              {selected.review_note && (
                <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                  Note: {selected.review_note}
                </p>
              )}
              {selected.failure_detail && (
                <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-xs text-err">
                  {selected.failure_detail}
                </p>
              )}
              {selected.legal_hold_active && (
                <p className="flex items-center gap-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-xs text-err">
                  <ShieldAlert size={14} /> Active legal hold blocks execution.
                </p>
              )}

              {selected.request_type === 'deletion' &&
                selected.status === 'legal_review' && (
                  <div className="space-y-2">
                    <label className="block text-xs font-medium text-fg-2" htmlFor="gdpr-review-note">
                      Review note
                    </label>
                    <textarea
                      id="gdpr-review-note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      rows={3}
                      maxLength={2000}
                      className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                      placeholder="Counsel/lawful-basis reference for the decision"
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => review('approved')}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60"
                      >
                        <ShieldCheck size={13} /> Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => review('rejected')}
                        disabled={busy !== null}
                        className="inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-err/40 px-3 py-2 text-xs font-semibold text-err disabled:opacity-60"
                      >
                        <Gavel size={13} /> Reject
                      </button>
                    </div>
                  </div>
                )}

              {selected.request_type === 'deletion' &&
                ['approved', 'failed', 'blocked'].includes(selected.status) && (
                  <button
                    type="button"
                    onClick={() => execute()}
                    disabled={busy !== null || selected.legal_hold_active}
                    className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busy === 'execute' ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <ShieldAlert size={13} />
                    )}
                    {selected.status === 'failed' ? 'Retry deletion job' : 'Execute deletion'}
                  </button>
                )}

              {selected.table_results.length > 0 && (
                <div className="max-h-64 overflow-auto rounded-[var(--radius-md)] border border-line">
                  <table className="w-full text-left text-[10px]">
                    <thead className="bg-surface-2 text-fg-3">
                      <tr>
                        <th className="px-2 py-1 font-medium">Table</th>
                        <th className="px-2 py-1 font-medium">Result</th>
                        <th className="px-2 py-1 font-medium">Rows</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.table_results.map((row) => (
                        <tr key={`${row.step}-${row.table}`} className="border-t border-line">
                          <td className="px-2 py-1 font-mono text-fg-2">{row.table}</td>
                          <td className="px-2 py-1">
                            <span
                              className={
                                row.status === 'failed'
                                  ? 'text-err'
                                  : row.status === 'retained'
                                    ? 'text-fg-3'
                                    : 'text-ok'
                              }
                            >
                              {row.status}
                              {row.error_code ? ` (${row.error_code})` : ''}
                            </span>
                          </td>
                          <td className="px-2 py-1 text-fg-3">{row.rows_affected}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-fg-3">Select a request to review its status and report.</p>
          )}
        </div>
      </div>

      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Gavel size={14} className="text-fg-2" />
          <h3 className="text-sm font-semibold text-fg">Legal holds</h3>
        </div>
        <p className="text-xs text-fg-3">
          A hold blocks every deletion step until released. Holds are admin-only and audited.
        </p>
        <div className="flex flex-wrap gap-2">
          <input
            value={holdUserId}
            onChange={(event) => setHoldUserId(event.target.value)}
            placeholder="User UUID"
            className="min-w-[260px] flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-xs text-fg outline-none focus:border-accent"
          />
          <input
            value={holdReason}
            onChange={(event) => setHoldReason(event.target.value)}
            placeholder="Hold reason (litigation, investigationâ€¦)"
            className="min-w-[260px] flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={() => placeHold()}
            disabled={busy !== null}
            className="rounded-[var(--radius-md)] bg-err px-3 py-2 text-xs font-semibold text-err-fg disabled:opacity-60"
          >
            Place hold
          </button>
        </div>

        {holds.length > 0 ? (
          <ul className="space-y-2">
            {holds.map((hold) => (
              <li
                key={hold.id}
                className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-mono text-[10px] text-fg-3">{hold.id}</p>
                    <p className="text-fg-2">
                      {hold.user_email_masked || 'anonymized'} Â· {hold.user_id}
                    </p>
                    <p className="text-fg-3">
                      {hold.reason} Â· placed {formatDateTime(hold.placed_at)}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <input
                      value={releaseReasons[hold.id] || ''}
                      onChange={(event) =>
                        setReleaseReasons((previous) => ({
                          ...previous,
                          [hold.id]: event.target.value,
                        }))
                      }
                      placeholder="Release reason"
                      className="w-44 rounded-[var(--radius-md)] border border-line bg-bg px-2 py-1 text-[11px] text-fg outline-none focus:border-accent"
                    />
                    <button
                      type="button"
                      onClick={() => releaseHold(hold)}
                      disabled={busy !== null}
                      className="rounded-[var(--radius-md)] border border-line px-2 py-1 text-[11px] font-semibold text-fg-2 disabled:opacity-60"
                    >
                      Release
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-fg-3">No active legal holds.</p>
        )}
      </div>
    </div>
  )
}

