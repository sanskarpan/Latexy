import { describe, expect, it } from 'vitest'

import TenantCohortEngagementDetail, {
    TenantCohortProgressSummary,
    formatReviewDelay,
} from '@/components/admin/TenantCohortProgress'
import type {
    CohortEngagementTrendPoint,
    TenantCohortEngagement,
    TenantCohortProgress,
} from '@/lib/api-client'

type Element = { type: unknown; props: Record<string, unknown> }

function renderElement(value: unknown): unknown {
    if (Array.isArray(value)) return value.flatMap(renderElement)
    if (
        value &&
        typeof value === 'object' &&
        'type' in value &&
        typeof (value as Element).type === 'function'
    ) {
        return renderElement(
            ((value as Element).type as (props: Record<string, unknown>) => unknown)(
                (value as Element).props
            )
        )
    }
    return value
}

function elements(value: unknown): Element[] {
    const rendered = renderElement(value)
    if (Array.isArray(rendered)) return rendered.flatMap(elements)
    if (!rendered || typeof rendered !== 'object' || !('props' in rendered)) return []
    const node = rendered as Element
    return [node, ...elements(node.props.children)]
}

function text(value: unknown): string {
    const rendered = renderElement(value)
    if (typeof rendered === 'string' || typeof rendered === 'number') return String(rendered)
    if (Array.isArray(rendered)) return rendered.map(text).join(' ')
    if (!rendered || typeof rendered !== 'object') return ''
    const node = rendered as Element
    return [node.props.children, node.props.value, node.props.hint].map(text).join(' ')
}

function progress(overrides: Partial<TenantCohortProgress> = {}): TenantCohortProgress {
    return {
        cohort_id: 'cohort-1',
        generated_at: '2026-11-27T00:00:00Z',
        suppressed: false,
        suppression: {
            suppressed: false,
            reason: null,
            minimum_cohort_size: 5,
            minimum_submissions: 5,
            cohort_size: 8,
            submissions: 6,
            note: 'Cohort progress is hidden below five members or five submissions.',
        },
        submissions: 6,
        reviewed: 4,
        unreviewed: 2,
        reviewer_count: 2,
        reviewer_actions: 5,
        reviewer_coverage: 0.6667,
        median_time_to_review_hours: 5,
        stale_submissions: 1,
        stale_after_days: 7,
        funnel: {
            submitted: 6,
            candidate_opened: 1,
            candidate_downloaded: 1,
            reviewed: 4,
        },
        ...overrides,
    }
}

function trendPoints(): CohortEngagementTrendPoint[] {
    return Array.from({ length: 7 }, (_, index) => ({
        date: `2026-11-${String(index + 20).padStart(2, '0')}`,
        submissions: index === 6 ? 2 : 0,
        reviewed: index === 6 ? 1 : 0,
        reviewer_actions: index === 6 ? 1 : 0,
    }))
}

function engagement(
    overrides: Partial<TenantCohortEngagement> = {}
): TenantCohortEngagement {
    return {
        cohort_id: 'cohort-1',
        generated_at: '2026-11-27T00:00:00Z',
        summary: progress(),
        trends: {
            '7': trendPoints(),
            '30': trendPoints(),
            '90': trendPoints(),
        },
        ...overrides,
    }
}

describe('TenantCohortProgressSummary', () => {
    it('formats review delays without hiding sub-hour values', () => {
        expect(formatReviewDelay(0.25)).toBe('15m')
        expect(formatReviewDelay(5)).toBe('5.0h')
        expect(formatReviewDelay(72)).toBe('3.0d')
        expect(formatReviewDelay(null)).toBe('—')
    })

    it('renders submissions, reviewed, median time-to-review and stale count', () => {
        const rendered = text(TenantCohortProgressSummary({ progress: progress() }))
            .replace(/\s+/g, ' ')
        expect(rendered).toContain('Reviewed')
        expect(rendered).toContain('4 of 6')
        expect(rendered).toContain('Reviewer coverage')
        expect(rendered).toContain('67%')
        expect(rendered).toContain('Median time to review')
        expect(rendered).toContain('5.0h')
        expect(rendered).toContain('Stale submissions')
        expect(rendered).toContain('No reviewer action after 7 days')
    })

    it('suppresses small cohorts without exposing engagement values', () => {
        const rendered = text(
            TenantCohortProgressSummary({
                progress: progress({
                    suppressed: true,
                    reviewed: null,
                    unreviewed: null,
                    reviewer_count: null,
                    reviewer_actions: null,
                    reviewer_coverage: null,
                    median_time_to_review_hours: null,
                    stale_submissions: null,
                    funnel: null,
                    suppression: {
                        suppressed: true,
                        reason: 'submissions_below_minimum',
                        minimum_cohort_size: 5,
                        minimum_submissions: 5,
                        cohort_size: 8,
                        submissions: 4,
                        note: 'hidden',
                    },
                }),
            })
        ).replace(/\s+/g, ' ')
        expect(rendered).toContain('hidden')
        expect(rendered).not.toContain('Median time to review')
        expect(rendered).not.toContain('67%')
    })
})

describe('TenantCohortEngagementDetail', () => {
    it('separates candidate self-milestones from reviewer actions', () => {
        const rendered = text(TenantCohortEngagementDetail({ engagement: engagement() }))
            .replace(/\s+/g, ' ')
        expect(rendered).toContain('Submission funnel')
        expect(rendered).toContain('Candidate opened (self)')
        expect(rendered).toContain('Candidate downloaded (self)')
        expect(rendered).toContain('Reviewed by recruiter')
        expect(rendered).toContain('2 reviewers')
        expect(rendered).toContain('5 reviewer actions')
        expect(rendered).toContain('Median time from sharing to first recruiter note/comment: 5.0h')
        expect(rendered).toContain('Stale (7d): 1')
    })

    it('renders the 7-day per-cohort trend and never renders document or identity fields', () => {
        const tree = TenantCohortEngagementDetail({
            engagement: {
                ...engagement(),
                summary: {
                    ...progress(),
                    student_email: 'private-student@example.com',
                    comment_text: 'private reviewer comment',
                    reviewer_email: 'reviewer@example.com',
                } as TenantCohortProgress,
            },
        })
        const rows = elements(tree).filter(node => node.type === 'tr')
        // Header row + seven day rows.
        expect(rows).toHaveLength(8)
        const rendered = text(tree).replace(/\s+/g, ' ')
        expect(rendered).toContain('2026-11-26')
        expect(rendered).not.toContain('private-student@example.com')
        expect(rendered).not.toContain('private reviewer comment')
        expect(rendered).not.toContain('reviewer@example.com')
    })

    it('renders loading and error states', () => {
        const loading = text(
            TenantCohortEngagementDetail({ engagement: null, loading: true })
        )
        expect(loading).toContain('Loading reviewer engagement')
        const error = text(
            TenantCohortEngagementDetail({
                engagement: null,
                error: 'Engagement unavailable',
            })
        )
        expect(error).toContain('Engagement unavailable')
    })

    it('does not render funnel detail for a suppressed cohort response', () => {
        const suppressed = progress({
            suppressed: true,
            reviewed: null,
            unreviewed: null,
            reviewer_count: null,
            reviewer_actions: null,
            reviewer_coverage: null,
            median_time_to_review_hours: null,
            stale_submissions: null,
            funnel: null,
            suppression: {
                suppressed: true,
                reason: 'cohort_below_minimum',
                minimum_cohort_size: 5,
                minimum_submissions: 5,
                cohort_size: 4,
                submissions: 5,
                note: 'hidden',
            },
        })
        const rendered = text(
            TenantCohortEngagementDetail({
                engagement: engagement({ summary: suppressed, trends: null }),
            })
        )
        expect(rendered).toContain('suppressed')
        expect(rendered).not.toContain('Submission funnel')
        expect(rendered).not.toContain('Candidate opened (self)')
    })
})
