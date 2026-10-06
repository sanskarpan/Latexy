import { describe, expect, it } from 'vitest'
import { countRenderedWords } from '@/lib/rendered-word-count'

describe('rendered PDF word count', () => {
  it('counts visible words instead of LaTeX commands', () => {
    expect(countRenderedWords('Senior Engineer at Acme')).toBe(4)
  })

  it('keeps apostrophes and hyphenated compounds as one word', () => {
    expect(countRenderedWords("Candidate's state-of-the-art résumé")).toBe(3)
  })

  it('supports Unicode letters, marks, and numbers', () => {
    expect(countRenderedWords('Résumé हिन्दी 2026')).toBe(3)
  })

  it('returns zero for empty or punctuation-only extraction', () => {
    expect(countRenderedWords(' — … ')).toBe(0)
  })
})
