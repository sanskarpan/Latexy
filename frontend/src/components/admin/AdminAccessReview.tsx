'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
    apiClient,
    type AdminAccessReviewAccount,
    type AdminAccessReviewDecision,
    type AdminAccessReviewResponse,
} from '@/lib/api-client'
import { formatDateTime, formatNumber, shortId } from '@/components/admin/admin-format'

type AccountFilter = 'all' | 'admin' | 'support' | 'flagged' | 'no_2fa' | 'stale' | 'never_used'

const FILTERS: Array<{ value: AccountFilter; label: string }> = [
    { value: 'all', label: 'All privileged accounts' },
    { value: 'admin', label: 'Admins' },
    { value: 'support', label: 'Support' },
    { value: 'flagged', label: 'Flagged only' },
    { value: 'no_2fa', label: 'No two-factor' },
    { value: 'stale', label: 'Stale' },
    { value: 'never_used', label: 'Never used' },
]

const FLAG_LABELS: Record<string, string> = {
    missing_two_factor: 'No 2FA',
    missing_strong_auth: 'No strong auth',
    stale: 'Stale',
    never_used: 'Never used',
}

function accountMatches(account: AdminAccessReviewAccount, filter: AccountFilter): boolean {
    if (filter === 'all') return true
    if (filter === 'admin' || filter === 'support') return account.role === filter
    if (filter === 'flagged') return account.flags.length > 0
    if (filter === 'no_2fa') return account.missing_two_factor
    if (filter === 'stale') return account.stale
    return account.never_used
}

function Badge({ tone, children }: { tone: 'warn' | 'err' | 'ok' | 'muted'; children: React.ReactNode }) {
    const tones = {
        warn: 'border-warn/30 bg-warn/10 text-warn',
        err: 'border-err/30 bg-err/10 text-err',
        ok: 'border-ok/30 bg-ok/10 text-ok',
        muted: 'border-line bg-surface-2 text-fg-3',
    }
    return (
        <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${tones[tone]}`}
        >
            {children}
        </span>
    )
}

function SummaryCard({
    label,
    value,
    detail,
    tone,
}: {
    label: string
    value: string
    detail: string
    tone?: string
}) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">{label}</p>
            <p className={`mt-1 text-lg font-semibold tabular-nums ${tone ?? 'text-fg'}`}>{value}</p>
            <p className="text-[10px] text-fg-3">{detail}</p>
        </div>
    )
}

function AccountFlags({ account }: { account: AdminAccessReviewAccount }) {
    if (account.flags.length === 0) return <span className="text-xs text-fg-3">—</span>
    return (
        <span className="flex flex-wrap gap-1">
            {account.flags.map(flag => (
                <Badge
                    key={flag}
                    tone={
                        flag === 'missing_two_factor' || flag === 'never_used'
                            ? 'err'
                            : flag === 'missing_strong_auth'
                              ? 'err'
                              : 'warn'
                    }
                >
                    {FLAG_LABELS[flag] ?? flag.replace(/_/g, ' ')}
                </Badge>
            ))}
        </span>
    )
}

export default function AdminAccessReview() {
    const [data, setData] = useState<AdminAccessReviewResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [exporting, setExporting] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [filter, setFilter] = useState<AccountFilter>('all')
    const [decision, setDecision] = useState<AdminAccessReviewDecision>('attested')
    const [note, setNote] = useState('')
    const [confirm, setConfirm] = useState(false)
    const [submitting, setSubmitting] = useState(false)
    const [attestError, setAttestError] = useState<string | null>(null)
    const [attestSuccess, setAttestSuccess] = useState<string | null>(null)
    const requestGeneration = useRef(0)
    const idempotencyKey = useRef<string | null>(null)

    const load = useCallback(async () => {
        const generation = ++requestGeneration.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminAccessReview()
            if (generation === requestGeneration.current) setData(next)
        } catch (err) {
            if (generation === requestGeneration.current) {
                setError(err instanceof Error ? err.message : 'Failed to load the access review')
            }
        } finally {
            if (generation === requestGeneration.current) setLoading(false)
        }
    }, [])

    useEffect(() => {
        void load()
        return () => {
            requestGeneration.current += 1
        }
    }, [load])

    const downloadCsv = useCallback(async () => {
        setExporting(true)
        setError(null)
        try {
            const blob = await apiClient.downloadAdminAccessReviewCsv()
            const url = URL.createObjectURL(blob)
            const anchor = document.createElement('a')
            anchor.href = url
            anchor.download = `admin-access-review-${data?.quarter ?? 'current'}.csv`
            document.body.appendChild(anchor)
            anchor.click()
            anchor.remove()
            URL.revokeObjectURL(url)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'CSV export failed')
        } finally {
            setExporting(false)
        }
    }, [data?.quarter])

    const submitAttestation = useCallback(async () => {
        if (!data || !confirm) return
        setSubmitting(true)
        setAttestError(null)
        setAttestSuccess(null)
        try {
            if (!idempotencyKey.current) {
                idempotencyKey.current =
                    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
                        ? crypto.randomUUID()
                        : `review-${Date.now()}-${Math.random().toString(16).slice(2)}`
            }
            const result = await apiClient.attestAdminAccessReview({
                quarter: data.quarter,
                expected_snapshot_hash: data.snapshot_hash,
                expected_accounts: data.accounts.map(account => ({
                    user_id: account.user_id,
                    role: account.role,
                })),
                decision,
                note: note.trim(),
                confirm: true,
                idempotency_key: idempotencyKey.current,
            })
            idempotencyKey.current = null
            setConfirm(false)
            setNote('')
            setAttestSuccess(
                result.duplicate
                    ? `This review was already attested for ${result.quarter}; the audit record was not duplicated.`
                    : `Quarterly attestation recorded for ${result.quarter}. No role or session was changed.`
            )
            await load()
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Attestation failed'
            if (
                message.includes('409') ||
                message.includes('roster_changed') ||
                message.includes('review_changed')
            ) {
                setAttestError(
                    'The privileged roster or security posture changed after this review loaded. Reload and review the current accounts before attesting.'
                )
            } else {
                setAttestError(message)
            }
        } finally {
            setSubmitting(false)
        }
    }, [confirm, data, decision, load, note])

    const filteredAccounts = useMemo(
        () => (data ? data.accounts.filter(account => accountMatches(account, filter)) : []),
        [data, filter]
    )

    const minimumNote = data?.review_policy.minimum_note_length ?? 10
    const canSubmit =
        Boolean(data) &&
        confirm &&
        note.trim().length >= minimumNote &&
        !submitting

    return (
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                    <h3 className="text-sm font-semibold text-fg">Quarterly admin access review</h3>
                    <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                        Every admin and support account with its current role, two-factor and passkey
                        state, last login, account age and stale/never-used flags. Last login comes from
                        Better Auth session creation time; session tokens, IP addresses, user agents,
                        TOTP secrets and passkey material are never read. The review is read-only and
                        never demotes an account automatically.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-2">
                        {data?.quarter ?? 'Current quarter'}
                    </span>
                    <button
                        type="button"
                        onClick={() => void load()}
                        disabled={loading}
                        className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                    >
                        {loading ? 'Refreshing...' : 'Refresh'}
                    </button>
                    <button
                        type="button"
                        onClick={() => void downloadCsv()}
                        disabled={exporting || !data}
                        className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
                    >
                        {exporting ? 'Preparing CSV...' : 'Export CSV'}
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

            {!data && loading ? (
                <div role="status" className="mt-6 text-center text-xs text-fg-3">
                    Loading privileged accounts...
                </div>
            ) : data ? (
                <>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
                        <SummaryCard
                            label="Admins"
                            value={formatNumber(data.summary.admins)}
                            detail={`${formatNumber(data.summary.support)} support accounts`}
                        />
                        <SummaryCard
                            label="Without 2FA"
                            value={formatNumber(data.summary.without_two_factor)}
                            detail={`${formatNumber(data.summary.admins_without_2fa)} admins, ${formatNumber(
                                data.summary.support_without_2fa
                            )} support`}
                            tone={data.summary.without_two_factor > 0 ? 'text-warn' : 'text-ok'}
                        />
                        <SummaryCard
                            label={`Stale > ${data.stale_after_days}d`}
                            value={formatNumber(data.summary.stale)}
                            detail={`${formatNumber(data.summary.stale_admins)} admin accounts`}
                            tone={data.summary.stale > 0 ? 'text-warn' : 'text-ok'}
                        />
                        <SummaryCard
                            label="Never used"
                            value={formatNumber(data.summary.never_used)}
                            detail={`${formatNumber(data.summary.never_used_admins)} admin accounts`}
                            tone={data.summary.never_used > 0 ? 'text-err' : 'text-ok'}
                        />
                        <SummaryCard
                            label="Active sessions"
                            value={formatNumber(data.summary.active_sessions)}
                            detail={`${formatNumber(data.summary.strong_auth_enabled)} with strong auth`}
                        />
                        <SummaryCard
                            label="Flagged"
                            value={formatNumber(data.summary.flagged)}
                            detail={`of ${formatNumber(data.summary.total)} privileged accounts`}
                            tone={data.summary.flagged > 0 ? 'text-warn' : 'text-ok'}
                        />
                    </div>

                    {data.flags.some(flag => flag.count > 0) && (
                        <div className="mt-4 grid gap-2 lg:grid-cols-2">
                            {data.flags
                                .filter(flag => flag.count > 0)
                                .map(flag => (
                                    <div
                                        key={flag.code}
                                        className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-line bg-surface-2/30 px-3 py-2"
                                    >
                                        <div>
                                            <p className="text-xs font-medium text-fg">{flag.label}</p>
                                            <p className="mt-0.5 text-[10px] text-fg-3">
                                                {formatNumber(flag.count)} account
                                                {flag.count === 1 ? '' : 's'}
                                                {flag.truncated
                                                    ? ' (first 50 account ids listed)'
                                                    : ''}
                                            </p>
                                        </div>
                                        <Badge tone={flag.severity === 'high' ? 'err' : 'warn'}>
                                            {flag.severity}
                                        </Badge>
                                    </div>
                                ))}
                        </div>
                    )}

                    <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                            Privileged accounts
                        </h4>
                        <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                            Filter
                            <select
                                value={filter}
                                onChange={event => setFilter(event.target.value as AccountFilter)}
                                className="ml-2 rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                            >
                                {FILTERS.map(option => (
                                    <option key={option.value} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                        </label>
                    </div>

                    <div className="mt-2 overflow-x-auto">
                        <table className="w-full min-w-[900px] border-collapse text-sm">
                            <thead>
                                <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                                    <th className="py-2 pr-3 font-semibold">Account</th>
                                    <th className="py-2 pr-3 font-semibold">Role</th>
                                    <th className="py-2 pr-3 font-semibold">2FA</th>
                                    <th className="py-2 pr-3 font-semibold">Passkeys</th>
                                    <th className="py-2 pr-3 font-semibold">Last login</th>
                                    <th className="py-2 pr-3 font-semibold">Account age</th>
                                    <th className="py-2 font-semibold">Flags</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredAccounts.map(account => (
                                    <tr key={account.user_id} className="border-b border-line/60 align-top">
                                        <td className="py-2 pr-3">
                                            <p className="font-medium text-fg">
                                                {account.email_masked ?? shortId(account.user_id)}
                                            </p>
                                            <p className="text-[10px] text-fg-3" title={account.user_id}>
                                                {shortId(account.user_id, 14)}
                                                {account.name_masked ? ` · ${account.name_masked}` : ''}
                                            </p>
                                        </td>
                                        <td className="py-2 pr-3">
                                            <Badge tone={account.role === 'admin' ? 'warn' : 'muted'}>
                                                {account.role}
                                            </Badge>
                                        </td>
                                        <td className="py-2 pr-3 text-xs">
                                            {account.two_factor_enabled ? (
                                                <span className="text-ok">Enabled</span>
                                            ) : (
                                                <span className="text-warn">Missing</span>
                                            )}
                                            <p className="text-[10px] text-fg-3">
                                                {account.strong_auth ? 'strong auth present' : 'no strong auth'}
                                            </p>
                                        </td>
                                        <td className="py-2 pr-3 text-xs tabular-nums">
                                            {formatNumber(account.passkey_count)}
                                        </td>
                                        <td className="py-2 pr-3 text-xs">
                                            {account.last_login_at ? (
                                                formatDateTime(account.last_login_at)
                                            ) : (
                                                <span className="text-warn">Never</span>
                                            )}
                                            <p className="text-[10px] text-fg-3">
                                                {formatNumber(account.session_count)} sessions ·{' '}
                                                {formatNumber(account.active_sessions)} active
                                            </p>
                                        </td>
                                        <td className="py-2 pr-3 text-xs tabular-nums">
                                            {account.account_age_days == null
                                                ? '—'
                                                : `${formatNumber(account.account_age_days)} days`}
                                        </td>
                                        <td className="py-2">
                                            <AccountFlags account={account} />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {filteredAccounts.length === 0 && (
                            <p className="py-6 text-center text-xs text-fg-3">
                                No privileged accounts match this filter.
                            </p>
                        )}
                    </div>

                    <div className="mt-5 rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                                <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-3">
                                    Quarterly attestation · {data.quarter}
                                </h4>
                                <p className="mt-1 text-[11px] text-fg-3">
                                    Attestations are append-only audit records. A submit is rejected if
                                    the roster or 2FA/passkey posture changed after this view loaded.
                                </p>
                            </div>
                            <Badge
                                tone={
                                    data.attestation.current
                                        ? data.attestation.latest?.decision === 'follow_up_required'
                                            ? 'warn'
                                            : 'ok'
                                        : 'warn'
                                }
                            >
                                {data.attestation.current
                                    ? data.attestation.latest?.decision === 'follow_up_required'
                                        ? 'Follow-up recorded'
                                        : 'Attested'
                                    : 'Awaiting attestation'}
                            </Badge>
                        </div>

                        {data.attestation.roster_changed_since_attestation && (
                            <div className="mt-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
                                The roster or security posture changed since the latest attestation.
                                Review the current accounts and re-attest.
                            </div>
                        )}

                        {data.attestation.latest && (
                            <p className="mt-3 text-xs text-fg-2">
                                Last attested {formatDateTime(data.attestation.latest.attested_at)} by{' '}
                                {data.attestation.latest.attested_by_email_masked ??
                                    shortId(data.attestation.latest.attested_by_user_id)}
                                . Snapshot{' '}
                                <span className="font-mono text-[10px] text-fg-3">
                                    {shortId(data.attestation.latest.snapshot_hash, 16)}
                                </span>
                            </p>
                        )}

                        <div className="mt-3 grid gap-3 lg:grid-cols-[180px_1fr]">
                            <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                                Decision
                                <select
                                    value={decision}
                                    onChange={event =>
                                        setDecision(event.target.value as AdminAccessReviewDecision)
                                    }
                                    className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
                                >
                                    <option value="attested">Attested — access confirmed</option>
                                    <option value="follow_up_required">Follow-up required</option>
                                </select>
                            </label>
                            <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                                Review note
                                <textarea
                                    value={note}
                                    onChange={event => setNote(event.target.value)}
                                    minLength={minimumNote}
                                    maxLength={1000}
                                    rows={2}
                                    placeholder="What did you review, and what follow-up is needed?"
                                    className="mt-1 block w-full rounded-[var(--radius-md)] border border-line bg-surface px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg placeholder:text-fg-3"
                                />
                                <span className="mt-1 block text-[10px] font-normal normal-case tracking-normal text-fg-3">
                                    Required, at least {minimumNote} characters.
                                </span>
                            </label>
                        </div>

                        <label className="mt-3 flex items-start gap-2 text-xs text-fg-2">
                            <input
                                type="checkbox"
                                checked={confirm}
                                onChange={event => setConfirm(event.target.checked)}
                                className="mt-0.5"
                            />
                            <span>
                                I reviewed every privileged account in this roster and confirm this
                                attestation is accurate.
                            </span>
                        </label>

                        {attestError && (
                            <div
                                role="alert"
                                className="mt-3 rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-xs text-err"
                            >
                                {attestError}
                            </div>
                        )}
                        {attestSuccess && (
                            <div
                                role="status"
                                className="mt-3 rounded-[var(--radius-md)] border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok"
                            >
                                {attestSuccess}
                            </div>
                        )}

                        <div className="mt-3 flex flex-wrap items-center gap-3">
                            <button
                                type="button"
                                onClick={() => void submitAttestation()}
                                disabled={!canSubmit}
                                className="rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
                            >
                                {submitting ? 'Recording attestation...' : 'Record quarterly attestation'}
                            </button>
                            <p className="text-[10px] text-fg-3">
                                No automatic demotion, role change, session revocation or credential change.
                            </p>
                        </div>

                        {data.attestation.history.length > 0 && (
                            <div className="mt-4 overflow-x-auto">
                                <h5 className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                                    Attestation history
                                </h5>
                                <table className="mt-2 w-full min-w-[700px] border-collapse text-xs">
                                    <thead>
                                        <tr className="border-b border-line text-left text-[10px] uppercase tracking-wider text-fg-3">
                                            <th className="py-1.5 pr-3 font-semibold">Quarter</th>
                                            <th className="py-1.5 pr-3 font-semibold">Decision</th>
                                            <th className="py-1.5 pr-3 font-semibold">Attested at</th>
                                            <th className="py-1.5 pr-3 font-semibold">Reviewer</th>
                                            <th className="py-1.5 pr-3 font-semibold">Roster</th>
                                            <th className="py-1.5 pr-3 font-semibold">Admins w/o 2FA</th>
                                            <th className="py-1.5 pr-3 font-semibold">Stale</th>
                                            <th className="py-1.5 font-semibold">Note</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.attestation.history.map(item => (
                                            <tr key={item.audit_id} className="border-b border-line/60 align-top">
                                                <td className="py-1.5 pr-3 text-fg-2">{item.quarter ?? '—'}</td>
                                                <td className="py-1.5 pr-3">
                                                    <Badge
                                                        tone={
                                                            item.decision === 'follow_up_required'
                                                                ? 'warn'
                                                                : 'ok'
                                                        }
                                                    >
                                                        {item.decision === 'follow_up_required'
                                                            ? 'Follow-up'
                                                            : 'Attested'}
                                                    </Badge>
                                                </td>
                                                <td className="py-1.5 pr-3 text-fg-2">
                                                    {formatDateTime(item.attested_at)}
                                                </td>
                                                <td className="py-1.5 pr-3 text-fg-2">
                                                    {item.attested_by_email_masked ??
                                                        shortId(item.attested_by_user_id)}
                                                </td>
                                                <td className="py-1.5 pr-3 tabular-nums text-fg-2">
                                                    {formatNumber(item.roster_size)}
                                                </td>
                                                <td className="py-1.5 pr-3 tabular-nums text-fg-2">
                                                    {formatNumber(item.admins_without_2fa)}
                                                </td>
                                                <td className="py-1.5 pr-3 tabular-nums text-fg-2">
                                                    {formatNumber(item.stale)}
                                                </td>
                                                <td className="py-1.5 text-fg-3" title={item.note ?? undefined}>
                                                    {item.note ? shortId(item.note, 48) : '—'}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </>
            ) : null}
        </section>
    )
}
