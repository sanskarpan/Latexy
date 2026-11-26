import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin integration analytics surface', () => {
    const page = read('../app/admin/page.tsx')
    const component = read('../components/admin/AdminIntegrations.tsx')
    const apiClient = read('../lib/api-client.ts')
    const service = read('../../../backend/app/services/integration_analytics_service.py')
    const route = read('../../../backend/app/api/admin_integration_routes.py')

    it('is mounted as a dedicated Product section', () => {
        expect(page).toContain(
            "import AdminIntegrations from '@/components/admin/AdminIntegrations'"
        )
        expect(page).toContain('<AdminIntegrations />')
    })

    it('reads the admin-only aggregate route and shows adoption, OAuth and sync health', () => {
        expect(apiClient).toContain('getAdminIntegrations')
        expect(apiClient).toContain('/admin/analytics/integrations')
        expect(component).toContain('Integration adoption and failures')
        expect(component).toContain('Connected accounts')
        expect(component).toContain('OAuth success')
        expect(component).toContain('Sync failure rate')
        expect(component).toContain('Disconnect reasons')
        expect(component).toContain('missing telemetry')
        expect(component).toContain('minimum_cohort_size')
    })

    it('keeps the aggregate boundary and never renders credentials or provider payloads', () => {
        expect(component).toContain('Aggregate')
        expect(component).toContain('token/status columns')
        expect(component).toContain('suppressed')
        expect(component).not.toContain('access_token')
        expect(component).not.toContain('refresh_token')
        expect(component).not.toContain('filename')
        expect(component).not.toContain('user_id')
        expect(component).not.toContain('provider error body')
        expect(service).toContain('MIN_GROUP_SIZE = 5')
        expect(service).toContain('missing_telemetry')
        expect(service).toContain('classify_integration_exception')
        expect(service).toContain('Per-user histories')
        expect(route).toContain('require_admin_actor')
    })
})
