'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import PricingCard from '@/components/billing/PricingCard'
import SubscriptionManager from '@/components/billing/SubscriptionManager'
import { apiClient } from '@/lib/api-client'

interface PricingPlan {
  id: string
  name: string
  price: number
  currency: string
  interval: string
  features: {
    compilations: number | string
    optimizations: number | string
    historyRetention: number
    prioritySupport: boolean
    apiAccess: boolean
    customModels?: boolean
  }
}

import { useSession } from '@/lib/auth-client'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'

export default function BillingPage() {
  const { data: session, isPending } = useSession()
  const router = useRouter()
  const flags = useFeatureFlags()
  const [plans, setPlans] = useState<Record<string, PricingPlan>>({})
  const [loading, setLoading] = useState(true)
  const [activePlan, setActivePlan] = useState<string | null>(null)
  const [showPlans, setShowPlans] = useState(false)

  useEffect(() => {
    if (!isPending && !session) {
      router.push('/login')
    }
  }, [session, isPending, router])

  useEffect(() => {
    const fetchPlans = async () => {
      setLoading(true)
      const response = await apiClient.getSubscriptionPlans()
      if (response.success && response.data) {
        setPlans(response.data.plans as Record<string, PricingPlan>)
      } else {
        toast.error(response.error || 'Failed to fetch plans')
      }
      setLoading(false)
    }
    fetchPlans()
  }, [])

  const handleSelectPlan = async (planId: string) => {
    if (planId === 'free') {
      toast.info('Free plan is already active for all users.')
      return
    }

    if (!session?.user?.email) {
      toast.error('Please sign in to subscribe to a plan')
      return
    }

    setActivePlan(planId)
    const result = await apiClient.createSubscription(
      planId,
      session.user.email,
      session.user.name || ''
    )
    setActivePlan(null)

    if (!result.success || !result.data) {
      toast.error(result.error || 'Failed to create subscription')
      return
    }

    if (result.data.shortUrl) {
      window.open(result.data.shortUrl, '_blank')
      toast.success('Payment link opened in a new tab.')
      return
    }

    toast.success('Subscription initialized successfully.')
  }

  if (!flags.billing) {
    return (
      <div className="content-shell">
        <div className="surface-panel edge-highlight p-6 sm:p-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">All Features Included</h1>
          <p className="mt-2 max-w-2xl text-zinc-400">
            All features are available to everyone — no billing or subscription required.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="content-shell">
      <div className="space-y-6">
        <div className="surface-panel edge-highlight p-6 sm:p-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">Billing & Subscription</h1>
          <p className="mt-2 max-w-2xl text-zinc-400">
            Manage your active plan and upgrade for higher throughput and retained history.
          </p>
        </div>

        <section className="surface-panel edge-highlight p-5 sm:p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Current Subscription</h2>
            <button
              onClick={() => setShowPlans((prev) => !prev)}
              className="rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-200 hover:bg-white/10"
            >
              {showPlans ? 'Hide Plans' : 'Change Plan'}
            </button>
          </div>
          <SubscriptionManager onUpgrade={() => setShowPlans(true)} />
        </section>

        {showPlans && (
          <section className="surface-panel edge-highlight p-5 sm:p-6">
            <div className="mb-4 text-white">
              <h2 className="text-lg font-semibold">Available Plans</h2>
            </div>
            {loading ? (
              <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4 text-slate-300">Loading plans...</div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                {Object.entries(plans).map(([id, plan]) => (
                  <PricingCard
                    key={id}
                    plan={{ ...plan, id }}
                    isPopular={id === 'pro'}
                    onSelectPlan={handleSelectPlan}
                    isLoading={activePlan === id}
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
