import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const QUEUE = readFileSync(new URL('../components/JobQueue.tsx', import.meta.url), 'utf8')
const SHIM = readFileSync(new URL('../lib/job-api-client.ts', import.meta.url), 'utf8')

describe('job queue API contract', () => {
  it('uses the top-level job type returned by the jobs endpoint', () => {
    expect(QUEUE).toContain("job.job_type || job.metadata?.job_type || 'latex_compilation'")
    expect(QUEUE).toContain("(job.job_type || job.metadata?.job_type || '').toLowerCase()")
  })

  it('does not render absent health counters as undefined', () => {
    expect(QUEUE).toContain('systemHealth.websocket_connections != null')
    expect(QUEUE).toContain('systemHealth.active_jobs_count != null')
    expect(SHIM).toContain('return res')
    expect(SHIM).not.toContain("return { status: 'ok', ...res }")
  })

  it('does not subscribe terminal history rows to live job streams', () => {
    expect(QUEUE).toContain('useJobStatus(canCancel ? job.job_id : null')
  })
})
