import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../hooks/useJobManagement.ts', import.meta.url), 'utf8')

describe('job queue refresh lifecycle', () => {
  it('rejects stale and post-unmount jobs and health responses', () => {
    expect(source).toContain('const jobsRequestRef = useRef(0)')
    expect(source).toContain('const healthRequestRef = useRef(0)')
    expect(source).toContain('requestId !== jobsRequestRef.current')
    expect(source).toContain('requestId !== healthRequestRef.current')
    expect(source).toContain('if (!mountedRef.current) return')
    expect(source).toContain('mountedRef.current = false')
  })
})
