import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin email delivery health', () => {
    const component = read('../components/admin/AdminEmailHealth.tsx')
    const adminPage = read('../app/admin/page.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('renders delivery, bounce, complaint and suppression health', () => {
        expect(component).toContain('Email delivery health')
        expect(component).toContain('getAdminEmailHealth')
        expect(component).toContain('bounce_rate_pct')
        expect(component).toContain('complaint_rate_pct')
        expect(component).toContain('recent_failures')
        expect(component).toContain('active_recipients')
        expect(component).toContain('rates_withheld')
        expect(component).toContain('minimum_rate_sample')
        expect(component).toContain('Suppression and reputation')
        expect(apiClient).toContain('AdminEmailHealthResponse')
        expect(apiClient).toContain('/admin/email/health?days=')
    })

    it('is wired into the admin-only tab set', () => {
        expect(adminPage).toContain(
            "import AdminEmailHealth from '@/components/admin/AdminEmailHealth'"
        )
        expect(adminPage).toContain("{ id: 'email', label: 'Email Health' }")
        expect(adminPage).toContain("{tab === 'email' && <AdminEmailHealth />}")
    })

    it('never renders recipient addresses, provider payloads or secrets', () => {
        for (const forbidden of [
            'recipient_email',
            'customer_email',
            'provider_message_id',
            'html_body',
            'subject:',
            'RESEND_WEBHOOK_SECRET',
            'dangerouslySetInnerHTML',
        ]) {
            expect(component).not.toContain(forbidden)
        }
    })
})
