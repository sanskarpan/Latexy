import { describe, expect, test } from 'vitest'
import { buildPublicationSection } from '../lib/publication-format'

describe('buildPublicationSection', () => {
  test('uses only backend-escaped entries for a partial selection', () => {
    const section = buildPublicationSection([
      {
        latex_entry:
          "``Research \\& Development.'' \\textit{Systems \\% Safety} 2026. \\href{https://doi.org/10.1/a_b}{\\detokenize{10.1/a_b}}",
      },
    ])

    expect(section).toContain('\\item ``Research \\& Development')
    expect(section).toContain('Systems \\% Safety')
    expect(section).toContain('\\detokenize{10.1/a_b}')
  })

  test('does not inspect or interpolate raw publication metadata', () => {
    const section = buildPublicationSection([
      { latex_entry: 'Safe entry.' },
      { latex_entry: 'Second safe entry.' },
    ])

    expect(section).toBe(
      '\\section{Publications}\n\\begin{enumerate}\n  \\item Safe entry.\n  \\item Second safe entry.\n\\end{enumerate}',
    )
  })
})
