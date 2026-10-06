import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const sharedRoute = readFileSync(
  new URL('../app/r/[token]/page.tsx', import.meta.url),
  'utf8',
)
const linkedVariantRoute = readFileSync(
  new URL('../app/workspace/variant/[resumeId]/page.tsx', import.meta.url),
  'utf8',
)

describe('shared and linked variant async reliability', () => {
  it('invalidates stale shared-link requests when the token changes or the route unmounts', () => {
    expect(sharedRoute).toContain('const requestGeneration = useRef(0)')
    expect(sharedRoute).toContain('const generation = ++requestGeneration.current')
    expect(sharedRoute).toContain('setData(null)')
    expect(sharedRoute).toContain('setError(null)')
    expect(sharedRoute).toContain('setIsLoading(true)')
    expect(sharedRoute).toContain('if (isCurrent()) setData(response)')
    expect(sharedRoute).toContain('if (isCurrent()) setIsLoading(false)')
    expect(sharedRoute).toContain('requestGeneration.current += 1')
  })

  it('keeps newer linked-variant edits dirty when an older save resolves', () => {
    expect(linkedVariantRoute).toContain('const loadGeneration = useRef(0)')
    expect(linkedVariantRoute).toContain('if (loadGeneration.current !== generation) return')
    expect(linkedVariantRoute).toContain('if (loadGeneration.current === generation) setLoading(false)')
    expect(linkedVariantRoute).toContain('const [dirty, setDirty] = useState(false)')
    expect(linkedVariantRoute).toContain('const editRevision = useRef(0)')
    expect(linkedVariantRoute).toContain('const revision = editRevision.current')
    expect(linkedVariantRoute).toContain('const snapshotVisibility = cloneVisibility(visibility)')
    expect(linkedVariantRoute).toContain('if (revision === editRevision.current)')
    expect(linkedVariantRoute).toContain('setDirty(false)')
    expect(linkedVariantRoute).toContain('setDirty(true)')
    expect(linkedVariantRoute).toContain('Earlier visibility saved; newer edits remain unsaved')
  })
})
