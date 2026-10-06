import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../hooks/useFormatConversion.ts', import.meta.url), 'utf8')

describe('format conversion async ownership', () => {
  it('invalidates stale uploads, result fetches, timeouts, and resets', () => {
    expect(source).toContain('const conversionGenerationRef = useRef(0)')
    expect(source).toContain('const generation = ++conversionGenerationRef.current')
    expect(source).toContain('generation !== conversionGenerationRef.current')
    expect(source).toContain('generation === conversionGenerationRef.current')
    expect(source).toContain('conversionGenerationRef.current += 1')
    expect(source).toContain('setJobId(null)')
  })
})
