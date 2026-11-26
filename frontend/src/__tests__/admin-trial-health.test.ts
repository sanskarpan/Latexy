import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin trial health signals', () => {
    const growth = read('../components/admin/AdminGrowth.tsx')
    const component = read('../components/admin/AdminTrialHealth.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated trial-health section into the Growth tab', () => {
        expect(growth).toContain(
            "import AdminTrialHealth from '@/components/admin/AdminTrialHealth'"
        )
        expect(growth).toContain('<AdminTrialHealth />')
    })

    it('calls the admin-only aggregate endpoint', () => {
        expect(apiClient).toContain('getAdminTrialHealth')
        expect(apiClient).toContain('/admin/analytics/trial-health')
        expect(component).toContain('getAdminTrialHealth')
    })

    it('renders 7/30/90 windows with every required signal', () => {
        expect(component).toContain('const WINDOWS = [7, 30, 90]')
        expect(component).toContain('Trial starts')
        expect(component).toContain('Unique devices')
        expect(component).toContain('Blocked devices')
        expect(component).toContain('Repeat-device distribution')
        expect(component).toContain('Usage distribution')
        expect(component).toContain('Trial → paid')
        expect(component).toContain('Top bounded rejection and abuse reasons')
        expect(component).toContain('Reconciliation')
    })

    it('keeps suppression, thresholds and read-only guardrails visible', () => {
        expect(component).toContain('minimum_cohort_size')
        expect(component).toContain('suppressed')
        expect(component).toContain('trial_limit')
        expect(component).toContain('repeat_device_cluster_threshold')
        expect(component).toContain('never blocks or changes a trial')
    })

    it('never renders or requests raw fingerprints or IPs', () => {
        expect(component).not.toContain('device_fingerprint')
        expect(component).not.toContain('ip_address')
        expect(component).not.toContain('ipKey')
        expect(component).not.toContain('fingerprintValue')
    })
})
