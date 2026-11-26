'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    apiClient,
    type AdminTeamSeatInvitations,
    type AdminTeamSeatOwner,
    type AdminTeamSeatResponse,
    type AdminTeamSeatTenant,
} from '@/lib/api-client'
import { formatNumber, shortId } from './admin-format'

const WINDOWS = [7, 30, 90, 365] as const

function rate(value: number | null | undefined): string {
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)}%`
}

function duration(hours: number | null | undefined): string {
    if (hours == null || !Number.isFinite(hours)) return '—'
    if (hours < 1) return `${Math.round(hours * 60)}m`
    if (hours < 48) return `${hours.toFixed(1)}h`
    return `${(hours / 24).toFixed(1)}d`
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

function InviteCell({ invitations }: { invitations: AdminTeamSeatInvitations | null }) {
    if (!invitations) {
        return <span className="text-[10px] text-fg-3">Hidden (&lt;5 invites)</span>
    }
    return <span>{rate(invitations.invite_to_active_pct)}</span>
}

function OwnerTable({ rows }: { rows: AdminTeamSeatOwner[] }) {
    return (
        <div className="overflow-x-auto rounded border border-line">
            <table className="w-full min-w-[900px] border-collapse text-xs">
                <caption className="sr-only">Team seat utilization by owner</caption>
                <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
                    <tr>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Owner
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Plan / tenant
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Active
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Invited
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Removed
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Utilization
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Invite → accept
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Invite → active
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Median accept
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Stale 30d
                        </th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-line">
                    {rows.map(row => (
                        <tr key={row.owner_user_id}>
                            <th scope="row" className="px-3 py-2 text-left font-medium text-fg">
                                <span title={row.owner_user_id}>{shortId(row.owner_user_id)}</span>
                                {!row.team_plan_active && (
                                    <span className="ml-1 rounded border border-warn/30 bg-warn/10 px-1 py-0.5 text-[9px] font-semibold uppercase text-warn">
                                        plan inactive
                                    </span>
                                )}
                            </th>
                            <td className="px-3 py-2 text-fg-2">
                                <p className="font-medium text-fg">{row.owner_plan}</p>
                                <p className="text-[10px] text-fg-3">
                                    {row.tenant?.tenant_name ?? 'Unassigned tenant'}
                                </p>
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg">
                                {formatNumber(row.current.active)} /{' '}
                                {formatNumber(row.current.seat_capacity)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.current.pending)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.current.removed)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums font-semibold text-fg">
                                {rate(row.current.utilization_pct)}
                                {row.current.over_capacity > 0 && (
                                    <span className="ml-1 text-[10px] font-semibold text-warn">
                                        +{formatNumber(row.current.over_capacity)} over
                                    </span>
                                )}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {rate(row.invitations?.invite_to_accept_pct)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                <InviteCell invitations={row.invitations} />
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {duration(row.invitations?.median_accept_hours)}
                                {row.invitations?.median_accept_suppressed && (
                                    <span className="ml-1 text-[9px] text-fg-3">hidden</span>
                                )}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.current.aging_invites.over_30_days)}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={10} className="px-3 py-5 text-center text-fg-3">
                                No owner has reached five seats in this selection.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

function TenantTable({ rows }: { rows: AdminTeamSeatTenant[] }) {
    return (
        <div className="overflow-x-auto rounded border border-line">
            <table className="w-full min-w-[860px] border-collapse text-xs">
                <caption className="sr-only">Team seat and member utilization by tenant</caption>
                <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
                    <tr>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Tenant
                        </th>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">
                            Plan / cap
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Team owners
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Active seats
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Seat utilization
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Members
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Member utilization
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Invite → active
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Median accept
                        </th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">
                            Stale 30d
                        </th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-line">
                    {rows.map(row => (
                        <tr key={row.tenant_id}>
                            <th scope="row" className="px-3 py-2 text-left font-medium text-fg">
                                {row.tenant_name}
                            </th>
                            <td className="px-3 py-2 text-fg-2">
                                <p className="font-medium text-fg">{row.tenant_plan_id}</p>
                                <p className="text-[10px] text-fg-3">
                                    {formatNumber(row.tenant_max_members)} member cap
                                </p>
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {formatNumber(row.team_owners)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg">
                                {row.current
                                    ? `${formatNumber(row.current.active)} / ${formatNumber(row.current.seat_capacity)}`
                                    : 'Hidden'}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums font-semibold text-fg">
                                {row.current
                                    ? rate(row.current.utilization_pct)
                                    : 'Hidden (<5 seats)'}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {row.tenant_members
                                    ? `${formatNumber(row.tenant_members.active_members)} / ${formatNumber(row.tenant_members.member_cap)}`
                                    : 'Hidden'}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums font-semibold text-fg">
                                {row.tenant_members
                                    ? rate(row.tenant_members.utilization_pct)
                                    : 'Hidden (<5)'}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {row.invitations
                                    ? rate(row.invitations.invite_to_active_pct)
                                    : 'Hidden'}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {row.invitations
                                    ? duration(row.invitations.median_accept_hours)
                                    : '—'}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-fg-2">
                                {row.current
                                    ? formatNumber(row.current.aging_invites.over_30_days)
                                    : '—'}
                            </td>
                        </tr>
                    ))}
                    {rows.length === 0 && (
                        <tr>
                            <td colSpan={10} className="px-3 py-5 text-center text-fg-3">
                                No tenant has reached the five-seat or five-member publication
                                floor.
                            </td>
                        </tr>
                    )}
                </tbody>
            </table>
        </div>
    )
}

export default function AdminTeamSeatUtilization() {
    const [days, setDays] = useState<number>(30)
    const [ownerId, setOwnerId] = useState('')
    const [tenantId, setTenantId] = useState('')
    const [applied, setApplied] = useState({ ownerId: '', tenantId: '' })
    const [data, setData] = useState<AdminTeamSeatResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const generation = useRef(0)

    const load = useCallback(async () => {
        const current = ++generation.current
        setLoading(true)
        setError(null)
        try {
            const next = await apiClient.getAdminTeamSeatUtilization({
                days,
                owner_id: applied.ownerId.trim() || undefined,
                tenant_id: applied.tenantId.trim() || undefined,
            })
            if (generation.current === current) setData(next)
        } catch (err) {
            if (generation.current === current) {
                setError(
                    err instanceof Error ? err.message : 'Failed to load team seat utilization'
                )
            }
        } finally {
            if (generation.current === current) setLoading(false)
        }
    }, [applied.ownerId, applied.tenantId, days])

    useEffect(() => {
        void load()
    }, [load])

    const summary = data?.summary
    const current = summary?.current ?? null
    const invitations = summary?.invitations ?? null
    const suppressSummary = Boolean(data?.suppression.summary_suppressed)
    const checksPass = data?.reconciliation.all_checks_passed ?? true

    return (
        <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
            <div className="border-b border-line px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h3 className="text-sm font-semibold text-fg">Team seat utilization</h3>
                        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
                            Aggregate seat states, invite conversion, stale invitations, median
                            accept time and utilization against the team plan cap. Invitee emails,
                            member ids and cross-tenant seats are never returned; cohorts below{' '}
                            {data?.minimum_group_size ?? 5} are suppressed.
                        </p>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                            {loading ? 'Loading…' : data ? `${data.days} days · UTC` : '—'}
                        </span>
                        <button
                            type="button"
                            onClick={() => void load()}
                            disabled={loading}
                            className="rounded border border-line px-2.5 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                            Refresh
                        </button>
                    </div>
                </div>

                <div className="mt-3 flex flex-wrap items-end gap-2">
                    <div
                        className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
                        role="group"
                        aria-label="Team seat period"
                    >
                        {WINDOWS.map(window => (
                            <button
                                key={window}
                                type="button"
                                aria-pressed={days === window}
                                onClick={() => setDays(window)}
                                className={`rounded px-2.5 py-1 text-[10px] font-medium ${days === window ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'}`}
                            >
                                {window}d
                            </button>
                        ))}
                    </div>
                    <label className="flex flex-col gap-1 text-[10px] text-fg-3">
                        Owner id
                        <input
                            value={ownerId}
                            onChange={event => setOwnerId(event.target.value)}
                            placeholder="optional UUID"
                            className="min-h-[32px] w-52 rounded-md border border-line bg-surface px-2 py-1 text-xs text-fg"
                        />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] text-fg-3">
                        Tenant id
                        <input
                            value={tenantId}
                            onChange={event => setTenantId(event.target.value)}
                            placeholder="optional UUID"
                            className="min-h-[32px] w-52 rounded-md border border-line bg-surface px-2 py-1 text-xs text-fg"
                        />
                    </label>
                    <button
                        type="button"
                        onClick={() => setApplied({ ownerId, tenantId })}
                        disabled={loading}
                        className="rounded border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                    >
                        Apply filters
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            setOwnerId('')
                            setTenantId('')
                            setApplied({ ownerId: '', tenantId: '' })
                        }}
                        disabled={loading || (!applied.ownerId && !applied.tenantId)}
                        className="rounded border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                    >
                        Clear
                    </button>
                    {data?.filters.tenant_name && (
                        <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                            Tenant: {data.filters.tenant_name}
                        </span>
                    )}
                </div>
            </div>

            {error && (
                <p
                    role="alert"
                    className="mx-5 mt-4 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err"
                >
                    {error}
                </p>
            )}

            {data && !checksPass && (
                <p
                    role="alert"
                    className="mx-5 mt-4 rounded border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn"
                >
                    Seat counts did not reconcile for this selection. Do not use these figures for
                    billing decisions until the source rows are reviewed.
                </p>
            )}

            {suppressSummary && (
                <p className="mx-5 mt-4 rounded border border-line bg-surface-2 px-3 py-2 text-xs text-fg-3">
                    Summary hidden because the selected seat cohort is smaller than{' '}
                    {data?.minimum_group_size ?? 5}.{' '}
                    {formatNumber(data?.suppression.suppressed_owner_rows)} owner row
                    {data?.suppression.suppressed_owner_rows === 1 ? '' : 's'} withheld.
                </p>
            )}

            {current && (
                <div className="grid gap-3 px-5 py-4 sm:grid-cols-2 xl:grid-cols-6">
                    <Metric
                        label="Active seats"
                        value={`${formatNumber(current.active)} / ${formatNumber(current.seat_capacity)}`}
                        detail={`${formatNumber(current.pending)} pending · ${formatNumber(current.removed)} removed`}
                    />
                    <Metric
                        label="Utilization"
                        value={rate(current.utilization_pct)}
                        detail={`Cap ${formatNumber(current.seat_cap)} per owner${current.over_capacity > 0 ? ` · ${formatNumber(current.over_capacity)} over` : ''}`}
                    />
                    <Metric
                        label="Invite → active"
                        value={rate(invitations?.invite_to_active_pct)}
                        detail={
                            invitations
                                ? `${formatNumber(invitations.active_now)} active of ${formatNumber(invitations.invited)} invited`
                                : 'Hidden below 5 invites'
                        }
                    />
                    <Metric
                        label="Invite → accept"
                        value={rate(invitations?.invite_to_accept_pct)}
                        detail={
                            invitations
                                ? `${formatNumber(invitations.accepted_ever)} ever accepted`
                                : 'Hidden below 5 invites'
                        }
                    />
                    <Metric
                        label="Median accept"
                        value={duration(invitations?.median_accept_hours)}
                        detail={
                            invitations?.median_accept_suppressed
                                ? 'Hidden below 5 accepted samples'
                                : `${formatNumber(invitations?.accept_samples)} accepted samples`
                        }
                    />
                    <Metric
                        label="Stale invites"
                        value={formatNumber(current.aging_invites.over_30_days)}
                        detail={`${formatNumber(current.aging_invites.over_7_days)} over 7d · oldest ${formatNumber(current.aging_invites.oldest_pending_days)}d`}
                    />
                </div>
            )}

            {data && (
                <div className="space-y-4 border-t border-line px-5 py-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <div>
                            <h4 className="text-xs font-semibold text-fg">Owners</h4>
                            <p className="mt-0.5 text-[10px] text-fg-3">
                                {formatNumber(data.reconciliation.owner_rows_published)} published ·{' '}
                                {formatNumber(data.suppression.suppressed_owner_rows)} withheld
                                {data.reconciliation.owners_with_multiple_tenants > 0
                                    ? ` · ${formatNumber(data.reconciliation.owners_with_multiple_tenants)} owners attributed to one of multiple tenants`
                                    : ''}
                            </p>
                        </div>
                        <span className="text-[10px] text-fg-3">
                            {formatNumber(summary?.team_plan_owners)} team-plan owners ·{' '}
                            {formatNumber(summary?.owners_at_or_over_cap)} at cap
                        </span>
                    </div>
                    <OwnerTable rows={data.owners} />

                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <div>
                            <h4 className="text-xs font-semibold text-fg">Tenants</h4>
                            <p className="mt-0.5 text-[10px] text-fg-3">
                                {formatNumber(data.reconciliation.tenant_rows_published)} published
                                · {formatNumber(data.suppression.suppressed_tenant_rows)} withheld ·{' '}
                                {formatNumber(data.reconciliation.unassigned_seats)} unassigned seat
                                {data.reconciliation.unassigned_seats === 1 ? '' : 's'}
                            </p>
                        </div>
                        <span className="text-[10px] text-fg-3">
                            Tenant member utilization uses the tenant max_members cap.
                        </span>
                    </div>
                    <TenantTable rows={data.tenants} />

                    <p className="text-[10px] leading-relaxed text-fg-3">
                        Seat status is normalized to active, pending (invited), removed and other.
                        Invitation rates count seats invited in the selected window; current
                        utilization counts seats that are active now. Median accept time uses
                        accepted seats with both timestamps. An owner is attributed to at most one
                        tenant so seats are not double-counted. No invitee email, member id, token
                        or payment identifier is included.
                    </p>
                </div>
            )}
        </section>
    )
}
