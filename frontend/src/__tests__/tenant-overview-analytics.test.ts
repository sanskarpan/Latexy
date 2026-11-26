import { describe, expect, it, vi } from 'vitest'

import TenantOverviewAnalytics, {
    TenantOverviewTrendChart,
} from '@/components/admin/TenantOverviewAnalytics'
import type { TenantStats, TenantTrendPoint } from '@/lib/api-client'

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

function findButton(tree: unknown, label: string) {
    return elements(tree).find(
        node => node.type === 'button' && text(node).replace(/\s+/g, ' ').trim() === label
    )
}

function click(node: Element | undefined) {
    expect(node).toBeDefined()
    return (node!.props.onClick as () => unknown)()
}

function points(days: number, submissions = 0): TenantTrendPoint[] {
    return Array.from({ length: days }, (_, index) => ({
        date: `2026-11-${String(index + 1).padStart(2, '0')}`,
        members_joined: 0,
        submissions,
        active_members: 0,
    }))
}

function stats(overrides: Partial<TenantStats> = {}): TenantStats {
    return {
        member_count: 8,
        seats_used: 8,
        seats_available: 2,
        seat_limit: 10,
        seat_utilization: 0.8,
        invited_members: 1,
        pending_invites_available: true,
        accepted_members: 8,
        active_members: 4,
        active_members_window_days: 30,
        cohort_count: 2,
        cohort_member_count: 12,
        cohorts_with_submissions: 1,
        submission_count: 5,
        activation: {
            submitted: 5,
            opened: 3,
            downloaded: 1,
            submitting_members: 4,
            activation_rate: 0.5,
        },
        trends: {
            '7': points(7, 1),
            '30': points(30, 2),
            '90': points(90, 3),
        },
        suppression: {
            minimum_cohort_size: 5,
            suppressed_cohorts: 0,
            cohort_breakdown_visible: false,
            note: 'Cohorts below five members are included in tenant totals only.',
        },
        generated_at: '2026-11-27T00:00:00Z',
        ...overrides,
    }
}

const baseProps = {
    loading: false,
    error: null,
    onRetry: vi.fn(),
    period: 30 as const,
    onPeriodChange: vi.fn(),
}

describe('TenantOverviewAnalytics', () => {
    it('renders a loading state without leaking stale tenant values', () => {
        const tree = TenantOverviewAnalytics({
            ...baseProps,
            stats: null,
            loading: true,
        })
        const rendered = text(tree)
        expect(rendered).toContain('Overview')
        expect(rendered).not.toContain('Seats')
        expect(rendered).not.toContain('Submissions')
    })

    it('renders an error with a retry action', async () => {
        const onRetry = vi.fn()
        const tree = TenantOverviewAnalytics({
            ...baseProps,
            stats: null,
            error: 'Overview API unavailable',
            onRetry,
        })
        expect(text(tree)).toContain('Overview could not be loaded')
        expect(text(tree)).toContain('Overview API unavailable')
        await click(findButton(tree, 'Retry overview'))
        expect(onRetry).toHaveBeenCalledOnce()
    })

    it('renders empty cohort and trend states with zeroed cards', () => {
        const tree = TenantOverviewAnalytics({
            ...baseProps,
            stats: stats({
                member_count: 0,
                seats_used: 0,
                seats_available: 10,
                accepted_members: 0,
                active_members: 0,
                invited_members: 0,
                cohort_count: 0,
                cohort_member_count: 0,
                cohorts_with_submissions: 0,
                submission_count: 0,
                activation: {
                    submitted: 0,
                    opened: 0,
                    downloaded: 0,
                    submitting_members: 0,
                    activation_rate: 0,
                },
                trends: { '7': points(7), '30': points(30), '90': points(90) },
            }),
        })
        const rendered = text(tree).replace(/\s+/g, ' ')
        expect(rendered).toContain('No cohorts or explicit submissions yet.')
        expect(rendered).toContain('No activity in this period.')
        expect(rendered).toContain('0 / 10')
        expect(rendered).toContain('0%')
    })

    it('drops the previous tenant values when stats switch tenants', () => {
        const first = TenantOverviewAnalytics({
            ...baseProps,
            stats: stats({ submission_count: 987 }),
        })
        expect(text(first)).toContain('987')

        const second = TenantOverviewAnalytics({
            ...baseProps,
            stats: stats({ submission_count: 3 }),
        })
        expect(text(second)).not.toContain('987')
        expect(text(second)).toContain('3')
    })

    it('switches the selected 7/30/90-day trend period', async () => {
        const onPeriodChange = vi.fn()
        const tree = TenantOverviewAnalytics({
            ...baseProps,
            stats: stats(),
            period: 30,
            onPeriodChange,
        })
        await click(findButton(tree, '7 days'))
        expect(onPeriodChange).toHaveBeenCalledWith(7)
        await click(findButton(tree, '90 days'))
        expect(onPeriodChange).toHaveBeenCalledWith(90)
        expect(text(tree)).toContain('Activity over 30 days')
    })

    it('suppresses small cohort detail and never renders hidden identity/document fields', () => {
        const tree = TenantOverviewAnalytics({
            ...baseProps,
            stats: stats({
                suppression: {
                    minimum_cohort_size: 5,
                    suppressed_cohorts: 2,
                    cohort_breakdown_visible: false,
                    note: 'Cohorts below five members are included in tenant totals only.',
                },
                member_email: 'private-member@example.com',
                resume_title: 'Confidential resume title',
                latex_content: '\\documentclass{article}',
            } as Partial<TenantStats>),
        })
        const rendered = text(tree).replace(/\s+/g, ' ')
        expect(rendered).toContain('2 cohorts below 5 members are included in totals only')
        expect(rendered).not.toContain('private-member@example.com')
        expect(rendered).not.toContain('Confidential resume title')
        expect(rendered).not.toContain('\\documentclass')
    })

    it('plots the selected period series in an accessible chart', () => {
        const tree = TenantOverviewTrendChart({ points: points(7, 4), period: 7 })
        const svg = elements(tree).find(node => node.type === 'svg')!
        expect(svg.props['aria-label']).toContain('over 7 days')
        expect(elements(tree).filter(node => node.type === 'path')).toHaveLength(3)
    })
})
