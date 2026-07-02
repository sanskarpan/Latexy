import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient } from '../lib/api-client'
import { jobApiClient } from '../lib/job-api-client'

type RawJob = Awaited<ReturnType<typeof apiClient.listJobs>>['jobs'][number]

function raw(overrides: Partial<RawJob> & { status: RawJob['status'] }): RawJob {
  return {
    job_id: 'j',
    job_type: 'latex_compilation',
    stage: 'compile',
    percent: 0,
    last_updated: 1000,
    ...overrides,
  } as RawJob
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('jobApiClient.listJobs', () => {
  test('preserves full job fields and maps queued -> pending', async () => {
    vi.spyOn(apiClient, 'listJobs').mockResolvedValue({
      jobs: [raw({ job_id: 'a', status: 'queued', stage: 'queued', percent: 12, last_updated: 42 })],
    })

    const res = await jobApiClient.listJobs()

    expect(res.jobs).toHaveLength(1)
    expect(res.jobs[0]).toMatchObject({
      job_id: 'a',
      job_type: 'latex_compilation',
      status: 'pending', // backend 'queued' normalized to 'pending'
      stage: 'queued',
      progress: 12,
      last_updated: 42,
    })
    expect(res.total).toBe(1)
    expect(res.total_count).toBe(1)
  })

  test('filters by status', async () => {
    vi.spyOn(apiClient, 'listJobs').mockResolvedValue({
      jobs: [
        raw({ job_id: 'a', status: 'queued' }),
        raw({ job_id: 'b', status: 'completed' }),
        raw({ job_id: 'c', status: 'processing' }),
      ],
    })

    const res = await jobApiClient.listJobs('pending')

    expect(res.jobs.map((j) => j.job_id)).toEqual(['a'])
    expect(res.total).toBe(1)
  })

  test('applies offset and limit client-side', async () => {
    vi.spyOn(apiClient, 'listJobs').mockResolvedValue({
      jobs: [
        raw({ job_id: 'a', status: 'completed' }),
        raw({ job_id: 'b', status: 'completed' }),
        raw({ job_id: 'c', status: 'completed' }),
        raw({ job_id: 'd', status: 'completed' }),
      ],
    })

    const res = await jobApiClient.listJobs(undefined, 2, 1)

    expect(res.jobs.map((j) => j.job_id)).toEqual(['b', 'c'])
    expect(res.total).toBe(4)
  })
})

describe('jobApiClient.getSupportedIndustries', () => {
  test('normalizes {key,label} objects from backend to string keys', async () => {
    vi.spyOn(apiClient, 'getSupportedIndustries').mockResolvedValue({
      success: true,
      // Backend returns objects, not bare strings.
      industries: [
        { key: 'software', label: 'Software' },
        { key: 'finance', label: 'Finance' },
      ],
      count: 2,
      message: 'ok',
    } as unknown as Awaited<ReturnType<typeof apiClient.getSupportedIndustries>>)

    const res = await jobApiClient.getSupportedIndustries()

    expect(res.industries).toEqual(['software', 'finance'])
    // The normalized keys must be comparable with .includes() for a string key.
    expect(res.industries.includes('software')).toBe(true)
  })

  test('passes through bare string industries unchanged', async () => {
    vi.spyOn(apiClient, 'getSupportedIndustries').mockResolvedValue({
      success: true,
      industries: ['software', 'finance'] as unknown as never,
      count: 2,
      message: 'ok',
    } as unknown as Awaited<ReturnType<typeof apiClient.getSupportedIndustries>>)

    const res = await jobApiClient.getSupportedIndustries()

    expect(res.industries).toEqual(['software', 'finance'])
  })
})
