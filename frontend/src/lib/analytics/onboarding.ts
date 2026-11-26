/**
 * Privacy-safe onboarding step telemetry (issue #2074).
 *
 * Only a bounded step key, flow version, clamped duration, bounded completion
 * source, an opaque event id and the browser's existing opaque analytics id
 * leave the client. Form contents, names, emails, document text, URLs and
 * free-form properties are never accepted by the payload builder.
 *
 * The browser analytics consent gate is shared with PostHog: nothing is sent
 * until the visitor grants consent. The backend then verifies the same
 * first-party grant before storing the event, so denial or withdrawal stops
 * capture even if a caller bypasses this client.
 */

import { createTraceHeaders } from '@/lib/telemetry'
import { consentAnonymousId, randomConsentId } from './consent'
import { readAnalyticsConsent } from './posthog'

const API_BASE =
  (typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_API_URL) ||
  'http://localhost:8030'

export const ONBOARDING_EVENT_PATH = '/analytics/onboarding/events'
export const ONBOARDING_FLOW_VERSION = 'v1'
export const ONBOARDING_STEP_KEYS = [
  'welcome',
  'how-it-works',
  'features',
  'get-started',
] as const
export type OnboardingStepKey = (typeof ONBOARDING_STEP_KEYS)[number]

export const ONBOARDING_EVENT_ACTIONS = [
  'onboarding_step_viewed',
  'onboarding_step_completed',
  'onboarding_step_skipped',
] as const
export type OnboardingEventAction = (typeof ONBOARDING_EVENT_ACTIONS)[number]

export const ONBOARDING_COMPLETION_SOURCES = [
  'next',
  'cta',
  'link',
  'skip',
  'escape',
  'backdrop',
  'close',
  'unknown',
] as const
export type OnboardingCompletionSource =
  (typeof ONBOARDING_COMPLETION_SOURCES)[number]

export const MAX_ONBOARDING_DURATION_MS = 24 * 60 * 60 * 1000

const STEP_SET = new Set<string>(ONBOARDING_STEP_KEYS)
const ACTION_SET = new Set<string>(ONBOARDING_EVENT_ACTIONS)
const SOURCE_SET = new Set<string>(ONBOARDING_COMPLETION_SOURCES)
const IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const FLOW_VERSION_PATTERN = /^v[0-9]{1,3}(?:\.[0-9]{1,3})?$/

export interface OnboardingEventPayload {
  action: OnboardingEventAction
  step_key: OnboardingStepKey
  flow_version: string
  duration_ms?: number
  completion_source?: OnboardingCompletionSource
  event_id: string
  anonymous_id: string
}

export interface OnboardingEventInput {
  action: OnboardingEventAction
  stepKey: OnboardingStepKey | string
  anonymousId: string
  eventId: string
  flowVersion?: string
  durationMs?: number | null
  completionSource?: OnboardingCompletionSource | string | null
}

export function normalizeOnboardingFlowVersion(value: string | null | undefined): string {
  const raw = value?.trim().toLowerCase()
  return raw && FLOW_VERSION_PATTERN.test(raw) ? raw : ONBOARDING_FLOW_VERSION
}

export function normalizeOnboardingDurationMs(
  value: number | null | undefined,
): number | undefined {
  if (value == null || !Number.isFinite(value) || value < 0) return undefined
  return Math.min(Math.trunc(value), MAX_ONBOARDING_DURATION_MS)
}

export function normalizeOnboardingCompletionSource(
  value: string | null | undefined,
): OnboardingCompletionSource {
  const raw = value?.trim().toLowerCase()
  return raw && SOURCE_SET.has(raw)
    ? (raw as OnboardingCompletionSource)
    : 'unknown'
}

/**
 * Build the exact allowlisted payload, or return null when a required field is
 * not a bounded safe value. The returned object has no extension point for a
 * caller to add document text, a name, an email, or arbitrary metadata.
 */
export function buildOnboardingEventPayload(
  input: OnboardingEventInput,
): OnboardingEventPayload | null {
  const action = input.action
  if (!ACTION_SET.has(action)) return null
  const stepKey = input.stepKey.trim().toLowerCase()
  if (!STEP_SET.has(stepKey)) return null
  const anonymousId = input.anonymousId.trim()
  if (!IDENTIFIER_PATTERN.test(anonymousId)) return null
  const eventId = input.eventId.trim()
  if (!IDENTIFIER_PATTERN.test(eventId)) return null

  const payload: OnboardingEventPayload = {
    action,
    step_key: stepKey as OnboardingStepKey,
    flow_version: normalizeOnboardingFlowVersion(input.flowVersion),
    event_id: eventId,
    anonymous_id: anonymousId,
  }
  const duration = normalizeOnboardingDurationMs(input.durationMs)
  if (duration !== undefined) payload.duration_ms = duration
  if (action === 'onboarding_step_completed' || action === 'onboarding_step_skipped') {
    payload.completion_source = normalizeOnboardingCompletionSource(
      input.completionSource,
    )
  }
  return payload
}

export interface OnboardingTelemetryClientOptions {
  readConsent: () => 'granted' | 'denied' | null
  anonymousId: () => string
  eventId: () => string
  send: (payload: OnboardingEventPayload) => void
}

export interface OnboardingTelemetryClient {
  track: (input: Omit<OnboardingEventInput, 'anonymousId' | 'eventId'>) => boolean
}

export function createOnboardingTelemetryClient(
  options: OnboardingTelemetryClientOptions,
): OnboardingTelemetryClient {
  return {
    track(input) {
      if (options.readConsent() !== 'granted') return false
      const payload = buildOnboardingEventPayload({
        ...input,
        anonymousId: options.anonymousId(),
        eventId: options.eventId(),
      })
      if (!payload) return false
      options.send(payload)
      return true
    },
  }
}

function sendOnboardingEvent(payload: OnboardingEventPayload): void {
  try {
    void fetch(`${API_BASE}${ONBOARDING_EVENT_PATH}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...createTraceHeaders(),
      },
      body: JSON.stringify(payload),
      credentials: 'include',
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // Analytics must never break onboarding.
  }
}

export const onboardingTelemetry = createOnboardingTelemetryClient({
  readConsent: readAnalyticsConsent,
  anonymousId: consentAnonymousId,
  eventId: randomConsentId,
  send: sendOnboardingEvent,
})

export function trackOnboardingStep(
  input: Omit<OnboardingEventInput, 'anonymousId' | 'eventId'>,
): boolean {
  if (typeof window === 'undefined') return false
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') {
    return false
  }
  return onboardingTelemetry.track(input)
}
