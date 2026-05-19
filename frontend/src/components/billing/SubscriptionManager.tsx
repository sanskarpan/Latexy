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

  const fetchSubscription = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    apiClient.setAuthToken(authToken)
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
    if (!subscription || !confirm('Cancel this subscription?')) return
    setIsCancelling(true)
    setError(null)
    try {
      apiClient.setAuthToken(authToken)
      const response = await apiClient.cancelSubscription()
      if (!response.success) throw new Error(response.error || 'Failed to cancel subscription')
      await fetchSubscription()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel subscription')
    } finally {
      setIsCancelling(false)
    }
  }

  if (isLoading) {
    return <div className="surface-card p-4 text-slate-300">Loading subscription state...</div>
  }

  if (error) {
    return (
      <div className="surface-card p-4">
        <p className="text-sm text-rose-300">{error}</p>
        <button onClick={fetchSubscription} className="mt-3 rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-100 hover:bg-white/10">
          Retry
        </button>
      </div>
    )
  }

  if (!subscription || (subscription.planId === 'free' && !subscription.subscriptionId)) {
    return (
      <div className="surface-card p-5 text-center">
        <h3 className="text-lg font-semibold text-white">
          {subscription?.planName ?? 'Free Tier'}
        </h3>
        <p className="mt-1 text-sm text-slate-400">
          {billingStatus?.available
            ? 'You are on the free tier.'
            : billingStatus?.message || 'Billing is unavailable in this environment.'}
        </p>
        {billingStatus?.available && (
          <button onClick={onUpgrade} className="mt-4 rounded-lg bg-orange-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-orange-200">
            Browse Plans
          </button>
        )}
      </div>
    )
  }

  const statusClass =
    subscription.status === 'active'
      ? 'text-emerald-200 border-emerald-300/30 bg-emerald-300/10'
      : 'text-amber-200 border-amber-300/30 bg-amber-300/10'

  return (
    <div className="surface-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-white">{subscription.planName}</h3>
        <span className={`rounded-full border px-2 py-1 text-xs uppercase tracking-wider ${statusClass}`}>
          {subscription.status}
        </span>
      </div>

      <div className="mt-2 text-sm text-slate-400">
        {subscription.currentPeriodEnd
          ? `Renews on ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}`
          : 'No renewal date'}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Metric label="Compilations" value={String(subscription.features.compilations)} />
        <Metric label="Optimizations" value={String(subscription.features.optimizations)} />
        <Metric
          label="History"
          value={subscription.features.historyRetention === 0 ? 'None' : `${subscription.features.historyRetention} days`}
        />
        <div className="surface-card p-3">
          <p className="text-xs uppercase tracking-wider text-slate-500">Enabled Features</p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-200">
            {subscription.features.prioritySupport && <Tag text="Priority" />}
            {subscription.features.apiAccess && <Tag text="API" />}
            {subscription.features.customModels && <Tag text="Custom Models" />}
            {!subscription.features.prioritySupport && !subscription.features.apiAccess && !subscription.features.customModels && (
              <span className="text-slate-500">None</span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={onUpgrade}
          disabled={!billingStatus?.available}
          className="rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-100 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Change Plan
        </button>
        {subscription.status === 'active' && subscription.subscriptionId && (
          <button
            onClick={handleCancel}
            disabled={isCancelling || !billingStatus?.available}
            className="rounded-lg border border-rose-300/30 bg-rose-300/10 px-3 py-2 text-sm text-rose-100 hover:bg-rose-300/20 disabled:opacity-60"
          >
            {isCancelling ? 'Cancelling...' : 'Cancel'}
          </button>
        )}
      </div>

      {billingStatus && !billingStatus.available && (
        <p className="mt-4 text-sm text-amber-200">{billingStatus.message}</p>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface-card p-3">
      <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-orange-200">{value}</p>
    </div>
  )
}

function Tag({ text }: { text: string }) {
  return <span className="rounded-full border border-orange-200/25 bg-orange-300/10 px-2 py-1 text-orange-100">{text}</span>
}
