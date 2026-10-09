import type { AdminEntitlementsState, EntitlementFeatureDef } from './api-client'

/** Walk every ancestor; a missing parent or cycle is a configuration error. */
export function entitlementBlocker(
  state: AdminEntitlementsState,
  feature: EntitlementFeatureDef,
  plan?: string,
): string | null {
  if (!feature.gateable) return null
  const registry = new Map(state.registry.map((entry) => [entry.key, entry]))
  const seen = new Set<string>()
  let current: EntitlementFeatureDef | undefined = feature
  while (current) {
    if (seen.has(current.key)) return 'Invalid parent configuration'
    seen.add(current.key)
    if (current.gateable) {
      if (state.kill_switches[current.key] !== true) return `${current.label}: globally disabled`
      const family = plan ? state.plan_family_by_key?.[plan] : undefined
      if (family && family !== plan && state.matrix[family]?.[current.key] !== true) {
        return `${current.label}: disabled for ${family}`
      }
      if (plan && state.matrix[plan]?.[current.key] !== true) return `${current.label}: disabled for ${plan}`
    }
    if (!current.parent_key) return null
    const parent: EntitlementFeatureDef | undefined = registry.get(current.parent_key)
    if (!parent) return 'Missing parent configuration'
    current = parent
  }
  return null
}

export function matchesFeatureSearch(feature: EntitlementFeatureDef, query: string): boolean {
  const text = [feature.label, feature.key, feature.inventory_id, feature.category,
    feature.description, feature.parent_key, feature.always_on_reason].filter(Boolean).join(' ').toLowerCase()
  return query.toLowerCase().split(/\s+/).every((term) => text.includes(term))
}

export function patchEntitlementCell(state: AdminEntitlementsState | null, scope: string, key: string, enabled: boolean): AdminEntitlementsState | null {
  if (!state) return state
  if (scope === 'global') return { ...state, kill_switches: { ...state.kill_switches, [key]: enabled } }
  return { ...state, matrix: { ...state.matrix, [scope]: { ...state.matrix[scope], [key]: enabled } } }
}

export function createEntitlementWriteLock() {
  const pending = new Set<string>()
  return {
    acquire(cell: string) { if (pending.has(cell)) return false; pending.add(cell); return true },
    release(cell: string) { pending.delete(cell) },
  }
}
