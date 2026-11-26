'use client'

/**
 * Read-only tenant billing/seat utilization card.
 *
 * This panel is intentionally isolated from the rest of tenant management: a
 * billing endpoint or invitation-store failure only affects this card, never
 * branding, members, cohorts or domain controls. It renders aggregate counts
 * only and never asks for card, payment or provider credentials.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AccountPreferenceRequestContext,
  type TenantBilling,
} from '@/lib/api-client'

function Spinner() {
  return (
    <div className="h-5 w-5 animate-spin rounded-full border-2 border-line-2 border-t-accent" />
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-fg-3">{label}</p>
      <p className="text-lg font-semibold text-fg">{value}</p>
      {hint && <p className="text-[11px] text-fg-3">{hint}</p>}
    </div>
  )
}

function subscriptionCopy(billing: TenantBilling): { label: string; detail: string } {
  if (billing.subscription.available) {
    const renewal = billing.subscription.renewal_at
      ? new Date(billing.subscription.renewal_at).toLocaleDateString()
      : 'not scheduled'
    return {
      label: billing.subscription.status ?? 'unknown',
      detail: `Renewal: ${renewal}`,
    }
  }
  return {
    label: 'Renewal status unavailable',
    detail: billing.subscription.detail ?? 'No tenant subscription link is available.',
  }
}

export default function TenantBillingPanel({
  tenantId,
  requestContext,
  canAct,
  isCurrent,
}: {
  tenantId: string
  requestContext: (isCurrent?: () => boolean) => AccountPreferenceRequestContext
  canAct: () => boolean
  isCurrent: () => boolean
}) {
  const [billing, setBilling] = useState<TenantBilling | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const requestRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      requestRef.current += 1
    }
  }, [])

  const load = useCallback(async () => {
    if (!canAct()) {
      setLoading(false)
      setBilling(null)
      return
    }
    const requestId = ++requestRef.current
    setLoading(true)
    setError(null)
    setBilling(null)
    try {
      const context = requestContext(
        () => canAct() && isCurrent() && requestRef.current === requestId,
      )
      const data = await apiClient.getTenantBilling(tenantId, context)
      if (!mountedRef.current || requestRef.current !== requestId) return
      setBilling(data)
    } catch (caught) {
      if (!mountedRef.current || requestRef.current !== requestId) return
      setError(
        caught instanceof Error ? caught.message : 'Billing details are unavailable right now',
      )
    } finally {
      if (mountedRef.current && requestRef.current === requestId) setLoading(false)
    }
  }, [tenantId, requestContext, canAct, isCurrent])

  useEffect(() => {
    void load()
    return () => {
      requestRef.current += 1
    }
  }, [load])

  const requestUpgrade = async () => {
    if (!billing?.upgrade.cta_visible || recording || !canAct()) return
    const requestId = requestRef.current
    setRecording(true)
    try {
      const context = requestContext(
        () => canAct() && isCurrent() && requestRef.current === requestId,
      )
      const result = await apiClient.recordTenantUpgradeIntent(
        tenantId,
        billing.upgrade.target_plan_id,
        context,
      )
      if (!mountedRef.current || requestRef.current !== requestId) return
      toast.success(result.message)
      setBilling((previous) =>
        previous
          ? {
              ...previous,
              upgrade: {
                ...previous.upgrade,
                cta_visible: false,
                cta_label: null,
                reason: 'intent_recorded',
              },
            }
          : previous,
      )
    } catch (caught) {
      if (!mountedRef.current || requestRef.current !== requestId) return
      toast.error(
        caught instanceof Error ? caught.message : 'The upgrade request could not be recorded',
      )
    } finally {
      if (mountedRef.current) setRecording(false)
    }
  }

  const subscription = billing ? subscriptionCopy(billing) : null
  const utilizationWidth = billing
    ? Math.min(100, Math.max(0, billing.seats.utilization_percent))
    : 0

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">
            Billing &amp; seats
          </p>
          <p className="text-xs text-fg-3">Read-only snapshot from tenant records.</p>
        </div>
        {billing && (
          <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-fg-2">
            {billing.plan.name}
          </span>
        )}
      </div>

      {loading && !billing ? (
        <div className="flex justify-center py-4">
          <Spinner />
        </div>
      ) : error ? (
        <div role="alert" className="space-y-2 py-2 text-center">
          <p className="text-xs text-err">{error}</p>
          <p className="text-[11px] text-fg-3">
            Tenant management stays available even when billing details cannot load.
          </p>
          <button
            type="button"
            onClick={() => void load()}
            className="text-xs text-err underline"
          >
            Retry billing
          </button>
        </div>
      ) : billing ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="Active seats" value={String(billing.seats.active)} />
            <Stat
              label="Invited"
              value={
                billing.seats.invited_available ? String(billing.seats.invited ?? 0) : 'Unavailable'
              }
              hint={billing.seats.invited_available ? undefined : 'Invitation store could not be read'}
            />
            <Stat label="Available" value={String(billing.seats.available)} />
            <Stat
              label="Seat limit"
              value={String(billing.seats.max)}
              hint={`${billing.seats.utilization_percent}% used`}
            />
          </div>

          <div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-2">
              <div
                className={`h-full rounded-full ${billing.seats.over_capacity > 0 ? 'bg-err' : 'bg-accent'}`}
                style={{ width: `${utilizationWidth}%` }}
              />
            </div>
            {billing.seats.over_capacity > 0 && (
              <p className="mt-1 text-[11px] text-err">
                {billing.seats.over_capacity} seat(s) over the current limit. New invitations may be
                refused until capacity is available.
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 gap-2 text-xs text-fg-2">
            <div className="flex justify-between gap-3">
              <span className="text-fg-3">Plan status</span>
              <span className="font-medium text-fg">{billing.plan.tenant_status}</span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-fg-3">Invite conversion</span>
              <span className="text-right">
                {billing.invite_conversion.available
                  ? `${billing.invite_conversion.conversion_percent}%`
                  : billing.invite_conversion.reason === 'suppressed_small_cohort'
                    ? `Hidden until ${billing.invite_conversion.minimum_cohort_size} invited seats`
                    : 'Unavailable'}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-fg-3">Subscription</span>
              <span className="text-right">{subscription?.label}</span>
            </div>
            {subscription?.detail && (
              <p className="text-left text-[11px] leading-relaxed text-fg-3">
                {subscription.detail}
              </p>
            )}
          </div>

          {billing.upgrade.cta_visible ? (
            <div className="rounded-[var(--radius-md)] border border-accent/40 bg-accent-soft p-3">
              <p className="text-sm font-medium text-accent-strong">
                {billing.upgrade.cta_label ?? 'Upgrade available'}
              </p>
              <p className="mt-1 text-[11px] leading-relaxed text-fg-2">
                Seat use is at {billing.upgrade.utilization_percent}% of the current limit. This
                records an upgrade request for review; it does not charge a card or change billing.
              </p>
              <button
                type="button"
                onClick={() => void requestUpgrade()}
                disabled={recording}
                className="mt-3 w-full rounded-[var(--radius-md)] bg-accent-soft py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
              >
                {recording ? 'Recording…' : (billing.upgrade.cta_label ?? 'Request upgrade')}
              </button>
            </div>
          ) : billing.upgrade.reason === 'no_higher_tenant_plan' ? (
            <p className="text-[11px] text-fg-3">
              This tenant is on the highest configured plan.
            </p>
          ) : billing.upgrade.reason === 'below_threshold' ? (
            <p className="text-[11px] text-fg-3">
              Upgrade prompts appear at {billing.upgrade.threshold_percent}% seat use.
            </p>
          ) : billing.upgrade.reason === 'intent_recorded' ? (
            <p className="text-[11px] text-ok">Upgrade request recorded for review.</p>
          ) : null}

          <p className="border-t border-line pt-2 text-[10px] leading-relaxed text-fg-3">
            {billing.mapping.subscription.status === 'unavailable'
              ? 'Subscription renewal and paid status are unavailable because tenants are not linked to a subscription record.'
              : 'Plan and seat data come from tenant-owned records.'}
          </p>
        </div>
      ) : null}
    </section>
  )
}
