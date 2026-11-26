import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { AdminPathAnalysisSection } from '@/lib/api-client'
import { filterSectionByNode, layoutSankey } from '@/lib/admin/path-sankey'
import { sanitizeLandingPath } from '@/lib/analytics/traffic-source'
import { SectionView } from '../components/admin/AdminPathAnalysis'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

const upgradeSection: AdminPathAnalysisSection = {
    key: 'upgrade',
    label: 'Upgrade',
    status: 'visible',
    total_outcomes: 12,
    missing_path_outcomes: 2,
    route_path_outcomes: 10,
    route_coverage_pct: 83.33,
    missing_path_suppressed: false,
    nodes: [
        {
            id: 'route:/dashboard',
            label: '/dashboard',
            kind: 'route',
            count: 10,
            users: 10,
            incoming: 0,
            outgoing: 10,
            route: '/dashboard',
            filter: { route: '/dashboard' },
        },
        {
            id: 'route:/billing',
            label: '/billing',
            kind: 'route',
            count: 10,
            users: 10,
            incoming: 10,
            outgoing: 10,
            route: '/billing',
            filter: { route: '/billing' },
        },
        {
            id: 'outcome:upgrade',
            label: 'Upgrade',
            kind: 'outcome',
            count: 10,
            users: 10,
            incoming: 10,
            outgoing: 0,
            outcome: 'upgrade',
            filter: { outcome: 'upgrade' },
        },
        {
            id: 'missing:upgrade',
            label: 'Path data missing',
            kind: 'missing',
            count: 2,
            users: 2,
            incoming: 0,
            outgoing: 2,
            missing: true,
            filter: { missing: true, outcome: 'upgrade' },
        },
    ],
    edges: [
        {
            source: 'route:/dashboard',
            target: 'route:/billing',
            source_label: '/dashboard',
            target_label: '/billing',
            label: '/dashboard → /billing',
            count: 10,
            users: 10,
        },
        {
            source: 'route:/billing',
            target: 'outcome:upgrade',
            source_label: '/billing',
            target_label: 'Upgrade',
            label: '/billing → Upgrade',
            count: 10,
            users: 10,
        },
    ],
    top_paths: [
        {
            path: ['/dashboard', '/billing'],
            node_ids: ['route:/dashboard', 'route:/billing', 'outcome:upgrade'],
            label: '/dashboard → /billing → Upgrade',
            count: 10,
            users: 10,
            missing: false,
        },
    ],
    suppressed_edges: 1,
    thresholded_edges: 0,
    suppressed_paths: 1,
    visible_paths: 1,
    top_paths_truncated: false,
    raw: {
        outcomes: 12,
        paths: 2,
        transitions: 12,
        route_paths: null,
        missing_path_outcomes: null,
    },
    reconciliation: {
        reconciled: true,
        checks: [{ key: 'source_nodes_reconcile', ok: true, detail: '10 / 10 visible edges' }],
    },
    notes: [],
}

describe('admin path analysis', () => {
    const analytics = read('../components/admin/AdminAnalytics.tsx')
    const component = read('../components/admin/AdminPathAnalysis.tsx')
    const apiClient = read('../lib/api-client.ts')
    const service = read('../../../backend/app/services/path_analysis_service.py')
    const landing = read('../lib/analytics/landing.ts')
    const tracker = read('../components/analytics/LandingPageviewTracker.tsx')

    it('mounts the path view in the Analytics tab with both exports', () => {
        expect(analytics).toContain(
            "import AdminPathAnalysis from '@/components/admin/AdminPathAnalysis'",
        )
        expect(analytics).toContain('<AdminPathAnalysis days={days} />')
        expect(component).toContain('getAdminPathAnalysis')
        expect(component).toContain('downloadAdminPathAnalysisCsv')
        expect(component).toContain('Export CSV')
        expect(component).toContain('Export JSON')
        expect(apiClient).toContain('getAdminPathAnalysis')
        expect(apiClient).toContain('downloadAdminPathAnalysisCsv')
        expect(apiClient).toContain('/admin/analytics/paths')
        expect(apiClient).toContain('/admin/analytics/paths/export.csv')
    })

    it('renders a Sankey, top paths, edge threshold and reconciliation', () => {
        expect(component).toContain('Sankey')
        expect(component).toContain('Top paths before')
        expect(component).toContain('Edge threshold')
        expect(component).toContain('Route coverage')
        expect(component).toContain('Reconciliation')
        expect(component).toContain('Before upgrade')
        expect(component).toContain('Before churn')
        expect(component).toContain('7/30/90-day Analytics range')
    })

    it('labels missing path data and never invents a transition', () => {
        expect(component).toContain('Path data missing')
        expect(component).toContain('never given an inferred route')
        expect(component).toContain('labelled')
        expect(component).toContain('never invented')
        expect(service).toContain('MISSING_LABEL = "Path data missing"')
        expect(service).toContain('missing_path_imputed')
        expect(service).toContain('never imputed')
    })

    it('enforces five-user suppression and route sanitization server-side', () => {
        expect(service).toContain('MIN_GROUP_SIZE = 5')
        expect(service).toContain('def sanitize_path_route')
        expect(service).toContain('split("?", 1)[0]')
        expect(service).toContain('/r/:token')
        expect(service).toContain('/workspace/:resumeId')
        expect(service).toContain('OTHER_ROUTE = "/other"')
        expect(component).toContain('five distinct users')
        expect(component).toContain('suppressed')
        expect(service).not.toContain('per_user_rows = True')
    })

    it('captures canonical routes for authenticated navigation', () => {
        expect(landing).toContain('isPathAnalysisPath')
        expect(landing).toContain("params.set('route'")
        expect(tracker).toContain('isPathAnalysisPath')
        expect(tracker).toContain('page: \'app\'')
        expect(tracker).toContain('share pages are excluded at the source')
    })

    it('sanitizes dynamic browser routes before transmission', () => {
        expect(sanitizeLandingPath('/workspace/abc-123/edit?token=secret#frag')).toBe(
            '/workspace/:resumeId/edit',
        )
        expect(sanitizeLandingPath('/workspace/builder/abc-123')).toBe(
            '/workspace/builder/:resumeId',
        )
        expect(sanitizeLandingPath('/workspace/variant/abc-123')).toBe(
            '/workspace/variant/:resumeId',
        )
        expect(sanitizeLandingPath('/workspace/builder/new')).toBe('/workspace/builder/new')
        expect(sanitizeLandingPath('/r/share-token')).toBe('/r/:token')
        expect(sanitizeLandingPath('/workspaces/abc-123/recruiter')).toBe(
            '/workspaces/:workspaceId/recruiter',
        )
    })

    it('keeps direct identifiers and document content out of the surface', () => {
        expect(component).not.toContain('user_id')
        expect(component).not.toContain('device_fingerprint')
        expect(component).not.toContain('user_agent')
        expect(component).not.toContain('ip_address')
        expect(component).not.toContain('document_content')
        expect(component).not.toContain('share_token')
        expect(service).not.toContain('per_user_rows = True')
    })

    it('lays out a visible Sankey graph with left-to-right depths', () => {
        const layout = layoutSankey(upgradeSection)
        expect(layout.links).toHaveLength(2)
        expect(layout.nodes).toHaveLength(4)
        const dashboard = layout.nodes.find((node) => node.id === 'route:/dashboard')
        const billing = layout.nodes.find((node) => node.id === 'route:/billing')
        const outcome = layout.nodes.find((node) => node.id === 'outcome:upgrade')
        expect(dashboard?.depth).toBe(0)
        expect(billing?.depth).toBe(1)
        expect(outcome?.depth).toBe(2)
        expect(layout.links[0].path.startsWith('M ')).toBe(true)
        expect(layout.links[0].thickness).toBeGreaterThan(0)
    })

    it('filters edges and paths to a selected node', () => {
        const dashboard = filterSectionByNode(upgradeSection, 'route:/dashboard')
        expect(dashboard.edges).toHaveLength(1)
        expect(dashboard.paths).toHaveLength(1)
        expect(dashboard.nodeIds.has('route:/billing')).toBe(true)

        const missing = filterSectionByNode(upgradeSection, 'missing:upgrade')
        expect(missing.edges).toHaveLength(0)
        expect(missing.paths).toHaveLength(0)
    })

    it('renders the Sankey view and missing-path label as static HTML', () => {
        const html = renderToStaticMarkup(createElement(SectionView, { section: upgradeSection }))
        const text = html.replace(/<!-- -->/g, '')
        expect(text).toContain('Path data missing')
        expect(text).toContain('/dashboard → /billing → Upgrade')
        expect(text).toContain('role="img"')
        expect(text).toContain('Top paths before upgrade')
        expect(text).toContain('Reconciliation checks')
        expect(text).toContain('/dashboard')
        expect(text).not.toContain('user_id')
        expect(text).not.toContain('device_fingerprint')
    })
})
