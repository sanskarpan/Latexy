'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminIntegrationProvider,
    type AdminIntegrationProviderKey,
    type AdminIntegrationsResponse,
} from '@/lib/api-client'

const RANGES = [7, 30, 90, 365] as const
const PLAN_OPTIONS = ['', 'free', 'basic', 'pro', 'byok', 'team', 'student']
const PROVIDER_OPTIONS: Array<{ value: '' | AdminIntegrationProviderKey; label: string }> = [
    { value: '', label: 'All integrations' },
    { value: 'github', label: 'GitHub' },
    { value: 'dropbox', label: 'Dropbox' },
    { value: 'google_drive', label: 'Google Drive' },
    { value: 'zotero', label: 'Zotero' },
    { value: 'mendeley', label: 'Mendeley' },
]
const numberFormatter = new Intl.NumberFormat('en-IN')

function count(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : numberFormatter.format(value)
}

function percent(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function dateTime(value: string | null | undefined): string {
    if (!value) return '—'
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString()
}

function Suppressed({ minimum }: { minimum: number }) {
    return (
        <span className="text-fg-3" title={`Hidden: fewer than ${minimum} distinct users`}>
            Suppressed
        </span>
    )
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
    return (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
                {label}
            </p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-fg">{value}</p>
            {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
        </div>
    )
}

function TelemetryBadge({ state, label }: { state: string; label: string }) {
    const tone =
        state === 'ok'
            ? 'border-ok/30 bg-ok/[0.08] text-ok'
            : state === 'missing_telemetry'
              ? 'border-warn/30 bg-warn/[0.08] text-warn'
              : 'border-line bg-surface-2 text-fg-3'
    return (
        <span
            className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium ${tone}`}
        >
            {label}
        </span>
    )
}

function ProviderTable({
    providers,
    minimum,
}: {
    providers: AdminIntegrationProvider[]
    minimum: number
}) {
    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
                    Provider health
                </h3>
                <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                    Connected accounts come from the token/status columns. OAuth conversion and sync
                    outcomes come from allowlisted telemetry events. Providers with connections but
                    no events are labelled missing telemetry.
                </p>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full min-w-[1040px] border-collapse text-xs">
                    <caption className="sr-only">
                        Integration provider adoption and failure metrics
                    </caption>
                    <thead>
                        <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                            <th scope="col" className="px-5 py-2.5 font-semibold">
                                Provider
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Connected accounts
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                OAuth started
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                OAuth connected
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                OAuth success
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Sync succeeded
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Sync failed
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Sync failure rate
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Disconnects
                            </th>
                            <th scope="col" className="px-5 py-2.5 text-right font-semibold">
                                Last activity
                            </th>
                            <th scope="col" className="px-5 py-2.5 text-right font-semibold">
                                Telemetry
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {providers.map(row => (
                            <tr key={row.provider} className="border-b border-line last:border-0">
                                <th scope="row" className="px-5 py-2 text-left font-medium text-fg">
                                    {row.label}
                                </th>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(row.connected_accounts)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(row.connect_started)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(row.connected)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right font-medium text-fg">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        percent(row.oauth_success_rate_pct)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(row.sync_succeeded)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(row.sync_failed)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right font-medium text-fg">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        percent(row.sync_failure_rate_pct)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(row.disconnected)
                                    )}
                                </td>
                                <td className="px-5 py-2 text-right text-fg-2">
                                    {row.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        dateTime(row.last_activity_at)
                                    )}
                                </td>
                                <td className="px-5 py-2 text-right">
                                    <TelemetryBadge
                                        state={row.telemetry_state}
                                        label={row.telemetry_state_label}
                                    />
                                </td>
                            </tr>
                        ))}
                        {providers.length === 0 && (
                            <tr>
                                <td colSpan={11} className="px-5 py-6 text-center text-fg-3">
                                    No integration provider is available for this filter.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </section>
    )
}

function PlanTable({
    providers,
    minimum,
}: {
    providers: AdminIntegrationProvider[]
    minimum: number
}) {
    const rows = providers.flatMap(provider => provider.by_plan.map(row => ({ provider, row })))
    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
                    Provider × plan
                </h3>
                <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                    Current connected accounts and period activity by plan family. A plan cohort
                    below {minimum} distinct users withholds that provider&apos;s whole plan
                    breakdown.
                </p>
            </div>
            {rows.length === 0 ? (
                <p className="px-5 py-6 text-center text-xs text-fg-3">
                    No provider/plan cohort meets the suppression floor in this period.
                </p>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full min-w-[960px] border-collapse text-xs">
                        <caption className="sr-only">
                            Integration activity by provider and plan
                        </caption>
                        <thead>
                            <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                                <th scope="col" className="px-5 py-2.5 font-semibold">
                                    Provider
                                </th>
                                <th scope="col" className="px-3 py-2.5 font-semibold">
                                    Plan
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    Connected
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    OAuth success
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    Sync succeeded
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    Sync failed
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    Sync failure rate
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    Users
                                </th>
                                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                    Last activity
                                </th>
                                <th scope="col" className="px-5 py-2.5 text-right font-semibold">
                                    Telemetry
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map(({ provider, row }) => (
                                <tr
                                    key={`${provider.provider}:${row.plan}`}
                                    className="border-b border-line last:border-0"
                                >
                                    <th
                                        scope="row"
                                        className="px-5 py-2 text-left font-medium text-fg"
                                    >
                                        {provider.label}
                                    </th>
                                    <td className="px-3 py-2 text-fg-2">{row.plan_label}</td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {count(row.connected_accounts)}
                                    </td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {percent(row.oauth_success_rate_pct)}
                                    </td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {count(row.sync_succeeded)}
                                    </td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {count(row.sync_failed)}
                                    </td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {percent(row.sync_failure_rate_pct)}
                                    </td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {count(row.distinct_users)}
                                    </td>
                                    <td className="px-3 py-2 text-right text-fg-2">
                                        {dateTime(row.last_activity_at)}
                                    </td>
                                    <td className="px-5 py-2 text-right">
                                        <TelemetryBadge
                                            state={row.telemetry_state}
                                            label={row.telemetry_state_label}
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            {providers.some(provider => provider.plan_breakdown_suppressed) && (
                <p className="border-t border-line px-5 py-2 text-[10px] text-fg-3">
                    {providers
                        .filter(provider => provider.plan_breakdown_suppressed)
                        .map(provider => provider.label)
                        .join(', ')}{' '}
                    hidden at plan level because at least one plan cohort has fewer than {minimum}{' '}
                    distinct users.
                </p>
            )}
        </section>
    )
}

function FailureDetail({
    providers,
    minimum,
}: {
    providers: AdminIntegrationProvider[]
    minimum: number
}) {
    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
                    Disconnect reasons and sync error buckets
                </h3>
                <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                    Stable buckets only. Provider error bodies, response text, account handles and
                    file names are never stored.
                </p>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] border-collapse text-xs">
                    <caption className="sr-only">
                        Integration disconnect reasons and sync error classes
                    </caption>
                    <thead>
                        <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                            <th scope="col" className="px-5 py-2.5 font-semibold">
                                Provider
                            </th>
                            <th scope="col" className="px-3 py-2.5 font-semibold">
                                Disconnect reasons
                            </th>
                            <th scope="col" className="px-3 py-2.5 font-semibold">
                                Sync errors
                            </th>
                            <th scope="col" className="px-5 py-2.5 font-semibold">
                                Failed operations
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {providers.map(provider => (
                            <tr
                                key={provider.provider}
                                className="border-b border-line last:border-0"
                            >
                                <th scope="row" className="px-5 py-2 text-left font-medium text-fg">
                                    {provider.label}
                                </th>
                                <td className="px-3 py-2 text-fg-2">
                                    {provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : provider.disconnect_reasons.length === 0 ? (
                                        <span className="text-fg-3">None</span>
                                    ) : (
                                        provider.disconnect_reasons
                                            .map(item => `${item.label} (${item.count})`)
                                            .join(' · ')
                                    )}
                                </td>
                                <td className="px-3 py-2 text-fg-2">
                                    {provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : provider.sync_error_classes.length === 0 ? (
                                        <span className="text-fg-3">None</span>
                                    ) : (
                                        provider.sync_error_classes
                                            .map(item => `${item.label} (${item.count})`)
                                            .join(' · ')
                                    )}
                                </td>
                                <td className="px-5 py-2 text-fg-2">
                                    {provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : provider.sync_failed_by_operation.length === 0 ? (
                                        <span className="text-fg-3">None</span>
                                    ) : (
                                        provider.sync_failed_by_operation
                                            .map(item => `${item.label} (${item.count})`)
                                            .join(' · ')
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    )
}

function ReconciliationTable({
    providers,
    minimum,
}: {
    providers: AdminIntegrationProvider[]
    minimum: number
}) {
    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
                    Token/status reconciliation
                </h3>
                <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                    Current rows are read from server-owned connection columns. Net connection
                    events are the period&apos;s connected minus disconnected events.
                </p>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] border-collapse text-xs">
                    <caption className="sr-only">
                        Integration telemetry and connection reconciliation
                    </caption>
                    <thead>
                        <tr className="border-b border-line bg-surface-2 text-left text-[10px] uppercase tracking-[0.12em] text-fg-3">
                            <th scope="col" className="px-5 py-2.5 font-semibold">
                                Provider
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Current connected
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Telemetry users
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Net connection events
                            </th>
                            <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                                Sync-enabled resources
                            </th>
                            <th scope="col" className="px-5 py-2.5 font-semibold">
                                Source
                            </th>
                            <th scope="col" className="px-5 py-2.5 text-right font-semibold">
                                State
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {providers.map(provider => (
                            <tr
                                key={provider.provider}
                                className="border-b border-line last:border-0"
                            >
                                <th scope="row" className="px-5 py-2 text-left font-medium text-fg">
                                    {provider.label}
                                </th>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(provider.reconciliation.current_connected_accounts)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(provider.reconciliation.telemetry_users)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(provider.reconciliation.period_net_connection_events)
                                    )}
                                </td>
                                <td className="px-3 py-2 text-right text-fg-2">
                                    {provider.reconciliation.sync_status_source == null ? (
                                        <span className="text-fg-3">—</span>
                                    ) : provider.suppressed ? (
                                        <Suppressed minimum={minimum} />
                                    ) : (
                                        count(provider.reconciliation.sync_enabled_resources)
                                    )}
                                </td>
                                <td className="px-5 py-2 font-mono text-[10px] text-fg-3">
                                    {provider.reconciliation.connection_source}
                                    {provider.reconciliation.sync_status_source
                                        ? ` · ${provider.reconciliation.sync_status_source}`
                                        : ''}
                                </td>
                                <td className="px-5 py-2 text-right">
                                    <TelemetryBadge
                                        state={provider.reconciliation.telemetry_state}
                                        label={provider.reconciliation.telemetry_state_label}
                                    />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    )
}

export default function AdminIntegrations() {
    const [days, setDays] = useState(30)
    const [plan, setPlan] = useState('')
    const [provider, setProvider] = useState<'' | AdminIntegrationProviderKey>('')
    const [applied, setApplied] = useState({
        days: 30,
        plan: '',
        provider: '' as '' | AdminIntegrationProviderKey,
    })
    const [data, setData] = useState<AdminIntegrationsResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const generation = useRef(0)

    const load = useCallback(async () => {
        const current = ++generation.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminIntegrations({
                days: applied.days,
                plan: applied.plan || undefined,
                provider: applied.provider || undefined,
            })
            if (generation.current === current) setData(next)
        } catch (err) {
            if (generation.current === current) {
                setError(
                    err instanceof Error ? err.message : 'Failed to load integration analytics'
                )
            }
        } finally {
            if (generation.current === current) setLoading(false)
        }
    }, [applied])

    useEffect(() => {
        void load()
    }, [load])

    const minimum = data?.minimum_cohort_size ?? 5
    const summary = data?.summary

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h2 className="text-sm font-semibold text-fg">
                            Integration adoption and failures
                        </h2>
                        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                            Aggregate GitHub, Dropbox, Google Drive, Zotero and Mendeley adoption,
                            OAuth conversion, sync failure rate, disconnect reasons and last
                            activity by provider and plan. Connected accounts are reconciled against
                            token/status columns; integrations with connections but no events are
                            labelled missing telemetry. Cohorts below {minimum} distinct users are
                            suppressed. OAuth tokens, refresh tokens, emails, file names, account
                            handles and provider error bodies are never stored or returned.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <div
                            className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                            role="group"
                            aria-label="Integration analytics date range"
                        >
                            {RANGES.map(value => (
                                <button
                                    key={value}
                                    type="button"
                                    aria-pressed={days === value}
                                    onClick={() => {
                                        setDays(value)
                                        setApplied(current => ({ ...current, days: value }))
                                    }}
                                    className={`rounded px-2.5 py-1 text-[11px] font-medium ${
                                        days === value
                                            ? 'bg-accent-soft text-accent-strong'
                                            : 'text-fg-3 hover:text-fg'
                                    }`}
                                >
                                    {value}d
                                </button>
                            ))}
                        </div>
                        <select
                            aria-label="Integration analytics plan filter"
                            value={plan}
                            onChange={event => {
                                setPlan(event.target.value)
                                setApplied(current => ({ ...current, plan: event.target.value }))
                            }}
                            className="min-h-[34px] rounded border border-line bg-bg px-2.5 py-1.5 text-[11px] text-fg"
                        >
                            {PLAN_OPTIONS.map(item => (
                                <option key={item || 'all'} value={item}>
                                    {item || 'All plans'}
                                </option>
                            ))}
                        </select>
                        <select
                            aria-label="Integration analytics provider filter"
                            value={provider}
                            onChange={event => {
                                const value = event.target.value as '' | AdminIntegrationProviderKey
                                setProvider(value)
                                setApplied(current => ({ ...current, provider: value }))
                            }}
                            className="min-h-[34px] rounded border border-line bg-bg px-2.5 py-1.5 text-[11px] text-fg"
                        >
                            {PROVIDER_OPTIONS.map(item => (
                                <option key={item.value || 'all'} value={item.value}>
                                    {item.label}
                                </option>
                            ))}
                        </select>
                        <button
                            type="button"
                            onClick={() => void load()}
                            disabled={loading}
                            className="min-h-[34px] rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                            {loading ? 'Refreshing…' : 'Refresh'}
                        </button>
                    </div>
                </div>
                {data && (
                    <p className="mt-3 text-[10px] text-fg-3">
                        {data.period.start} → {data.period.end} · UTC · minimum cohort{' '}
                        {data.minimum_cohort_size} ·{' '}
                        {data.filters.plan ? `plan ${data.filters.plan}` : 'all plans'} ·{' '}
                        {data.filters.provider ?? 'all integrations'}
                    </p>
                )}
            </div>

            {error && (
                <div
                    role="alert"
                    className="mx-5 mt-4 rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err"
                >
                    {error}
                </div>
            )}

            {loading && !data ? (
                <div className="space-y-3 p-5">
                    {Array.from({ length: 4 }).map((_, index) => (
                        <div key={index} className="h-16 animate-pulse rounded-md bg-surface-2" />
                    ))}
                </div>
            ) : data && summary ? (
                <div className="space-y-5 p-5">
                    {summary.suppressed && (
                        <div className="rounded border border-line bg-surface-2 px-4 py-3 text-xs text-fg-3">
                            Report totals are hidden because at least one provider cohort has fewer
                            than {data.minimum_cohort_size} distinct users. Visible provider rows
                            are still shown.
                        </div>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                        <Metric
                            label="Connected accounts"
                            value={count(summary.connected_accounts)}
                            detail={`${count(summary.providers_with_connections)} provider${
                                summary.providers_with_connections === 1 ? '' : 's'
                            } with connections`}
                        />
                        <Metric
                            label="OAuth success"
                            value={percent(summary.oauth_success_rate_pct)}
                            detail={`${count(summary.connected)} connected / ${count(summary.connect_started)} started`}
                        />
                        <Metric
                            label="Sync failure rate"
                            value={percent(summary.sync_failure_rate_pct)}
                            detail={`${count(summary.sync_failed)} failed / ${count(summary.sync_succeeded)} succeeded`}
                        />
                        <Metric
                            label="Disconnects"
                            value={count(summary.disconnected)}
                            detail="User-scoped disconnect events in period"
                        />
                        <Metric
                            label="Distinct users"
                            value={count(summary.distinct_users)}
                            detail="Unique users across connections and telemetry"
                        />
                    </div>

                    <ProviderTable providers={data.providers} minimum={minimum} />
                    <PlanTable providers={data.providers} minimum={minimum} />
                    <FailureDetail providers={data.providers} minimum={minimum} />
                    <ReconciliationTable providers={data.providers} minimum={minimum} />

                    {(data.reconciliation.unattributed_events > 0 ||
                        data.reconciliation.invalid_rows > 0 ||
                        data.reconciliation.event_rows_truncated ||
                        data.reconciliation.connection_rows_truncated) && (
                        <p className="text-[10px] text-fg-3">
                            {data.reconciliation.unattributed_events > 0
                                ? `${data.reconciliation.unattributed_events} de-identified event(s) excluded from distinct-user totals. `
                                : ''}
                            {data.reconciliation.invalid_rows > 0
                                ? `${data.reconciliation.invalid_rows} malformed event row(s) ignored. `
                                : ''}
                            {data.reconciliation.event_rows_truncated ||
                            data.reconciliation.connection_rows_truncated
                                ? 'Report truncated at the configured row cap.'
                                : ''}
                        </p>
                    )}

                    <ul className="list-disc space-y-0.5 pl-4 text-[10px] leading-relaxed text-fg-3">
                        {data.notes.map(note => (
                            <li key={note}>{note}</li>
                        ))}
                    </ul>
                </div>
            ) : (
                !error && (
                    <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
                        Loading integration analytics…
                    </div>
                )
            )}
        </section>
    )
}
