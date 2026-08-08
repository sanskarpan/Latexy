'use client'

import { Suspense, useEffect, useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import PricingCard from '@/components/billing/PricingCard'
import SubscriptionManager from '@/components/billing/SubscriptionManager'
import { useSession } from '@/lib/auth-client'
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
function openInTab(tab: Window | null, url: string): void {
  if (tab) {
    tab.location.href = url
  } else {
    window.open(url, '_blank')
  }
}

interface PricingPlan {
  id: string
  name: string
  price: number
  currency: string
  interval: string
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

const MONTHLY_PLAN_IDS = ['free', 'basic', 'pro', 'byok', 'student', 'team']
const ANNUAL_PLAN_IDS = ['free', 'basic_annual', 'pro_annual', 'byok_annual', 'student', 'team']

function BillingPageContent() {
  const { data: session, isPending } = useSession()
  const sessionToken = session?.session?.token ?? null
  const sessionUser = session?.user ?? null
  const isAuthenticated = Boolean(sessionUser?.email)
  const router = useRouter()
  const searchParams = useSearchParams()
  const flags = useFeatureFlags()

  const [plans, setPlans] = useState<Record<string, PricingPlan>>({})
  const [billingStatus, setBillingStatus] = useState<BillingAvailability | null>(null)
  const [loading, setLoading] = useState(true)
  const [activePlan, setActivePlan] = useState<string | null>(null)
  const [billingPeriod, setBillingPeriod] = useState<BillingPeriod>('monthly')
  const [couponCode, setCouponCode] = useState('')
  const [couponState, setCouponState] = useState<CouponValidationResponse | null>(null)
  const [couponLoading, setCouponLoading] = useState(false)
  const [studentEmail, setStudentEmail] = useState('')
  const [studentCheckoutPlan, setStudentCheckoutPlan] = useState<string | null>(null)
  const [currentSubscription, setCurrentSubscription] = useState<CurrentSubscriptionResponse | null>(null)
  const [teamSeats, setTeamSeats] = useState<TeamSeat[]>([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [teamLoading, setTeamLoading] = useState(false)
  const [handledStudentToken, setHandledStudentToken] = useState<string | null>(null)
  const [handledTeamToken, setHandledTeamToken] = useState<string | null>(null)

  // Note: the Bearer token is published to apiClient by <AuthSync /> in the root
  // layout — it is the single source of truth. Mirroring it from here would race
  // AuthSync (child effects run first) and could publish a null token.

  useEffect(() => {
    const fetchPlans = async () => {
      setLoading(true)
      const response = await apiClient.getSubscriptionPlans()
      if (response.success && response.data) {
        setPlans(response.data.plans as Record<string, PricingPlan>)
        setBillingStatus(response.data.billing)
      } else {
        toast.error(response.error || 'Failed to fetch plans')
      }
      setLoading(false)
    }
    fetchPlans()
  }, [])

  const studentVerifyToken = searchParams.get('student_verify')
  const teamInviteToken = searchParams.get('team_invite')

  useEffect(() => {
    if (!studentVerifyToken || handledStudentToken === studentVerifyToken || !sessionToken) {
      return
    }
    const verify = async () => {
      const result = await apiClient.verifyStudentSubscription(studentVerifyToken)
      if (result.success) {
        toast.success(result.data?.message || 'Student plan activated')
      } else {
        toast.error(result.error || 'Student verification failed')
      }
      setHandledStudentToken(studentVerifyToken)
    }
    verify()
  }, [handledStudentToken, sessionToken, studentVerifyToken])

  useEffect(() => {
    if (!teamInviteToken || handledTeamToken === teamInviteToken || !sessionToken) {
      return
    }
    const joinSeat = async () => {
      const result = await apiClient.joinTeamSeat(teamInviteToken)
      if (result.success) {
        toast.success(result.data?.message || 'Team seat activated')
      } else {
        toast.error(result.error || 'Unable to join team seat')
      }
      setHandledTeamToken(teamInviteToken)
    }
    joinSeat()
  }, [handledTeamToken, sessionToken, teamInviteToken])

  const visiblePlans = useMemo(() => {
    const order = billingPeriod === 'annual' ? ANNUAL_PLAN_IDS : MONTHLY_PLAN_IDS
    return order
      .map((id) => plans[id])
      .filter((plan): plan is PricingPlan => Boolean(plan))
  }, [billingPeriod, plans])

  const appliedCoupon = couponState?.valid ? couponState : null

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
      toast.success(result.data.message)
    } else {
      toast.error(result.data.message)
    }
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

  const handleSelectPlan = async (planId: string) => {
    if (planId !== 'free' && billingStatus && !billingStatus.available && planId !== 'student') {
      toast.error(billingStatus.message)
      return
    }

    if (!sessionUser?.email) {
      router.push('/login?next=/billing')
      return
    }

    if (planId === 'free') {
      toast.info('Free plan is already available.')
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
    const result = await apiClient.createSubscription(
      planId,
      sessionUser.email,
      sessionUser.name || '',
      {
        billingPeriod,
        couponCode: appliedCoupon?.code ?? undefined,
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
    const result = await apiClient.createSubscription(
      studentCheckoutPlan,
      sessionUser.email,
      sessionUser.name || '',
      {
        billingPeriod: 'monthly',
        couponCode: appliedCoupon?.code ?? undefined,
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

  const handleRemoveSeat = async (seatId: string) => {
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
            Compare monthly and annual plans, unlock the student discount, and manage seats for team subscriptions.
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
            <div className="mt-4 rounded-[var(--radius-lg)] border border-accent/30 bg-accent-soft p-4 text-sm text-accent-strong">
              Sign in with the invited email address to activate your team seat.
            </div>
          )}
        </section>

        <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-fg">Choose a plan</h2>
              <p className="mt-1 text-sm text-fg-2">Annual billing saves 20% on Basic, Pro, and BYOK.</p>
            </div>
            <div className="inline-flex rounded-[var(--radius-lg)] border border-line bg-bg p-1">
              <button
                onClick={() => setBillingPeriod('monthly')}
                className={`rounded-[var(--radius-md)] px-4 py-2 text-sm ${billingPeriod === 'monthly' ? 'bg-accent text-accent-fg' : 'text-fg-2'}`}
              >
                Monthly
              </button>
              <button
                onClick={() => setBillingPeriod('annual')}
                className={`rounded-[var(--radius-md)] px-4 py-2 text-sm ${billingPeriod === 'annual' ? 'bg-accent text-accent-fg' : 'text-fg-2'}`}
              >
                Annual
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
              {couponState && (
                <p className={`mt-3 text-sm ${couponState.valid ? 'text-ok' : 'text-err'}`}>
                  {couponState.message}
                  {couponState.valid && couponState.discountPercent ? ` (${couponState.discountPercent}% off)` : ''}
                </p>
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
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {visiblePlans.map((plan, idx) => (
                <PricingCard
                  key={`${plan.id ?? 'plan'}-${idx}`}
                  plan={plan}
                  isPopular={plan.id === (billingPeriod === 'annual' ? 'pro_annual' : 'pro')}
                  onSelectPlan={handleSelectPlan}
                  isLoading={activePlan === plan.id}
                  disabled={plan.id !== 'free' && plan.id !== 'student' && !!billingStatus && !billingStatus.available}
                  disabledLabel="Unavailable"
                />
              ))}
            </div>
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
                onUpgrade={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
                onLoaded={setCurrentSubscription}
              />
            ) : (
              <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
                <h3 className="text-lg font-semibold text-fg">Public pricing view</h3>
                <p className="mt-2 text-sm text-fg-2">
                  Sign in to subscribe, manage billing, or redeem team invitations.
                </p>
                <button
                  onClick={() => router.push('/login?next=/billing')}
                  className="mt-4 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110"
                >
                  Sign In to Subscribe
                </button>
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
                      onClick={() => handleRemoveSeat(seat.id)}
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
