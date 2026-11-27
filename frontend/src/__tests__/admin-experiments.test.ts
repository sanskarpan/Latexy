import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
    EXPERIMENT_ASSIGNMENT_PATH,
    flagOverridesFromAssignments,
    type ExperimentAssignmentResponse,
} from '@/lib/analytics/experiments'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

const response = (
    assignments: ExperimentAssignmentResponse['assignments']
): ExperimentAssignmentResponse => ({
    assignments,
    accepted: assignments.length,
    duplicate: 0,
    rejected: 0,
    skipped: 0,
    window: '2026-11-27',
})

describe('experiment assignment boundary', () => {
    it('publishes the first-party path and only allowlisted flag overrides', () => {
        expect(EXPERIMENT_ASSIGNMENT_PATH).toBe('/analytics/experiments/assignment')

        const overrides = flagOverridesFromAssignments(
            response([
                {
                    experiment_key: 'upgrade_cta_copy',
                    variant: 'treatment',
                    variant_label: 'Clear CTA',
                    flag_key: 'upgrade_ctas',
                    flag_override: true,
                    exposure_recorded: true,
                },
                {
                    experiment_key: 'Unknown Experiment',
                    variant: 'treatment',
                    variant_label: 'Unknown',
                    flag_key: 'upgrade_ctas',
                    flag_override: false,
                    exposure_recorded: false,
                },
                {
                    experiment_key: 'billing_test',
                    variant: 'treatment',
                    variant_label: 'Billing',
                    flag_key: 'not_a_real_flag',
                    flag_override: true,
                    exposure_recorded: true,
                },
                {
                    experiment_key: 'boolean_test',
                    variant: 'control',
                    variant_label: 'Control',
                    flag_key: 'billing',
                    flag_override: null,
                    exposure_recorded: true,
                },
            ])
        )

        expect(overrides).toEqual({ upgrade_ctas: true })
    })

    it('drops malformed assignments instead of trusting client-shaped data', () => {
        expect(flagOverridesFromAssignments(null)).toEqual({})
        expect(flagOverridesFromAssignments({} as ExperimentAssignmentResponse)).toEqual({})
        expect(
            flagOverridesFromAssignments(
                response([
                    {
                        experiment_key: 'Bad Key With Spaces',
                        variant: 'treatment',
                        variant_label: 'Bad',
                        flag_key: 'upgrade_ctas',
                        flag_override: true,
                        exposure_recorded: true,
                    },
                    {
                        experiment_key: 'valid_key',
                        variant: 'treatment',
                        variant_label: 'Valid',
                        flag_key: 'upgrade_ctas',
                        flag_override: 'true' as unknown as boolean,
                        exposure_recorded: true,
                    },
                ])
            )
        ).toEqual({})
    })

    it('sends only the opaque consent id and is consent-gated', () => {
        const transport = read('../lib/analytics/experiments.ts')
        expect(transport).toContain("readAnalyticsConsent() !== 'granted'")
        expect(transport).toContain("credentials: 'include'")
        expect(transport).toContain('keepalive: true')
        expect(transport).toContain('anonymous_id')
        expect(transport).toContain('experiment_keys')
        expect(transport.toLowerCase()).not.toContain('localstorage')
        expect(transport).not.toContain('email:')
        expect(transport).not.toContain('user_agent:')
        expect(transport).not.toContain('ip_address:')
        expect(transport).not.toContain('document_id')
        expect(transport).not.toContain('document_text')
        expect(transport).not.toContain('prompt:')
    })
})

describe('admin experiments surface', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminExperiments.tsx')
    const apiClient = read('../lib/api-client.ts')
    const featureFlags = read('../contexts/FeatureFlagsContext.tsx')

    it('is wired into a dedicated admin tab', () => {
        expect(page).toContain("import AdminExperiments from '@/components/admin/AdminExperiments'")
        expect(page).toContain("{ id: 'experiments', label: 'Experiments' }")
        expect(page).toContain("tab === 'experiments' && <AdminExperiments />")
        expect(component).toContain('getAdminExperiments')
        expect(apiClient).toContain("'/admin/experiments'")
    })

    it('supports preregistration, lifecycle changes and aggregate results', () => {
        expect(component).toContain('Pre-register an experiment')
        expect(component).toContain('Minimum sample per variant')
        expect(component).toContain('Registration is immutable')
        expect(component).toContain('startAdminExperiment')
        expect(component).toContain('stopAdminExperiment')
        expect(component).toContain('stopRevert')
        expect(apiClient).toContain('revert_assignments')
        expect(component).toContain('getAdminExperimentResults')
        expect(component).toContain('95% CI')
        expect(component).toContain('lift_pp')
        expect(component).toContain('ci_low_pp')
        expect(component).toContain('minimum_sample_met')
    })

    it('states the five-user, minimum-sample and no-peeking policy', () => {
        expect(component).toContain('five-user rule')
        expect(component).toContain('Minimum sample not met')
        expect(component).toContain('No lift or confidence interval is published')
        expect(component).toContain('Claim policy')
        expect(component).toContain('No automatic rollout')
        expect(component).toContain('results.claim.peeking')
        expect(component).toContain('results.claim.winner')
    })

    it('applies only safe experiment flag overrides after server flag evaluation', () => {
        expect(featureFlags).toContain('loadExperimentAssignments')
        expect(featureFlags).toContain('recordFlagExposures(safe)')
        expect(featureFlags).toContain('key in safe')
    })
})
