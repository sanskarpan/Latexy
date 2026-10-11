'use client'

import { apiAllowance, formatCatalogPrice, type CatalogPlan as PricingPlan } from '@/lib/plan-catalog'

interface PricingCardProps {
  plan: PricingPlan
  isPopular?: boolean
  onSelectPlan: (planId: string) => void
  isLoading?: boolean
  disabled?: boolean
  disabledLabel?: string
}

export default function PricingCard({
  plan,
  isPopular = false,
  onSelectPlan,
  isLoading = false,
  disabled = false,
  disabledLabel = 'Unavailable',
}: PricingCardProps) {
  const formatPrice = (price: number) => {
    if (price === 0) return 'Free'
    return formatCatalogPrice(price, plan.currency)
  }

  const formatValue = (value: string | number) => {
    if (value === 'unlimited') return 'Unlimited'
    if (value === 0) return 'None'
    return value
  }

  const yesNo = (enabled: boolean) => (enabled ? 'Yes' : 'No')

  return (
    <article className={`relative rounded-[var(--radius-lg)] border border-line bg-surface p-5 ${isPopular ? 'bg-accent-soft' : ''}`}>
      <div className="mb-2 flex flex-wrap justify-end gap-2">
        {plan.discount_percent ? (
          <span className="rounded-full border border-ok/30 bg-ok/10 px-2 py-1 text-[10px] uppercase tracking-wider text-ok">
            Save {plan.discount_percent}%
          </span>
        ) : null}
        {isPopular && (
          <span className="rounded-full border border-accent bg-accent-soft px-2 py-1 text-[10px] uppercase tracking-wider text-accent-strong">
            Recommended
          </span>
        )}
      </div>

      <div className="mb-5">
        <h3 className="break-words text-xl font-semibold text-fg">{plan.name}</h3>
        {plan.description && <p className="mt-1 break-words text-sm text-fg-2">{plan.description}</p>}
        <p className="mt-2 text-3xl font-semibold text-fg">{formatPrice(plan.price)}</p>
        <p className="text-sm text-fg-2">
          {plan.id === 'free'
            ? 'No payment required'
            : plan.price > 0
              ? (plan.purchase_type === 'one_time' ? 'one-time payment' : `per ${plan.interval}`)
              : 'Not configured'}
        </p>
        {plan.price > 0 ? (
          <p className="mt-1 text-xs text-fg-3">Incl. GST &middot; no surprises at checkout</p>
        ) : null}
        {plan.monthly_equivalent_price ? (
          <p className="mt-1 text-xs text-ok">₹{(plan.monthly_equivalent_price / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}/month effective</p>
        ) : null}
        {plan.requires_student_verification ? (
          <p className="mt-1 text-xs text-fg-2">Requires student email verification</p>
        ) : null}
        {plan.max_seats ? (
          <p className="mt-1 text-xs text-warn">Includes {plan.max_seats} seats</p>
        ) : null}
      </div>

      <div className="space-y-3 text-sm">
        <FeatureRow label="LaTeX compilations" value={formatValue(plan.features.compilations)} />
        <FeatureRow label="AI optimizations" value={formatValue(plan.features.optimizations)} />
        <FeatureRow
          label="History retention"
          value={plan.features.historyRetention === 0 ? 'None' : `${plan.features.historyRetention} days`}
        />
        <FeatureRow label="Priority support" value={yesNo(plan.features.prioritySupport)} />
        <FeatureRow label="API requests" value={apiAllowance(plan)} />
        {plan.features.ai_assists !== undefined && <FeatureRow label="AI assists" value={formatValue(plan.features.ai_assists)} />}
        {typeof plan.features.customModels === 'boolean' && (
          <FeatureRow label="Custom models" value={yesNo(plan.features.customModels)} />
        )}
        {typeof plan.features.teamSeats === 'number' && (
          <FeatureRow label="Team seats" value={plan.features.teamSeats} />
        )}
      </div>

      {plan.capabilities && plan.capability_labels && (
        <details className="mt-4 border-t border-line pt-3 text-sm">
          <summary className="cursor-pointer text-fg-2">Included capabilities</summary>
          <ul className="mt-2 space-y-1 text-fg-2">
            {Object.entries(plan.capabilities).filter(([key, enabled]) => enabled && plan.capability_labels?.[key]).map(([key]) => (
              <li key={key}>{plan.capability_labels?.[key]}</li>
            ))}
          </ul>
        </details>
      )}

      <button
        onClick={() => onSelectPlan(plan.id)}
        disabled={isLoading || disabled || plan.purchasable === false}
        className={`mt-5 inline-flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
          isPopular
            ? 'bg-accent text-accent-fg hover:brightness-110'
            : 'border border-line-2 bg-surface-2 text-fg hover:bg-surface'
        }`}
      >
        {isLoading ? 'Processing...' : disabled ? disabledLabel : plan.purchasable === false ? plan.unavailable_reason || 'Unavailable' : 'Select Plan'}
      </button>
    </article>
  )
}

function FeatureRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-fg-2">{label}</span>
      <span className="font-medium text-accent-strong">{value}</span>
    </div>
  )
}
