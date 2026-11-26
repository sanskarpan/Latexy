import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin daily metrics rollup surface', () => {
    const analytics = read('../components/admin/AdminAnalytics.tsx')
    const apiClient = read('../lib/api-client.ts')

    it('exposes rollup freshness and the dedicated aggregate endpoint', () => {
        expect(analytics).toContain('metrics_freshness')
        expect(analytics).toContain('Daily rollup')
        expect(analytics).toContain('Live base-table metrics')
        expect(apiClient).toContain('/admin/analytics/daily-metrics')
        expect(apiClient).toContain('getAdminDailyMetrics')
        expect(apiClient).toContain('AdminDailyMetricsResponse')
        expect(apiClient).toContain('metrics_freshness?: AdminDailyMetricsFreshness')
    })

    it('labels stale or coverage fallbacks instead of silently showing aged data', () => {
        expect(analytics).toContain('rollup does not cover this period')
        expect(analytics).toContain('daily rollup is stale')
        expect(apiClient).toContain("source: 'rollup' | 'base_tables'")
        expect(apiClient).toContain("reason: 'fresh' | 'stale' | 'no_rollup' | 'insufficient_coverage'")
    })

    it('documents the bounded refresh and aggregate/privacy contract', () => {
        expect(apiClient).toContain('refresh_interval_seconds')
        expect(apiClient).toContain('stale_after_seconds')
        expect(apiClient).toContain('minimum_cohort_users')
        expect(apiClient).toContain('aggregate_only')
        expect(apiClient).toContain('per_user_rows')
    })
})
