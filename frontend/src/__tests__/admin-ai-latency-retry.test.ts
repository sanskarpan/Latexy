import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin AI latency and retry report', () => {
  const analytics = read('../components/admin/AdminAnalytics.tsx')
  const latency = read('../components/admin/AdminAiLatencyRetry.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('wires the aggregate latency card into admin analytics', () => {
    expect(analytics).toContain(
      "import AdminAiLatencyRetry from '@/components/admin/AdminAiLatencyRetry'",
    )
    expect(analytics).toContain('<AdminAiLatencyRetry days={days} />')
    expect(apiClient).toContain('/admin/analytics/ai-latency-retry')
    expect(apiClient).toContain('AdminAiLatencyRetryResponse')
    expect(apiClient).toContain('p50_ms')
    expect(apiClient).toContain('p95_ms')
    expect(apiClient).toContain('p99_ms')
  })

  it('renders percentiles, retry rate and timeout/error rates', () => {
    expect(latency).toContain('AI latency and retry rate')
    expect(latency).toContain('p50 latency')
    expect(latency).toContain('p95 latency')
    expect(latency).toContain('p99 latency')
    expect(latency).toContain('Retry rate')
    expect(latency).toContain('Timeout rate')
    expect(latency).toContain('Error rate')
    expect(latency).toContain('Retry reasons')
    expect(latency).toContain('all_dimensions_reconcile')
    expect(latency).toContain('Sparse')
  })

  it('stays aggregate-only and never references prompts, documents or raw errors', () => {
    expect(latency).toContain('aggregate')
    expect(latency).not.toContain('latex_content')
    expect(latency).not.toContain('job_description')
    expect(latency).not.toContain('error_message')
    expect(latency).not.toContain('raw_response')
    expect(latency).not.toContain('run_ref')
  })
})
