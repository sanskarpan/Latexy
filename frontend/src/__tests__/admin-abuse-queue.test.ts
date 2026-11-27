import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin abuse review queue', () => {
    const page = read('../app/admin/page.tsx')
    const queue = read('../components/admin/AdminAbuseQueue.tsx')
    const approvals = read('../components/admin/AdminApprovals.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('adds a dedicated Abuse tab and renders the queue', () => {
        expect(page).toContain("import AdminAbuseQueue from '@/components/admin/AdminAbuseQueue'")
        expect(page).toContain("{ id: 'abuse', label: 'Abuse' }")
        expect(page).toContain("tab === 'abuse'")
        expect(page).toContain('<AdminAbuseQueue />')
        expect(queue).toContain('id="admin-abuse-queue"')
        expect(queue).toContain('Abuse review queue')
        expect(queue).toContain('Aggregate evidence')
    })

    it('aggregates every existing signal family and is time-bounded', () => {
        expect(queue).toContain('blocked_device')
        expect(queue).toContain('trial_limit_reached')
        expect(queue).toContain('repeat_ip_cluster')
        expect(queue).toContain('trial_velocity')
        expect(queue).toContain('payment_failure')
        expect(queue).toContain('referral_rejection')
        expect(queue).toContain('coupon_reuse')
        expect(queue).toContain('rate_limit_pressure')
        expect(queue).toContain('window_days')
        expect(apiClient).toContain('AdminAbuseSignalType')
        expect(apiClient).toContain('/admin/abuse/queue/scan')
    })

    it('never shows raw fingerprints, IPs, accounts or customer payloads', () => {
        expect(queue).not.toContain('device_fingerprint')
        expect(queue).not.toContain('ip_address')
        expect(queue).not.toContain('customer_email')
        expect(queue).not.toContain('provider_payload')
        expect(queue).not.toContain('structured_content')
        expect(queue).not.toContain('latex_content')
        expect(queue).toContain('subject_key')
        expect(queue).toContain('subject_ref')
        expect(queue).toContain('Raw fingerprints')
        expect(apiClient).toContain('subject_key')
    })

    it('requires reason, confirm and a second admin for enforcement', () => {
        expect(queue).toContain('Reason (required for every scan, assignment and decision)')
        expect(queue).toContain('confirm')
        expect(queue).toContain('two-person approval queue')
        expect(queue).toContain('A different admin must approve it')
        expect(queue).toContain('decideAdminAbuseItem')
        expect(queue).toContain('assignAdminAbuseItem')
        expect(queue).toContain('Device enforcement (second admin required)')
        expect(apiClient).toContain('/decision')
        expect(apiClient).toContain('/assign')
        expect(apiClient).toContain('approval_id')
        expect(approvals).toContain('abuse_review_action')
        expect(approvals).toContain('Abuse review enforcement')
    })

    it('makes no automatic enforcement claim and supports false-positive unblock', () => {
        expect(queue).toContain('Scanning')
        expect(queue).toContain('advisory only')
        expect(queue).toContain('Dismiss false positive')
        expect(queue).toContain('unblock')
        expect(queue).toContain('whitelist')
        expect(queue).toContain('No account was punished automatically')
        expect(queue).toContain('append-only audit log')
        expect(apiClient).toContain('AdminAbuseQueueList')
    })
})
