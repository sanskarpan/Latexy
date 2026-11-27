/**
 * Aggregate-only browser error signal.
 *
 * PostHog remains the source of truth for exception grouping, error tracking,
 * and masked replay. This module mirrors only the sanitized identity of an
 * exception (`route`, `release`, `error_class`) to the backend admin error
 * feed. It never sends an exception message, stack trace, source snippet,
 * prompt, document content, email, token, person id, or session id.
 *
 * Callers run after `sanitizeAnalyticsEvent`, and this module re-checks analytics
 * consent before sending. Both gates must pass, so a visitor who denied or
 * withdrew consent never reaches `/telemetry/errors`.
 */

import {
  normalizeQualityErrorClass,
  normalizeQualityRelease,
  normalizeQualityRoute,
} from './quality-triage'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

// Mirrors ANALYTICS_CONSENT_KEY in ./posthog. Kept local to avoid a cycle:
// posthog imports this module to mirror its consent-gated `$exception` events.
const ANALYTICS_CONSENT_KEY = 'latexy-analytics-consent'

export interface ClientErrorSignal {
  error_class: string
  route: string
  release?: string
}

function hasAnalyticsConsent(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.localStorage?.getItem(ANALYTICS_CONSENT_KEY) === 'granted'
  } catch {
    return false
  }
}

export interface AnalyticsErrorEventLike {
  event?: string
  properties?: Record<string, unknown>
}

function firstString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

/** Build the bounded signal, or null when the event is not an eligible error. */
export function buildClientErrorSignal(event: AnalyticsErrorEventLike): ClientErrorSignal | null {
  if (event.event !== '$exception') return null
  const properties = event.properties ?? {}
  const route =
    normalizeQualityRoute(properties.route) ??
    normalizeQualityRoute(properties.$pathname) ??
    null
  if (!route) return null
  const release = normalizeQualityRelease(
    firstString(properties.$release_id) ?? firstString(properties.release),
  )
  const errorClass = normalizeQualityErrorClass(properties.error_type) ?? 'UnknownError'
  return {
    error_class: errorClass,
    route,
    ...(release ? { release } : {}),
  }
}

function send(signal: ClientErrorSignal): void {
  if (typeof window === 'undefined') return
  const url = `${API_BASE}/telemetry/errors`
  const body = JSON.stringify(signal)
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      if (navigator.sendBeacon(url, blob)) return
    }
  } catch {
    // Fall through to keepalive fetch.
  }
  void fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  }).catch(() => undefined)
}

/** Consent-gated, fire-and-forget mirror of one sanitized exception event. */
export function reportClientErrorSignal(event: AnalyticsErrorEventLike): void {
  const signal = buildClientErrorSignal(event)
  if (!signal || !hasAnalyticsConsent()) return
  send(signal)
}
