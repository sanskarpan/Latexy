/**
 * First-party A/B experiment assignment transport (issue #2158).
 *
 * Only the opaque browser consent id leaves the browser. The backend verifies
 * the latest first-party analytics grant, assigns a stable variant, records the
 * exposure and returns bounded variant keys. No email, name, account id,
 * document text, prompt, token, IP address, user agent or free-form property is
 * read or sent by this module.
 *
 * Assignment is best-effort and never blocks the page. A missing assignment,
 * consent denial or network failure leaves the server-evaluated feature flags
 * unchanged. A returned flag override is applied only to an allowlisted
 * operational flag; a winning variant is never rolled out automatically.
 */

import { consentAnonymousId, normalizeConsentIdentifier } from './consent'
import { OPERATIONAL_FLAG_KEYS, type OperationalFlagKey } from './flag-exposure'
import { readAnalyticsConsent } from './posthog'

export const EXPERIMENT_ASSIGNMENT_PATH = '/analytics/experiments/assignment'
export const MAX_EXPERIMENT_KEYS = 10

export interface ExperimentAssignment {
    experiment_key: string
    variant: string
    variant_label: string
    flag_key: string | null
    flag_override: boolean | null
    exposure_recorded: boolean
}

export interface ExperimentAssignmentResponse {
    assignments: ExperimentAssignment[]
    accepted: number
    duplicate: number
    rejected: number
    skipped: number
    window: string
}

const API_BASE =
    (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_API_URL) ||
    'http://localhost:8030'

const OPERATIONAL_FLAG_SET = new Set<string>(OPERATIONAL_FLAG_KEYS)
const EXPERIMENT_KEY_PATTERN = /^[a-z][a-z0-9_]{1,63}$/

function assignmentKeys(keys: string[] | undefined): string[] | undefined {
    if (!keys) return undefined
    const safe: string[] = []
    for (const key of keys) {
        if (typeof key !== 'string') continue
        const normalized = key.trim()
        if (!EXPERIMENT_KEY_PATTERN.test(normalized)) continue
        if (!safe.includes(normalized)) safe.push(normalized)
        if (safe.length >= MAX_EXPERIMENT_KEYS) break
    }
    return safe.length > 0 ? safe : undefined
}

/**
 * Keep only allowlisted operational flag overrides returned by the server.
 * Unknown experiments, keys and non-boolean overrides are dropped.
 */
export function flagOverridesFromAssignments(
    response: ExperimentAssignmentResponse | null | undefined
): Partial<Record<OperationalFlagKey, boolean>> {
    const overrides: Partial<Record<OperationalFlagKey, boolean>> = {}
    if (!response || !Array.isArray(response.assignments)) return overrides
    for (const assignment of response.assignments) {
        if (!assignment || typeof assignment !== 'object') continue
        if (typeof assignment.experiment_key !== 'string') continue
        if (!EXPERIMENT_KEY_PATTERN.test(assignment.experiment_key)) continue
        if (typeof assignment.variant !== 'string') continue
        if (
            typeof assignment.flag_key !== 'string' ||
            !OPERATIONAL_FLAG_SET.has(assignment.flag_key)
        ) {
            continue
        }
        if (typeof assignment.flag_override !== 'boolean') continue
        overrides[assignment.flag_key as OperationalFlagKey] = assignment.flag_override
    }
    return overrides
}

/**
 * Request assignments for running experiments and return safe flag overrides.
 *
 * The server requires authentication and a current analytics grant, dedupes
 * exposure per experiment/subject/UTC-day and skips experiments whose linked
 * operational flag is off. Playwright tests never call the live endpoint.
 */
export async function loadExperimentAssignments(
    experimentKeys?: string[]
): Promise<Partial<Record<OperationalFlagKey, boolean>> | null> {
    if (typeof window === 'undefined') return null
    if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') {
        return null
    }
    if (readAnalyticsConsent() !== 'granted') return null

    const anonymousId = normalizeConsentIdentifier(consentAnonymousId())
    if (!anonymousId) return null
    const keys = assignmentKeys(experimentKeys)

    try {
        const response = await fetch(`${API_BASE}${EXPERIMENT_ASSIGNMENT_PATH}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                anonymous_id: anonymousId,
                ...(keys ? { experiment_keys: keys } : {}),
            }),
            credentials: 'include',
            keepalive: true,
        })
        if (!response.ok) return null
        const data = (await response.json()) as ExperimentAssignmentResponse
        return flagOverridesFromAssignments(data)
    } catch {
        // Assignment is best-effort; it must never break the page.
        return null
    }
}
