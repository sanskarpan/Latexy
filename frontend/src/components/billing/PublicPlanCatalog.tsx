'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiClient } from '@/lib/api-client'
import { catalogPlansForPeriod, type CatalogPlan } from '@/lib/plan-catalog'
import PricingCard from './PricingCard'

export default function PublicPlanCatalog() {
  const router = useRouter()
  const [plans, setPlans] = useState<Record<string, CatalogPlan>>({})
  const [period, setPeriod] = useState<'monthly' | 'annual'>('monthly')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    const response = await apiClient.getSubscriptionPlans()
    if (response.success && response.data) setPlans(response.data.plans as Record<string, CatalogPlan>)
    else setError(response.error || 'Pricing is temporarily unavailable.')
    setLoading(false)
  }, [])
  useEffect(() => { void load() }, [load])

  if (loading) return <p className="mt-10 text-fg-2" role="status">Loading current plans…</p>
  if (error) return (
    <div className="mt-10 rounded-[var(--radius-lg)] border border-line p-5" role="alert">
      <p>{error}</p>
      <button type="button" onClick={() => void load()} className="mt-3 underline">Try again</button>
    </div>
  )
  return (
    <div className="mt-10">
      <div aria-label="Billing period" className="mb-6 flex gap-2">
        {(['monthly', 'annual'] as const).map((value) => (
          <button key={value} type="button" aria-pressed={period === value} onClick={() => setPeriod(value)}
            className={`rounded-[var(--radius-md)] border px-4 py-2 text-sm ${period === value ? 'border-accent bg-accent-soft text-accent-strong' : 'border-line text-fg-2'}`}>
            {value === 'monthly' ? 'Monthly' : 'Annual'}
          </button>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {catalogPlansForPeriod(plans, period).map((plan) => (
          <PricingCard key={plan.id} plan={plan} onSelectPlan={(id) => router.push(id === 'free' ? '/signup' : '/billing')} />
        ))}
      </div>
    </div>
  )
}
