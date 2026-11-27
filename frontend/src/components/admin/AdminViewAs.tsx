'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { CircleAlert, Eye, Loader2, LockKeyhole, ShieldAlert, Square } from 'lucide-react'
import {
    apiClient,
    type AdminViewAsRequestResult,
    type AdminViewAsSnapshot,
} from '@/lib/api-client'
import {
    VIEW_AS_EVENT,
    clearAdminViewAsSession,
    formatViewAsRemaining,
    readStoredAdminViewAsSession,
    saveAdminViewAsSession,
    viewAsBannerLabel,
    viewAsIsExpired,
    viewAsTimeLeftSeconds,
    type StoredAdminViewAsSession,
} from '@/lib/admin-view-as'
import { formatDateTime, formatNumber, shortId } from './admin-format'

const TIMELINE_LIMIT = 20

function Section({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}) {
    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
            <h4 className="text-sm font-semibold text-fg">{title}</h4>
            {description && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{description}</p>}
            <div className="mt-3">{children}</div>
        </section>
    )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
    return (
        <div className="rounded-md border border-line bg-surface-2/60 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">{label}</p>
            <p className="mt-0.5 text-lg font-semibold text-fg">{value}</p>
            {hint && <p className="text-[10px] text-fg-3">{hint}</p>}
        </div>
    )
}

function ReadOnlySnapshot({ snapshot }: { snapshot: AdminViewAsSnapshot }) {
    const { session, dashboard, plan, usage, support_timeline: timeline } = snapshot
    return (
        <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Stat label="Resumes" value={formatNumber(dashboard.resumes)} />
                <Stat
                    label="Compiles"
                    value={formatNumber(dashboard.compilations)}
                    hint={`${formatNumber(dashboard.failed_compilations)} failed`}
                />
                <Stat label="AI optimizations" value={formatNumber(dashboard.optimizations)} />
                <Stat
                    label="Usage events (30d)"
                    value={formatNumber(dashboard.usage_events_30d)}
                    hint={dashboard.last_activity_at ? `last ${formatDateTime(dashboard.last_activity_at)}` : 'no activity'}
                />
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
                <Section
                    title="Plan and entitlements"
                    description="Effective product plan for the target. Override internals are not copied into this preview."
                >
                    <p className="text-xs text-fg-2">
                        {plan.subscription_plan} · {plan.subscription_status}
                        {plan.trial_used ? ' · trial used' : ' · trial eligible'}
                    </p>
                    <ul className="mt-2 space-y-1">
                        {Object.entries(plan.entitlements.features).slice(0, 12).map(([key, enabled]) => (
                            <li key={key} className="flex items-center justify-between gap-2 text-[11px] text-fg-3">
                                <span className="font-mono">{key}</span>
                                <span className={enabled ? 'text-ok' : 'text-fg-3'}>
                                    {enabled ? 'enabled' : 'off'}
                                </span>
                            </li>
                        ))}
                        {Object.keys(plan.entitlements.features).length === 0 && (
                            <li className="text-[11px] text-fg-3">No gateable feature state available.</li>
                        )}
                    </ul>
                </Section>

                <Section
                    title="Usage actions"
                    description="First-party action names and counts only. No event metadata, IP address or user agent."
                >
                    <ul className="space-y-1">
                        {usage.actions.map((row) => (
                            <li key={row.action} className="flex items-center justify-between gap-2 text-[11px]">
                                <span className="truncate font-mono text-fg-2">{row.action}</span>
                                <span className="shrink-0 text-fg-3">
                                    {formatNumber(row.count)} · {formatDateTime(row.last_at)}
                                </span>
                            </li>
                        ))}
                        {usage.actions.length === 0 && <li className="text-[11px] text-fg-3">No usage events.</li>}
                    </ul>
                </Section>
            </div>

            <Section
                title="Resume list metadata"
                description="Titles, types and timestamps only. Document bodies, LaTeX, prompts and job descriptions are never loaded."
            >
                <ul className="space-y-1">
                    {snapshot.resumes.map((row) => (
                        <li key={row.id} className="flex items-center justify-between gap-3 border-b border-line py-1.5 last:border-0">
                            <span className="truncate text-xs text-fg-2">{row.title || 'Untitled document'}</span>
                            <span className="shrink-0 text-[10px] text-fg-3">
                                {row.document_type || 'resume'} · {formatDateTime(row.updated_at)}
                            </span>
                        </li>
                    ))}
                    {snapshot.resumes.length === 0 && <li className="text-xs text-fg-3">No resumes.</li>}
                </ul>
            </Section>

            <Section
                title="Support timeline"
                description="Billing and operator events for the target. Raw webhook payloads, credentials and document content are excluded."
            >
                <ol className="divide-y divide-line">
                    {timeline.items.map((item) => (
                        <li key={item.id} className="flex flex-wrap items-start justify-between gap-2 py-2">
                            <div className="min-w-0">
                                <p className="text-xs text-fg-2">{item.summary || item.event_type || 'Event'}</p>
                                <p className="text-[10px] text-fg-3">
                                    {item.kind.replace(/_/g, ' ')} · {formatDateTime(item.occurred_at)}
                                    {item.status ? ` · ${item.status}` : ''}
                                    {item.reference ? ` · ${shortId(item.reference, 20)}` : ''}
                                </p>
                            </div>
                            {item.amount_minor != null && (
                                <span className="font-mono text-[11px] text-fg">
                                    {formatNumber(item.amount_minor / 100)} {item.currency || ''}
                                </span>
                            )}
                        </li>
                    ))}
                    {timeline.items.length === 0 && <li className="py-2 text-xs text-fg-3">No timeline events.</li>}
                </ol>
                <p className="mt-2 text-[10px] text-fg-3">
                    {formatNumber(timeline.total)} visible event(s) · newest first
                </p>
            </Section>

            <p className="rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
                {session.banner} {snapshot.limitations}
            </p>
        </div>
    )
}

export default function AdminViewAs({ canAdmin = true }: { canAdmin?: boolean }) {
    const [active, setActive] = useState<StoredAdminViewAsSession | null>(null)
    const [snapshot, setSnapshot] = useState<AdminViewAsSnapshot | null>(null)
    const [now, setNow] = useState(() => Date.now())
    const [targetId, setTargetId] = useState('')
    const [minutes, setMinutes] = useState(15)
    const [reason, setReason] = useState('')
    const [approvalId, setApprovalId] = useState('')
    const [startNote, setStartNote] = useState('')
    const [endReason, setEndReason] = useState('')
    const [requested, setRequested] = useState<AdminViewAsRequestResult | null>(null)
    const [loading, setLoading] = useState(false)
    const [busy, setBusy] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [notice, setNotice] = useState<string | null>(null)

    const loadSnapshot = useCallback(async (stored: StoredAdminViewAsSession) => {
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminViewAsSnapshot(stored.session.id, stored.token, {
                timelineLimit: TIMELINE_LIMIT,
            })
            setSnapshot(next)
            setNow(Date.now())
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Could not load the view-as snapshot'
            if (message.includes('view_as_expired') || message.includes('expired')) {
                clearAdminViewAsSession()
                setActive(null)
                setSnapshot(null)
                setNotice('The read-only view-as session expired and was closed.')
            } else {
                setError(message)
            }
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        if (!canAdmin) return
        const stored = readStoredAdminViewAsSession()
        setActive(stored)
        if (stored) void loadSnapshot(stored)
    }, [canAdmin, loadSnapshot])

    useEffect(() => {
        const onChanged = () => {
            const stored = readStoredAdminViewAsSession()
            setActive(stored)
            if (stored) void loadSnapshot(stored)
            if (!stored) setSnapshot(null)
        }
        window.addEventListener(VIEW_AS_EVENT, onChanged)
        window.addEventListener('storage', onChanged)
        return () => {
            window.removeEventListener(VIEW_AS_EVENT, onChanged)
            window.removeEventListener('storage', onChanged)
        }
    }, [loadSnapshot])

    useEffect(() => {
        if (!active) return
        const timer = window.setInterval(() => setNow(Date.now()), 1000)
        return () => window.clearInterval(timer)
    }, [active])

    useEffect(() => {
        if (!active) return
        if (!viewAsIsExpired(active.session.expires_at, now)) return
        clearAdminViewAsSession()
        setActive(null)
        setSnapshot(null)
        setNotice('The read-only view-as session expired and was closed.')
    }, [active, now])

    const remaining = useMemo(
        () => (active ? formatViewAsRemaining(viewAsTimeLeftSeconds(active.session.expires_at, now)) : '00:00'),
        [active, now],
    )

    if (!canAdmin) return null

    const requestViewAs = async () => {
        if (!targetId.trim() || reason.trim().length < 3) {
            setError('A target user id and a reason of at least 3 characters are required')
            return
        }
        setBusy('request')
        setError(null)
        setNotice(null)
        try {
            const next = await apiClient.requestAdminViewAs({
                target_user_id: targetId.trim(),
                reason: reason.trim(),
                expires_in_minutes: minutes,
            })
            setRequested(next)
            setApprovalId(next.approval.id)
            setNotice('Approval requested. A different admin must approve it before starting.')
            setReason('')
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not request view-as')
        } finally {
            setBusy(null)
        }
    }

    const startViewAs = async () => {
        if (!approvalId.trim()) {
            setError('Paste the approved two-person approval id first')
            return
        }
        setBusy('start')
        setError(null)
        setNotice(null)
        try {
            const started = await apiClient.startAdminViewAsSession({
                approval_id: approvalId.trim(),
                note: startNote.trim() || undefined,
            })
            saveAdminViewAsSession(started.session, started.token)
            const stored = { session: started.session, token: started.token }
            setActive(stored)
            setSnapshot(null)
            setNotice('Read-only preview started. The write guard is active for this token.')
            setStartNote('')
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not start view-as')
        } finally {
            setBusy(null)
        }
    }

    const endViewAs = async () => {
        if (!active) return
        if (endReason.trim().length < 3) {
            setError('An end reason of at least 3 characters is required')
            return
        }
        setBusy('end')
        setError(null)
        setNotice(null)
        try {
            await apiClient.endAdminViewAsSession(active.session.id, endReason.trim())
            clearAdminViewAsSession()
            setActive(null)
            setSnapshot(null)
            setEndReason('')
            setNotice('Read-only preview ended and audited.')
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not end view-as')
        } finally {
            setBusy(null)
        }
    }

    return (
        <div className="mb-6 space-y-4">
            {active && (
                <div
                    role="status"
                    aria-live="polite"
                    className="sticky top-0 z-40 rounded-[var(--radius-lg)] border-2 border-warn/50 bg-warn/10 px-4 py-3 shadow-lg backdrop-blur"
                >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                            <p className="flex items-center gap-2 text-sm font-semibold text-warn">
                                <ShieldAlert size={16} /> READ-ONLY VIEW-AS
                            </p>
                            <p className="mt-1 break-all text-xs text-fg-2">
                                {viewAsBannerLabel(active.session, now)}
                            </p>
                            <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                                Target {active.session.target.id} · started {formatDateTime(active.session.created_at)} ·
                                scope is read-only. Writes are refused; credentials and document content are excluded.
                            </p>
                        </div>
                        <div className="flex w-full max-w-sm flex-col gap-2 sm:w-auto">
                            <input
                                aria-label="Reason for ending the view-as session"
                                value={endReason}
                                onChange={(event) => setEndReason(event.target.value)}
                                maxLength={1000}
                                placeholder="Reason for ending this preview"
                                className="rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                            />
                            <button
                                type="button"
                                onClick={() => void endViewAs()}
                                disabled={busy !== null}
                                className="inline-flex items-center justify-center gap-1 rounded-[var(--radius-md)] border border-err/40 px-3 py-2 text-xs font-semibold text-err hover:bg-err/5 disabled:opacity-60"
                            >
                                {busy === 'end' ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                                End view-as ({remaining})
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {(error || notice) && (
                <div className="space-y-2">
                    {error && (
                        <p className="flex items-start gap-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-xs text-err ring-1 ring-err/20">
                            <CircleAlert size={14} className="mt-0.5 shrink-0" /> {error}
                        </p>
                    )}
                    {notice && (
                        <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-xs text-ok ring-1 ring-ok/20">
                            {notice}
                        </p>
                    )}
                </div>
            )}

            {!active && (
                <details className="rounded-[var(--radius-lg)] border border-line bg-surface p-3">
                    <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-fg">
                        <Eye size={15} /> Audited read-only view-as user
                    </summary>
                    <p className="mt-2 text-xs leading-relaxed text-fg-3">
                        Request a second-admin approval for one explicit target. An approval can start exactly one
                        preview; the token expires within 15 minutes and every write carrying it is refused. This is a
                        server-composed snapshot, not a target-user login.
                    </p>

                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                        <div className="rounded-md border border-line bg-surface-2/40 p-3">
                            <p className="text-xs font-semibold text-fg">1. Request approval</p>
                            <div className="mt-2 space-y-2">
                                <input
                                    aria-label="View-as target user id"
                                    value={targetId}
                                    onChange={(event) => setTargetId(event.target.value)}
                                    placeholder="Target user UUID"
                                    className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-xs text-fg outline-none focus:border-accent"
                                />
                                <div className="flex gap-2">
                                    <select
                                        aria-label="View-as approval duration"
                                        value={minutes}
                                        onChange={(event) => setMinutes(Number(event.target.value))}
                                        className="rounded-[var(--radius-md)] border border-line bg-bg px-2 py-2 text-xs text-fg"
                                    >
                                        <option value={5}>5 minutes</option>
                                        <option value={10}>10 minutes</option>
                                        <option value={15}>15 minutes</option>
                                    </select>
                                    <input
                                        aria-label="Reason for view-as"
                                        value={reason}
                                        onChange={(event) => setReason(event.target.value)}
                                        maxLength={1000}
                                        placeholder="Ticket or incident reason"
                                        className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                                    />
                                </div>
                                <button
                                    type="button"
                                    onClick={() => void requestViewAs()}
                                    disabled={busy !== null}
                                    className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-60"
                                >
                                    {busy === 'request' ? 'Requesting…' : 'Request approval'}
                                </button>
                                {requested && (
                                    <div className="rounded-md border border-line bg-bg px-3 py-2 text-[11px] text-fg-2">
                                        <p>
                                            Target {requested.target.id} · {requested.target.email || 'masked email'}
                                        </p>
                                        <p className="mt-1 break-all font-mono text-[10px] text-fg-3">
                                            Approval {requested.approval.id}
                                        </p>
                                        <p className="mt-1 text-fg-3">
                                            A different admin must approve it in the Approvals tab.
                                        </p>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="rounded-md border border-line bg-surface-2/40 p-3">
                            <p className="flex items-center gap-1 text-xs font-semibold text-fg">
                                <LockKeyhole size={13} /> 2. Start the approved preview
                            </p>
                            <div className="mt-2 space-y-2">
                                <input
                                    aria-label="Approved view-as approval id"
                                    value={approvalId}
                                    onChange={(event) => setApprovalId(event.target.value)}
                                    placeholder="Approved approval UUID"
                                    className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 font-mono text-xs text-fg outline-none focus:border-accent"
                                />
                                <input
                                    aria-label="View-as start note"
                                    value={startNote}
                                    onChange={(event) => setStartNote(event.target.value)}
                                    maxLength={1000}
                                    placeholder="Optional start note"
                                    className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-xs text-fg outline-none focus:border-accent"
                                />
                                <button
                                    type="button"
                                    onClick={() => void startViewAs()}
                                    disabled={busy !== null}
                                    className="rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:opacity-60"
                                >
                                    {busy === 'start' ? 'Starting…' : 'Start read-only preview'}
                                </button>
                                <p className="text-[10px] leading-relaxed text-fg-3">
                                    The approval is consumed once. The returned token is held only in this tab’s
                                    session storage and is never written to the audit log.
                                </p>
                            </div>
                        </div>
                    </div>
                </details>
            )}

            {active && (
                <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div>
                            <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
                                <Eye size={15} /> Read-only snapshot
                            </h3>
                            <p className="mt-0.5 break-all text-[11px] text-fg-3">
                                {active.session.target.email || active.session.target.id} · {active.session.scope} ·
                                expires {formatDateTime(active.session.expires_at)}
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => void loadSnapshot(active)}
                            disabled={loading}
                            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-60"
                        >
                            {loading ? <Loader2 size={13} className="animate-spin" /> : 'Refresh snapshot'}
                        </button>
                    </div>
                    {loading && !snapshot && <p className="text-xs text-fg-3">Loading snapshot…</p>}
                    {snapshot && <ReadOnlySnapshot snapshot={snapshot} />}
                </div>
            )}
        </div>
    )
}
