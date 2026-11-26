import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin BYOK vs platform credential mix', () => {
    const growth = read('../components/admin/AdminGrowth.tsx')
    const component = read('../components/admin/AdminCredentialMix.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('wires a dedicated section into the Growth & Cost tab', () => {
        expect(growth).toContain(
            "import AdminCredentialMix from '@/components/admin/AdminCredentialMix'"
        )
        expect(growth).toContain('<AdminCredentialMix days={days} />')
    })

    it('calls the admin-only aggregate endpoint', () => {
        expect(apiClient).toContain('getAdminCredentialMix')
        expect(apiClient).toContain('/admin/analytics/credential-mix')
        expect(component).toContain('getAdminCredentialMix')
        expect(component).toContain('BYOK vs platform-key mix')
    })

    it('renders calls, tokens, estimated cost, ownership and reconciliation', () => {
        expect(component).toContain('call_share_pct')
        expect(component).toContain('token_share_pct')
        expect(component).toContain('cost_share_pct')
        expect(component).toContain('Estimated AI cost')
        expect(component).toContain('Key ownership')
        expect(component).toContain('Reconciliation')
        expect(component).toContain('minimum_group_size')
        expect(component).toContain('suppressed_groups')
        expect(component).toContain('credential_source_note')
    })

    it('exposes every required mix dimension', () => {
        expect(component).toContain("key: 'feature'")
        expect(component).toContain("key: 'plan'")
        expect(component).toContain("key: 'provider'")
        expect(component).toContain("key: 'model'")
        expect(component).toContain("key: 'persona'")
        expect(component).toContain("key: 'day'")
    })

    it('never renders key material, fingerprints or per-user identifiers', () => {
        expect(component).not.toContain('encrypted_key')
        expect(component).not.toContain('key_name')
        expect(component).not.toContain('credential_scope')
        expect(component).not.toContain('credential_hash')
        expect(component).not.toContain('user_id')
        expect(component).not.toContain('api_key')
    })
})
