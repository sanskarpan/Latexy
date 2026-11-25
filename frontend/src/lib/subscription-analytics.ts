export type SubscriptionMovementDirection = 'upgrade' | 'downgrade' | 'lateral'

const MOVEMENT_LABELS: Record<SubscriptionMovementDirection, string> = {
    upgrade: 'Upgrade',
    downgrade: 'Downgrade',
    lateral: 'Lateral',
}

const CHURN_LABELS: Record<string, string> = {
    cancelled: 'Cancelled',
    cancellation_scheduled: 'Cancel scheduled',
    expired: 'Expired',
    payment_failed: 'Payment failed',
    refunded: 'Refunded',
}

export function movementDirectionLabel(direction: string): string {
    return MOVEMENT_LABELS[direction as SubscriptionMovementDirection] ?? direction
}

export function movementLabel(fromPlan: string, toPlan: string): string {
    return `${fromPlan} → ${toPlan}`
}

export function churnReasonLabel(reason: string): string {
    return CHURN_LABELS[reason] ?? reason.replace(/_/g, ' ')
}

export function planLabel(planId: string): string {
    const cleaned = planId.trim()
    if (!cleaned) return 'unknown'
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1).replace(/_/g, ' ')
}

/** Backend amounts are always minor units; never treat them as major units. */
export function minorToMajor(minor: number | null | undefined): number {
    return Number.isFinite(minor ?? NaN) ? Number(minor) / 100 : 0
}

export function shareLabel(percentage: number | null | undefined): string {
    if (!Number.isFinite(percentage ?? NaN)) return '0.0%'
    return `${Number(percentage).toFixed(1)}%`
}

export function cohortLabel(month: string): string {
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return month || 'Unknown'
    const [year, monthNumber] = month.split('-')
    const date = new Date(Date.UTC(Number(year), Number(monthNumber) - 1, 1))
    return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

export function suppressedCohortNote(minimum: number, hidden: number): string {
    const label = hidden === 1 ? 'cohort' : 'cohorts'
    return `${hidden} ${label} with fewer than ${minimum} subscribers hidden for privacy.`
}
