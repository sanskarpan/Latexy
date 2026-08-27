'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiClient, type BillingAvailability, type CurrentSubscriptionResponse } from '@/lib/api-client'

interface SubscriptionManagerProps {
  authToken: string | null
  billingStatus: BillingAvailability | null
  onUpgrade: () => void
  onLoaded?: (subscription: CurrentSubscriptionResponse | null) => void
}

export default function SubscriptionManager({ authToken, billingStatus, onUpgrade, onLoaded }: SubscriptionManagerProps) {
  const [subscription, setSubscription] = useState<CurrentSubscriptionResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCancelling, setIsCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Cancellation failures are shown inline: the subscription is still live, so
  // replacing the card with an error would hide the state the user needs.
  const [cancelError, setCancelError] = useState<string | null>(null)

  const fetchSubscription = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    // The Bearer token itself is published to apiClient by <AuthSync /> — this
    // component must not set it (a child effect would race AuthSync and could
    // publish a null). authToken stays a dependency purely so that a session
    // change re-fetches the subscription.
    void authToken
    const response = await apiClient.getCurrentSubscription()
    if (response.success && response.data) {
      setSubscription(response.data)
      onLoaded?.(response.data)
      setIsLoading(false)
      return
    }

    onLoaded?.(null)
    setError(response.error || 'Failed to load subscription')
    setIsLoading(false)
  }, [authToken, onLoaded])

  useEffect(() => {
    fetchSubscription()
  }, [fetchSubscription])

  const handleCancel = async () => {
    if (
      !subscription ||
      !confirm('Cancel renewal? Your paid access will continue through the current billing cycle.')
    ) return
    setIsCancelling(true)
    setCancelError(null)
    try {
      const response = await apiClient.cancelSubscription()
      if (!response.success) throw new Error(response.error || 'Failed to cancel subscription')
      await fetchSubscription()
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : 'Failed to cancel subscription')
    } finally {
      setIsCancelling(false)
    }
  }

  if (isLoading) {
    return <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 text-fg-2">Loading subscription state...</div>
  }

  if (error) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <p className="text-sm text-err">{error}</p>
        <button onClick={fetchSubscription} className="mt-3 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-sm text-fg hover:bg-surface-2">
          Retry
        </button>
      </div>
    )
  }

  if (!subscription || (subscription.planId === 'free' && !subscription.subscriptionId)) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 text-center">
        <h3 className="text-lg font-semibold text-fg">
          {subscription?.planName ?? 'Free Tier'}
        </h3>
        {/* Free-tier copy is intentionally independent of billingStatus.message —
            that string explains *why paid plans are unavailable* (e.g. Razorpay
            isn't configured), which is unrelated to why this user is on Free and
            must not be presented as if it were the reason. */}
        <p className="mt-1 text-sm text-fg-2">You&apos;re currently on the Free plan.</p>
        {billingStatus && !billingStatus.available && (
          <p className="mt-1 text-xs text-fg-3">{billingStatus.message}</p>
        )}
        {billingStatus?.available && (
          <button onClick={onUpgrade} className="mt-4 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110">
            Browse Plans
          </button>
        )}
      </div>
    )
  }

  const cancellationScheduled = subscription.status === 'cancel_scheduled'
  const statusClass =
    subscription.status === 'active'
      ? 'text-ok border-ok/30 bg-ok/10'
      : 'text-warn border-warn/30 bg-warn/10'

  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-fg">{subscription.planName}</h3>
        <span className={`rounded-full border px-2 py-1 text-xs uppercase tracking-wider ${statusClass}`}>
          {cancellationScheduled ? 'Cancellation scheduled' : subscription.status}
        </span>
      </div>

      <div className="mt-2 text-sm text-fg-2">
        {subscription.currentPeriodEnd
          ? `${cancellationScheduled ? 'Access until' : 'Renews on'} ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}`
          : 'No renewal date'}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Metric label="Compilations" value={String(subscription.features.compilations)} />
        <Metric label="Optimizations" value={String(subscription.features.optimizations)} />
        <Metric
          label="History"
          value={subscription.features.historyRetention === 0 ? 'None' : `${subscription.features.historyRetention} days`}
        />
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-3">
          <p className="text-xs uppercase tracking-wider text-fg-3">Enabled Features</p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-fg">
            {subscription.features.prioritySupport && <Tag text="Priority" />}
            {subscription.features.apiAccess && <Tag text="API" />}
            {subscription.features.customModels && <Tag text="Custom Models" />}
            {!subscription.features.prioritySupport && !subscription.features.apiAccess && !subscription.features.customModels && (
              <span className="text-fg-3">None</span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={onUpgrade}
          disabled={!billingStatus?.available || cancellationScheduled}
          className="rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-sm text-fg hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Change Plan
        </button>
        {subscription.status === 'active' && subscription.subscriptionId && (
          <button
            onClick={handleCancel}
            disabled={isCancelling || !billingStatus?.available}
            className="rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-sm text-err hover:bg-err/20 disabled:opacity-60"
          >
            {isCancelling ? 'Cancelling...' : 'Cancel'}
          </button>
        )}
      </div>

      {cancelError && <p className="mt-4 text-sm text-err">{cancelError}</p>}

      {billingStatus && !billingStatus.available && (
        <p className="mt-4 text-sm text-warn">{billingStatus.message}</p>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-3">
      <p className="text-xs uppercase tracking-wider text-fg-3">{label}</p>
      <p className="mt-1 text-lg font-semibold text-accent-strong">{value}</p>
    </div>
  )
}

function Tag({ text }: { text: string }) {
  return <span className="rounded-full border border-accent bg-accent-soft px-2 py-1 text-accent-strong">{text}</span>
}
