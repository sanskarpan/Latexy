'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type BillingAvailability, type CurrentSubscriptionResponse } from '@/lib/api-client'

interface SubscriptionManagerProps {
  authToken: string | null
  billingStatus: BillingAvailability | null
  checkoutReturned?: boolean
  checkoutStatus?: 'failed' | 'cancelled' | null
  refreshKey?: number
  onUpgrade: () => void
  onLoaded?: (subscription: CurrentSubscriptionResponse | null) => void
}

export default function SubscriptionManager({ authToken, billingStatus, checkoutReturned = false, checkoutStatus = null, refreshKey = 0, onUpgrade, onLoaded }: SubscriptionManagerProps) {
  const [subscription, setSubscription] = useState<CurrentSubscriptionResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCheckingCheckout, setIsCheckingCheckout] = useState(false)
  const [isReconciling, setIsReconciling] = useState(false)
  const [reconcileError, setReconcileError] = useState<string | null>(null)
  const [reconcileNotice, setReconcileNotice] = useState<string | null>(null)
  const [isCancelling, setIsCancelling] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Cancellation failures are shown inline: the subscription is still live, so
  // replacing the card with an error would hide the state the user needs.
  const [cancelError, setCancelError] = useState<string | null>(null)
  const generationRef = useRef(0)
  const latestAuthTokenRef = useRef(authToken)
  const subscriptionRequestRef = useRef(0)
  const reconcileRequestRef = useRef<symbol | null>(null)
  const cancelRequestRef = useRef<symbol | null>(null)
  const autoReconcileRef = useRef<{
    token: string
    promise: ReturnType<typeof apiClient.reconcileSubscription>
  } | null>(null)
  // Invalidate during render, before another account's response can publish
  // between rendering its identity and running the replacement effect.
  if (latestAuthTokenRef.current !== authToken) {
    latestAuthTokenRef.current = authToken
    generationRef.current += 1
    autoReconcileRef.current = null
  }

  const captureRequestContext = useCallback(() => {
    const generation = generationRef.current
    return {
      authToken: authToken ?? '',
      isCurrent: () => generationRef.current === generation && latestAuthTokenRef.current === authToken,
    }
  }, [authToken])

  const fetchSubscription = useCallback(async (quiet = false): Promise<CurrentSubscriptionResponse | null> => {
    const context = captureRequestContext()
    const request = ++subscriptionRequestRef.current
    if (!quiet) {
      setIsLoading(true)
      setError(null)
    }
    // AuthSync owns the singleton token. Bind dispatch and completion to this
    // account without publishing or overwriting that token from a child.
    const response = await apiClient.getCurrentSubscription(authToken ? context : undefined)
    if (!context.isCurrent() || request !== subscriptionRequestRef.current) return null
    setIsLoading(false)
    if (response.success && response.data) {
      setSubscription(response.data)
      onLoaded?.(response.data)
      setError(null)
      return response.data
    }
    if (!quiet) {
      onLoaded?.(null)
      setError(response.error || 'Failed to load subscription')
      setIsLoading(false)
    }
    return null
  }, [authToken, captureRequestContext, onLoaded])

  const showReconcileResult = (result: Awaited<ReturnType<typeof apiClient.reconcileSubscription>>) => {
    if (!result.success || !result.data) {
      setReconcileError(result.error || 'Unable to check payment status right now.')
    } else if (result.data.status === 'unavailable' ||
      (result.data.status === 'reconciled' && !result.data.success)) {
      setReconcileError(result.data.message || 'Unable to check payment status right now.')
    } else if (result.data.status === 'closed') {
      setReconcileNotice(result.data.message || 'This checkout is closed. Your current subscription state is shown below.')
    }
  }

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    const context = captureRequestContext()
    reconcileRequestRef.current = null
    cancelRequestRef.current = null
    setIsReconciling(false)
    setIsCancelling(false)
    setCancelError(null)
    setReconcileError(null)
    setReconcileNotice(null)
    if (!checkoutReturned) autoReconcileRef.current = null
    setIsCheckingCheckout(checkoutReturned && !checkoutStatus)

    const load = async () => {
      const shouldReconcile = attempts === 0 && checkoutReturned && Boolean(authToken)
      if (shouldReconcile && authToken) {
        const request = Symbol('automatic reconciliation')
        reconcileRequestRef.current = request
        setIsReconciling(true)
        // Effect replay or a changed return-status query can await the same
        // owner request. Each new effect owns its own completion and spinner.
        if (autoReconcileRef.current?.token !== authToken) {
          autoReconcileRef.current = {
            token: authToken,
            promise: apiClient.reconcileSubscription(context),
          }
        }
        try {
          const result = await autoReconcileRef.current.promise
          if (!context.isCurrent()) return
          showReconcileResult(result)
        } catch (reconcileFailure) {
          if (!context.isCurrent()) return
          setReconcileError(reconcileFailure instanceof Error
            ? reconcileFailure.message : 'Unable to check payment status right now.')
        } finally {
          if (context.isCurrent() && reconcileRequestRef.current === request) {
            reconcileRequestRef.current = null
            setIsReconciling(false)
          }
        }
      }
      if (!context.isCurrent()) return
      const current = await fetchSubscription(attempts > 0)
      if (!context.isCurrent()) return
      const paymentConfirmed = Boolean(current && current.planId !== 'free' &&
        ['active', 'cancel_scheduled'].includes(current.status))
      if (!checkoutReturned || checkoutStatus || paymentConfirmed || attempts >= 11) {
        setIsCheckingCheckout(false)
        return
      }
      attempts += 1
      timer = setTimeout(load, 2_500)
    }
    void load()
    return () => {
      generationRef.current += 1
      if (timer) clearTimeout(timer)
    }
  }, [authToken, checkoutReturned, checkoutStatus, refreshKey, captureRequestContext, fetchSubscription])

  const pendingCheckout = Boolean(subscription && ['checkout_pending', 'checkout_unknown'].includes(subscription.status))

  const handleCheckPaymentStatus = async () => {
    if (!(checkoutReturned || pendingCheckout) || !authToken || reconcileRequestRef.current) return
    const context = captureRequestContext()
    const request = Symbol('manual reconciliation')
    reconcileRequestRef.current = request
    setIsReconciling(true)
    setReconcileError(null)
    setReconcileNotice(null)
    try {
      const result = await apiClient.reconcileSubscription(context)
      if (!context.isCurrent()) return
      showReconcileResult(result)
    } catch (reconcileFailure) {
      if (!context.isCurrent()) return
      setReconcileError(reconcileFailure instanceof Error
        ? reconcileFailure.message : 'Unable to check payment status right now.')
    } finally {
      if (context.isCurrent()) {
        // Entitlements always come from the authenticated current endpoint.
        await fetchSubscription()
        if (context.isCurrent() && reconcileRequestRef.current === request) {
          reconcileRequestRef.current = null
          setIsReconciling(false)
        }
      }
    }
  }

  const handleCancel = async () => {
    if (!subscription || !authToken || cancelRequestRef.current ||
      !confirm('Cancel renewal? Your paid access will continue through the current billing cycle.')) return
    const context = captureRequestContext()
    const request = Symbol('cancellation')
    cancelRequestRef.current = request
    setIsCancelling(true)
    setCancelError(null)
    try {
      const response = await apiClient.cancelSubscription(context)
      if (!context.isCurrent()) return
      if (!response.success) throw new Error(response.error || 'Failed to cancel subscription')
      await fetchSubscription()
    } catch (err) {
      if (context.isCurrent()) setCancelError(err instanceof Error ? err.message : 'Failed to cancel subscription')
    } finally {
      if (context.isCurrent() && cancelRequestRef.current === request) {
        cancelRequestRef.current = null
        setIsCancelling(false)
      }
    }
  }

  const checkoutRecovery = (checkoutReturned || pendingCheckout) && (
    <div className="mt-3 space-y-2">
      {checkoutStatus && <CheckoutNotice status={checkoutStatus} />}
      {(!subscription || subscription.planId === 'free' || !['active', 'cancel_scheduled'].includes(subscription.status)) && (
        <p role="status" className="text-xs text-fg-3">
          {reconcileNotice || (isCheckingCheckout
            ? 'Checking for your payment confirmation…'
            : 'Payment confirmation has not been verified. Your current plan remains unchanged.')}
        </p>
      )}
      {reconcileError && <p role="alert" className="text-xs text-err">{reconcileError}</p>}
      {authToken && (
        <button
          type="button"
          onClick={() => { void handleCheckPaymentStatus() }}
          disabled={isReconciling}
          className="rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-sm text-fg hover:bg-surface-2 disabled:cursor-wait disabled:opacity-60"
        >
          {isReconciling ? 'Checking payment status…' : 'Check payment status'}
        </button>
      )}
    </div>
  )

  if (isLoading) {
    return <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 text-fg-2">Loading subscription state...</div>
  }

  if (error) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <p role="alert" className="text-sm text-err">{error}</p>
        <button onClick={() => { void fetchSubscription() }} className="mt-3 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-sm text-fg hover:bg-surface-2">
          Retry
        </button>
        {checkoutRecovery}
      </div>
    )
  }

  if (!subscription || subscription.planId === 'free') {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 text-center">
        <h3 className="text-lg font-semibold text-fg">
          {subscription?.planName ?? 'Free Tier'}
        </h3>
        {/* Free-tier copy is intentionally independent of billingStatus.message,
            which explains why paid plans are unavailable and is unrelated to
            why this user is currently on Free. */}
        <p className="mt-1 text-sm text-fg-2">You&apos;re currently on the Free plan.</p>
        {checkoutRecovery}
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

      {checkoutRecovery}

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
            disabled={isCancelling}
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

function CheckoutNotice({ status }: { status: 'failed' | 'cancelled' }) {
  return (
    <p role="status" className="mt-3 text-sm text-warn">
      {status === 'failed'
        ? 'This checkout was reported as unsuccessful. Your current subscription status is shown below.'
        : 'This checkout was reported as cancelled. Your current subscription status is shown below.'}
    </p>
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
