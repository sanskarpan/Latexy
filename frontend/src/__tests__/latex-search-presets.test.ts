import { describe, test, expect } from 'vitest'
import { LATEX_SEARCH_PRESETS } from '../data/latex-search-presets'

describe('LATEX_SEARCH_PRESETS', () => {
  test('exports a non-empty array', () => {
    expect(Array.isArray(LATEX_SEARCH_PRESETS)).toBe(true)
    expect(LATEX_SEARCH_PRESETS.length).toBeGreaterThan(0)
  })

  test('every preset has required fields', () => {
    for (const preset of LATEX_SEARCH_PRESETS) {
      expect(typeof preset.label).toBe('string')
      expect(preset.label.length).toBeGreaterThan(0)
      expect(typeof preset.pattern).toBe('string')
      expect(preset.pattern.length).toBeGreaterThan(0)
      expect(typeof preset.isRegex).toBe('boolean')
    }
  })

  test('all patterns are valid regex strings', () => {
    for (const preset of LATEX_SEARCH_PRESETS) {
      expect(() => new RegExp(preset.pattern)).not.toThrow()
    }
  })

  test('section headers preset matches \\section{...}', () => {
    const preset = LATEX_SEARCH_PRESETS.find((p) => p.label === 'All section headers')!
    expect(preset).toBeDefined()
    const re = new RegExp(preset.pattern)
    expect(re.test('\\section{Experience}')).toBe(true)
    expect(re.test('\\subsection{Experience}')).toBe(false)
  })

  test('textbf preset matches \\textbf{...}', () => {
    const preset = LATEX_SEARCH_PRESETS.find((p) => p.label === 'All \\\\textbf content' || p.pattern.includes('textbf'))!
    expect(preset).toBeDefined()
    const re = new RegExp(preset.pattern)
    expect(re.test('\\textbf{Senior Engineer}')).toBe(true)
    expect(re.test('\\textit{Senior Engineer}')).toBe(false)
  })

  test('item bullets preset matches \\item lines', () => {
    const preset = LATEX_SEARCH_PRESETS.find((p) => p.pattern.includes('item'))!
    expect(preset).toBeDefined()
    const re = new RegExp(preset.pattern, 'm')
    expect(re.test('  \\item Built a distributed system')).toBe(true)
    expect(re.test('\\begin{itemize}')).toBe(false)
  })

  test('date preset matches Month Year format', () => {
    const preset = LATEX_SEARCH_PRESETS.find((p) => p.label.includes('date') || p.label.includes('Month'))!
    expect(preset).toBeDefined()
    const re = new RegExp(preset.pattern)
    expect(re.test('Jan 2023')).toBe(true)
    expect(re.test('February 2021')).toBe(true)
    expect(re.test('2023-01')).toBe(false)
  })

  test('href preset matches \\href{url}{text}', () => {
    const preset = LATEX_SEARCH_PRESETS.find((p) => p.pattern.includes('href'))!
    expect(preset).toBeDefined()
    const re = new RegExp(preset.pattern)
    expect(re.test('\\href{https://example.com}{My Site}')).toBe(true)
    expect(re.test('\\url{https://example.com}')).toBe(false)
  })
})
