'use client'

import type {
    TenantCohortEngagement,
    TenantCohortProgress,
} from '@/lib/api-client'

function formatCount(value: number | null | undefined): string {
    return Number.isFinite(value) ? Number(value).toLocaleString() : '—'
}

function formatRate(value: number | null | undefined): string {
    return Number.isFinite(value) ? `${Math.round(Number(value) * 100)}%` : '—'
}

export function formatReviewDelay(hours: number | null | undefined): string {
    if (!Number.isFinite(hours)) return '—'
    const value = Number(hours)
    if (value < 1) return `${Math.max(1, Math.round(value * 60))}m`
    if (value < 48) return `${value.toFixed(value < 10 ? 1 : 0)}h`
    return `${(value / 24).toFixed(1)}d`
}

export function TenantCohortProgressSummary({
    progress,
}: {
    progress?: TenantCohortProgress | null
}) {
    if (!progress) {
        return (
            <p className="mt-2 text-xs text-fg-3">
                Reviewer engagement is not available yet.
            </p>
        )
    }
    if (progress.suppressed) {
        return (
            <p className="mt-2 rounded-[var(--radius-md)] border border-dashed border-line px-3 py-2 text-[11px] text-fg-3">
                {`Reviewer engagement is hidden because this cohort has fewer than ${progress.suppression.minimum_cohort_size} members or fewer than ${progress.suppression.minimum_submissions} submissions.`}
            </p>
        )
    }
    return (
        <dl
            className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4"
            aria-label="Cohort reviewer engagement"
        >
            <div className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-fg-3">Reviewed</dt>
                <dd className="mt-1 font-semibold text-fg">
                    {`${formatCount(progress.reviewed)} of ${formatCount(progress.submissions)}`}
                </dd>
            </div>
            <div className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-fg-3">
                    Reviewer coverage
                </dt>
                <dd className="mt-1 font-semibold text-fg">
                    {formatRate(progress.reviewer_coverage)}
                </dd>
            </div>
            <div className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-fg-3">
                    Median time to review
                </dt>
                <dd className="mt-1 font-semibold text-fg">
                    {formatReviewDelay(progress.median_time_to_review_hours)}
                </dd>
                <dd className="mt-0.5 text-[10px] text-fg-3">
                    First recruiter note or comment
                </dd>
            </div>
            <div className="rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2">
                <dt className="text-[10px] uppercase tracking-[0.18em] text-fg-3">
                    Stale submissions
                </dt>
                <dd className="mt-1 font-semibold text-fg">
                    {formatCount(progress.stale_submissions)}
                </dd>
                <dd className="mt-0.5 text-[10px] text-fg-3">
                    {`No reviewer action after ${progress.stale_after_days} days`}
                </dd>
            </div>
        </dl>
    )
}

export default function TenantCohortEngagementDetail({
    engagement,
    loading,
    error,
}: {
    engagement?: TenantCohortEngagement | null
    loading?: boolean
    error?: string | null
}) {
    if (loading) {
        return (
            <p className="mt-3 text-xs text-fg-3" role="status">
                Loading reviewer engagement…
            </p>
        )
    }
    if (error) {
        return (
            <p className="mt-3 text-xs text-err" role="alert">
                {error}
            </p>
        )
    }
    if (!engagement) return null

    const summary = engagement.summary
    if (summary.suppressed || !summary.funnel) {
        return (
            <p className="mt-3 rounded-[var(--radius-md)] border border-dashed border-line px-3 py-2 text-[11px] text-fg-3">
                Reviewer engagement details are suppressed for this cohort.
            </p>
        )
    }

    const funnel = summary.funnel
    const trend = engagement.trends?.['7'] ?? []

    return (
        <div className="mt-3 rounded-[var(--radius-md)] border border-line bg-surface p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">
                        Submission funnel
                    </p>
                    <p className="mt-1 text-[11px] text-fg-3">
                        Candidate self-milestones are shown separately from reviewer actions.
                    </p>
                </div>
                <p className="text-[11px] text-fg-3">
                    {`${formatCount(summary.reviewer_count)} reviewers · ${formatCount(summary.reviewer_actions)} reviewer actions`}
                </p>
            </div>

            <dl className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                <div>
                    <dt className="text-fg-3">Submitted</dt>
                    <dd className="font-semibold text-fg">{formatCount(funnel.submitted)}</dd>
                </div>
                <div>
                    <dt className="text-fg-3">Candidate opened (self)</dt>
                    <dd className="font-semibold text-fg">{formatCount(funnel.candidate_opened)}</dd>
                </div>
                <div>
                    <dt className="text-fg-3">Candidate downloaded (self)</dt>
                    <dd className="font-semibold text-fg">{formatCount(funnel.candidate_downloaded)}</dd>
                </div>
                <div>
                    <dt className="text-fg-3">Reviewed by recruiter</dt>
                    <dd className="font-semibold text-fg">{formatCount(funnel.reviewed)}</dd>
                </div>
            </dl>

            <p className="mt-3 text-[11px] text-fg-3">
                {`Median time from sharing to first recruiter note/comment: ${formatReviewDelay(summary.median_time_to_review_hours)} · Unreviewed: ${formatCount(summary.unreviewed)} · Stale (${summary.stale_after_days}d): ${formatCount(summary.stale_submissions)}`}
            </p>

            {trend.length > 0 && (
                <div className="mt-3 overflow-x-auto">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-fg-3">
                        Last 7 days
                    </p>
                    <table className="mt-1 w-full text-left text-[11px]">
                        <thead className="text-fg-3">
                            <tr>
                                <th className="py-1 pr-3">Date</th>
                                <th className="pr-3">Submissions</th>
                                <th className="pr-3">First reviewed</th>
                                <th>Reviewer actions</th>
                            </tr>
                        </thead>
                        <tbody className="text-fg-2">
                            {trend.map(point => (
                                <tr key={point.date} className="border-t border-line">
                                    <td className="py-1 pr-3">{point.date}</td>
                                    <td className="pr-3">{formatCount(point.submissions)}</td>
                                    <td className="pr-3">{formatCount(point.reviewed)}</td>
                                    <td>{formatCount(point.reviewer_actions)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}
