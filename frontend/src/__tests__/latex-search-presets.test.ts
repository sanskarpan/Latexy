import { describe, test, expect } from 'vitest'
import { LATEX_SEARCH_PRESETS, type LatexSearchPreset } from '../data/latex-search-presets'

// Deterministic lookup — throws if the label doesn't exist, so a renamed preset
// fails loudly in the test instead of silently returning undefined.
function byLabel(label: string): LatexSearchPreset {
  const preset = LATEX_SEARCH_PRESETS.find((p) => p.label === label)
  if (!preset) throw new Error(`Preset "${label}" not found in LATEX_SEARCH_PRESETS`)
  return preset
}

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
    const re = new RegExp(byLabel('All section headers').pattern)
    expect(re.test('\\section{Experience}')).toBe(true)
    expect(re.test('\\subsection{Experience}')).toBe(false)
  })

  test('textbf preset matches \\textbf{...}', () => {
    const re = new RegExp(byLabel('All \\textbf content').pattern)
    expect(re.test('\\textbf{Senior Engineer}')).toBe(true)
    expect(re.test('\\textit{Senior Engineer}')).toBe(false)
  })

  test('item bullets preset matches \\item lines', () => {
    const re = new RegExp(byLabel('All \\item bullets').pattern, 'm')
    expect(re.test('  \\item Built a distributed system')).toBe(true)
    expect(re.test('\\begin{itemize}')).toBe(false)
  })

  test('date preset matches Month Year format', () => {
    const re = new RegExp(byLabel('All dates (Month Year format)').pattern)
    expect(re.test('Jan 2023')).toBe(true)
    expect(re.test('February 2021')).toBe(true)
    expect(re.test('2023-01')).toBe(false)
  })

  test('href preset matches \\href{url}{text}', () => {
    const re = new RegExp(byLabel('All \\href links').pattern)
    expect(re.test('\\href{https://example.com}{My Site}')).toBe(true)
    expect(re.test('\\url{https://example.com}')).toBe(false)
  })
})
