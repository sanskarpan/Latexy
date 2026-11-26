/**
 * First-party feature-flag exposure transport (issue #2157).
 *
 * Only the bounded operational flag keys and the evaluated boolean leave the
 * browser. The opaque browser consent id is included so the backend can verify
 * the current first-party analytics grant before storing anything. No email,
 * name, account id, document text, URL, prompt, token, IP address, user agent or
 * free-form property is read or sent by this module.
 *
 * The backend deduplicates per subject/flag/variant/UTC-day, so repeated calls
 * from a remount or a Strict Mode effect cannot create duplicate exposures.
 */

import { consentAnonymousId, normalizeConsentIdentifier } from './consent'
import { readAnalyticsConsent } from './posthog'

export const FLAG_EXPOSURE_PATH = '/analytics/flag-exposure'

export const OPERATIONAL_FLAG_KEYS = [
  'trial_limits',
  'deep_analysis_trial',
  'compile_timeouts',
  'task_priority',
  'billing',
  'upgrade_ctas',
] as const

export type OperationalFlagKey = (typeof OPERATIONAL_FLAG_KEYS)[number]
export type FlagExposureMap = Partial<Record<OperationalFlagKey, boolean>>

export interface FlagExposurePayload {
  anonymous_id: string
  flags: Array<{ key: OperationalFlagKey; enabled: boolean }>
}

const API_BASE =
  (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_API_URL) ||
  'http://localhost:8030'

const FLAG_KEY_SET = new Set<string>(OPERATIONAL_FLAG_KEYS)

/** Build the exact allowlisted payload, or null when nothing can be sent. */
export function buildFlagExposurePayload(
  flags: FlagExposureMap,
  anonymousId: string | null | undefined,
): FlagExposurePayload | null {
  const safeAnonymousId = normalizeConsentIdentifier(anonymousId)
  if (!safeAnonymousId) return null

  const entries: Array<{ key: OperationalFlagKey; enabled: boolean }> = []
  for (const key of OPERATIONAL_FLAG_KEYS) {
    if (!FLAG_KEY_SET.has(key)) continue
    const enabled = flags[key]
    if (typeof enabled === 'boolean') entries.push({ key, enabled })
  }
  if (entries.length === 0) return null
  return { anonymous_id: safeAnonymousId, flags: entries }
}

/**
 * Send the evaluated operational flags once per mount.
 *
 * Capture is gated on the same analytics consent as PostHog. The server checks
 * the latest first-party choice again, so a denial or withdrawal wins even if a
 * caller bypasses this gate.
 */
export function recordFlagExposures(flags: FlagExposureMap): boolean {
  if (typeof window === 'undefined') return false
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') {
    return false
  }
  if (readAnalyticsConsent() !== 'granted') return false

  const payload = buildFlagExposurePayload(flags, consentAnonymousId())
  if (!payload) return false

  try {
    void fetch(`${API_BASE}${FLAG_EXPOSURE_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include',
      keepalive: true,
    }).catch(() => undefined)
    return true
  } catch {
    // Exposure capture is best-effort; it must never break the page.
    return false
  }
}
