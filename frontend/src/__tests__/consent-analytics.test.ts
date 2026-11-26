import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  buildConsentEventPayload,
  normalizeConsentIdentifier,
  normalizeConsentSurface,
  resolveConsentDecision,
} from '@/lib/analytics/consent'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('first-party consent payload boundary', () => {
  it('sends only the allowlisted consent fields', () => {
    const payload = buildConsentEventPayload(
      'granted',
      'banner',
      '550e8400-e29b-41d4-a716-446655440000',
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      '7c9e6679-7425-40de-944b-e07fc1f90ae7',
    )

    expect(payload).toEqual({
      decision: 'granted',
      surface: 'banner',
      anonymous_id: '550e8400-e29b-41d4-a716-446655440000',
      session_id: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
      event_id: '7c9e6679-7425-40de-944b-e07fc1f90ae7',
    })
    expect(Object.keys(payload).sort()).toEqual([
      'anonymous_id',
      'decision',
      'event_id',
      'session_id',
      'surface',
    ])
    const serialized = JSON.stringify(payload).toLowerCase()
    expect(serialized).not.toContain('email')
    expect(serialized).not.toContain('name')
    expect(serialized).not.toContain('document')
    expect(serialized).not.toContain('replay')
  })

  it('drops free-form identifiers and buckets unknown surfaces', () => {
    expect(normalizeConsentSurface('banner')).toBe('banner')
    expect(normalizeConsentSurface('privacy_choices')).toBe('privacy_choices')
    expect(normalizeConsentSurface('person@example.com')).toBe('other')
    expect(normalizeConsentSurface('a'.repeat(300))).toBe('other')

    expect(normalizeConsentIdentifier('abc-123_safe:id')).toBe('abc-123_safe:id')
    expect(normalizeConsentIdentifier('person@example.com')).toBeNull()
    expect(normalizeConsentIdentifier('has spaces')).toBeNull()
    expect(normalizeConsentIdentifier('a'.repeat(129))).toBeNull()

    const payload = buildConsentEventPayload(
      'denied',
      'not-a-surface',
      'person@example.com',
      'has spaces',
      'not a valid event id',
    )
    expect(payload.surface).toBe('other')
    expect(payload.anonymous_id).toBeNull()
    expect(payload.session_id).toBeNull()
    expect(payload.event_id).not.toBe('not a valid event id')
  })
})

describe('consent decision transitions', () => {
  it('records a fresh grant or first denial exactly once', () => {
    expect(resolveConsentDecision(null, 'granted')).toBe('granted')
    expect(resolveConsentDecision(null, 'denied')).toBe('denied')
    expect(resolveConsentDecision('denied', 'granted')).toBe('granted')
    expect(resolveConsentDecision('granted', 'granted')).toBeNull()
    expect(resolveConsentDecision('denied', 'denied')).toBeNull()
    expect(resolveConsentDecision('denied', null)).toBeNull()
  })

  it('treats every move away from a grant as a withdrawal', () => {
    expect(resolveConsentDecision('granted', 'denied')).toBe('withdrawn')
    expect(resolveConsentDecision('granted', null)).toBe('withdrawn')
    expect(resolveConsentDecision('granted', 'withdrawn')).toBe('withdrawn')
  })
})

describe('consent-first initialization and withdrawal', () => {
  const wrapper = read('../lib/analytics/posthog.ts')
  const provider = read('../components/analytics/AnalyticsProvider.tsx')
  const consent = read('../lib/analytics/consent.ts')

  it('records the first-party choice before PostHog can initialize', () => {
    const writer = wrapper.slice(
      wrapper.indexOf('export function writeAnalyticsConsent'),
      wrapper.indexOf('/** Remove query strings'),
    )
    expect(writer.indexOf('recordConsentDecision(decision, surface)')).toBeLessThan(
      writer.indexOf('initializeAnalytics()'),
    )
    expect(writer.indexOf('initializeAnalytics()')).toBeLessThan(
      writer.indexOf("captureAnalyticsEvent('consent_granted'"),
    )
    expect(writer).toContain("if (decision === 'granted')")
    expect(writer).not.toContain("'consent_denied'")
    expect(writer).not.toContain("'consent_withdrawn'")
    expect(consent).toContain("'/analytics/consent'")
    expect(consent).toContain("'granted' | 'denied' | 'withdrawn'")
    expect(consent).toContain('keepalive: true')
  })

  it('stops capture and replay synchronously on withdrawal', () => {
    const writer = wrapper.slice(
      wrapper.indexOf('export function writeAnalyticsConsent'),
      wrapper.indexOf('/** Remove query strings'),
    )
    expect(writer.indexOf('disableAnalytics()')).toBeLessThan(
      writer.indexOf('recordConsentDecision(decision, surface)'),
    )
    expect(wrapper).toContain('client.stopSessionRecording()')
    expect(wrapper).toContain('client.opt_out_capturing()')
    expect(provider).toContain('disableAnalytics()')
    expect(provider).toContain("window.addEventListener('storage', onStorage)")
  })

  it('never initializes PostHog without a stored grant', () => {
    const initializer = wrapper.slice(
      wrapper.indexOf('export async function initializeAnalytics'),
      wrapper.indexOf('/** Stop capture and replay immediately'),
    )
    expect(initializer.indexOf("readAnalyticsConsent() !== 'granted'")).toBeLessThan(
      initializer.indexOf('loadClient()'),
    )
    expect(wrapper).toContain("if (readAnalyticsConsent() === 'granted')")
    expect(wrapper).toContain('ph.stopSessionRecording()')
    expect(wrapper).toContain('ph.opt_out_capturing()')
  })
})

describe('admin consent dashboard boundary', () => {
  const component = read('../components/admin/AdminConsentAnalytics.tsx')
  const analytics = read('../components/admin/AdminAnalytics.tsx')
  const apiClient = read('../lib/api-client.ts')
  const banner = read('../components/analytics/AnalyticsConsentBanner.tsx')
  const privacyButton = read('../components/analytics/PrivacyChoicesButton.tsx')

  it('is mounted in the admin analytics tab and reads the aggregate endpoint', () => {
    expect(analytics).toContain(
      "import AdminConsentAnalytics from '@/components/admin/AdminConsentAnalytics'",
    )
    expect(analytics).toContain('<AdminConsentAnalytics days={days} />')
    expect(apiClient).toContain('/admin/analytics/consent')
    expect(component).toContain('getAdminConsentAnalytics')
    expect(component).toContain('by_day')
    expect(component).toContain('by_surface')
    expect(component).toContain('withdrawal_trend')
    expect(component).toContain('replay_coverage')
  })

  it('documents suppression and never reads identifiers for display', () => {
    expect(component).toContain('Counts of 1-4 are suppressed')
    expect(component).toContain('suppressed_cells')
    const serialized = component.toLowerCase()
    expect(serialized).not.toContain('anonymous_id')
    expect(serialized).not.toContain('session_id')
    expect(component).not.toContain('row.email')
    expect(component).not.toContain('row.user_id')
  })

  it('tags the consent surface for banner and privacy choices', () => {
    expect(banner).toContain("writeAnalyticsConsent(value, 'banner')")
    expect(privacyButton).toContain("writeAnalyticsConsent(null, 'privacy_choices')")
  })
})
