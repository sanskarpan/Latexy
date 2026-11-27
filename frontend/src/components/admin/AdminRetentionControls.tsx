'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
    apiClient,
    type AdminRetentionClass,
    type AdminRetentionDataClass,
    type AdminRetentionOverview,
    type AdminRetentionRun,
} from '@/lib/api-client'

const CLASS_ORDER: AdminRetentionDataClass[] = [
    'pdfs',
    'job_finalizations',
    'analytics',
    'audit',
    'exports',
]

const PURGE_LABEL: Record<string, string> = {
    delete: 'Bounded delete',
    scrub: 'Token scrub',
    immutable: 'Immutable',
}

function formatHours(hours: number | null | undefined): string {
    if (hours == null || !Number.isFinite(hours)) return '—'
    if (hours % 24 === 0 && hours >= 24) return `${hours / 24}d`
    return `${hours}h`
}

function formatWhen(value: string | null | undefined): string {
    if (!value) return '—'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '—'
    return date.toLocaleString()
}

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : 'The request could not be completed'
}

function CountTile({ label, value, tone }: { label: string; value: number; tone?: 'warn' | 'err' }) {
    const toneClass = tone === 'err' ? 'text-err' : tone === 'warn' ? 'text-warn' : 'text-fg'
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">{label}</p>
            <p className={`mt-1 text-sm font-semibold tabular-nums ${toneClass}`}>
                {value.toLocaleString()}
            </p>
        </div>
    )
}

function ClassRow({
    item,
    onManage,
}: {
    item: AdminRetentionClass
    onManage: () => void
}) {
    return (
        <tr className="border-t border-line/70 align-top">
            <td className="px-3 py-3">
                <p className="text-sm font-medium text-fg">{item.label}</p>
                <p className="mt-0.5 font-mono text-[10px] text-fg-3">{item.data_class}</p>
                <p className="mt-1 inline-flex rounded border border-line bg-surface-2 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-fg-3">
                    {PURGE_LABEL[item.purge_mode] ?? item.purge_mode}
                </p>
            </td>
            <td className="px-3 py-3 text-xs tabular-nums text-fg-2">
                <p>{formatHours(item.configured_hours)}</p>
                <p className="text-[10px] text-fg-3">effective {formatHours(item.effective_hours)}</p>
                <p className="mt-0.5 text-[10px] text-fg-3">v{item.version}</p>
            </td>
            <td className="px-3 py-3 text-xs tabular-nums text-fg-2">
                <p>{item.enabled ? `every ${formatHours(item.schedule_hours)}` : 'schedule disabled'}</p>
                <p className="mt-0.5 text-[10px] text-fg-3">next {formatWhen(item.next_run_at)}</p>
                <p className="text-[10px] text-fg-3">
                    last {item.last_run ? `${item.last_run.mode} · ${formatWhen(item.last_run.started_at)}` : 'never'}
                </p>
            </td>
            <td className="px-3 py-3 text-xs tabular-nums text-fg-2">
                <p>{item.counts.older_than_policy.toLocaleString()} past window</p>
                <p className="text-[10px] text-fg-3">{item.counts.eligible.toLocaleString()} eligible now</p>
                <p className="text-[10px] text-fg-3">{item.counts.recent.toLocaleString()} retained</p>
            </td>
            <td className="px-3 py-3 text-xs tabular-nums">
                <p className="text-warn">{item.counts.protected_active_jobs.toLocaleString()} active work</p>
                <p className="text-warn">{item.counts.protected_legal_hold.toLocaleString()} legal hold</p>
                {item.counts.protected_immutable > 0 && (
                    <p className="text-fg-3">{item.counts.protected_immutable.toLocaleString()} immutable</p>
                )}
            </td>
            <td className="px-3 py-3">
                <button
                    type="button"
                    onClick={onManage}
                    className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
                >
                    Manage
                </button>
            </td>
        </tr>
    )
}

function RunResult({ result, label }: { result: AdminRetentionRun; label: string }) {
    return (
        <div className="mt-3 rounded-[var(--radius-md)] border border-line bg-bg/40 p-3" aria-live="polite">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-semibold text-fg">
                    {result.dry_run ? 'Dry run complete — nothing changed' : `${label} complete`}
                </p>
                <span className="font-mono text-[10px] text-fg-3">
                    cutoff {formatWhen(result.cutoff_at)}
                </span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <CountTile
                    label={result.dry_run ? 'Would affect' : 'Affected'}
                    value={result.dry_run ? result.would_affect : result.affected}
                />
                <CountTile label="Eligible" value={result.counts.eligible} />
                <CountTile label="Active work protected" value={result.counts.protected_active_jobs} />
                <CountTile label="Legal hold protected" value={result.counts.protected_legal_hold} />
            </div>
            {result.counts.protected_immutable > 0 && (
                <p className="mt-2 text-[10px] text-fg-3">
                    {result.counts.protected_immutable.toLocaleString()} append-only audit rows are
                    beyond the configured window but cannot be deleted.
                </p>
            )}
            {result.has_more && (
                <p className="mt-2 text-[10px] text-warn">
                    More eligible rows remain. Each run is bounded; run again after reviewing this page.
                </p>
            )}
            {result.replayed && (
                <p className="mt-2 text-[10px] text-fg-3">
                    Replayed the earlier run for this idempotency key; nothing was executed twice.
                </p>
            )}
        </div>
    )
}

export default function AdminRetentionControls() {
    const [overview, setOverview] = useState<AdminRetentionOverview | null>(null)
    const [selected, setSelected] = useState<AdminRetentionDataClass | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [busy, setBusy] = useState<'policy' | 'dry_run' | 'purge' | null>(null)
    const [results, setResults] = useState<Partial<Record<AdminRetentionDataClass, AdminRetentionRun>>>({})

    const [retentionHours, setRetentionHours] = useState('24')
    const [scheduleHours, setScheduleHours] = useState('24')
    const [enabled, setEnabled] = useState(true)
    const [policyReason, setPolicyReason] = useState('')
    const [policyConfirm, setPolicyConfirm] = useState(false)

    const [runReason, setRunReason] = useState('')
    const [runLimit, setRunLimit] = useState('200')
    const [purgeConfirm, setPurgeConfirm] = useState(false)

    const load = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            setOverview(await apiClient.getAdminRetentionOverview())
        } catch (err) {
            setError(errorMessage(err))
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        void load()
    }, [load])

    const selectedClass = useMemo(
        () => overview?.classes.find(item => item.data_class === selected) ?? null,
        [overview, selected]
    )

    const selectClass = (item: AdminRetentionClass) => {
        setSelected(item.data_class)
        setRetentionHours(String(item.configured_hours))
        setScheduleHours(String(item.schedule_hours))
        setEnabled(item.enabled)
        setPolicyReason('')
        setPolicyConfirm(false)
        setRunReason('')
        setPurgeConfirm(false)
        setActionError(null)
    }

    const refresh = async () => {
        const next = await apiClient.getAdminRetentionOverview()
        setOverview(next)
        return next
    }

    const savePolicy = async () => {
        if (!selectedClass) return
        if (policyReason.trim().length < 3) {
            setActionError('Enter a reason of at least 3 characters.')
            return
        }
        if (!policyConfirm) {
            setActionError('Confirm the policy change before saving.')
            return
        }
        setBusy('policy')
        setActionError(null)
        try {
            await apiClient.updateAdminRetentionPolicy(selectedClass.data_class, {
                retention_hours: Number(retentionHours),
                schedule_hours: Number(scheduleHours),
                enabled,
                expected_version: selectedClass.version,
                reason: policyReason.trim(),
                confirm: true,
            })
            await refresh()
            setPolicyReason('')
            setPolicyConfirm(false)
        } catch (err) {
            setActionError(errorMessage(err))
        } finally {
            setBusy(null)
        }
    }

    const runAction = async (dryRun: boolean) => {
        if (!selectedClass) return
        if (runReason.trim().length < 3) {
            setActionError('Enter a run reason of at least 3 characters.')
            return
        }
        if (!dryRun && !purgeConfirm) {
            setActionError('Confirm the purge before running it.')
            return
        }
        setBusy(dryRun ? 'dry_run' : 'purge')
        setActionError(null)
        try {
            const body = {
                reason: runReason.trim(),
                limit: Number(runLimit),
            }
            const result = dryRun
                ? await apiClient.runAdminRetentionDryRun(selectedClass.data_class, body)
                : await apiClient.runAdminRetentionPurge(selectedClass.data_class, body)
            setResults(prev => ({ ...prev, [selectedClass.data_class]: result }))
            if (!dryRun) await refresh()
        } catch (err) {
            setActionError(errorMessage(err))
        } finally {
            setBusy(null)
        }
    }

    if (loading && !overview) {
        return (
            <div role="status" aria-busy="true" className="rounded-[var(--radius-lg)] border border-line bg-surface px-5 py-8 text-sm text-fg-3">
                Loading retention controls…
            </div>
        )
    }
    if (error) {
        return (
            <div role="alert" className="rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.06] px-5 py-4">
                <p className="text-sm font-medium text-err">Retention controls unavailable</p>
                <p className="mt-1 text-xs text-err/70">{error}</p>
                <button
                    type="button"
                    onClick={() => void load()}
                    className="mt-3 rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
                >
                    Retry
                </button>
            </div>
        )
    }
    if (!overview) return null

    const classes = CLASS_ORDER
        .map(key => overview.classes.find(item => item.data_class === key))
        .filter((item): item is AdminRetentionClass => Boolean(item))
    const result = selected ? results[selected] : undefined

    return (
        <section aria-labelledby="retention-controls-heading" className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 id="retention-controls-heading" className="text-lg font-semibold text-fg">
                        Data-retention controls
                    </h2>
                    <p className="mt-1 max-w-3xl text-xs text-fg-3">
                        Configured versus effective windows per data class, with boundary previews,
                        dry runs and confirmed bounded purges. Active jobs, legal holds and append-only
                        audit rows are refused. Aggregate only — minimum cohort size{' '}
                        {overview.minimum_cohort_size}; no per-account history is exposed.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => void load()}
                    disabled={loading}
                    className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                >
                    {loading ? 'Refreshing…' : 'Refresh retention'}
                </button>
            </div>

            <div className="overflow-x-auto rounded-[var(--radius-lg)] border border-line bg-surface">
                <table className="w-full min-w-[900px] border-collapse text-sm">
                    <thead>
                        <tr className="text-[10px] uppercase tracking-wider text-fg-3">
                            <th className="px-3 py-2 text-left font-semibold">Data class</th>
                            <th className="px-3 py-2 text-left font-semibold">Window</th>
                            <th className="px-3 py-2 text-left font-semibold">Schedule</th>
                            <th className="px-3 py-2 text-left font-semibold">Affected</th>
                            <th className="px-3 py-2 text-left font-semibold">Protected</th>
                            <th className="px-3 py-2 text-left font-semibold"></th>
                        </tr>
                    </thead>
                    <tbody>
                        {classes.map(item => (
                            <ClassRow key={item.data_class} item={item} onManage={() => selectClass(item)} />
                        ))}
                    </tbody>
                </table>
            </div>

            {selectedClass && (
                <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
                    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
                        <div>
                            <p className="text-sm font-semibold text-fg">{selectedClass.label}</p>
                            <p className="mt-0.5 max-w-3xl text-[11px] text-fg-3">{selectedClass.description}</p>
                        </div>
                        <span className="rounded border border-line bg-surface-2 px-2 py-1 font-mono text-[10px] text-fg-3">
                            v{selectedClass.version} · {selectedClass.purge_mode}
                        </span>
                    </div>

                    <div className="grid gap-3 border-b border-line px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
                        <CountTile label="Rows total" value={selectedClass.counts.total} />
                        <CountTile label="Past configured window" value={selectedClass.counts.older_than_policy} />
                        <CountTile label="Eligible for purge" value={selectedClass.counts.eligible} />
                        <CountTile label="Retained inside window" value={selectedClass.counts.recent} />
                        <CountTile
                            label="Active work refused"
                            value={selectedClass.counts.protected_active_jobs}
                            tone="warn"
                        />
                        <CountTile
                            label="Legal hold refused"
                            value={selectedClass.counts.protected_legal_hold}
                            tone="warn"
                        />
                        <CountTile
                            label="Immutable"
                            value={selectedClass.counts.protected_immutable}
                            tone={selectedClass.counts.protected_immutable > 0 ? 'warn' : undefined}
                        />
                        <CountTile
                            label="Already scrubbed"
                            value={selectedClass.counts.already_scrubbed}
                        />
                    </div>

                    <div className="grid gap-4 border-b border-line px-4 py-4 lg:grid-cols-2">
                        <div>
                            <p className="text-xs font-semibold text-fg">Boundary-age preview</p>
                            <p className="mt-1 text-[11px] text-fg-3">
                                Cutoff {formatWhen(selectedClass.boundary.cutoff_at)}. Rows exactly on the
                                boundary are eligible.
                            </p>
                            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                                <div>
                                    <dt className="text-fg-3">Crossing within {overview.boundary_window_hours}h</dt>
                                    <dd className="font-semibold tabular-nums text-fg">
                                        {selectedClass.boundary.inside_24h.toLocaleString()}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Crossed in last {overview.boundary_window_hours}h</dt>
                                    <dd className="font-semibold tabular-nums text-fg">
                                        {selectedClass.boundary.outside_24h.toLocaleString()}
                                    </dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Configured</dt>
                                    <dd className="font-semibold text-fg">{formatHours(selectedClass.configured_hours)}</dd>
                                </div>
                                <div>
                                    <dt className="text-fg-3">Effective</dt>
                                    <dd className="font-semibold text-fg">{formatHours(selectedClass.effective_hours)}</dd>
                                </div>
                            </dl>
                            {selectedClass.exceptions.length > 0 && (
                                <ul className="mt-2 space-y-1 text-[10px] text-warn">
                                    {selectedClass.exceptions.map(code => (
                                        <li key={code}>Exception: {code.replace(/_/g, ' ')}</li>
                                    ))}
                                </ul>
                            )}
                        </div>
                        <div>
                            <p className="text-xs font-semibold text-fg">Run history</p>
                            <p className="mt-1 text-[11px] text-fg-3">
                                Next {formatWhen(selectedClass.next_run_at)}
                                {selectedClass.schedule_due ? ' · due now' : ''}
                            </p>
                            {selectedClass.last_run ? (
                                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                                    <div>
                                        <dt className="text-fg-3">Last mode</dt>
                                        <dd className="font-semibold text-fg">{selectedClass.last_run.mode}</dd>
                                    </div>
                                    <div>
                                        <dt className="text-fg-3">Status</dt>
                                        <dd className="font-semibold text-fg">{selectedClass.last_run.status}</dd>
                                    </div>
                                    <div>
                                        <dt className="text-fg-3">Scanned</dt>
                                        <dd className="font-semibold tabular-nums text-fg">
                                            {selectedClass.last_run.counts.scanned.toLocaleString()}
                                        </dd>
                                    </div>
                                    <div>
                                        <dt className="text-fg-3">Affected</dt>
                                        <dd className="font-semibold tabular-nums text-fg">
                                            {selectedClass.last_run.affected.toLocaleString()}
                                        </dd>
                                    </div>
                                </dl>
                            ) : (
                                <p className="mt-2 text-[11px] text-fg-3">No run recorded yet.</p>
                            )}
                        </div>
                    </div>

                    <div className="grid gap-4 px-4 py-4 lg:grid-cols-2">
                        <div className="space-y-3">
                            <p className="text-xs font-semibold text-fg">Policy version {selectedClass.version}</p>
                            <div className="grid grid-cols-2 gap-2">
                                <label className="block text-[11px] text-fg-2">
                                    Retention hours
                                    <input
                                        type="number"
                                        min={1}
                                        max={87600}
                                        value={retentionHours}
                                        onChange={event => setRetentionHours(event.target.value)}
                                        className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
                                    />
                                </label>
                                <label className="block text-[11px] text-fg-2">
                                    Schedule hours
                                    <input
                                        type="number"
                                        min={1}
                                        max={8760}
                                        value={scheduleHours}
                                        onChange={event => setScheduleHours(event.target.value)}
                                        className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
                                    />
                                </label>
                            </div>
                            <label className="flex items-center gap-2 text-[11px] text-fg-2">
                                <input
                                    type="checkbox"
                                    checked={enabled}
                                    onChange={event => setEnabled(event.target.checked)}
                                    className="h-4 w-4 rounded border-line"
                                />
                                Schedule enabled (previews only; purges still require confirmation)
                            </label>
                            <label className="block text-[11px] text-fg-2">
                                Change reason
                                <input
                                    value={policyReason}
                                    onChange={event => setPolicyReason(event.target.value)}
                                    maxLength={2000}
                                    placeholder="Ticket or policy reference (required)"
                                    className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
                                />
                            </label>
                            <label className="flex items-start gap-2 text-[11px] text-fg-2">
                                <input
                                    type="checkbox"
                                    checked={policyConfirm}
                                    onChange={event => setPolicyConfirm(event.target.checked)}
                                    className="mt-0.5 h-4 w-4 rounded border-line"
                                />
                                <span>
                                    I confirm this policy change. It creates an append-only revision and an
                                    audit row.
                                </span>
                            </label>
                            <button
                                type="button"
                                disabled={busy !== null || !policyConfirm}
                                onClick={() => void savePolicy()}
                                className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-semibold text-fg-2 hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {busy === 'policy' ? 'Saving policy…' : 'Save policy version'}
                            </button>
                        </div>

                        <div className="space-y-3">
                            <p className="text-xs font-semibold text-fg">Dry run and confirmed purge</p>
                            <label className="block text-[11px] text-fg-2">
                                Run reason
                                <input
                                    value={runReason}
                                    onChange={event => setRunReason(event.target.value)}
                                    maxLength={2000}
                                    placeholder="Incident or retention review reference (required)"
                                    className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
                                />
                            </label>
                            <label className="block text-[11px] text-fg-2">
                                Rows per run (bounded)
                                <input
                                    type="number"
                                    min={1}
                                    max={1000}
                                    value={runLimit}
                                    onChange={event => setRunLimit(event.target.value)}
                                    className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
                                />
                            </label>
                            {!selectedClass.purge_supported && (
                                <p className="rounded border border-warn/30 bg-warn/10 px-2.5 py-2 text-[10px] text-warn">
                                    This class is append-only. Previews are available; deletion is refused
                                    by design.
                                </p>
                            )}
                            <label className="flex items-start gap-2 text-[11px] text-fg-2">
                                <input
                                    type="checkbox"
                                    checked={purgeConfirm}
                                    onChange={event => setPurgeConfirm(event.target.checked)}
                                    disabled={!selectedClass.purge_supported}
                                    className="mt-0.5 h-4 w-4 rounded border-line"
                                />
                                <span>
                                    I confirm this bounded purge. Active jobs and legal holds are refused,
                                    and the run writes an audit row.
                                </span>
                            </label>
                            <div className="flex flex-wrap gap-2">
                                <button
                                    type="button"
                                    disabled={busy !== null}
                                    onClick={() => void runAction(true)}
                                    className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                                >
                                    {busy === 'dry_run' ? 'Running dry run…' : 'Dry run'}
                                </button>
                                <button
                                    type="button"
                                    disabled={busy !== null || !purgeConfirm || !selectedClass.purge_supported}
                                    onClick={() => void runAction(false)}
                                    className="rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-1.5 text-xs font-semibold text-err hover:bg-err/15 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {busy === 'purge' ? 'Purging…' : 'Run confirmed purge'}
                                </button>
                            </div>
                            {actionError && (
                                <p role="alert" className="text-xs text-err">
                                    {actionError}
                                </p>
                            )}
                            {result && <RunResult result={result} label={selectedClass.purge_mode === 'scrub' ? 'Scrub' : 'Purge'} />}
                        </div>
                    </div>
                </div>
            )}

            <p className="text-[10px] text-fg-3">
                Purges affect at most the configured row limit and never run automatically. PDF object
                bytes are removed only by the reference-aware storage sweep; this panel deletes expired
                manifest rows. Legal holds and active jobs always win over retention.
            </p>
        </section>
    )
}
