'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CircleAlert,
  Download,
  Loader2,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import {
  apiClient,
  type GdprPolicy,
  type GdprRequestSummary,
} from '@/lib/api-client'

function formatTimestamp(value: string | null): string {
  if (!value) return 'â€”'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'â€”' : parsed.toLocaleString()
}

function statusLabel(status: GdprRequestSummary['status']): string {
  switch (status) {
    case 'legal_review':
      return 'Awaiting legal review'
    case 'approved':
      return 'Approved â€” ready to execute'
    case 'processing':
      return 'Deletion in progress'
    case 'blocked':
      return 'Blocked by legal hold'
    case 'ready':
      return 'Ready to download'
    case 'completed':
      return 'Completed'
    case 'failed':
      return 'Needs retry'
    case 'rejected':
      return 'Rejected'
    case 'cancelled':
      return 'Cancelled'
    case 'expired':
      return 'Link expired'
    default:
      return 'Pending'
  }
}

function statusTone(status: GdprRequestSummary['status']): string {
  if (status === 'completed') return 'bg-ok/10 text-ok ring-ok/20'
  if (status === 'failed' || status === 'blocked' || status === 'rejected') {
    return 'bg-err/10 text-err ring-err/20'
  }
  if (status === 'ready' || status === 'approved') {
    return 'bg-accent-soft text-accent-strong ring-accent/20'
  }
  return 'bg-surface-2 text-fg-3 ring-line'
}

export default function PrivacyDataControls() {
  const [policy, setPolicy] = useState<GdprPolicy | null>(null)
  const [requests, setRequests] = useState<GdprRequestSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [deletionReason, setDeletionReason] = useState('')
  const [exportTokens, setExportTokens] = useState<Record<string, string>>({})

  const reload = useCallback(async () => {
    setError(null)
    try {
      const [nextPolicy, nextRequests] = await Promise.all([
        apiClient.getGdprPolicy(),
        apiClient.getGdprRequests(25),
      ])
      setPolicy(nextPolicy)
      setRequests(nextRequests.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load privacy controls')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const latestDeletion = useMemo(
    () => requests.find((item) => item.request_type === 'deletion') ?? null,
    [requests],
  )
  const hasOpenDeletion = latestDeletion
    ? ['legal_review', 'approved', 'processing', 'blocked', 'failed'].includes(
        latestDeletion.status,
      )
    : false
  const expectedConfirmation = policy?.deletion_confirmation ?? 'DELETE MY ACCOUNT'
  const confirmationMatches = confirmation.trim().toUpperCase() === expectedConfirmation

  const downloadBundle = useCallback(async (id: string, token: string) => {
    const blob = await apiClient.downloadGdprExport(id, token)
    const objectUrl = URL.createObjectURL(blob)
    try {
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = `latexy-gdpr-export-${id}.json`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }, [])

  const handleExport = async () => {
    setExporting(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiClient.requestGdprExport()
      setExportTokens((previous) => ({
        ...previous,
        [result.request.id]: result.download_token,
      }))
      await downloadBundle(result.request.id, result.download_token)
      setNotice(
        `Export generated. The signed link is valid until ${formatTimestamp(result.expires_at)} and requires your signed-in session.`,
      )
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the export')
    } finally {
      setExporting(false)
    }
  }

  const handleDeletionRequest = async () => {
    if (!confirmationMatches) return
    setDeleting(true)
    setError(null)
    setNotice(null)
    try {
      const result = await apiClient.requestGdprDeletion({
        confirmation: confirmation.trim().toUpperCase(),
        reason: deletionReason.trim() || undefined,
      })
      setConfirmation('')
      setDeletionReason('')
      setNotice(
        result.created
          ? 'Deletion request submitted. An administrator must complete legal review before anything is erased.'
          : 'An existing deletion request is already open; its status is shown below.',
      )
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not submit the deletion request')
    } finally {
      setDeleting(false)
    }
  }

  const handleCancel = async (id: string) => {
    if (!window.confirm('Cancel this pending deletion request?')) return
    setCancellingId(id)
    setError(null)
    try {
      await apiClient.cancelGdprDeletion(id)
      setNotice('Deletion request cancelled.')
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel the request')
    } finally {
      setCancellingId(null)
    }
  }

  return (
    <div className="space-y-8">
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
            <Download size={14} className="text-accent-strong" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-fg">Export your data</h2>
            <p className="text-xs text-fg-3">
              Profile, resumes, cover letters, applications, payment summary and usage.
            </p>
          </div>
        </div>

        <p className="text-xs text-fg-3">
          The download is signed, expires after {policy?.export_ttl_minutes ?? 30} minutes and
          requires your signed-in session. Passwords, OAuth tokens, encrypted BYOK keys and
          binary PDF imports are never included.
        </p>

        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={exporting || loading}
          className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110 disabled:opacity-60"
        >
          {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          {exporting ? 'Preparing exportâ€¦' : 'Request export bundle'}
        </button>

        {requests.some((item) => item.request_type === 'export') && (
          <ul className="space-y-2">
            {requests
              .filter((item) => item.request_type === 'export')
              .slice(0, 5)
              .map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-xs"
                >
                  <span className="text-fg-2">
                    Export Â· {formatTimestamp(item.created_at)} Â·{' '}
                    <span className={`rounded-full px-2 py-0.5 ring-1 ${statusTone(item.status)}`}>
                      {statusLabel(item.status)}
                    </span>
                  </span>
                  {exportTokens[item.id] && item.export_available ? (
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 font-semibold text-accent-strong hover:underline"
                      onClick={() => void downloadBundle(item.id, exportTokens[item.id])}
                    >
                      <Download size={12} /> Download again
                    </button>
                  ) : (
                    <span className="text-fg-3">
                      Request a new link to download
                    </span>
                  )}
                </li>
              ))}
          </ul>
        )}
      </div>

      <div className="rounded-[var(--radius-lg)] border border-err/30 bg-surface p-6 space-y-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-err/10">
            <Trash2 size={14} className="text-err" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-fg">Delete your account</h2>
            <p className="text-xs text-fg-3">
              Requires a fresh sign-in, a typed confirmation and administrator legal review.
            </p>
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3 text-xs text-fg-2">
          <p className="font-semibold text-fg">What is retained</p>
          <ul className="mt-1 list-disc space-y-1 pl-4">
            {(policy?.retention_exceptions ?? []).map((item) => (
              <li key={item.category}>
                <span className="font-medium">{item.category.replace(/_/g, ' ')}</span>: {item.reason}
              </li>
            ))}
          </ul>
        </div>

        {latestDeletion && (
          <div className="space-y-2 rounded-[var(--radius-md)] border border-line bg-surface-2 p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-fg-2">
                Deletion request Â· {formatTimestamp(latestDeletion.created_at)}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 ring-1 ${statusTone(latestDeletion.status)}`}
              >
                {statusLabel(latestDeletion.status)}
              </span>
            </div>
            {latestDeletion.review_note && (
              <p className="text-fg-3">Review note: {latestDeletion.review_note}</p>
            )}
            {latestDeletion.failure_detail && (
              <p className="text-err">{latestDeletion.failure_detail}</p>
            )}
            {latestDeletion.failed_tables.length > 0 && (
              <p className="text-fg-3">
                Tables needing a retry: {latestDeletion.failed_tables.join(', ')}
              </p>
            )}
            {latestDeletion.can_cancel && (
              <button
                type="button"
                onClick={() => void handleCancel(latestDeletion.id)}
                disabled={cancellingId === latestDeletion.id}
                className="inline-flex items-center gap-1 text-xs font-semibold text-accent-strong hover:underline disabled:opacity-60"
              >
                {cancellingId === latestDeletion.id ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <ShieldCheck size={12} />
                )}
                Cancel deletion request
              </button>
            )}
          </div>
        )}
        {!hasOpenDeletion && (
          <div className="space-y-3">
            <label className="block text-xs font-medium text-fg-2" htmlFor="gdpr-deletion-reason">
              Reason (optional)
            </label>
            <textarea
              id="gdpr-deletion-reason"
              value={deletionReason}
              onChange={(event) => setDeletionReason(event.target.value)}
              rows={2}
              maxLength={1000}
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              placeholder="Tell us why you are leaving (optional)"
            />
            <label className="block text-xs font-medium text-fg-2" htmlFor="gdpr-deletion-confirm">
              Type <span className="font-mono font-semibold">{expectedConfirmation}</span> to confirm
            </label>
            <input
              id="gdpr-deletion-confirm"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="off"
              className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-sm text-fg outline-none focus:border-accent"
              placeholder={expectedConfirmation}
            />
            <button
              type="button"
              onClick={() => void handleDeletionRequest()}
              disabled={!confirmationMatches || deleting}
              className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-err px-4 py-2 text-sm font-semibold text-err-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              {deleting ? 'Submittingâ€¦' : 'Request account deletion'}
            </button>
            <p className="text-[11px] text-fg-3">
              If your session is older than {policy?.reauth_max_age_minutes ?? 15} minutes, sign out
              and back in first.
            </p>
          </div>
        )}
      </div>

      {notice && (
        <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-xs text-ok ring-1 ring-ok/20">
          {notice}
        </p>
      )}
      {error && (
        <p className="flex items-start gap-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-xs text-err ring-1 ring-err/20">
          <CircleAlert size={14} className="mt-0.5 shrink-0" />
          {error}
        </p>
      )}
    </div>
  )
}

