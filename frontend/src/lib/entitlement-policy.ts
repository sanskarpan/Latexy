/** Recovery, account security and baseline document access remain available offline.
 * Keep this deliberately small and aligned with the server's immutable registry.
 */
export const BASELINE_FEATURES = new Set([
  'compile', 'a01', 'a02', 'a03', 'a04', 'a05', 'a07', 'a08',
  'b01', 'c01', 'c05', 'c08', 'c09', 'c25', 'c26', 'f10', 'f11',
  'h10', 'h11', 'h12', 'h13', 'i01', 'i04',
])

export function isFeatureAllowed(features: Record<string, boolean>, featureKey: string): boolean {
  if (BASELINE_FEATURES.has(featureKey)) return true
  return Object.prototype.hasOwnProperty.call(features, featureKey) && features[featureKey] === true
}

export function parseEffectiveFeatures(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Feature availability response is invalid')
  }
  const features: Record<string, boolean> = Object.create(null)
  for (const [key, enabled] of Object.entries(value)) {
    if (typeof enabled !== 'boolean') throw new Error('Feature availability response is invalid')
    features[key] = enabled
  }
  return features
}
