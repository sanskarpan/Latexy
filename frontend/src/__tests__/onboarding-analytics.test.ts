import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
    buildOnboardingEventPayload,
    createOnboardingTelemetryClient,
    normalizeOnboardingCompletionSource,
    normalizeOnboardingDurationMs,
    normalizeOnboardingFlowVersion,
    type OnboardingEventPayload,
} from '@/lib/analytics/onboarding'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
const ANON = '550e8400-e29b-41d4-a716-446655440000'
const EVENT = '7c9e6679-7425-40de-944b-e07fc1f90ae7'

describe('onboarding event payload boundary', () => {
    it('builds only the allowlisted low-cardinality fields', () => {
        const payload = buildOnboardingEventPayload({
            action: 'onboarding_step_completed',
            stepKey: 'get-started',
            flowVersion: 'v1',
            durationMs: 4321,
            completionSource: 'cta',
            anonymousId: ANON,
            eventId: EVENT,
        })

        expect(payload).toEqual({
            action: 'onboarding_step_completed',
            step_key: 'get-started',
            flow_version: 'v1',
            duration_ms: 4321,
            completion_source: 'cta',
            event_id: EVENT,
            anonymous_id: ANON,
        })
        expect(Object.keys(payload ?? {}).sort()).toEqual([
            'action',
            'anonymous_id',
            'completion_source',
            'duration_ms',
            'event_id',
            'flow_version',
            'step_key',
        ])

        const serialized = JSON.stringify(payload).toLowerCase()
        for (const forbidden of [
            'email',
            'name',
            'document',
            'resume',
            'latex',
            'form',
            'answer',
            'replay',
            '@example.com',
        ]) {
            expect(serialized).not.toContain(forbidden)
        }
    })

    it('rejects unknown actions, steps and identifiers instead of storing free text', () => {
        const base = {
            action: 'onboarding_step_viewed' as const,
            stepKey: 'welcome',
            anonymousId: ANON,
            eventId: EVENT,
        }
        expect(buildOnboardingEventPayload({ ...base, stepKey: 'salary-expectation' })).toBeNull()
        expect(buildOnboardingEventPayload({ ...base, stepKey: 'person@example.com' })).toBeNull()
        expect(
            buildOnboardingEventPayload({
                ...base,
                action: 'onboarding_step_submitted' as never,
            }),
        ).toBeNull()
        expect(buildOnboardingEventPayload({ ...base, anonymousId: 'has spaces' })).toBeNull()
        expect(buildOnboardingEventPayload({ ...base, eventId: 'has spaces' })).toBeNull()
    })

    it('clamps durations and only attaches a completion source to terminal actions', () => {
        expect(normalizeOnboardingDurationMs(12.9)).toBe(12)
        expect(normalizeOnboardingDurationMs(-1)).toBeUndefined()
        expect(normalizeOnboardingDurationMs(Number.NaN)).toBeUndefined()
        expect(normalizeOnboardingDurationMs(99_999_999_999)).toBe(86_400_000)

        const viewed = buildOnboardingEventPayload({
            action: 'onboarding_step_viewed',
            stepKey: 'welcome',
            completionSource: 'cta',
            anonymousId: ANON,
            eventId: EVENT,
        })
        expect(viewed && 'completion_source' in viewed).toBe(false)

        expect(normalizeOnboardingCompletionSource('escape')).toBe('escape')
        expect(normalizeOnboardingCompletionSource('person@example.com')).toBe('unknown')
        expect(normalizeOnboardingFlowVersion('v2.1')).toBe('v2.1')
        expect(normalizeOnboardingFlowVersion('not-a-version')).toBe('v1')
    })
})

describe('onboarding consent gating', () => {
    it('sends nothing without a granted analytics consent', () => {
        const sent: OnboardingEventPayload[] = []
        const client = createOnboardingTelemetryClient({
            readConsent: () => 'denied',
            anonymousId: () => ANON,
            eventId: () => EVENT,
            send: (payload) => sent.push(payload),
        })

        expect(
            client.track({
                action: 'onboarding_step_viewed',
                stepKey: 'welcome',
            }),
        ).toBe(false)
        expect(sent).toEqual([])

        const noChoice = createOnboardingTelemetryClient({
            readConsent: () => null,
            anonymousId: () => ANON,
            eventId: () => EVENT,
            send: (payload) => sent.push(payload),
        })
        expect(
            noChoice.track({
                action: 'onboarding_step_viewed',
                stepKey: 'welcome',
            }),
        ).toBe(false)
        expect(sent).toEqual([])
    })

    it('sends the allowlisted payload after a grant', () => {
        const sent: OnboardingEventPayload[] = []
        const client = createOnboardingTelemetryClient({
            readConsent: () => 'granted',
            anonymousId: () => ANON,
            eventId: () => EVENT,
            send: (payload) => sent.push(payload),
        })

        expect(
            client.track({
                action: 'onboarding_step_skipped',
                stepKey: 'features',
                durationMs: 900,
                completionSource: 'skip',
            }),
        ).toBe(true)
        expect(sent).toEqual([
            {
                action: 'onboarding_step_skipped',
                step_key: 'features',
                flow_version: 'v1',
                duration_ms: 900,
                completion_source: 'skip',
                event_id: EVENT,
                anonymous_id: ANON,
            },
        ])
    })
})

describe('onboarding wiring and admin boundary', () => {
    const flow = read('../components/onboarding/OnboardingFlow.tsx')
    const growth = read('../components/admin/AdminGrowth.tsx')
    const component = read('../components/admin/AdminOnboardingAnalytics.tsx')
    const apiClient = read('../lib/api-client.ts')
    const telemetry = read('../lib/analytics/onboarding.ts')

    it('instruments step views, completions and skips', () => {
        expect(flow).toContain("from '@/lib/analytics/onboarding'")
        expect(flow).toContain("action: 'onboarding_step_viewed'")
        expect(flow).toContain("recordStepEvent('onboarding_step_completed', 'next')")
        expect(flow).toContain("completeFlow('link')")
        expect(flow).toContain("completeFlow('cta')")
        expect(flow).toContain("skipFlow('skip')")
        expect(flow).toContain("skipFlowRef.current('escape')")
        expect(flow).toContain("skipFlow('backdrop')")
        expect(flow).toContain('durationMs: duration')
    })

    it('uses the shared consent gate and the first-party backend path', () => {
        expect(telemetry).toContain("options.readConsent() !== 'granted'")
        expect(telemetry).toContain('/analytics/onboarding/events')
        expect(telemetry).toContain('consentAnonymousId')
        expect(telemetry).toContain('keepalive: true')
        expect(telemetry).not.toContain('posthog-js')
    })

    it('is mounted in the Growth tab and reads the aggregate admin endpoint', () => {
        expect(growth).toContain(
            "import AdminOnboardingAnalytics from '@/components/admin/AdminOnboardingAnalytics'",
        )
        expect(growth).toContain('<AdminOnboardingAnalytics days={days} />')
        expect(apiClient).toContain('getAdminOnboardingAnalytics')
        expect(apiClient).toContain('/admin/analytics/onboarding')
        expect(component).toContain('completion_reconciliation')
        expect(component).toContain('suppressed_segments')
        expect(component).toContain('median_duration_seconds')
        expect(component).toMatch(/Cohorts smaller than/)
    })

    it('never renders identifiers or event metadata', () => {
        const serialized = component.toLowerCase()
        for (const forbidden of [
            'user_id',
            'anonymous_id',
            'event_id',
            'event_metadata',
            'device_fingerprint',
            'user_agent',
            'row.email',
            'row.name',
        ]) {
            expect(serialized).not.toContain(forbidden)
        }
    })
})
