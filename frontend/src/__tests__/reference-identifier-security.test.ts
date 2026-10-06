import { describe, expect, it } from 'vitest'

import { detectReferenceIdentifierType as detectLineType } from '@/lib/reference-identifiers'

describe('reference identifier detection', () => {
  it('accepts supported bare identifiers and canonical provider URLs', () => {
    expect(detectLineType('10.1234/example')).toBe('doi')
    expect(detectLineType('https://doi.org/10.1234/example')).toBe('doi')
    expect(detectLineType('2401.12345v2')).toBe('arxiv')
    expect(detectLineType('https://arxiv.org/abs/2401.12345')).toBe('arxiv')
  })

  it('rejects hostname lookalikes and provider names embedded in arbitrary text', () => {
    expect(detectLineType('https://doi.org.evil.example/10.1234/example')).toBeNull()
    expect(detectLineType('https://evil.example/doi.org/10.1234/example')).toBeNull()
    expect(detectLineType('prefix doi.org/10.1234/example')).toBeNull()
    expect(detectLineType('https://arxiv.org.evil.example/abs/2401.12345')).toBeNull()
  })
})
