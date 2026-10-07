'use client'

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import PricingCard from '@/components/billing/PricingCard'
import SubscriptionManager from '@/components/billing/SubscriptionManager'
import { useSession } from '@/lib/auth-client'
import { isTeamInviteOwnerCurrent, type TeamInviteOwner } from '@/lib/team-invite-ownership'
import {
  apiClient,
  type BillingAvailability,
  type CouponValidationResponse,
  type CurrentSubscriptionResponse,
  type TeamSeat,
} from '@/lib/api-client'

type BillingPeriod = 'monthly' | 'annual'

/**
 * Navigate a pre-opened tab to `url`. The tab must be opened synchronously
 * within the click gesture (see callers) to avoid popup blocking. Falls back
 * to a fresh window.open when the pre-opened tab is unavailable.
 */
function safeNavigationUrl(url: string): string | null {
  try {
    const destination = new URL(url, window.location.origin)
    return destination.protocol === 'http:' || destination.protocol === 'https:'
      ? destination.href
      : null
  } catch {
    return null
  }
}

function openInTab(tab: Window | null, url: string): void {
  const destination = safeNavigationUrl(url)
  if (!destination) {
    tab?.close()
    toast.error('The destination URL is invalid.')
    return
  }

  if (tab) {
    tab.opener = null
    tab.location.href = destination
  } else {
    window.open(destination, '_blank', 'noopener,noreferrer')
  }
}

interface PricingPlan {
  id: string
  name: string
  price: number
  currency: string
  interval: string
  purchase_type?: 'one_time' | 'subscription'
  billing_period?: BillingPeriod
  discount_percent?: number
  monthly_equivalent_price?: number
  max_seats?: number
  requires_student_verification?: boolean
  features: {
    compilations: number | string
    optimizations: number | string
    historyRetention: number
    prioritySupport: boolean
    apiAccess: boolean
    customModels?: boolean
    teamSeats?: number
  }
}

const MONTHLY_PLAN_IDS = ['free', 'basic', 'pro', 'byok', 'student', 'team', 'weekly', 'lifetime']
const ANNUAL_PLAN_IDS = ['free', 'basic_annual', 'pro_annual', 'byok_annual', 'student', 'team']

const formatFeature = (value: string | number) => {
  if (value === 'unlimited') return 'Unlimited'
  if (value === 0) return 'None'
  return String(value)
}

const COMPARISON_ROWS: { label: string; value: (plan: PricingPlan) => string | number }[] = [
  { label: 'LaTeX compilations', value: (p) => formatFeature(p.features.compilations) },
  { label: 'AI optimizations', value: (p) => formatFeature(p.features.optimizations) },
  {
    label: 'History retention',
    value: (p) => (p.features.historyRetention === 0 ? 'None' : `${p.features.historyRetention} days`),
  },
  { label: 'Priority support', value: (p) => (p.features.prioritySupport ? 'Yes' : 'No') },
  { label: 'API access', value: (p) => (p.features.apiAccess ? 'Yes' : 'No') },
  {
    label: 'Custom models',
    value: (p) => (typeof p.features.customModels === 'boolean' ? (p.features.customModels ? 'Yes' : 'No') : '—'),
  },
  { label: 'Team seats', value: (p) => (typeof p.features.teamSeats === 'number' ? p.features.teamSeats : '—') },
]

function BillingPageContent() {
  const { data: session, isPending, error: sessionError } = useSession()
  const lastKnownSessionRef = useRef<typeof session>(null)
  if (session) {
    lastKnownSessionRef.current = session
  } else if (!isPending && !sessionError) {
    lastKnownSessionRef.current = null
  }
  const effectiveSession = session ?? ((isPending || sessionError) ? lastKnownSessionRef.current : null)
  const sessionToken = effectiveSession?.session?.token ?? null
  const sessionUser = effectiveSession?.user ?? null
  const isAuthenticated = Boolean(sessionUser?.email)
  const router = useRouter()
  const searchParams = useSearchParams()
  const checkoutReturned = searchParams.get('checkout') === 'return'
  const checkoutStatusParam = searchParams.get('status')?.toLowerCase()
  const checkoutStatus = checkoutReturned
    ? checkoutStatusParam === 'failed'
      ? 'failed'
      : checkoutStatusParam === 'cancelled' || checkoutStatusParam === 'canceled'
        ? 'cancelled'
        : null
    : null
  const flags = useFeatureFlags()

  const [plans, setPlans] = useState<Record<string, PricingPlan>>({})
  const [billingStatus, setBillingStatus] = useState<BillingAvailability | null>(null)
  const [loading, setLoading] = useState(true)
  const [plansError, setPlansError] = useState<string | null>(null)
  const [activePlan, setActivePlan] = useState<string | null>(null)
  const [billingPeriod, setBillingPeriod] = useState<BillingPeriod>('monthly')
  const [couponCode, setCouponCode] = useState('')
  const [couponState, setCouponState] = useState<CouponValidationResponse | null>(null)
  const [couponPlanId, setCouponPlanId] = useState<string | null>(null)
  const [couponLoading, setCouponLoading] = useState(false)
  const [showComparison, setShowComparison] = useState(false)
  const [studentEmail, setStudentEmail] = useState('')
  const [studentCheckoutPlan, setStudentCheckoutPlan] = useState<string | null>(null)
  const [currentSubscription, setCurrentSubscription] = useState<CurrentSubscriptionResponse | null>(null)
  const [teamSeats, setTeamSeats] = useState<TeamSeat[]>([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [teamLoading, setTeamLoading] = useState(false)
  const [handledStudentToken, setHandledStudentToken] = useState<string | null>(null)
  const [teamInviteChecking, setTeamInviteChecking] = useState(false)
  const [teamInviteAccepting, setTeamInviteAccepting] = useState(false)
  const [teamInviteReady, setTeamInviteReady] = useState(false)
  const [teamInviteAccepted, setTeamInviteAccepted] = useState(false)
  const [teamInviteError, setTeamInviteError] = useState<string | null>(null)
  const studentVerifyGenerationRef = useRef(0)
  const studentVerifyAttemptRef = useRef<{
    token: string
    accountKey: string
    generation: number
  } | null>(null)
  // Invitation preview/accept requests are owned by both the token and the
  // authenticated account generation. A late response from a previous token
  // or account must never overwrite the current invitation state.
  const teamInviteGenerationRef = useRef(0)
  const teamInviteOwnerRef = useRef<TeamInviteOwner | null>(null)
  const teamInviteAcceptanceRef = useRef<TeamInviteOwner | null>(null)

  // Note: the Bearer token is published to apiClient by <AuthSync /> in the root
  // layout — it is the single source of truth. Mirroring it from here would race
  // AuthSync (child effects run first) and could publish a null token.

  const fetchPlans = useCallback(async () => {
    setLoading(true)
    setPlansError(null)
    const response = await apiClient.getSubscriptionPlans()
    if (response.success && response.data) {
      setPlans(response.data.plans as Record<string, PricingPlan>)
      setBillingStatus(response.data.billing)
    } else {
      // Keep any previously-loaded plans on screen (e.g. a transient 429 on a
      // background refresh) — only fall back to the empty-state card when we
      // have nothing to show at all.
      setPlansError(response.error || "Couldn't load pricing plans. Please try again.")
      toast.error(response.error || 'Failed to fetch plans')
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    fetchPlans()
  }, [fetchPlans])

  const studentVerifyToken = searchParams.get('student_verify')
  const teamInviteToken = searchParams.get('team_invite')
  const studentVerifyAccountKey = sessionUser && sessionToken
    ? `${sessionUser.id}:${sessionToken}`
    : null

  useEffect(() => {
    const generation = ++studentVerifyGenerationRef.current
    const previousAttempt = studentVerifyAttemptRef.current
    if (
      previousAttempt &&
      studentVerifyToken &&
      studentVerifyAccountKey &&
      previousAttempt.token === studentVerifyToken &&
      previousAttempt.accountKey === studentVerifyAccountKey
    ) {
      // React Strict Mode replays effects after cleanup. Transfer ownership to
      // the replay instead of issuing a second verification request.
      previousAttempt.generation = generation
      return () => {
        if (studentVerifyGenerationRef.current === generation) {
          studentVerifyGenerationRef.current += 1
        }
      }
    }
    if (!studentVerifyToken || handledStudentToken === studentVerifyToken || !studentVerifyAccountKey) {
      studentVerifyAttemptRef.current = null
      return () => {
        if (studentVerifyGenerationRef.current === generation) {
          studentVerifyGenerationRef.current += 1
        }
      }
    }
    const owner = { token: studentVerifyToken, accountKey: studentVerifyAccountKey, generation }
    studentVerifyAttemptRef.current = owner
    const verify = async () => {
      const result = await apiClient.verifyStudentSubscription(studentVerifyToken)
      const stillCurrent =
        studentVerifyGenerationRef.current === owner.generation &&
        studentVerifyAttemptRef.current === owner &&
        studentVerifyToken === owner.token &&
        studentVerifyAccountKey === owner.accountKey
      if (!stillCurrent) return
      studentVerifyAttemptRef.current = null
      if (result.success) {
        toast.success(result.data?.message || 'Student email verified')
        // The short URL is returned by the server and may be an external
        // payment-provider link; reject non-http(s) schemes before navigating.
        if (result.data?.shortUrl && safeNavigationUrl(result.data.shortUrl)) {
          window.location.assign(result.data.shortUrl)
        } else if (result.data?.shortUrl) {
          toast.error('The verification destination URL is invalid.')
        }
      } else {
        toast.error(result.error || 'Student verification failed')
      }
      setHandledStudentToken(studentVerifyToken)
    }
    verify()
    return () => {
      if (studentVerifyGenerationRef.current === generation) {
        studentVerifyGenerationRef.current += 1
      }
    }
  }, [handledStudentToken, studentVerifyAccountKey, studentVerifyToken])

  useEffect(() => {
    const generation = ++teamInviteGenerationRef.current
    teamInviteOwnerRef.current = teamInviteToken && sessionToken
      ? { token: teamInviteToken, sessionToken, generation }
      : null
    teamInviteAcceptanceRef.current = null

    if (!teamInviteToken || !sessionToken) {
      setTeamInviteChecking(false)
      setTeamInviteAccepting(false)
      setTeamInviteReady(false)
      setTeamInviteAccepted(false)
      setTeamInviteError(null)
      return
    }
    let cancelled = false
    setTeamInviteChecking(true)
    setTeamInviteAccepting(false)
    setTeamInviteReady(false)
    setTeamInviteAccepted(false)
    setTeamInviteError(null)
    const previewInvite = async () => {
      const result = await apiClient.previewTeamSeat(teamInviteToken)
      if (cancelled || teamInviteGenerationRef.current !== generation) return
      setTeamInviteChecking(false)
      if (result.success) {
        setTeamInviteReady(true)
      } else {
        setTeamInviteError(result.error || 'Unable to load team invitation')
      }
    }
    previewInvite()
    return () => {
      cancelled = true
      // Invalidate in-flight acceptance work on token/account changes and
      // unmount, before a late response can reach the next owner.
      if (teamInviteGenerationRef.current === generation) {
        teamInviteGenerationRef.current += 1
        teamInviteOwnerRef.current = null
        teamInviteAcceptanceRef.current = null
      }
    }
  }, [sessionToken, teamInviteToken])

  const handleAcceptTeamInvite = async () => {
    const owner = teamInviteOwnerRef.current
    if (
      !isTeamInviteOwnerCurrent(owner, teamInviteToken, sessionToken, teamInviteGenerationRef.current) ||
      teamInviteAcceptanceRef.current !== null
    ) return

    const requestGeneration = owner.generation
    const requestToken = owner.token
    const requestSessionToken = owner.sessionToken
    teamInviteAcceptanceRef.current = {
      token: requestToken,
      sessionToken: requestSessionToken,
      generation: requestGeneration,
    }
    setTeamInviteAccepting(true)
    setTeamInviteError(null)
    const result = await apiClient.joinTeamSeat(requestToken)
    const stillCurrent = isTeamInviteOwnerCurrent(
      teamInviteOwnerRef.current,
      requestToken,
      requestSessionToken,
      requestGeneration,
    )
    if (!stillCurrent) return
    teamInviteAcceptanceRef.current = null
    setTeamInviteAccepting(false)
    if (!result.success) {
      setTeamInviteError(result.error || 'Unable to join team seat')
      // 403/404/409 mean the invitation is no longer actionable. Hide the
      // pending guidance and accept CTA; transient failures remain retryable.
      if (result.status === 403 || result.status === 404 || result.status === 409) {
        setTeamInviteReady(false)
      } else {
        setTeamInviteReady(true)
      }
      return
    }
    setTeamInviteReady(false)
    setTeamInviteAccepted(true)
    toast.success(result.data?.message || 'Team seat activated')
    const refreshed = await apiClient.getCurrentSubscription()
    if (
      isTeamInviteOwnerCurrent(
        teamInviteOwnerRef.current,
        requestToken,
        requestSessionToken,
        requestGeneration,
      ) &&
      refreshed.success &&
      refreshed.data
    ) {
      setCurrentSubscription(refreshed.data)
    }
  }

  const visiblePlans = useMemo(() => {
    const order = billingPeriod === 'annual' ? ANNUAL_PLAN_IDS : MONTHLY_PLAN_IDS
    return order
      .map((id) => plans[id])
      .filter((plan): plan is PricingPlan => Boolean(plan))
  }, [billingPeriod, plans])

  // Mirrors SubscriptionManager's own "no active paid subscription" check so the
  // Free plan card's CTA and behavior stay consistent with the subscription panel.
  const isFreeTier =
    !currentSubscription || (currentSubscription.planId === 'free' && !currentSubscription.subscriptionId)
  const cancellationScheduled = currentSubscription?.status === 'cancel_scheduled'
  const currentPaidPlanId =
    currentSubscription?.subscriptionId &&
    currentSubscription.planId !== 'free' &&
    ['active', 'cancel_scheduled'].includes(currentSubscription.status)
      ? currentSubscription.planId
      : null

  const appliedCoupon = couponState?.valid ? couponState : null
  const couponScopePlan = couponPlanId ? plans[couponPlanId] ?? null : null
  const couponDiscountedPrice =
    appliedCoupon?.discountPercent && couponScopePlan
      ? Math.round(couponScopePlan.price * (1 - appliedCoupon.discountPercent / 100))
      : null
  const formatRupees = (paise: number) => `₹${(paise / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

  const handleApplyCoupon = async () => {
    if (!couponCode.trim()) return
    const targetPlanId = billingPeriod === 'annual' ? 'pro_annual' : 'pro'
    setCouponLoading(true)
    const result = await apiClient.validateCoupon(couponCode.trim(), targetPlanId, billingPeriod)
    setCouponLoading(false)
    if (!result.success || !result.data) {
      toast.error(result.error || 'Coupon validation failed')
      return
    }
    setCouponState(result.data)
    if (result.data.valid) {
      // Record the plan the coupon was validated against so the UI can state its
      // scope explicitly and preview the discounted price on the applicable card.
      setCouponPlanId(targetPlanId)
      toast.success(result.data.message)
    } else {
      setCouponPlanId(null)
      toast.error(result.data.message)
    }
  }

  const handleRemoveCoupon = () => {
    setCouponCode('')
    setCouponState(null)
    setCouponPlanId(null)
  }

  /**
   * A coupon is validated against the Pro plan in the panel above, but it may
   * not apply to the tier the user actually selects. Re-validate against the
   * chosen plan before checkout so we never promise a discount the payment step
   * would reject. Returns the code to send, or null (checkout should abort).
   */
  const resolveCouponForPlan = async (
    planId: string,
    period: BillingPeriod,
  ): Promise<{ code: string | undefined; abort: boolean }> => {
    if (!appliedCoupon?.code) return { code: undefined, abort: false }
    const check = await apiClient.validateCoupon(appliedCoupon.code, planId, period)
    if (check.success && check.data?.valid) {
      return { code: appliedCoupon.code, abort: false }
    }
    toast.error(
      `Coupon ${appliedCoupon.code} is not valid on this plan — remove it or choose a Pro plan to continue.`,
    )
    return { code: undefined, abort: true }
  }

  const refreshTeamSeats = async () => {
    if (!sessionToken || currentSubscription?.planId !== 'team') return
    setTeamLoading(true)
    const result = await apiClient.getTeamSeats()
    setTeamLoading(false)
    if (result.success && result.data) {
      setTeamSeats(result.data)
    }
  }

  useEffect(() => {
    if (currentSubscription?.planId === 'team') {
      refreshTeamSeats()
    }
  }, [currentSubscription?.planId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Selecting Free schedules a paid subscription to end with its current
  // billing cycle, so the UI must not claim that access ends immediately.
  const handleDowngradeToFree = async () => {
    if (
      !confirm(
        'Cancel renewal and switch to Free after this billing cycle? Your paid access continues until then.',
      )
    ) return
    setActivePlan('free')
    const result = await apiClient.cancelSubscription()
    setActivePlan(null)
    if (!result.success) {
      toast.error(result.error || 'Failed to downgrade to Free')
      return
    }
    toast.success(result.message || 'Cancellation scheduled for the end of the billing cycle.')
    const refreshed = await apiClient.getCurrentSubscription()
    if (refreshed.success && refreshed.data) {
      setCurrentSubscription(refreshed.data)
    } else {
      setCurrentSubscription(null)
    }
  }

  const handleSelectPlan = async (planId: string) => {
    if (planId !== 'free' && billingStatus && !billingStatus.available) {
      toast.error(billingStatus.message)
      return
    }

    if (!sessionUser?.email) {
      router.push(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
      return
    }

    if (planId === 'free') {
      if (isFreeTier) {
        toast.info('You are already on the Free plan.')
        return
      }
      await handleDowngradeToFree()
      return
    }

    if (planId === 'student') {
      setStudentCheckoutPlan(planId)
      return
    }

    setActivePlan(planId)
    // Open the target tab synchronously within the click gesture; navigating it
    // after the await avoids the browser popup blocker that fires when
    // window.open is called outside a user gesture.
    const checkoutTab = window.open('', '_blank')
    if (checkoutTab) checkoutTab.opener = null
    const { code: couponCodeForPlan, abort } = await resolveCouponForPlan(planId, billingPeriod)
    if (abort) {
      checkoutTab?.close()
      setActivePlan(null)
      return
    }
    const result = await apiClient.createSubscription(
      planId,
      sessionUser.email,
      sessionUser.name || '',
      {
        billingPeriod: planId === 'weekly' ? 'weekly' : billingPeriod,
        couponCode: couponCodeForPlan,
      },
    )
    setActivePlan(null)

    if (!result.success || !result.data) {
      checkoutTab?.close()
      toast.error(result.error || 'Failed to create subscription')
      return
    }

    // The endpoint answers 200 with success:false for refusals the user must
    // act on (already subscribed, checkout in flight, coupon unusable).
    // SubscriptionCreateResponse does not model those envelope fields.
    const created = result.data as typeof result.data & { success?: boolean; error?: string }
    if (created.success === false) {
      checkoutTab?.close()
      toast.error(created.error || 'Failed to create subscription')
      return
    }

    if (result.data.shortUrl) {
      openInTab(checkoutTab, result.data.shortUrl)
      toast.success('Payment link opened in a new tab.')
      return
    }

    if (result.data.verificationRequired) {
      toast.success(result.data.message || 'Verification email sent')
      if (result.data.verificationPreviewUrl) {
        openInTab(checkoutTab, result.data.verificationPreviewUrl)
      } else {
        checkoutTab?.close()
      }
      return
    }

    checkoutTab?.close()
    toast.success(result.data.message || 'Subscription initialized successfully.')
  }

  const handleStudentCheckout = async () => {
    if (!studentCheckoutPlan || !sessionUser?.email) return
    setActivePlan(studentCheckoutPlan)
    // Pre-open synchronously within the click gesture to avoid popup blocking.
    const previewTab = window.open('', '_blank')
    if (previewTab) previewTab.opener = null
    const { code: couponCodeForPlan, abort } = await resolveCouponForPlan(studentCheckoutPlan, 'monthly')
    if (abort) {
      previewTab?.close()
      setActivePlan(null)
      return
    }
    const result = await apiClient.createSubscription(
      studentCheckoutPlan,
      sessionUser.email,
      sessionUser.name || '',
      {
        billingPeriod: 'monthly',
        couponCode: couponCodeForPlan,
        studentEmail,
      },
    )
    setActivePlan(null)

    if (!result.success || !result.data) {
      previewTab?.close()
      toast.error(result.error || 'Failed to start student verification')
      return
    }

    const requested = result.data as typeof result.data & { success?: boolean; error?: string }
    if (requested.success === false) {
      previewTab?.close()
      toast.error(requested.error || 'Failed to start student verification')
      return
    }

    toast.success(result.data.message || 'Verification email sent')
    if (result.data.verificationPreviewUrl) {
      openInTab(previewTab, result.data.verificationPreviewUrl)
    } else {
      previewTab?.close()
    }
    setStudentCheckoutPlan(null)
    setStudentEmail('')
  }

  const handleInviteSeat = async () => {
    if (!inviteEmail.trim()) return
    setTeamLoading(true)
    // Pre-open synchronously within the click gesture to avoid popup blocking.
    const previewTab = window.open('', '_blank')
    if (previewTab) previewTab.opener = null
    const result = await apiClient.inviteTeamSeat(inviteEmail.trim())
    setTeamLoading(false)
    if (!result.success || !result.data) {
      previewTab?.close()
      toast.error(result.error || 'Failed to invite teammate')
      return
    }
    toast.success(result.data.message)
    if (result.data.invite_preview_url) {
      openInTab(previewTab, result.data.invite_preview_url)
    } else {
      previewTab?.close()
    }
    setInviteEmail('')
    refreshTeamSeats()
  }

  const handleRemoveSeat = async (seatId: string, memberEmail: string) => {
    if (!window.confirm(`Remove ${memberEmail} from your team? They will lose access immediately.`)) {
      return
    }
    setTeamLoading(true)
    const result = await apiClient.removeTeamSeat(seatId)
    setTeamLoading(false)
    if (!result.success) {
      toast.error(result.error || 'Failed to remove seat')
      return
    }
    toast.success('Seat removed')
    refreshTeamSeats()
  }

  if (!flags.billing) {
    return (
      <div className="content-shell">
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 sm:p-8">
          <h1 className="text-3xl font-bold text-fg tracking-tight">All Features Included</h1>
          <p className="mt-2 max-w-2xl text-fg-2">
            All features are available to everyone — no billing or subscription required.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="content-shell">
      <div className="space-y-6">
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 sm:p-8">
          <h1 className="text-3xl font-bold text-fg tracking-tight">Pricing & Billing</h1>
          <p className="mt-2 max-w-2xl text-fg-2">
            Compare configured plans, including optional weekly and lifetime offers, unlock the student discount, and manage seats for team subscriptions.
          </p>
          {billingStatus && !billingStatus.available && (
            <div className="mt-4 rounded-[var(--radius-lg)] border border-warn/30 bg-warn/10 p-4 text-sm text-warn">
              <p className="font-semibold">
                {billingStatus.mode === 'disabled' ? 'Billing Disabled' : 'Billing Unavailable'}
              </p>
              <p className="mt-1 text-warn/80">{billingStatus.message}</p>
            </div>
          )}
          {studentVerifyToken && !sessionToken && !isPending && (
            <div className="mt-4 rounded-[var(--radius-lg)] border border-accent/30 bg-accent-soft p-4 text-sm text-accent-strong">
              Sign in first to finish student verification.
            </div>
          )}
          {teamInviteToken && !sessionToken && !isPending && (
            <div className="mt-4 flex flex-col gap-3 rounded-[var(--radius-lg)] border border-accent/30 bg-accent-soft p-4 text-sm text-accent-strong sm:flex-row sm:items-center sm:justify-between">
              <p>Sign in with the invited email address to review and activate your team seat.</p>
              <button
                type="button"
                onClick={() => router.push(
                  `/login?redirect=${encodeURIComponent(`/billing?team_invite=${teamInviteToken}`)}`,
                )}
                className="shrink-0 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110"
              >
                Sign in to review invitation
              </button>
            </div>
          )}
          {teamInviteToken && sessionToken && (
            <div className="mt-4 rounded-[var(--radius-lg)] border border-accent/30 bg-accent-soft p-4 text-sm text-accent-strong">
              {teamInviteChecking && <p>Checking your team invitation...</p>}
              {teamInviteError && <p>{teamInviteError}</p>}
              {teamInviteReady && (
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p>Review the invitation and accept it to activate your team seat.</p>
                  <button
                    type="button"
                    onClick={handleAcceptTeamInvite}
                    disabled={teamInviteAccepting}
                    className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:opacity-60"
                  >
                    {teamInviteAccepting ? 'Activating...' : 'Accept team invitation'}
                  </button>
                </div>
              )}
              {teamInviteAccepted && <p>Team seat activated successfully.</p>}
            </div>
          )}
        </section>

        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-fg">Choose a plan</h2>
              <p className="mt-1 text-sm text-fg-2">Annual billing saves 20% on Basic, Pro, and BYOK.</p>
              <p className="mt-1 text-xs text-fg-3">All prices include GST — nothing extra added at checkout.</p>
            </div>
            <div
              role="group"
              aria-label="Billing period"
              className="inline-flex rounded-[var(--radius-lg)] border border-line bg-bg p-1"
            >
              <button
                type="button"
                aria-pressed={billingPeriod === 'monthly'}
                onClick={() => setBillingPeriod('monthly')}
                className={`rounded-[var(--radius-md)] px-4 py-2 text-sm ${billingPeriod === 'monthly' ? 'bg-accent text-accent-fg' : 'text-fg-2'}`}
              >
                Monthly
              </button>
              <button
                type="button"
                aria-pressed={billingPeriod === 'annual'}
                onClick={() => setBillingPeriod('annual')}
                className={`inline-flex items-center gap-2 rounded-[var(--radius-md)] px-4 py-2 text-sm ${billingPeriod === 'annual' ? 'bg-accent text-accent-fg' : 'text-fg-2'}`}
              >
                Annual
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                    billingPeriod === 'annual' ? 'bg-accent-fg/20 text-accent-fg' : 'bg-ok/10 text-ok'
                  }`}
                >
                  Save 20%
                </span>
              </button>
            </div>
          </div>

          <div className="mb-5 grid gap-4 lg:grid-cols-[1.6fr_1fr]">
            <div className="rounded-[var(--radius-lg)] border border-line bg-bg p-4">
              <p className="text-sm font-medium text-fg">Have a coupon code?</p>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                <input
                  value={couponCode}
                  onChange={(event) => setCouponCode(event.target.value.toUpperCase())}
                  placeholder="SAVE20"
                  className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3"
                />
                <button
                  onClick={handleApplyCoupon}
                  disabled={couponLoading || !couponCode.trim()}
                  className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg hover:bg-surface-2 disabled:opacity-60"
                >
                  {couponLoading ? 'Applying...' : 'Apply'}
                </button>
              </div>
              {couponState && !couponState.valid && (
                <p className="mt-3 text-sm text-err">{couponState.message}</p>
              )}
              {appliedCoupon && (
                <div className="mt-3 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-2 rounded-[var(--radius-pill)] border border-ok/30 bg-ok/10 px-3 py-1 font-mono text-xs uppercase tracking-wider text-ok">
                      {appliedCoupon.code ?? couponCode}
                      {appliedCoupon.discountPercent ? ` · ${appliedCoupon.discountPercent}% off` : ''}
                      <button
                        type="button"
                        onClick={handleRemoveCoupon}
                        aria-label={`Remove coupon ${appliedCoupon.code ?? couponCode}`}
                        className="rounded-[var(--radius-pill)] px-1 text-ok/80 hover:text-ok focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ok"
                      >
                        ✕
                      </button>
                    </span>
                    <span className="font-mono text-[11px] uppercase tracking-wider text-fg-3">
                      Valid on Pro plans
                    </span>
                  </div>
                  {couponScopePlan && couponDiscountedPrice !== null && (
                    <p className="text-sm text-fg-2">
                      {couponScopePlan.name}:{' '}
                      <span className="text-fg-3 line-through">{formatRupees(couponScopePlan.price)}</span>{' '}
                      <span className="font-semibold text-ok">{formatRupees(couponDiscountedPrice)}</span>
                      <span className="text-fg-3"> / {couponScopePlan.interval}</span>
                    </p>
                  )}
                  <p className="text-xs text-fg-3">
                    Re-checked against your selected plan at checkout.
                  </p>
                </div>
              )}
            </div>

            <div className="rounded-[var(--radius-lg)] border border-accent/20 bg-accent-soft p-4">
              <p className="text-sm font-semibold text-accent-strong">Student plan</p>
              <p className="mt-2 text-sm text-fg-2">
                Get Pro-level features at 50% off after verifying an academic email address.
              </p>
            </div>
          </div>

          {loading ? (
            <div className="rounded-[var(--radius-lg)] border border-line bg-bg p-4 text-fg-2">Loading plans...</div>
          ) : plansError && visiblePlans.length === 0 ? (
            <div className="rounded-[var(--radius-lg)] border border-line bg-bg p-6 text-center">
              <p className="text-sm font-medium text-fg">Couldn&apos;t load billing info</p>
              <p className="mt-1 text-sm text-fg-2">{plansError}</p>
              <button
                type="button"
                onClick={() => fetchPlans()}
                className="mt-4 rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg hover:bg-surface-2"
              >
                Try again
              </button>
            </div>
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {visiblePlans.map((plan, idx) => (
                  <div key={`${plan.id ?? 'plan'}-${idx}`}>
                    <PricingCard
                      plan={plan}
                      isPopular={plan.id === (billingPeriod === 'annual' ? 'pro_annual' : 'pro')}
                      onSelectPlan={handleSelectPlan}
                      isLoading={activePlan === plan.id}
                      disabled={
                        plan.id === 'free'
                          ? isFreeTier || cancellationScheduled
                          : plan.id === currentPaidPlanId || (!!billingStatus && !billingStatus.available)
                      }
                      disabledLabel={
                        plan.id === 'free'
                          ? cancellationScheduled ? 'Free plan scheduled' : 'Current Plan'
                          : plan.id === currentPaidPlanId ? 'Current Plan' : 'Unavailable'
                      }
                    />
                    {plan.id === 'free' && currentPaidPlanId && (
                      <p className="mt-2 text-xs text-fg-3">
                        {cancellationScheduled
                          ? 'Your paid access continues through the current billing period, then your account returns to Free.'
                          : 'Selecting Free schedules cancellation at the end of your current billing period. Your paid access continues until then.'}
                      </p>
                    )}
                  </div>
                ))}
              </div>

              {visiblePlans.length > 1 && (
                <div className="mt-5">
                  <button
                    type="button"
                    onClick={() => setShowComparison((prev) => !prev)}
                    aria-expanded={showComparison}
                    aria-controls="plan-comparison"
                    className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg hover:bg-surface-2"
                  >
                    {showComparison ? 'Hide comparison table' : 'Compare all plans'}
                  </button>

                  {showComparison && (
                    <div id="plan-comparison" className="mt-4 overflow-x-auto rounded-[var(--radius-lg)] border border-line">
                      <table className="w-full min-w-[640px] border-collapse text-sm">
                        <caption className="sr-only">Feature comparison across plans</caption>
                        <thead>
                          <tr className="border-b border-line bg-bg">
                            <th scope="col" className="px-4 py-3 text-left font-mono text-xs uppercase tracking-wider text-fg-3">
                              Feature
                            </th>
                            {visiblePlans.map((plan, idx) => (
                              <th
                                key={`h-${plan.id ?? idx}`}
                                scope="col"
                                className="px-4 py-3 text-left text-sm font-semibold text-fg"
                              >
                                {plan.name}
                                <span className="mt-1 block text-xs font-normal text-fg-2">
                                  {plan.price === 0 ? 'Free' : `${formatRupees(plan.price)} / ${plan.interval}`}
                                </span>
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {COMPARISON_ROWS.map((row) => (
                            <tr key={row.label} className="border-b border-line last:border-b-0">
                              <th scope="row" className="px-4 py-3 text-left font-normal text-fg-2">
                                {row.label}
                              </th>
                              {visiblePlans.map((plan, idx) => (
                                <td key={`${row.label}-${plan.id ?? idx}`} className="px-4 py-3 font-medium text-accent-strong">
                                  {row.value(plan)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </section>

        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 sm:p-6">
          <h2 className="text-lg font-semibold text-fg">Current subscription</h2>
          <div className="mt-4">
            {isPending ? (
              <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 text-fg-2">Loading subscription state...</div>
            ) : isAuthenticated ? (
              <SubscriptionManager
                authToken={sessionToken}
                billingStatus={billingStatus}
                checkoutReturned={checkoutReturned}
                checkoutStatus={checkoutStatus}
                onUpgrade={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                onLoaded={setCurrentSubscription}
              />
            ) : (
              <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <h3 className="text-lg font-semibold text-fg">Public pricing view</h3>
                <p className="mt-2 text-sm text-fg-2">
                  Sign in to subscribe, manage billing, or redeem team invitations.
                </p>
                <Link
                  href={`/login?redirect=${encodeURIComponent('/billing')}`}
                  className="mt-4 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110"
                >
                  Sign In to Subscribe
                </Link>
              </div>
            )}
          </div>
        </section>

        {currentSubscription?.planId === 'team' && (
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-fg">Team seats</h2>
                <p className="mt-1 text-sm text-fg-2">Invite up to 5 teammates and manage active seats.</p>
              </div>
            </div>

            <div className="mb-5 flex flex-col gap-3 sm:flex-row">
              <input
                value={inviteEmail}
                onChange={(event) => setInviteEmail(event.target.value)}
                placeholder="teammate@company.com"
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3"
              />
              <button
                onClick={handleInviteSeat}
                disabled={teamLoading || !inviteEmail.trim()}
                className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg hover:bg-surface-2 disabled:opacity-60"
              >
                {teamLoading ? 'Inviting...' : 'Invite teammate'}
              </button>
            </div>

            <div className="space-y-3">
              {teamSeats.length === 0 ? (
                <div className="rounded-[var(--radius-lg)] border border-line bg-bg p-4 text-sm text-fg-2">
                  No team seats assigned yet.
                </div>
              ) : (
                teamSeats.map((seat) => (
                  <div key={seat.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-line bg-bg p-4">
                    <div>
                      <p className="text-sm font-medium text-fg">{seat.member_email}</p>
                      <p className="mt-1 text-xs text-fg-2">
                        {seat.status} • invited {new Date(seat.invited_at).toLocaleDateString()}
                      </p>
                    </div>
                    <button
                      onClick={() => handleRemoveSeat(seat.id, seat.member_email)}
                      className="rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-sm text-err hover:bg-err/20"
                    >
                      Remove
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        )}

        {studentCheckoutPlan && (
          <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-fg">Verify student plan</h2>
            <p className="mt-2 max-w-2xl text-sm text-fg-2">
              Enter your academic email address. We’ll send a verification link before activating the discounted student plan.
            </p>
            <div className="mt-4 flex flex-col gap-3 sm:flex-row">
              <input
                value={studentEmail}
                onChange={(event) => setStudentEmail(event.target.value)}
                placeholder="you@university.edu"
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3"
              />
              <button
                onClick={handleStudentCheckout}
                disabled={!studentEmail.trim() || activePlan === studentCheckoutPlan}
                className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:opacity-60"
              >
                {activePlan === studentCheckoutPlan ? 'Sending...' : 'Send Verification'}
              </button>
              <button
                onClick={() => {
                  setStudentCheckoutPlan(null)
                  setStudentEmail('')
                }}
                className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm text-fg hover:bg-surface-2"
              >
                Cancel
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

export default function BillingPage() {
  return (
    <Suspense
      fallback={(
        <div className="content-shell">
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 sm:p-8 text-fg-2">
            Loading billing page...
          </div>
        </div>
      )}
    >
      <BillingPageContent />
    </Suspense>
  )
}
