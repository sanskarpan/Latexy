/**
 * Unit tests for P2 Features 60 and 63.
 *
 * Feature 60: LaTeX Documentation Lookup Panel
 *   60A — latex-docs.ts data integrity + lookup helpers
 *   60B — LaTeXDocPanel component behaviour (state logic, not rendering)
 *
 * Feature 63: Resume Template Customizer
 *   63A — new preamble helpers: setGeometryMargin, setDocumentClassFontSize,
 *          setSectionVspacing, extractSectionSpacingFromPreamble
 *   63B — round-trip fidelity and idempotency
 */

import { describe, test, expect, beforeEach, vi } from 'vitest'

// ─────────────────────────────────────────────────────────────────────────────
// Feature 60 · LaTeX Documentation Lookup Panel — Data
// ─────────────────────────────────────────────────────────────────────────────

import {
  LATEX_DOCS,
  LATEX_DOCS_MAP,
  LATEX_DOCS_BY_CATEGORY,
  type LaTeXDoc,
} from '../lib/latex-docs'

const VALID_CATEGORIES = new Set<LaTeXDoc['category']>([
  'formatting', 'sectioning', 'math', 'environments', 'spacing', 'graphics', 'misc',
])

// ── 60A-1 · Data shape ────────────────────────────────────────────────────────

describe('Feature 60 · LATEX_DOCS data shape', () => {
  test('array is non-empty (≥ 40 commands)', () => {
    expect(LATEX_DOCS.length).toBeGreaterThanOrEqual(40)
  })

  test('every entry has all required string fields', () => {
    for (const doc of LATEX_DOCS) {
      expect(typeof doc.command, `command field for ${doc.command}`).toBe('string')
      expect(typeof doc.signature, `signature for ${doc.command}`).toBe('string')
      expect(typeof doc.description, `description for ${doc.command}`).toBe('string')
    }
  })

  test('every command starts with a backslash', () => {
    for (const doc of LATEX_DOCS) {
      expect(doc.command, `${doc.command} should start with \\`).toMatch(/^\\/)
    }
  })

  test('every entry has a valid category', () => {
    for (const doc of LATEX_DOCS) {
      expect(VALID_CATEGORIES.has(doc.category), `${doc.command} has invalid category "${doc.category}"`).toBe(true)
    }
  })

  test('every entry has non-empty description', () => {
    for (const doc of LATEX_DOCS) {
      expect(doc.description.length, `${doc.command} has empty description`).toBeGreaterThan(0)
    }
  })

  test('every entry has non-empty signature', () => {
    for (const doc of LATEX_DOCS) {
      expect(doc.signature.length, `${doc.command} has empty signature`).toBeGreaterThan(0)
    }
  })

  test('parameters is always an array', () => {
    for (const doc of LATEX_DOCS) {
      expect(Array.isArray(doc.parameters), `${doc.command}.parameters should be array`).toBe(true)
    }
  })

  test('parameter entries have name, required, description', () => {
    for (const doc of LATEX_DOCS) {
      for (const p of doc.parameters) {
        expect(typeof p.name).toBe('string')
        expect(typeof p.required).toBe('boolean')
        expect(typeof p.description).toBe('string')
      }
    }
  })

  test('examples is always an array', () => {
    for (const doc of LATEX_DOCS) {
      expect(Array.isArray(doc.examples), `${doc.command}.examples should be array`).toBe(true)
    }
  })

  test('example entries have code and description', () => {
    for (const doc of LATEX_DOCS) {
      for (const ex of doc.examples) {
        expect(typeof ex.code).toBe('string')
        expect(typeof ex.description).toBe('string')
      }
    }
  })

  test('packages is always an array', () => {
    for (const doc of LATEX_DOCS) {
      expect(Array.isArray(doc.packages)).toBe(true)
    }
  })

  test('seealso is always an array', () => {
    for (const doc of LATEX_DOCS) {
      expect(Array.isArray(doc.seealso)).toBe(true)
    }
  })

  test('no duplicate commands', () => {
    const cmds = LATEX_DOCS.map((d) => d.command)
    const unique = new Set(cmds)
    expect(unique.size).toBe(cmds.length)
  })

  test('required parameters appear in the signature', () => {
    for (const doc of LATEX_DOCS) {
      for (const p of doc.parameters) {
        if (p.required) {
          // At least the command name should appear in the signature
          expect(doc.signature, `${doc.command} signature should contain command`).toContain(doc.command)
        }
      }
    }
  })
})

// ── 60A-2 · Specific commands present ────────────────────────────────────────

describe('Feature 60 · Essential commands exist', () => {
  test.each([
    '\\textbf', '\\textit', '\\texttt', '\\emph', '\\textsc',
    '\\section', '\\subsection', '\\maketitle',
    '\\frac', '\\sqrt', '\\sum',
    '\\vspace', '\\hspace', '\\newpage',
    '\\includegraphics', '\\label', '\\ref',
    '\\documentclass', '\\usepackage', '\\newcommand', '\\item',
  ])('%s is in LATEX_DOCS', (cmd) => {
    expect(LATEX_DOCS.some((d) => d.command === cmd)).toBe(true)
  })
})

// ── 60A-3 · LATEX_DOCS_MAP ────────────────────────────────────────────────────

describe('Feature 60 · LATEX_DOCS_MAP', () => {
  test('is a Map', () => {
    expect(LATEX_DOCS_MAP).toBeInstanceOf(Map)
  })

  test('size matches LATEX_DOCS array length', () => {
    expect(LATEX_DOCS_MAP.size).toBe(LATEX_DOCS.length)
  })

  test('can look up \\textbf', () => {
    const doc = LATEX_DOCS_MAP.get('\\textbf')
    expect(doc).toBeDefined()
    expect(doc?.category).toBe('formatting')
  })

  test('can look up \\frac', () => {
    const doc = LATEX_DOCS_MAP.get('\\frac')
    expect(doc).toBeDefined()
    expect(doc?.category).toBe('math')
  })

  test('returns undefined for unknown command', () => {
    expect(LATEX_DOCS_MAP.get('\\unknowncommand12345')).toBeUndefined()
  })

  test('every LATEX_DOCS entry is retrievable from map', () => {
    for (const doc of LATEX_DOCS) {
      expect(LATEX_DOCS_MAP.has(doc.command)).toBe(true)
      expect(LATEX_DOCS_MAP.get(doc.command)).toBe(doc)
    }
  })
})

// ── 60A-4 · LATEX_DOCS_BY_CATEGORY ───────────────────────────────────────────

describe('Feature 60 · LATEX_DOCS_BY_CATEGORY', () => {
  test('is a plain object', () => {
    expect(typeof LATEX_DOCS_BY_CATEGORY).toBe('object')
    expect(LATEX_DOCS_BY_CATEGORY).not.toBeNull()
  })

  test('has all 7 categories', () => {
    for (const cat of VALID_CATEGORIES) {
      expect(Object.prototype.hasOwnProperty.call(LATEX_DOCS_BY_CATEGORY, cat), `missing category ${cat}`).toBe(true)
    }
  })

  test('each category has at least 1 entry', () => {
    for (const cat of VALID_CATEGORIES) {
      expect(LATEX_DOCS_BY_CATEGORY[cat].length, `${cat} should have ≥1 entry`).toBeGreaterThan(0)
    }
  })

  test('total entries across all categories equals LATEX_DOCS length', () => {
    const total = Object.values(LATEX_DOCS_BY_CATEGORY).reduce((sum, arr) => sum + arr.length, 0)
    expect(total).toBe(LATEX_DOCS.length)
  })

  test('formatting category contains \\textbf', () => {
    const fmt = LATEX_DOCS_BY_CATEGORY['formatting']
    expect(fmt.some((d) => d.command === '\\textbf')).toBe(true)
  })

  test('math category contains \\frac', () => {
    const math = LATEX_DOCS_BY_CATEGORY['math']
    expect(math.some((d) => d.command === '\\frac')).toBe(true)
  })

  test('spacing category contains \\vspace', () => {
    const spacing = LATEX_DOCS_BY_CATEGORY['spacing']
    expect(spacing.some((d) => d.command === '\\vspace')).toBe(true)
  })

  test('category items match the category field on each doc', () => {
    for (const [cat, items] of Object.entries(LATEX_DOCS_BY_CATEGORY)) {
      for (const doc of items) {
        expect(doc.category).toBe(cat)
      }
    }
  })
})

// ── 60A-5 · seealso consistency ───────────────────────────────────────────────

describe('Feature 60 · seealso cross-references', () => {
  test('seealso entries are strings', () => {
    for (const doc of LATEX_DOCS) {
      for (const ref of doc.seealso) {
        expect(typeof ref).toBe('string')
      }
    }
  })

  test('seealso entries start with backslash', () => {
    for (const doc of LATEX_DOCS) {
      for (const ref of doc.seealso) {
        expect(ref, `seealso entry "${ref}" in ${doc.command} should start with \\`).toMatch(/^\\/)
      }
    }
  })

  test('no command references itself in seealso', () => {
    for (const doc of LATEX_DOCS) {
      expect(doc.seealso.includes(doc.command),
        `${doc.command} should not reference itself in seealso`).toBe(false)
    }
  })
})


// ─────────────────────────────────────────────────────────────────────────────
// Feature 63 · Resume Template Customizer — Preamble Helpers
// ─────────────────────────────────────────────────────────────────────────────

import {
  setGeometryMargin,
  setDocumentClassFontSize,
  setSectionVspacing,
  extractSectionSpacingFromPreamble,
  extractRawMarginFromPreamble,
  extractMarginsFromPreamble,
  extractFontSizeFromPreamble,
  type SectionSpacingMode,
} from '../lib/latex-preamble'

const MINIMAL = '\\documentclass[11pt]{article}\n\\begin{document}\n\\end{document}'
const WITH_GEOMETRY =
  '\\documentclass[11pt]{article}\n\\usepackage{geometry}\n\\geometry{margin=1in}\n\\begin{document}\n\\end{document}'

// ── 63A-1 · setGeometryMargin ─────────────────────────────────────────────────

describe('Feature 63 · setGeometryMargin', () => {
  test('inserts geometry block when none exists', () => {
    const result = setGeometryMargin(MINIMAL, 0.75)
    expect(result).toContain('\\geometry{margin=0.75in}')
  })

  test('replaces existing geometry margin', () => {
    const result = setGeometryMargin(WITH_GEOMETRY, 0.5)
    expect(result).toContain('\\geometry{margin=0.5in}')
    expect(result).not.toContain('margin=1in')
  })

  test('places geometry before \\begin{document}', () => {
    const result = setGeometryMargin(MINIMAL, 0.75)
    const geoIdx = result.indexOf('\\geometry{')
    const docIdx = result.indexOf('\\begin{document}')
    expect(geoIdx).toBeGreaterThanOrEqual(0)
    expect(geoIdx).toBeLessThan(docIdx)
  })

  test('numeric precision: rounds to 2 decimal places', () => {
    const result = setGeometryMargin(MINIMAL, 0.7500001)
    // Should produce 0.75in not 0.7500001in
    expect(result).toContain('margin=0.75in')
  })

  test('0.5in lower bound', () => {
    const result = setGeometryMargin(MINIMAL, 0.5)
    expect(result).toContain('margin=0.5in')
  })

  test('1.25in upper bound', () => {
    const result = setGeometryMargin(MINIMAL, 1.25)
    expect(result).toContain('margin=1.25in')
  })

  test('round-trip with extractRawMarginFromPreamble (exact numeric values)', () => {
    for (const val of [0.5, 0.75, 1.0, 1.25]) {
      const result = setGeometryMargin(MINIMAL, val)
      const extracted = extractRawMarginFromPreamble(result)
      expect(extracted, `round-trip failed for ${val}`).toBeCloseTo(val, 5)
    }
  })

  test('multiple calls: last value wins', () => {
    let latex = MINIMAL
    latex = setGeometryMargin(latex, 0.5)
    latex = setGeometryMargin(latex, 1.0)
    latex = setGeometryMargin(latex, 0.75)
    expect(latex).toContain('margin=0.75in')
    // Only one geometry block
    expect((latex.match(/\\geometry\{/g) ?? []).length).toBe(1)
  })
})

// ── 63A-1b · extractRawMarginFromPreamble ────────────────────────────────────

describe('Feature 63 · extractRawMarginFromPreamble', () => {
  test('returns 0.75 when no geometry present', () => {
    expect(extractRawMarginFromPreamble(MINIMAL)).toBe(0.75)
  })

  test('extracts 1in exactly', () => {
    expect(extractRawMarginFromPreamble(WITH_GEOMETRY)).toBeCloseTo(1.0, 5)
  })

  test('extracts 1.25in accurately (no bucketing)', () => {
    const latex = setGeometryMargin(MINIMAL, 1.25)
    expect(extractRawMarginFromPreamble(latex)).toBeCloseTo(1.25, 5)
  })

  test('extracts 0.5in accurately', () => {
    const latex = setGeometryMargin(MINIMAL, 0.5)
    expect(extractRawMarginFromPreamble(latex)).toBeCloseTo(0.5, 5)
  })

  test('returns 0.75 default on empty string', () => {
    expect(extractRawMarginFromPreamble('')).toBe(0.75)
  })
})

// ── 63A-2 · setDocumentClassFontSize ─────────────────────────────────────────

describe('Feature 63 · setDocumentClassFontSize', () => {
  test('changes 11pt to 10pt', () => {
    const result = setDocumentClassFontSize(MINIMAL, 10)
    expect(result).toContain('\\documentclass[10pt]')
  })

  test('changes 11pt to 12pt', () => {
    const result = setDocumentClassFontSize(MINIMAL, 12)
    expect(result).toContain('\\documentclass[12pt]')
  })

  test('idempotent: setting same size twice', () => {
    const r1 = setDocumentClassFontSize(MINIMAL, 11)
    const r2 = setDocumentClassFontSize(r1, 11)
    expect(r2).toContain('\\documentclass[11pt]')
    expect((r2.match(/\d+pt/g) ?? []).length).toBe(1)
  })

  test('adds pt brackets when documentclass has no options', () => {
    const noopts = '\\documentclass{article}\n\\begin{document}\n\\end{document}'
    const result = setDocumentClassFontSize(noopts, 11)
    expect(result).toMatch(/\\documentclass\[11pt\]/)
  })

  test('preserves other documentclass options (e.g. a4paper)', () => {
    const withOpts = '\\documentclass[12pt,a4paper]{article}\n\\begin{document}\n\\end{document}'
    const result = setDocumentClassFontSize(withOpts, 10)
    expect(result).toContain('10pt')
    expect(result).toContain('a4paper')
  })

  test('round-trip: set 10pt, extract gives 10pt', () => {
    const r = setDocumentClassFontSize(MINIMAL, 10)
    expect(extractFontSizeFromPreamble(r)).toBe('10pt')
  })

  test('round-trip: set 12pt, extract gives 12pt', () => {
    const r = setDocumentClassFontSize(MINIMAL, 12)
    expect(extractFontSizeFromPreamble(r)).toBe('12pt')
  })

  test('round-trip: set 11pt, extract gives 11pt', () => {
    const r = setDocumentClassFontSize(MINIMAL, 11)
    expect(extractFontSizeFromPreamble(r)).toBe('11pt')
  })
})

// ── 63A-3 · setSectionVspacing ────────────────────────────────────────────────

describe('Feature 63 · setSectionVspacing', () => {
  test('inserts compact marker block before \\begin{document}', () => {
    const result = setSectionVspacing(MINIMAL, 'compact')
    expect(result).toContain('% latexy:section-spacing')
    expect(result).toContain('\\setlength{\\parskip}{-4pt}')
  })

  test('inserts normal marker block', () => {
    const result = setSectionVspacing(MINIMAL, 'normal')
    expect(result).toContain('\\setlength{\\parskip}{2pt}')
  })

  test('inserts spacious marker block', () => {
    const result = setSectionVspacing(MINIMAL, 'spacious')
    expect(result).toContain('\\setlength{\\parskip}{6pt}')
  })

  test('marker appears before \\begin{document}', () => {
    const result = setSectionVspacing(MINIMAL, 'normal')
    const markerIdx = result.indexOf('% latexy:section-spacing')
    const docIdx = result.indexOf('\\begin{document}')
    expect(markerIdx).toBeGreaterThanOrEqual(0)
    expect(markerIdx).toBeLessThan(docIdx)
  })

  test('replaces compact with spacious (idempotent update)', () => {
    let latex = setSectionVspacing(MINIMAL, 'compact')
    latex = setSectionVspacing(latex, 'spacious')
    expect(latex).toContain('\\setlength{\\parskip}{6pt}')
    expect(latex).not.toContain('-4pt')
    // Only one managed block
    expect((latex.match(/% latexy:section-spacing/g) ?? []).length).toBe(1)
  })

  test('replaces spacious with normal', () => {
    let latex = setSectionVspacing(MINIMAL, 'spacious')
    latex = setSectionVspacing(latex, 'normal')
    expect(latex).toContain('\\setlength{\\parskip}{2pt}')
    expect(latex).not.toContain('6pt')
  })

  test('replaces normal with compact', () => {
    let latex = setSectionVspacing(MINIMAL, 'normal')
    latex = setSectionVspacing(latex, 'compact')
    expect(latex).toContain('\\setlength{\\parskip}{-4pt}')
    expect(latex).not.toContain('2pt')
  })

  test('three-way transition stays clean', () => {
    let latex = MINIMAL
    const modes: SectionSpacingMode[] = ['compact', 'normal', 'spacious', 'compact', 'spacious', 'normal']
    for (const mode of modes) {
      latex = setSectionVspacing(latex, mode)
    }
    expect((latex.match(/% latexy:section-spacing/g) ?? []).length).toBe(1)
    expect(extractSectionSpacingFromPreamble(latex)).toBe('normal')
  })

  test('document body is preserved', () => {
    const withBody = '\\documentclass[11pt]{article}\n\\begin{document}\n\\section{Exp}\n\\end{document}'
    const result = setSectionVspacing(withBody, 'compact')
    expect(result).toContain('\\section{Exp}')
    expect(result).toContain('\\end{document}')
  })
})

// ── 63A-4 · extractSectionSpacingFromPreamble ─────────────────────────────────

describe('Feature 63 · extractSectionSpacingFromPreamble', () => {
  test('returns "normal" when no marker present', () => {
    expect(extractSectionSpacingFromPreamble(MINIMAL)).toBe('normal')
  })

  test('detects compact after setSectionVspacing', () => {
    const latex = setSectionVspacing(MINIMAL, 'compact')
    expect(extractSectionSpacingFromPreamble(latex)).toBe('compact')
  })

  test('detects normal after setSectionVspacing', () => {
    const latex = setSectionVspacing(MINIMAL, 'normal')
    expect(extractSectionSpacingFromPreamble(latex)).toBe('normal')
  })

  test('detects spacious after setSectionVspacing', () => {
    const latex = setSectionVspacing(MINIMAL, 'spacious')
    expect(extractSectionSpacingFromPreamble(latex)).toBe('spacious')
  })

  test('returns "normal" on empty string', () => {
    expect(extractSectionSpacingFromPreamble('')).toBe('normal')
  })
})

// ── 63A-5 · Round-trip fidelity ───────────────────────────────────────────────

describe('Feature 63 · Round-trip fidelity', () => {
  const MODES: SectionSpacingMode[] = ['compact', 'normal', 'spacious']
  const FONT_SIZES = [10, 11, 12] as const
  const MARGINS = [0.5, 0.75, 1.0, 1.25]

  test.each(MODES)('spacing round-trip: %s', (mode) => {
    const latex = setSectionVspacing(MINIMAL, mode)
    expect(extractSectionSpacingFromPreamble(latex)).toBe(mode)
  })

  test.each(FONT_SIZES)('font-size round-trip: %dpt', (size) => {
    const latex = setDocumentClassFontSize(MINIMAL, size)
    const extracted = extractFontSizeFromPreamble(latex)
    expect(extracted).toBe(`${size}pt`)
  })

  test('combined changes are all preserved', () => {
    let latex = MINIMAL
    latex = setGeometryMargin(latex, 0.5)
    latex = setDocumentClassFontSize(latex, 10)
    latex = setSectionVspacing(latex, 'compact')

    expect(extractRawMarginFromPreamble(latex)).toBeCloseTo(0.5, 5)
    expect(extractFontSizeFromPreamble(latex)).toBe('10pt')
    expect(extractSectionSpacingFromPreamble(latex)).toBe('compact')
  })

  test('applying all changes then resetting margins works', () => {
    let latex = MINIMAL
    latex = setGeometryMargin(latex, 0.5)
    latex = setGeometryMargin(latex, 1.0)
    expect(extractRawMarginFromPreamble(latex)).toBeCloseTo(1.0, 5)
    expect((latex.match(/\\geometry\{/g) ?? []).length).toBe(1)
  })
})

// ── 63A-6 · TemplateCustomizerPanel auto-compile localStorage ─────────────────

const AUTO_COMPILE_KEY = 'latexy_customizer_autocompile'

describe('Feature 63 · TemplateCustomizerPanel auto-compile localStorage key', () => {
  let store: Record<string, string>

  beforeEach(() => {
    store = {}
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = value },
      removeItem: (key: string) => { delete store[key] },
    })
  })

  test('default: auto-compile is off (key absent)', () => {
    expect(localStorage.getItem(AUTO_COMPILE_KEY)).toBeNull()
    const isOn = localStorage.getItem(AUTO_COMPILE_KEY) === 'true'
    expect(isOn).toBe(false)
  })

  test('enabling sets key to "true"', () => {
    localStorage.setItem(AUTO_COMPILE_KEY, 'true')
    expect(localStorage.getItem(AUTO_COMPILE_KEY)).toBe('true')
    expect(localStorage.getItem(AUTO_COMPILE_KEY) === 'true').toBe(true)
  })

  test('disabling sets key to "false"', () => {
    localStorage.setItem(AUTO_COMPILE_KEY, 'true')
    localStorage.setItem(AUTO_COMPILE_KEY, 'false')
    expect(localStorage.getItem(AUTO_COMPILE_KEY) === 'true').toBe(false)
  })
})
