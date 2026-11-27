'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    Ban,
    CheckCircle2,
    CircleAlert,
    Loader2,
    RefreshCw,
    ScanSearch,
    ShieldCheck,
    UserCheck,
    XCircle,
} from 'lucide-react'
import {
    apiClient,
    type AdminAbuseDecision,
    type AdminAbuseEnforcementAction,
    type AdminAbuseQueueItem,
    type AdminAbuseQueueList,
    type AdminAbuseSeverity,
    type AdminAbuseSignalType,
    type AdminAbuseStatus,
} from '@/lib/api-client'
import { formatDateTime, shortId } from './admin-format'

const STATUS_OPTIONS: Array<{ value: AdminAbuseStatus | 'all'; label: string }> = [
    { value: 'open', label: 'Open review' },
    { value: 'approved', label: 'Acknowledged' },
    { value: 'dismissed', label: 'Dismissed' },
    { value: 'actioned', label: 'Actioned' },
    { value: 'all', label: 'All statuses' },
]

const SEVERITY_OPTIONS: Array<{ value: AdminAbuseSeverity | ''; label: string }> = [
    { value: '', label: 'All severities' },
    { value: 'critical', label: 'Critical' },
    { value: 'high', label: 'High' },
    { value: 'medium', label: 'Medium' },
    { value: 'low', label: 'Low' },
]

const SIGNAL_OPTIONS: Array<{ value: AdminAbuseSignalType | ''; label: string }> = [
    { value: '', label: 'All signal types' },
    { value: 'blocked_device', label: 'Blocked device' },
    { value: 'trial_limit_reached', label: 'Trial limit reached' },
    { value: 'repeat_ip_cluster', label: 'Repeat hashed-IP cluster' },
    { value: 'trial_velocity', label: 'Trial velocity cluster' },
    { value: 'payment_failure', label: 'Repeated payment failures' },
    { value: 'referral_rejection', label: 'Referral rejection reason' },
    { value: 'coupon_reuse', label: 'Coupon release churn' },
    { value: 'rate_limit_pressure', label: 'Usage velocity pressure' },
]

const ACTION_LABELS: Record<AdminAbuseEnforcementAction, string> = {
    block: 'Block device',
    unblock: 'Unblock device',
    whitelist: 'Whitelist device',
}

function severityTone(severity: AdminAbuseSeverity): string {
    if (severity === 'critical') return 'bg-err/15 text-err ring-err/30'
    if (severity === 'high') return 'bg-err/10 text-err ring-err/20'
    if (severity === 'medium') return 'bg-warn/10 text-warn ring-warn/20'
    return 'bg-surface-2 text-fg-2 ring-line'
}

function statusTone(status: AdminAbuseStatus): string {
    if (status === 'actioned') return 'bg-ok/10 text-ok ring-ok/20'
    if (status === 'approved') return 'bg-accent-soft text-accent-strong ring-accent/20'
    if (status === 'dismissed') return 'bg-surface-2 text-fg-3 ring-line'
    return 'bg-warn/10 text-warn ring-warn/20'
}

function evidenceValue(value: unknown): string {
    if (typeof value === 'boolean') return value ? 'yes' : 'no'
    if (value === null || value === undefined) return '—'
    if (typeof value === 'number') return String(value)
    if (typeof value === 'string') return value
    return JSON.stringify(value)
}

export default function AdminAbuseQueue() {
    const [data, setData] = useState<AdminAbuseQueueList | null>(null)
    const [status, setStatus] = useState<AdminAbuseStatus | 'all'>('open')
    const [severity, setSeverity] = useState<AdminAbuseSeverity | ''>('')
    const [signalType, setSignalType] = useState<AdminAbuseSignalType | ''>('')
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [reason, setReason] = useState('')
    const [confirm, setConfirm] = useState(false)
    const [assignee, setAssignee] = useState('')
    const [approvalId, setApprovalId] = useState('')
    const [pendingApprovalId, setPendingApprovalId] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)
    const [busy, setBusy] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [notice, setNotice] = useState<string | null>(null)

    const selected = useMemo(
        () => data?.items.find(item => item.id === selectedId) ?? null,
        [data, selectedId]
    )
    const openCount = data?.open_total ?? 0
    const highCount = (data?.by_severity.high ?? 0) + (data?.by_severity.critical ?? 0)

    const reload = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminAbuseQueue({
                status,
                severity: severity || undefined,
                signal_type: signalType || undefined,
                limit: 100,
            })
            setData(next)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not load the abuse review queue')
        } finally {
            setLoading(false)
        }
    }, [severity, signalType, status])

    useEffect(() => {
        void reload()
    }, [reload])

    const run = async (key: string, fn: () => Promise<string | void>, success: string) => {
        setBusy(key)
        setError(null)
        setNotice(null)
        try {
            const message = await fn()
            setNotice(message || success)
            setReason('')
            setConfirm(false)
            await reload()
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Action failed')
        } finally {
            setBusy(null)
        }
    }

    const requireReason = (): string | null => {
        const cleaned = reason.trim()
        if (cleaned.length < 3) {
            setError('Enter a reason of at least 3 characters')
            return null
        }
        if (!confirm) {
            setError('Tick the confirmation box to record this reviewed action')
            return null
        }
        return cleaned
    }

    const scan = () => {
        const cleaned = requireReason()
        if (!cleaned) return
        void run(
            'scan',
            async () => {
                await apiClient.scanAdminAbuseQueue({
                    window_days: 30,
                    reason: cleaned,
                    confirm: true,
                })
            },
            'Signals aggregated into the queue. No account was punished automatically.'
        )
    }

    const assign = () => {
        const cleaned = requireReason()
        if (!cleaned) return
        if (!selected) return
        void run(
            'assign',
            async () => {
                await apiClient.assignAdminAbuseItem(selected.id, {
                    assignee_id: assignee.trim() || null,
                    reason: cleaned,
                    confirm: true,
                })
            },
            assignee.trim() ? 'Reviewer assigned.' : 'Reviewer unassigned.'
        )
    }

    const decide = (decision: AdminAbuseDecision, action?: AdminAbuseEnforcementAction) => {
        const cleaned = requireReason()
        if (!cleaned || !selected) return
        const key = action ? `action:${action}` : `decision:${decision}`
        void run(
            key,
            async () => {
                const result = await apiClient.decideAdminAbuseItem(selected.id, {
                    decision,
                    action,
                    reason: cleaned,
                    confirm: true,
                    approval_id: approvalId.trim() || undefined,
                })
                if (result.approval_required && result.approval) {
                    setPendingApprovalId(result.approval.id)
                    return `Enforcement approval ${shortId(
                        result.approval.id
                    )} requested. A different admin must approve it in the Approvals tab, then paste the approval id here and retry.`
                }
                setPendingApprovalId(null)
                setApprovalId('')
                return result.idempotent
                    ? 'This decision was already recorded.'
                    : action
                      ? 'Approved enforcement applied to the hashed device subject only.'
                      : 'Review decision recorded in the append-only audit log.'
            },
            'Review updated.'
        )
    }

    return (
        <div id="admin-abuse-queue" className="space-y-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                    <h2 className="text-lg font-semibold text-fg">Abuse review queue</h2>
                    <p className="text-xs text-fg-3">
                        Aggregate trial, payment, referral, coupon and usage-velocity signals are
                        materialised into one review item per hashed subject and ISO week. Scanning
                        is advisory only. Block, unblock and whitelist require a second admin
                        through the two-person approval queue.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <span className="rounded-full bg-warn/10 px-3 py-1 text-xs font-semibold text-warn">
                        {openCount} open
                    </span>
                    <span className="rounded-full bg-err/10 px-3 py-1 text-xs font-semibold text-err">
                        {highCount} high/critical
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
                    aria-label="Filter abuse signals by status"
                    value={status}
                    onChange={event => setStatus(event.target.value as AdminAbuseStatus | 'all')}
                    className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
                >
                    {STATUS_OPTIONS.map(option => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
                <select
                    aria-label="Filter abuse signals by severity"
                    value={severity}
                    onChange={event => setSeverity(event.target.value as AdminAbuseSeverity | '')}
                    className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
                >
                    {SEVERITY_OPTIONS.map(option => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
                <select
                    aria-label="Filter abuse signals by type"
                    value={signalType}
                    onChange={event =>
                        setSignalType(event.target.value as AdminAbuseSignalType | '')
                    }
                    className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-xs text-fg"
                >
                    {SIGNAL_OPTIONS.map(option => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
                <span className="self-center text-xs text-fg-3">
                    {data?.total ?? 0} matching signal(s)
                </span>
            </div>

            <div className="grid gap-3 rounded-[var(--radius-lg)] border border-line bg-surface p-3 md:grid-cols-[1fr_auto]">
                <div className="grid gap-2">
                    <input
                        aria-label="Reason for the abuse scan or review action"
                        value={reason}
                        onChange={event => setReason(event.target.value)}
                        maxLength={1000}
                        className="rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                        placeholder="Reason (required for every scan, assignment and decision)"
                    />
                    <label className="flex items-center gap-2 text-xs text-fg-2">
                        <input
                            type="checkbox"
                            checked={confirm}
                            onChange={event => setConfirm(event.target.checked)}
                            className="h-4 w-4 rounded border-line"
                        />
                        I reviewed the aggregate evidence and confirm this action.
                    </label>
                </div>
                <button
                    type="button"
                    onClick={scan}
                    disabled={busy !== null}
                    className="inline-flex items-center justify-center gap-2 self-start rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60"
                >
                    {busy === 'scan' ? (
                        <Loader2 size={13} className="animate-spin" />
                    ) : (
                        <ScanSearch size={13} />
                    )}
                    Aggregate signals
                </button>
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

            <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
                <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
                    <table className="w-full text-left text-xs">
                        <thead className="bg-surface-2 text-fg-3">
                            <tr>
                                <th className="px-3 py-2 font-medium">Signal</th>
                                <th className="px-3 py-2 font-medium">Subject</th>
                                <th className="px-3 py-2 font-medium">Severity</th>
                                <th className="px-3 py-2 font-medium">Status</th>
                                <th className="px-3 py-2 font-medium">Last seen</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data?.items.map(item => (
                                <tr
                                    key={item.id}
                                    onClick={() => {
                                        setSelectedId(item.id)
                                        setPendingApprovalId(null)
                                        setApprovalId('')
                                        setAssignee('')
                                        setError(null)
                                    }}
                                    className={`cursor-pointer border-t border-line hover:bg-surface-2 ${
                                        selectedId === item.id ? 'bg-surface-2' : ''
                                    }`}
                                >
                                    <td className="px-3 py-2">
                                        <p className="font-medium text-fg">{item.signal_label}</p>
                                        <p className="text-[10px] text-fg-3">
                                            {item.occurrence_count} occurrence(s) ·{' '}
                                            {item.window_days}d window
                                        </p>
                                        <p className="font-mono text-[10px] text-fg-3">
                                            {shortId(item.id)}
                                        </p>
                                    </td>
                                    <td className="px-3 py-2 font-mono text-[10px] text-fg-2">
                                        {item.subject_type} · {item.subject_ref}
                                    </td>
                                    <td className="px-3 py-2">
                                        <span
                                            className={`inline-flex rounded-full px-2 py-0.5 ring-1 ${severityTone(item.severity)}`}
                                        >
                                            {item.severity}
                                        </span>
                                    </td>
                                    <td className="px-3 py-2">
                                        <span
                                            className={`inline-flex rounded-full px-2 py-0.5 ring-1 ${statusTone(item.status)}`}
                                        >
                                            {item.status}
                                        </span>
                                    </td>
                                    <td className="px-3 py-2 text-fg-3">
                                        {formatDateTime(item.last_seen_at)}
                                    </td>
                                </tr>
                            ))}
                            {!data?.items.length && !loading && (
                                <tr>
                                    <td colSpan={5} className="px-3 py-6 text-center text-fg-3">
                                        No review items match this filter. Run an aggregate scan to
                                        refresh signals.
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
                                        {selected.signal_label}
                                    </p>
                                    <p className="font-mono text-[10px] text-fg-3">{selected.id}</p>
                                </div>
                                <span
                                    className={`rounded-full px-2 py-0.5 text-[10px] ring-1 ${statusTone(selected.status)}`}
                                >
                                    {selected.status}
                                </span>
                            </div>

                            <dl className="grid grid-cols-2 gap-2 text-xs">
                                <div>
                                    <dt className="text-fg-3">Subject hash</dt>
                                    <dd className="break-all font-mono text-[10px] text-fg-2">
                                        {selected.subject_key}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Assigned to</dt>
                                    <dd className="break-all font-mono text-[10px] text-fg-2">
                                        {selected.assigned_to || 'unassigned'}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">First seen</dt>
                                    <dd className="text-fg-2">
                                        {formatDateTime(selected.first_seen_at)}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Last seen</dt>
                                    <dd className="text-fg-2">
                                        {formatDateTime(selected.last_seen_at)}
                                    </dd>
                                </div>
                            </dl>

                            <div className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2">
                                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-fg-3">
                                    Aggregate evidence
                                </p>
                                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                                    {Object.entries(selected.evidence).map(([key, value]) => (
                                        <div key={key} className="contents">
                                            <dt className="text-fg-3">{key.replace(/_/g, ' ')}</dt>
                                            <dd className="text-fg-2">{evidenceValue(value)}</dd>
                                        </div>
                                    ))}
                                </dl>
                                {selected.evidence_links.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-2">
                                        {selected.evidence_links
                                            .filter(link => link.href.startsWith('/admin'))
                                            .map(link => (
                                                <a
                                                    key={`${link.kind}:${link.href}`}
                                                    href={link.href}
                                                    className="rounded-full bg-surface px-2 py-1 text-[10px] font-semibold text-accent-strong ring-1 ring-line hover:bg-surface-2"
                                                >
                                                    {link.label}
                                                </a>
                                            ))}
                                    </div>
                                )}
                            </div>

                            {selected.decision_reason && (
                                <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                    Decision reason: {selected.decision_reason}
                                </p>
                            )}
                            {selected.enforcement_action && (
                                <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-2">
                                    Enforced {selected.enforcement_action} by {selected.decided_by}{' '}
                                    · approval{' '}
                                    <span className="font-mono">
                                        {shortId(selected.approval_id || '')}
                                    </span>
                                </p>
                            )}

                            <div className="border-t border-line pt-3">
                                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-fg-3">
                                    Assignment
                                </p>
                                <div className="flex gap-2">
                                    <input
                                        aria-label="Admin UUID to assign this review item"
                                        value={assignee}
                                        onChange={event => setAssignee(event.target.value)}
                                        className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-[10px] text-fg outline-none focus:border-accent"
                                        placeholder="Admin UUID (blank to unassign)"
                                    />
                                    <button
                                        type="button"
                                        onClick={assign}
                                        disabled={busy !== null}
                                        className="inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:opacity-60"
                                    >
                                        <UserCheck size={13} /> Assign
                                    </button>
                                </div>
                            </div>

                            <div className="space-y-2 border-t border-line pt-3">
                                <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-3">
                                    Review decisions
                                </p>
                                <div className="flex flex-wrap gap-2">
                                    {selected.can_acknowledge && (
                                        <button
                                            type="button"
                                            onClick={() => decide('approve')}
                                            disabled={busy !== null}
                                            className="inline-flex items-center gap-1 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60"
                                        >
                                            <ShieldCheck size={13} /> Acknowledge
                                        </button>
                                    )}
                                    {selected.can_dismiss && (
                                        <button
                                            type="button"
                                            onClick={() => decide('dismiss')}
                                            disabled={busy !== null}
                                            className="inline-flex items-center gap-1 rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:opacity-60"
                                        >
                                            <XCircle size={13} /> Dismiss false positive
                                        </button>
                                    )}
                                </div>
                            </div>

                            {selected.can_enforce && (
                                <div className="space-y-2 border-t border-line pt-3">
                                    <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-3">
                                        Device enforcement (second admin required)
                                    </p>
                                    <p className="text-[10px] text-fg-3">
                                        Unblock clears the block flag; the usage ceiling still
                                        applies. Whitelist also exempts the device from automatic
                                        trial blocking.
                                    </p>
                                    <div className="flex flex-wrap gap-2">
                                        {selected.enforcement_actions.map(action => (
                                            <button
                                                key={action}
                                                type="button"
                                                onClick={() => decide('action', action)}
                                                disabled={busy !== null}
                                                className={`inline-flex items-center gap-1 rounded-[var(--radius-md)] px-3 py-2 text-xs font-semibold disabled:opacity-60 ${
                                                    action === 'block'
                                                        ? 'bg-err/10 text-err ring-1 ring-err/20 hover:bg-err/20'
                                                        : 'bg-accent-soft text-accent-strong ring-1 ring-accent/20 hover:bg-accent/20'
                                                }`}
                                            >
                                                <Ban size={13} /> {ACTION_LABELS[action]}
                                            </button>
                                        ))}
                                    </div>
                                    <input
                                        aria-label="Approved abuse action approval id"
                                        value={approvalId}
                                        onChange={event => setApprovalId(event.target.value)}
                                        className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-[10px] text-fg outline-none focus:border-accent"
                                        placeholder="Paste an approved approval id to execute"
                                    />
                                    {pendingApprovalId && (
                                        <p className="rounded-[var(--radius-md)] bg-warn/10 px-3 py-2 text-xs text-warn ring-1 ring-warn/20">
                                            Waiting on approval{' '}
                                            <span className="font-mono">
                                                {shortId(pendingApprovalId)}
                                            </span>{' '}
                                            in the Approvals tab. A different admin must approve it;
                                            the requester cannot approve their own request.
                                        </p>
                                    )}
                                </div>
                            )}

                            {selected.status === 'actioned' && (
                                <p className="flex items-center gap-2 rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-xs text-ok">
                                    <CheckCircle2 size={14} /> Enforcement completed once and cannot
                                    be replayed.
                                </p>
                            )}
                            {selected.status === 'dismissed' && (
                                <p className="flex items-center gap-2 rounded-[var(--radius-md)] bg-surface-2 px-3 py-2 text-xs text-fg-3">
                                    <Ban size={14} /> Dismissed as a false positive; no enforcement
                                    was applied.
                                </p>
                            )}
                        </div>
                    ) : (
                        <p className="text-xs text-fg-3">
                            Select a signal to review its aggregate evidence. Raw fingerprints, IP
                            addresses, account ids and emails are never included.
                        </p>
                    )}
                </div>
            </div>
        </div>
    )
}
