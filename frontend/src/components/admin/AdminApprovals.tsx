'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    Ban,
    CheckCircle2,
    CircleAlert,
    Loader2,
    PlayCircle,
    RefreshCw,
    ShieldCheck,
    XCircle,
} from 'lucide-react'
import {
    apiClient,
    type AdminApproval,
    type AdminApprovalRequestType,
    type AdminApprovalStatus,
} from '@/lib/api-client'
import { formatDateTime, shortId } from './admin-format'

const STATUS_OPTIONS: Array<{ value: AdminApprovalStatus | 'all'; label: string }> = [
    { value: 'pending', label: 'Pending approval' },
    { value: 'approved', label: 'Approved / ready' },
    { value: 'executing', label: 'Executing' },
    { value: 'executed', label: 'Executed' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'failed', label: 'Failed' },
    { value: 'expired', label: 'Expired' },
    { value: 'cancelled', label: 'Cancelled' },
    { value: 'all', label: 'All statuses' },
]

const TYPE_LABELS: Record<AdminApprovalRequestType, string> = {
    refund: 'Refund',
    account_deletion: 'Account deletion',
    impersonation: 'Impersonation / view-as',
    role_escalation: 'Role escalation',
    bulk_entitlement_change: 'Bulk entitlement change',
    abuse_review_action: 'Abuse review enforcement',
}

function statusTone(status: AdminApprovalStatus): string {
    if (status === 'executed') return 'bg-ok/10 text-ok ring-ok/20'
    if (status === 'approved') return 'bg-accent-soft text-accent-strong ring-accent/20'
    if (status === 'pending' || status === 'executing') return 'bg-surface-2 text-fg-2 ring-line'
    return 'bg-err/10 text-err ring-err/20'
}

function payloadSummary(approval: AdminApproval): string {
    const payload = approval.payload || {}
    if (approval.request_type === 'role_escalation') {
        return `Promote ${String(payload.target_user_id || '')} from ${String(
            payload.previous_role || ''
        )} to ${String(payload.new_role || '')}`
    }
    if (approval.request_type === 'refund') {
        return `Refund ${String(payload.amount ?? 'full')} ${
            payload.currency ? String(payload.currency) : ''
        } for payment ${String(payload.payment_id || '')}`.trim()
    }
    if (approval.request_type === 'account_deletion') {
        return `Delete account ${String(payload.user_id || '')} via GDPR request ${String(
            payload.gdpr_request_id || ''
        )}`
    }
    if (approval.request_type === 'bulk_entitlement_change') {
        const changes = Array.isArray(payload.changes) ? payload.changes.length : 0
        return `${changes} entitlement cell${changes === 1 ? '' : 's'} in one atomic change`
    }
    if (approval.request_type === 'impersonation') {
        return `Read-only view-as snapshot for ${String(payload.target_user_id || '')}`
    }
    if (approval.request_type === 'abuse_review_action') {
        const action = String(payload.action || 'action')
        const subject = String(payload.subject_key || '').slice(0, 12)
        return `${action} device subject ${subject} for queue item ${String(
            payload.queue_item_id || ''
        )}`
    }
    return 'Reserved request type'
}

export default function AdminApprovals() {
    const [items, setItems] = useState<AdminApproval[]>([])
    const [total, setTotal] = useState(0)
    const [counts, setCounts] = useState<Record<string, number>>({})
    const [status, setStatus] = useState<AdminApprovalStatus | 'all'>('pending')
    const [requestType, setRequestType] = useState<'' | AdminApprovalRequestType>('')
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [note, setNote] = useState('')
    const [cancelReason, setCancelReason] = useState('')
    const [escalationTarget, setEscalationTarget] = useState('')
    const [escalationPrevious, setEscalationPrevious] = useState<'user' | 'support'>('user')
    const [escalationReason, setEscalationReason] = useState('')
    const [loading, setLoading] = useState(true)
    const [busy, setBusy] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [notice, setNotice] = useState<string | null>(null)

    const selected = useMemo(
        () => items.find(item => item.id === selectedId) ?? null,
        [items, selectedId]
    )
    const pendingCount = counts.pending ?? 0

    const reload = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminApprovals({
                status,
                request_type: requestType || undefined,
                limit: 100,
            })
            setItems(next.items)
            setTotal(next.total)
            setCounts(next.counts)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not load the approval queue')
        } finally {
            setLoading(false)
        }
    }, [requestType, status])

    useEffect(() => {
        void reload()
    }, [reload])

    const runAction = async (action: string, fn: () => Promise<unknown>, success: string) => {
        setBusy(action)
        setError(null)
        setNotice(null)
        try {
            await fn()
            setNotice(success)
            setNote('')
            setCancelReason('')
            await reload()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Action failed')
        } finally {
            setBusy(null)
        }
    }

    const decide = (decision: 'approve' | 'reject') => {
        if (!selected) return
        if (note.trim().length < 3) {
            setError('A decision note of at least 3 characters is required')
            return
        }
        void runAction(
            `decision:${decision}`,
            () =>
                decision === 'approve'
                    ? apiClient.approveAdminApproval(selected.id, note.trim())
                    : apiClient.rejectAdminApproval(selected.id, note.trim()),
            decision === 'approve'
                ? 'Approved. A different admin must still execute the action.'
                : 'Request rejected.'
        )
    }

    const execute = () => {
        if (!selected) return
        void runAction(
            'execute',
            () => apiClient.executeAdminApproval(selected.id, note.trim() || undefined),
            'Approved action executed once.'
        )
    }

    const cancel = () => {
        if (!selected) return
        if (cancelReason.trim().length < 3) {
            setError('A cancellation reason of at least 3 characters is required')
            return
        }
        void runAction(
            'cancel',
            () => apiClient.cancelAdminApproval(selected.id, cancelReason.trim()),
            'Request cancelled.'
        )
    }

    const requestEscalation = () => {
        if (!escalationTarget.trim() || escalationReason.trim().length < 3) {
            setError('A target user id and a reason of at least 3 characters are required')
            return
        }
        void runAction(
            'request-escalation',
            () =>
                apiClient.createAdminApproval({
                    request_type: 'role_escalation',
                    payload: {
                        target_user_id: escalationTarget.trim(),
                        previous_role: escalationPrevious,
                        new_role: 'admin',
                    },
                    reason: escalationReason.trim(),
                    expires_in_hours: 24,
                }),
            'Escalation requested. A different admin must approve it before the role can change.'
        )
        setEscalationTarget('')
        setEscalationReason('')
    }

    const canExecuteHere =
        selected?.can_execute &&
        [
            'refund',
            'account_deletion',
            'role_escalation',
            'bulk_entitlement_change',
            'abuse_review_action',
        ].includes(selected.request_type)

    return (
        <div id="admin-approvals" className="space-y-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h2 className="text-lg font-semibold text-fg">Two-person approvals</h2>
                    <p className="text-xs text-fg-3">
                        Sensitive actions are requested by one admin and approved by a different
                        admin. The requester cannot approve their own request. Execution is bound to
                        the approved payload hash and can happen only once. Every transition is in
                        the append-only admin audit log.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <span className="rounded-full bg-accent-soft px-3 py-1 text-xs font-semibold text-accent-strong">
                        {pendingCount} pending
                    </span>
                    <button
                        type="button"
                        onClick={() => void reload()}
                        disabled={loading}
                        className="inline-flex items-center gap-2 rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:opacity-60"
                    >
                        {loading ? (
                            <Loader2 size={13} className="animate-spin" />
                        ) : (
                            <RefreshCw size={13} />
                        )}
                        Refresh
                    </button>
                </div>
            </div>

            <div className="flex flex-wrap gap-2">
                <select
                    aria-label="Filter approvals by status"
                    value={status}
                    onChange={event => setStatus(event.target.value as AdminApprovalStatus | 'all')}
                    className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
                >
                    {STATUS_OPTIONS.map(option => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
                <select
                    aria-label="Filter approvals by request type"
                    value={requestType}
                    onChange={event =>
                        setRequestType(event.target.value as '' | AdminApprovalRequestType)
                    }
                    className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
                >
                    <option value="">All request types</option>
                    {Object.entries(TYPE_LABELS).map(([value, label]) => (
                        <option key={value} value={value}>
                            {label}
                        </option>
                    ))}
                </select>
                <span className="self-center text-xs text-fg-3">{total} matching approval(s)</span>
            </div>

            <details className="rounded-[var(--radius-lg)] border border-line bg-surface p-3">
                <summary className="cursor-pointer text-xs font-semibold text-fg-2">
                    Request a role escalation
                </summary>
                <div className="mt-3 grid gap-2 md:grid-cols-[1fr_160px]">
                    <input
                        aria-label="Target user id for role escalation"
                        value={escalationTarget}
                        onChange={event => setEscalationTarget(event.target.value)}
                        className="rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-xs text-fg outline-none focus:border-accent"
                        placeholder="Target user UUID"
                    />
                    <select
                        aria-label="Target user's current role"
                        value={escalationPrevious}
                        onChange={event =>
                            setEscalationPrevious(event.target.value as 'user' | 'support')
                        }
                        className="rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg"
                    >
                        <option value="user">Currently user</option>
                        <option value="support">Currently support</option>
                    </select>
                    <input
                        aria-label="Reason for role escalation"
                        value={escalationReason}
                        onChange={event => setEscalationReason(event.target.value)}
                        className="rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent md:col-span-2"
                        placeholder="Why this user needs admin access"
                    />
                    <button
                        type="button"
                        onClick={requestEscalation}
                        disabled={busy !== null}
                        className="justify-self-start rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60 md:col-span-2"
                    >
                        Request approval
                    </button>
                </div>
            </details>

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
                                <th className="px-3 py-2 font-medium">Action</th>
                                <th className="px-3 py-2 font-medium">Requester</th>
                                <th className="px-3 py-2 font-medium">Status</th>
                                <th className="px-3 py-2 font-medium">Expires</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items.map(item => (
                                <tr
                                    key={item.id}
                                    onClick={() => {
                                        setSelectedId(item.id)
                                        setNote('')
                                        setCancelReason('')
                                        setError(null)
                                    }}
                                    className={`cursor-pointer border-t border-line hover:bg-surface-2 ${
                                        selectedId === item.id ? 'bg-surface-2' : ''
                                    }`}
                                >
                                    <td className="px-3 py-2">
                                        <p className="font-medium text-fg">
                                            {TYPE_LABELS[item.request_type]}
                                        </p>
                                        <p className="text-[10px] text-fg-3">
                                            {payloadSummary(item)}
                                        </p>
                                        <p className="font-mono text-[10px] text-fg-3">
                                            {shortId(item.id)}
                                        </p>
                                    </td>
                                    <td className="px-3 py-2 font-mono text-[10px] text-fg-2">
                                        {shortId(item.requested_by)}
                                    </td>
                                    <td className="px-3 py-2">
                                        <span
                                            className={`inline-flex rounded-full px-2 py-0.5 ring-1 ${statusTone(item.status)}`}
                                        >
                                            {item.status.replace(/_/g, ' ')}
                                        </span>
                                    </td>
                                    <td className="px-3 py-2 text-fg-3">
                                        {formatDateTime(item.expires_at)}
                                    </td>
                                </tr>
                            ))}
                            {!items.length && !loading && (
                                <tr>
                                    <td colSpan={4} className="px-3 py-6 text-center text-fg-3">
                                        No approvals match this filter.
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
                                        {TYPE_LABELS[selected.request_type]}
                                    </p>
                                    <p className="font-mono text-[10px] text-fg-3">{selected.id}</p>
                                </div>
                                <span
                                    className={`rounded-full px-2 py-0.5 text-[10px] ring-1 ${statusTone(selected.status)}`}
                                >
                                    {selected.status.replace(/_/g, ' ')}
                                </span>
                            </div>

                            <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                {payloadSummary(selected)}
                            </p>

                            <dl className="grid grid-cols-2 gap-2 text-xs">
                                <div>
                                    <dt className="text-fg-3">Requested by</dt>
                                    <dd className="break-all font-mono text-[10px] text-fg-2">
                                        {selected.requested_by}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Approved by</dt>
                                    <dd className="break-all font-mono text-[10px] text-fg-2">
                                        {selected.approved_by || 'awaiting a second admin'}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Requested</dt>
                                    <dd className="text-fg-2">
                                        {formatDateTime(selected.requested_at)}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Expires</dt>
                                    <dd className="text-fg-2">
                                        {formatDateTime(selected.expires_at)}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Payload hash</dt>
                                    <dd className="break-all font-mono text-[10px] text-fg-2">
                                        {selected.payload_hash}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Executed by</dt>
                                    <dd className="break-all font-mono text-[10px] text-fg-2">
                                        {selected.executed_by || 'not executed'}
                                    </dd>
                                </div>
                            </dl>

                            <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                Reason: {selected.reason}
                            </p>
                            {selected.decision_note && (
                                <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                    Decision note: {selected.decision_note}
                                </p>
                            )}
                            {selected.execution_note && (
                                <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                    Execution note: {selected.execution_note}
                                </p>
                            )}
                            {selected.is_expired && (
                                <p className="flex items-center gap-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-xs text-err">
                                    <CircleAlert size={14} /> Expired approvals cannot be replayed.
                                    Request a new approval for the current state.
                                </p>
                            )}

                            {selected.can_approve && (
                                <div className="space-y-2">
                                    <label
                                        className="block text-xs font-medium text-fg-2"
                                        htmlFor="approval-note"
                                    >
                                        Decision note
                                    </label>
                                    <textarea
                                        id="approval-note"
                                        value={note}
                                        onChange={event => setNote(event.target.value)}
                                        rows={3}
                                        maxLength={1000}
                                        className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                                        placeholder="Why this action is justified and safe to approve"
                                    />
                                    <div className="flex flex-wrap gap-2">
                                        <button
                                            type="button"
                                            onClick={() => decide('approve')}
                                            disabled={busy !== null}
                                            className="inline-flex items-center gap-1 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60"
                                        >
                                            <ShieldCheck size={13} /> Approve
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => decide('reject')}
                                            disabled={busy !== null}
                                            className="inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-err/40 px-3 py-2 text-xs font-semibold text-err disabled:opacity-60"
                                        >
                                            <XCircle size={13} /> Reject
                                        </button>
                                    </div>
                                </div>
                            )}

                            {canExecuteHere && (
                                <div className="space-y-2">
                                    <label
                                        className="block text-xs font-medium text-fg-2"
                                        htmlFor="execution-note"
                                    >
                                        Execution note (optional)
                                    </label>
                                    <textarea
                                        id="execution-note"
                                        value={note}
                                        onChange={event => setNote(event.target.value)}
                                        rows={2}
                                        maxLength={1000}
                                        className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                                        placeholder="Operator reference for this execution"
                                    />
                                    <button
                                        type="button"
                                        onClick={execute}
                                        disabled={busy !== null}
                                        className="inline-flex items-center gap-1 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60"
                                    >
                                        {busy === 'execute' ? (
                                            <Loader2 size={13} className="animate-spin" />
                                        ) : (
                                            <PlayCircle size={13} />
                                        )}
                                        Execute once
                                    </button>
                                </div>
                            )}

                            {selected.can_execute && selected.request_type === 'impersonation' && (
                                <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                    Approved. Start this read-only preview from the View-as panel at the top
                                    of the admin page. The approval can start exactly one session.
                                </p>
                            )}

                            {selected.status === 'pending' && (
                                <div className="space-y-2 border-t border-line pt-3">
                                    <label
                                        className="block text-xs font-medium text-fg-2"
                                        htmlFor="cancel-reason"
                                    >
                                        Cancel request
                                    </label>
                                    <input
                                        id="cancel-reason"
                                        value={cancelReason}
                                        onChange={event => setCancelReason(event.target.value)}
                                        maxLength={1000}
                                        className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                                        placeholder="Reason for withdrawing this request"
                                    />
                                    <button
                                        type="button"
                                        onClick={cancel}
                                        disabled={busy !== null}
                                        className="inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:opacity-60"
                                    >
                                        <Ban size={13} /> Cancel request
                                    </button>
                                </div>
                            )}

                            {selected.status === 'executed' && (
                                <p className="flex items-center gap-2 rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-xs text-ok">
                                    <CheckCircle2 size={14} /> Execution completed once and cannot
                                    be replayed.
                                </p>
                            )}
                        </div>
                    ) : (
                        <p className="text-xs text-fg-3">
                            Select an approval to review its bounded action summary.
                        </p>
                    )}
                </div>
            </div>
        </div>
    )
}
