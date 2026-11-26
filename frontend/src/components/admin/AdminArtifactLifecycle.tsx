'use client'

import { useCallback, useEffect, useState } from 'react'
import {
    apiClient,
    type AdminArtifactCleanupResponse,
    type AdminArtifactCountBytes,
    type AdminArtifactKeySummary,
    type AdminArtifactLifecycleReport,
} from '@/lib/api-client'

const MANIFEST_STATE_ORDER = ['active', 'expiring_24h', 'expiring_7d', 'expired'] as const
const MANIFEST_AGE_ORDER = ['under_1d', '1_to_7d', '7_to_30d', 'over_30d'] as const
const STORAGE_STATE_ORDER = [
    'referenced',
    'unaccepted_reference',
    'legal_hold',
    'recent',
    'orphan_candidate',
    'database_marker',
] as const

const STATE_LABEL: Record<string, string> = {
    active: 'Active',
    expiring_24h: 'Expiring in 24h',
    expiring_7d: 'Expiring in 7d',
    expired: 'Expired manifest',
    under_1d: 'Under 1 day',
    '1_to_7d': '1–7 days',
    '7_to_30d': '7–30 days',
    over_30d: 'Over 30 days',
    referenced: 'Referenced',
    unaccepted_reference: 'Unaccepted reference',
    legal_hold: 'Legal hold',
    recent: 'Inside grace period',
    orphan_candidate: 'Orphan candidate',
    database_marker: 'Database binding',
    under_1h: 'Under 1 hour',
    '1h_to_1d': '1 hour – 1 day',
    '1d_to_7d': '1–7 days',
    over_7d: 'Over 7 days',
}

function formatBytes(value: number | null | undefined): string {
    if (value == null || !Number.isFinite(value)) return '—'
    if (value < 1024) return `${value} B`
    const units = ['KB', 'MB', 'GB', 'TB']
    let size = value / 1024
    let unit = 0
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024
        unit += 1
    }
    return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`
}

function formatAge(seconds: number | null | undefined): string {
    if (seconds == null || !Number.isFinite(seconds)) return 'unknown age'
    if (seconds < 60) return 'just now'
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
    if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
    return `${Math.round(seconds / 86400)}d ago`
}

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : 'The request could not be completed'
}

function CountBytes({ label, value }: { label: string; value: AdminArtifactCountBytes }) {
    return (
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">{label}</p>
            <p className="mt-1 text-sm font-semibold tabular-nums text-fg">
                {value.count.toLocaleString()} <span className="text-fg-3">objects</span>
            </p>
            <p className="text-[11px] tabular-nums text-fg-2">{formatBytes(value.bytes)}</p>
        </div>
    )
}

function CountBytesTable({
    order,
    buckets,
}: {
    order: readonly string[]
    buckets: Record<string, AdminArtifactCountBytes>
}) {
    return (
        <div className="overflow-x-auto">
            <table className="w-full min-w-[360px] border-collapse text-sm">
                <thead>
                    <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                        <th className="px-3 py-2 text-left font-semibold">Bucket</th>
                        <th className="px-3 py-2 text-right font-semibold">Objects</th>
                        <th className="px-3 py-2 text-right font-semibold">Bytes</th>
                    </tr>
                </thead>
                <tbody>
                    {order.map(key => {
                        const bucket = buckets[key] ?? { count: 0, bytes: 0 }
                        return (
                            <tr key={key} className="border-t border-line/70">
                                <td className="px-3 py-2 text-fg-2">
                                    {STATE_LABEL[key] ?? key.replace(/_/g, ' ')}
                                </td>
                                <td className="px-3 py-2 text-right tabular-nums text-fg">
                                    {bucket.count.toLocaleString()}
                                </td>
                                <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                    {formatBytes(bucket.bytes)}
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

function KeyList({ keys }: { keys: AdminArtifactKeySummary[] }) {
    if (keys.length === 0) {
        return <p className="text-xs text-fg-3">No candidate keys in this page.</p>
    }
    return (
        <ul className="space-y-1.5">
            {keys.map(item => (
                <li key={item.key} className="rounded border border-line bg-bg/40 px-2.5 py-2">
                    <code className="block break-all font-mono text-[10px] leading-relaxed text-fg-2">
                        {item.key}
                    </code>
                    <p className="mt-1 text-[10px] text-fg-3">
                        {formatBytes(item.bytes)} · {formatAge(item.age_seconds)}
                    </p>
                </li>
            ))}
        </ul>
    )
}

function CleanupResult({ result }: { result: AdminArtifactCleanupResponse }) {
    return (
        <div
            className="mt-4 rounded-[var(--radius-md)] border border-line bg-bg/40 p-3"
            aria-live="polite"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-semibold text-fg">
                    {result.dry_run ? 'Dry run complete — nothing deleted' : 'Cleanup complete'}
                </p>
                <span className="font-mono text-[10px] text-fg-3">
                    {formatBytes(result.scanned.bytes)} scanned
                </span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <CountBytes
                    label={result.dry_run ? 'Would delete' : 'Deleted'}
                    value={result.dry_run ? result.would_delete : result.deleted}
                />
                <CountBytes label="Candidates" value={result.candidates} />
                <CountBytes label="Failed deletes" value={result.failed} />
                <CountBytes
                    label="Protected"
                    value={Object.values(result.protected).reduce(
                        (total, bucket) => ({
                            count: total.count + bucket.count,
                            bytes: total.bytes + bucket.bytes,
                        }),
                        { count: 0, bytes: 0 }
                    )}
                />
            </div>
            <p className="mt-2 text-[10px] text-fg-3">
                Referenced, unaccepted, legal-hold and inside-grace objects were refused. No object
                contents were read.
            </p>
            {result.failed.keys.length > 0 && (
                <div className="mt-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-err">
                        Failed deletion keys
                    </p>
                    <code className="mt-1 block max-h-28 overflow-auto break-all rounded border border-err/20 bg-err/[0.04] p-2 font-mono text-[10px] text-err">
                        {result.failed.keys.join('\n')}
                    </code>
                </div>
            )}
            {result.next_cursor && (
                <p className="mt-2 text-[10px] text-fg-3">
                    More objects remain in the bucket; the next page cursor was returned for a
                    follow-up run.
                </p>
            )}
        </div>
    )
}

export default function AdminArtifactLifecycle() {
    const [report, setReport] = useState<AdminArtifactLifecycleReport | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [reason, setReason] = useState('')
    const [confirmDeletion, setConfirmDeletion] = useState(false)
    const [busy, setBusy] = useState<'dry_run' | 'delete' | null>(null)
    const [actionError, setActionError] = useState<string | null>(null)
    const [result, setResult] = useState<AdminArtifactCleanupResponse | null>(null)

    const load = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            setReport(await apiClient.getAdminArtifactLifecycle())
        } catch (err) {
            setError(errorMessage(err))
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        void load()
    }, [load])

    const runCleanup = async (dryRun: boolean) => {
        const cleanedReason = reason.trim()
        if (cleanedReason.length < 3) {
            setActionError('Enter a reason of at least 3 characters.')
            return
        }
        if (!dryRun && !confirmDeletion) {
            setActionError('Confirm the deletion before running a real cleanup.')
            return
        }
        setBusy(dryRun ? 'dry_run' : 'delete')
        setActionError(null)
        setResult(null)
        try {
            const response = await apiClient.runAdminArtifactCleanup({
                reason: cleanedReason,
                dry_run: dryRun,
                confirm: dryRun ? undefined : true,
            })
            setResult(response)
            if (!dryRun) {
                await load()
            }
        } catch (err) {
            setActionError(errorMessage(err))
        } finally {
            setBusy(null)
        }
    }

    if (loading && !report) {
        return (
            <div
                role="status"
                aria-busy="true"
                className="rounded-[var(--radius-lg)] border border-line bg-surface px-5 py-8 text-sm text-fg-3"
            >
                Loading artifact lifecycle…
            </div>
        )
    }
    if (error) {
        return (
            <div
                role="alert"
                className="rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.06] px-5 py-4"
            >
                <p className="text-sm font-medium text-err">Artifact lifecycle unavailable</p>
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
    if (!report) return null

    const manifests = report.manifests
    const storage = report.storage
    const growth = report.growth

    return (
        <section aria-labelledby="artifact-lifecycle-heading" className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 id="artifact-lifecycle-heading" className="text-lg font-semibold text-fg">
                        PDF artifact lifecycle
                    </h2>
                    <p className="mt-1 max-w-3xl text-xs text-fg-3">
                        Manifest and object-storage aggregates for render artifacts. Counts and
                        bytes reconcile to retention manifests and the object listing. Aggregate
                        only · minimum cohort size {report.minimum_cohort_size} · no per-account,
                        device or document breakdown is exposed.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => void load()}
                    disabled={loading}
                    className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                >
                    {loading ? 'Refreshing…' : 'Refresh lifecycle'}
                </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <CountBytes label="Registered manifests" value={manifests.total} />
                <CountBytes label="Orphan candidates" value={storage.orphan_candidates} />
                <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wider text-fg-3">
                        Storage growth · 7d
                    </p>
                    <p className="mt-1 text-sm font-semibold tabular-nums text-fg">
                        {formatBytes(growth.added_7d.bytes)}
                    </p>
                    <p className="text-[11px] tabular-nums text-fg-2">
                        {growth.added_7d.count.toLocaleString()} manifests
                    </p>
                </div>
                <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2">
                    <p className="text-[10px] uppercase tracking-wider text-fg-3">Last sweep</p>
                    <p className="mt-1 text-sm font-semibold tabular-nums text-fg">
                        {report.last_sweep
                            ? `${report.last_sweep.deleted ?? 0} deleted`
                            : 'No sweep recorded'}
                    </p>
                    <p className="text-[11px] tabular-nums text-fg-2">
                        {report.last_sweep
                            ? `${report.last_sweep.failed ?? 0} failed`
                            : 'telemetry pending'}
                    </p>
                </div>
            </div>

            {report.failed_deletions.failed_last_7d > 0 && (
                <div
                    role="alert"
                    className="rounded-[var(--radius-lg)] border border-warn/30 bg-warn/10 px-4 py-3"
                >
                    <p className="text-xs font-semibold text-warn">
                        {report.failed_deletions.failed_last_7d} scheduled or manual deletion
                        failures in the last 7 days.
                    </p>
                    <p className="mt-1 text-[11px] text-fg-2">
                        Failed keys stay visible below. A failed deletion is retried only by a later
                        bounded sweep; this page never retries automatically.
                    </p>
                </div>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
                    <div className="border-b border-line px-4 py-3">
                        <p className="text-sm font-semibold text-fg">Manifests by state</p>
                        <p className="mt-0.5 text-[11px] text-fg-3">
                            Retention state across render artifact manifests.
                        </p>
                    </div>
                    <CountBytesTable order={MANIFEST_STATE_ORDER} buckets={manifests.states} />
                </div>
                <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
                    <div className="border-b border-line px-4 py-3">
                        <p className="text-sm font-semibold text-fg">Manifests by age</p>
                        <p className="mt-0.5 text-[11px] text-fg-3">
                            Creation age of registered manifest rows.
                        </p>
                    </div>
                    <CountBytesTable order={MANIFEST_AGE_ORDER} buckets={manifests.age_buckets} />
                </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
                    <div className="border-b border-line px-4 py-3">
                        <p className="text-sm font-semibold text-fg">Object listing by state</p>
                        <p className="mt-0.5 text-[11px] text-fg-3">
                            {storage.complete
                                ? `${storage.pages_scanned} page(s) scanned · complete`
                                : `${storage.pages_scanned} page(s) scanned · bounded view`}
                        </p>
                    </div>
                    {storage.status === 'ok' ? (
                        <CountBytesTable order={STORAGE_STATE_ORDER} buckets={storage.states} />
                    ) : (
                        <p className="px-4 py-4 text-xs text-warn">
                            {storage.detail ?? 'Object listing is unavailable.'}
                        </p>
                    )}
                </div>
                <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
                    <div className="border-b border-line px-4 py-3">
                        <p className="text-sm font-semibold text-fg">Reference safety</p>
                        <p className="mt-0.5 text-[11px] text-fg-3">
                            Live pointers and protections that block cleanup.
                        </p>
                    </div>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-4 text-xs">
                        <div>
                            <dt className="text-fg-3">Live finalizations</dt>
                            <dd className="font-semibold tabular-nums text-fg">
                                {manifests.references.live_finalizations.toLocaleString()}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-fg-3">Accepted canonical paths</dt>
                            <dd className="font-semibold tabular-nums text-fg">
                                {manifests.references.accepted_canonical_paths.toLocaleString()}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-fg-3">Unaccepted canonical paths</dt>
                            <dd className="font-semibold tabular-nums text-fg">
                                {manifests.references.unaccepted_canonical_paths.toLocaleString()}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-fg-3">Legal-hold manifests</dt>
                            <dd className="font-semibold tabular-nums text-fg">
                                {manifests.references.legal_hold_manifests.toLocaleString()}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-fg-3">Legal-hold canonical paths</dt>
                            <dd className="font-semibold tabular-nums text-fg">
                                {manifests.references.legal_hold_compilations.toLocaleString()}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-fg-3">Grace period</dt>
                            <dd className="font-semibold tabular-nums text-fg">
                                {Math.round(report.grace_seconds / 60)} minutes
                            </dd>
                        </div>
                    </dl>
                </div>
            </div>

            <div className="rounded-[var(--radius-lg)] border border-line bg-surface">
                <div className="border-b border-line px-4 py-3">
                    <p className="text-sm font-semibold text-fg">
                        Storage growth and sweep history
                    </p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                        Registered manifest bytes are the growth basis. Sweep telemetry is
                        operational only and carries no account identifier.
                    </p>
                </div>
                <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 lg:grid-cols-4">
                    <CountBytes label="Added · 24h" value={growth.added_24h} />
                    <CountBytes label="Added · 7d" value={growth.added_7d} />
                    <CountBytes label="Added · 30d" value={growth.added_30d} />
                    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2">
                        <p className="text-[10px] uppercase tracking-wider text-fg-3">
                            Since last sweep
                        </p>
                        <p className="mt-1 text-sm font-semibold tabular-nums text-fg">
                            {growth.change_since_last_sweep_bytes == null
                                ? 'No baseline'
                                : `${growth.change_since_last_sweep_bytes >= 0 ? '+' : ''}${formatBytes(growth.change_since_last_sweep_bytes)}`}
                        </p>
                        <p className="text-[11px] text-fg-2">
                            {report.last_sweep?.at
                                ? new Date(report.last_sweep.at).toLocaleString()
                                : 'no sweep telemetry'}
                        </p>
                    </div>
                </div>
                <div className="border-t border-line px-4 py-3">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                        Orphan candidate keys (sample)
                    </p>
                    <div className="mt-2 max-h-48 overflow-auto">
                        <KeyList keys={storage.orphan_candidates.keys} />
                    </div>
                    {report.failed_deletions.failed_keys.length > 0 && (
                        <div className="mt-3">
                            <p className="text-[10px] font-semibold uppercase tracking-wider text-err">
                                Failed deletion keys
                            </p>
                            <code className="mt-1 block max-h-28 overflow-auto break-all rounded border border-err/20 bg-err/[0.04] p-2 font-mono text-[10px] text-err">
                                {report.failed_deletions.failed_keys.join('\n')}
                            </code>
                        </div>
                    )}
                </div>
            </div>

            <div className="rounded-[var(--radius-lg)] border border-warn/30 bg-surface">
                <div className="border-b border-line px-4 py-3">
                    <p className="text-sm font-semibold text-fg">Guarded orphan cleanup</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                        One bounded page at a time. Referenced artifacts (accepted or unaccepted),
                        legal-hold artifacts and objects inside the{' '}
                        {Math.round(report.grace_seconds / 60)}-minute grace period are never
                        deleted.
                    </p>
                </div>
                <div className="space-y-3 px-4 py-4">
                    <label className="block text-[11px] text-fg-2">
                        Reason for cleanup
                        <input
                            value={reason}
                            onChange={event => setReason(event.target.value)}
                            maxLength={1000}
                            placeholder="Ticket or incident reference (required)"
                            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
                        />
                    </label>
                    <label className="flex items-start gap-2 text-[11px] text-fg-2">
                        <input
                            type="checkbox"
                            checked={confirmDeletion}
                            onChange={event => setConfirmDeletion(event.target.checked)}
                            className="mt-0.5 h-4 w-4 rounded border-line"
                        />
                        <span>
                            I confirm this deletion run. It requires a reason and writes an
                            append-only audit row. Only strictly unreferenced objects older than the
                            grace period can be removed.
                        </span>
                    </label>
                    <div className="flex flex-wrap gap-2">
                        <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => void runCleanup(true)}
                            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
                        >
                            {busy === 'dry_run' ? 'Running dry run…' : 'Dry run'}
                        </button>
                        <button
                            type="button"
                            disabled={busy !== null || !confirmDeletion}
                            onClick={() => void runCleanup(false)}
                            className="rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-1.5 text-xs font-semibold text-err hover:bg-err/15 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {busy === 'delete' ? 'Deleting orphans…' : 'Delete orphan candidates'}
                        </button>
                    </div>
                    {actionError && (
                        <p role="alert" className="text-xs text-err">
                            {actionError}
                        </p>
                    )}
                    {result && <CleanupResult result={result} />}
                    <p className="text-[10px] text-fg-3">
                        The UI never receives object contents. It receives opaque storage keys,
                        sizes and aggregate counts only. Aggregate-only suppression is preserved: no
                        account or document cohort appears in this view.
                    </p>
                </div>
            </div>
        </section>
    )
}
