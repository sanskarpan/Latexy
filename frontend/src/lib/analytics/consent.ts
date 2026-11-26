/**
 * First-party consent choice transport.
 *
 * Consent choices are recorded by Latexy itself, not by PostHog, so a denial or
 * withdrawal is captured even when the analytics vendor is blocked, not
 * configured, or still loading. Only allowlisted fields are sent: the decision,
 * a bounded surface label, an opaque browser id, an opaque per-tab session id,
 * and a random event id used for retry deduplication.
 *
 * No email, name, account id, document text, URL, IP address, user agent, or
 * replay payload is ever read or sent by this module.
 */

export type ConsentDecision = 'granted' | 'denied' | 'withdrawn'
export type ConsentSurface =
  | 'banner'
  | 'privacy_choices'
  | 'privacy_page'
  | 'settings'
  | 'footer'
  | 'other'

export const CONSENT_EVENT_PATH = '/analytics/consent'
export const ANALYTICS_ANONYMOUS_ID_KEY = 'latexy-analytics-anonymous-id'
export const ANALYTICS_SESSION_ID_KEY = 'latexy-analytics-session-id'
export const CONSENT_SURFACES: readonly ConsentSurface[] = [
  'banner',
  'privacy_choices',
  'privacy_page',
  'settings',
  'footer',
  'other',
]

const SAFE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/

const API_BASE =
  (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_API_URL) ||
  'http://localhost:8030'

export interface ConsentEventPayload {
  decision: ConsentDecision
  surface: ConsentSurface
  anonymous_id: string | null
  session_id: string | null
  event_id: string
}

/** Keep a client identifier only when it is a bounded, non-PII token. */
export function normalizeConsentIdentifier(value: string | null | undefined): string | null {
  const trimmed = value?.trim()
  return trimmed && SAFE_IDENTIFIER.test(trimmed) ? trimmed : null
}

/**
 * Translate a stored consent state and the new choice into the one event that
 * should be recorded, if any.
 *
 * - a fresh grant records `granted`;
 * - leaving a prior grant records `withdrawn` (denial after a grant is a
 *   withdrawal of the earlier permission);
 * - a first denial records `denied`;
 * - re-selecting the same state, or reopening the banner from a denial,
 *   records nothing.
 */
export function resolveConsentDecision(
  previous: ConsentDecision | null,
  next: ConsentDecision | null,
): ConsentDecision | null {
  if (next === 'granted') return previous === 'granted' ? null : 'granted'
  if (previous === 'granted') return 'withdrawn'
  if (next === 'denied' && previous === null) return 'denied'
  return null
}

export function normalizeConsentSurface(value: string | null | undefined): ConsentSurface {
  const raw = value?.trim().toLowerCase()
  return raw && (CONSENT_SURFACES as readonly string[]).includes(raw)
    ? (raw as ConsentSurface)
    : 'other'
}

export function randomConsentId(): string {
  const cryptoObject =
    typeof globalThis !== 'undefined'
      ? (globalThis.crypto as Crypto | undefined)
      : undefined
  const bytes = new Uint8Array(16)
  if (cryptoObject?.getRandomValues) {
    cryptoObject.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function storedId(storage: Storage | null, key: string): string {
  if (storage) {
    try {
      const existing = storage.getItem(key)
      const normalized = normalizeConsentIdentifier(existing)
      if (normalized) return normalized
      const created = randomConsentId()
      storage.setItem(key, created)
      return created
    } catch {
      // Storage can be unavailable in private browsing.
    }
  }
  return randomConsentId()
}

export function consentAnonymousId(): string {
  if (typeof window === 'undefined') return randomConsentId()
  return storedId(window.localStorage, ANALYTICS_ANONYMOUS_ID_KEY)
}

export function consentSessionId(): string {
  if (typeof window === 'undefined') return randomConsentId()
  return storedId(window.sessionStorage, ANALYTICS_SESSION_ID_KEY)
}

/** Pure payload builder so the privacy boundary is directly testable. */
export function buildConsentEventPayload(
  decision: ConsentDecision,
  surface: ConsentSurface | string,
  anonymousId: string | null,
  sessionId: string | null,
  eventId: string,
): ConsentEventPayload {
  return {
    decision,
    surface: normalizeConsentSurface(surface),
    anonymous_id: normalizeConsentIdentifier(anonymousId),
    session_id: normalizeConsentIdentifier(sessionId),
    event_id: normalizeConsentIdentifier(eventId) ?? randomConsentId(),
  }
}

/**
 * Send one consent choice to the first-party backend.
 *
 * This does not consult PostHog and does not require analytics consent: it is
 * the record of the choice itself, including a denial or withdrawal. The
 * request survives navigation via `keepalive`.
 */
export function recordConsentDecision(
  decision: ConsentDecision,
  surface: ConsentSurface | string,
): boolean {
  if (typeof window === 'undefined') return false
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') {
    return false
  }

  const payload = buildConsentEventPayload(
    decision,
    surface,
    consentAnonymousId(),
    consentSessionId(),
    randomConsentId(),
  )

  try {
    void fetch(`${API_BASE}${CONSENT_EVENT_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'include',
      keepalive: true,
    }).catch(() => undefined)
    return true
  } catch {
    // Consent recording is best-effort; it must never break the page.
    return false
  }
}
