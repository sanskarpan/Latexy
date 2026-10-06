import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(
  new URL('../app/workspace/[resumeId]/batch-tailor/page.tsx', import.meta.url),
  'utf8',
)

describe('batch-tailor route reliability', () => {
  it('uses confirmed-session gating for the protected route', () => {
    expect(SOURCE).toContain('useRequireAuth()')
    expect(SOURCE).toContain('if (!session) return null')
  })

  it('does not turn a failed first status poll into an infinite spinner', () => {
    expect(SOURCE).toContain('Batch status could not be refreshed')
    expect(SOURCE).toContain('onClick={fetchBatchStatus}')
    expect(SOURCE).toContain('batchId && !batchStatus && !batchError')
  })
})
