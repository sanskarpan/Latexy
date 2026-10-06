import { describe, expect, test } from 'vitest'

import { LATEX_SYMBOLS, SYMBOL_CATEGORIES } from '../lib/latex-symbols'

describe('LaTeX symbol catalog', () => {
  test('provides a substantial, uniquely insertable catalog', () => {
    expect(LATEX_SYMBOLS.length).toBeGreaterThanOrEqual(150)
    expect(new Set(LATEX_SYMBOLS.map((symbol) => symbol.command)).size).toBe(
      LATEX_SYMBOLS.length,
    )
    expect(
      LATEX_SYMBOLS.every(
        (symbol) =>
          symbol.command.startsWith('\\') &&
          symbol.name.trim().length > 0 &&
          symbol.unicode.trim().length > 0,
      ),
    ).toBe(true)
  })

  test('represents every advertised category', () => {
    const represented = new Set(LATEX_SYMBOLS.map((symbol) => symbol.category))
    expect(SYMBOL_CATEGORIES.every((category) => represented.has(category.id))).toBe(true)
  })

  test('retains package provenance for non-core commands', () => {
    expect(LATEX_SYMBOLS.find((symbol) => symbol.command === '\\mathbb{R}')?.package).toBe(
      'amssymb',
    )
    expect(LATEX_SYMBOLS.find((symbol) => symbol.command === '\\degree')?.package).toBe(
      'gensymb',
    )
  })
})
