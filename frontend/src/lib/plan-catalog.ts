/** Catalog identities and commercial values come from the server. */
export interface CatalogPlan {
  id: string
  sku?: string
  name: string
  description?: string
  price: number
  currency: string
  interval: string
  plan_family?: string
  purchase_type?: 'one_time' | 'subscription'
  billing_period?: string
  discount_percent?: number
  monthly_equivalent_price?: number
  max_seats?: number
  requires_student_verification?: boolean
  visible?: boolean
  purchase_enabled?: boolean
  purchasable?: boolean
  configured?: boolean
  unavailable_reason?: string | null
  display_order?: number
  version?: number
  provider_plan_id?: string | null
  commercial_fields_read_only?: boolean
  quota_fields_read_only?: boolean
  quota_windows_read_only?: boolean
  developer_api_daily_limit_read_only?: boolean
  updated_at?: string | null
  capabilities?: Record<string, boolean>
  capability_labels?: Record<string, string>
  quotas?: Record<string, { limit: number | null; window: string; version?: number; source?: string }>
  features: {
    compilations: number | string
    optimizations: number | string
    ai_assists?: number | string
    historyRetention: number
    prioritySupport: boolean
    apiAccess: boolean
    apiDailyLimit?: number
    customModels?: boolean
    teamSeats?: number
  }
}

export interface AdminPlanCatalogResponse {
  plans: Record<string, CatalogPlan>
  editable_fields: string[]
  pricing_policy: string
  quota_policy: string
}

export interface CatalogQuotaUpdate {
  version: number
  limit: number | null
}

export interface CatalogPlanUpdate {
  version: number
  name?: string
  description?: string
  visible?: boolean
  purchase_enabled?: boolean
  display_order?: number
}

export function catalogPlansForPeriod(plans: Record<string, CatalogPlan>, period: 'monthly' | 'annual'): CatalogPlan[] {
  return Object.entries(plans)
    .map(([id, plan], index) => ({ ...plan, id, display_order: plan.display_order ?? index }))
    .filter((plan) => plan.visible !== false)
    .filter((plan) => period === 'monthly'
      ? plan.billing_period !== 'annual' && plan.interval !== 'year'
      : plan.billing_period === 'annual' || plan.interval === 'year' || plan.id === 'free'
        || (plan.interval === 'month' && !plans[`${plan.id}_annual`]))
    .sort((a, b) => a.display_order - b.display_order || a.id.localeCompare(b.id))
}

export function formatCatalogPrice(price: number, currency: string): string {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 2 }).format(price / 100)
}

export function apiAllowance(plan: CatalogPlan): string {
  if (!plan.features.apiAccess) return 'Unavailable'
  const limit = plan.features.apiDailyLimit
  return limit === undefined ? 'Yes' : limit <= 0 ? 'Unavailable' : `${limit.toLocaleString()} / day`
}


export function quotaLimitUpdate(version: number, value: string, unlimited: boolean): CatalogQuotaUpdate | null {
  if (!Number.isSafeInteger(version) || version < 1) return null
  if (unlimited) return { version, limit: null }
  const limit = Number(value)
  if (value.trim() === '' || !Number.isSafeInteger(limit) || limit < 0 || limit > 1_000_000_000) return null
  return { version, limit }
}
