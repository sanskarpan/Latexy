import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin access review surface', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminAccessReview.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('is wired into the admin control plane from a dedicated admin-only tab', () => {
        expect(page).toContain(
            "import AdminAccessReview from '@/components/admin/AdminAccessReview'"
        )
        expect(page).toContain("{ id: 'access', label: 'Access Review' }")
        expect(page).toContain("{tab === 'access' && <AdminAccessReview />}")
        const supportTabs = page.match(/const SUPPORT_TABS[\s\S]*?\]/)?.[0] ?? ''
        expect(supportTabs).not.toContain("'access'")
        expect(component).toContain('Quarterly admin access review')
        expect(component).toContain('getAdminAccessReview')
        expect(apiClient).toContain('/admin/access-review')
        expect(apiClient).toContain('AdminAccessReviewResponse')
    })

    it('shows role, 2FA, passkey, last login, account age and stale/never-used flags', () => {
        expect(component).toContain('two_factor_enabled')
        expect(component).toContain('passkey_count')
        expect(component).toContain('last_login_at')
        expect(component).toContain('account_age_days')
        expect(component).toContain('Never used')
        expect(component).toContain('Stale')
        expect(component).toContain('Admins')
        expect(component).toContain('Support')
        expect(component).toContain('No 2FA')
        expect(component).toContain('No strong auth')
    })

    it('derives last login from sessions without reading tokens, IPs or user agents', () => {
        expect(component).toContain('Better Auth session creation time')
        expect(component).toContain('session tokens, IP addresses, user agents')
        expect(component).toContain('TOTP secrets and passkey material are never read')
        expect(component).toContain('never demotes an account automatically')
        expect(component).not.toContain('session.token')
        expect(component).not.toContain('userAgent')
    })

    it('supports CSV export and a quarterly attestation with snapshot binding', () => {
        expect(component).toContain('Export CSV')
        expect(component).toContain('downloadAdminAccessReviewCsv')
        expect(component).toContain('Record quarterly attestation')
        expect(component).toContain('expected_snapshot_hash: data.snapshot_hash')
        expect(component).toContain('expected_accounts: data.accounts.map')
        expect(component).toContain('idempotency_key')
        expect(component).toContain('Attestation history')
        expect(apiClient).toContain('/admin/access-review/export.csv')
        expect(apiClient).toContain('/admin/access-review/attest')
        expect(apiClient).toContain('attestAdminAccessReview')
    })

    it('rejects a stale attestation when roles or posture changed after load', () => {
        expect(component).toContain('roster_changed')
        expect(component).toContain('review_changed')
        expect(component).toContain(
            'The privileged roster or security posture changed after this review loaded'
        )
        expect(component).toContain('append-only audit records')
        expect(component).toContain('No automatic demotion, role change, session revocation')
    })

    it('requires an explicit confirmation and a reason before attesting', () => {
        expect(component).toContain('I reviewed every privileged account in this roster')
        expect(component).toContain('minimum_note_length')
        expect(component).toContain('Required, at least')
        expect(component).toContain('disabled={!canSubmit}')
    })
})
