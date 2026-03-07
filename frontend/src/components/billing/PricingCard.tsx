'use client'

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

interface PricingCardProps {
  plan: PricingPlan
  isPopular?: boolean
  onSelectPlan: (planId: string) => void
  isLoading?: boolean
}

export default function PricingCard({
  plan,
  isPopular = false,
  onSelectPlan,
  isLoading = false,
}: PricingCardProps) {
  const formatPrice = (price: number) => {
    if (price === 0) return 'Free'
    return `₹${(price / 100).toFixed(0)}`
  }

  const formatValue = (value: string | number) => {
    if (value === 'unlimited') return 'Unlimited'
    if (value === 0) return 'None'
    return value
  }

  const yesNo = (enabled: boolean) => (enabled ? 'Yes' : 'No')

  return (
    <article className={`surface-card relative p-5 ${isPopular ? 'edge-highlight bg-orange-300/5' : ''}`}>
      {isPopular && (
        <span className="absolute right-4 top-4 rounded-full border border-orange-200/30 bg-orange-300/20 px-2 py-1 text-[10px] uppercase tracking-wider text-orange-100">
          Recommended
        </span>
      )}

      <div className="mb-5">
        <p className="text-sm text-slate-400">{plan.name}</p>
        <h3 className="mt-2 text-3xl font-semibold text-white">{formatPrice(plan.price)}</h3>
        <p className="text-sm text-slate-400">{plan.price > 0 ? `per ${plan.interval}` : 'No payment required'}</p>
      </div>

      <div className="space-y-3 text-sm">
        <FeatureRow label="LaTeX compilations" value={formatValue(plan.features.compilations)} />
        <FeatureRow label="AI optimizations" value={formatValue(plan.features.optimizations)} />
        <FeatureRow
          label="History retention"
          value={plan.features.historyRetention === 0 ? 'None' : `${plan.features.historyRetention} days`}
        />
        <FeatureRow label="Priority support" value={yesNo(plan.features.prioritySupport)} />
        <FeatureRow label="API access" value={yesNo(plan.features.apiAccess)} />
        {typeof plan.features.customModels === 'boolean' && (
          <FeatureRow label="Custom models" value={yesNo(plan.features.customModels)} />
        )}
      </div>

      <button
        onClick={() => onSelectPlan(plan.id)}
        disabled={isLoading}
        className={`mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
          isPopular
            ? 'bg-orange-300 text-slate-950 hover:bg-orange-200'
            : 'border border-white/15 bg-white/5 text-slate-100 hover:bg-white/10'
        }`}
      >
        {isLoading ? 'Processing...' : 'Select Plan'}
      </button>
    </article>
  )
}

function FeatureRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-300">{label}</span>
      <span className="font-medium text-orange-200">{value}</span>
    </div>
  )
}
