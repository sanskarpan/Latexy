import { describe, expect, it } from 'vitest'
import {
  normalizedDictionary,
  normalizeDictionaryWord,
  wordAtIssue,
} from '@/hooks/useSpellCheck'

describe('personal spell dictionary', () => {
  it('normalizes valid proper nouns and technology tokens', () => {
    expect(normalizeDictionaryWord(' OpenAI ')).toBe('openai')
    expect(normalizeDictionaryWord('Node.js')).toBe('node.js')
  })

  it('rejects empty, whitespace-containing, control, and oversized entries', () => {
    expect(normalizeDictionaryWord('')).toBeNull()
    expect(normalizeDictionaryWord('two words')).toBeNull()
    expect(normalizeDictionaryWord('bad\nword')).toBeNull()
    expect(normalizeDictionaryWord('x'.repeat(65))).toBeNull()
  })

  it('deduplicates and caps untrusted stored arrays', () => {
    const values = ['OpenAI', 'openai', ...Array.from({ length: 600 }, (_, index) => `word${index}`)]
    const dictionary = normalizedDictionary(values)
    expect(dictionary.size).toBe(500)
    expect(dictionary.has('openai')).toBe(true)
  })

  it('resolves a LanguageTool range against the current line', () => {
    expect(wordAtIssue('First line\nUses OpenAI daily', {
      line: 2,
      column_start: 6,
      column_end: 12,
      message: 'Unknown word',
      severity: 'spelling',
      rule_id: 'MORFOLOGIK_RULE_EN_US',
      replacements: [],
    })).toBe('openai')
  })
})
